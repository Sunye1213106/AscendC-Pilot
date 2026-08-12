#!/usr/bin/env python3
"""Producer/consumer DAG check for Workflow Spec IO contracts.

Fails with:
  - CONTRACT_ORPHAN_INPUT when a declared read has no producer (legacy tg-* check)
  - ARTIFACT_ORPHAN_CONSUME when a gate/explicit consume has no producer (P1 DAG)

Inputs that may exist without a Workflow Spec producer use external roots
(context/**, local/**, runs/**, source trees, control/**).

Formal UO handoff is modeled as logical resources:
  uo/*.uo / uo:product / uo:view:*
produced by uo-commit (output contract uo-commit-v1).
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path
from typing import Any


# Inputs that may exist without a Workflow Spec producer.
_EXTERNAL_ROOTS = (
    "context/**",
    "runs/**",
    "source/**",
    "op_host/**",
    "op_kernel/**",
    "op_api/**",
    "local/**",
    "control/**",
)

# Logical resources embedded in the formal .uo product.
_UO_LOGICAL = {
    "uo:product",
    "uo:view:tiling/exhaustive_key_space",
    "uo:view:tiling/legal_key_index",
    "uo:view:ir/tg_host_view",
    "uo:view:ir/operator_graph",
    "uo:view:views/kernel",
    "uo:view:views/tilingdata",
    "uo/*.uo",
}


def _normalize_read(path: str) -> str:
    p = str(path or "").replace("\\", "/").strip()
    if not p:
        return ""
    if p == "uo" or p == "uo/**" or p.startswith("uo/"):
        return "uo/*.uo"
    return p


def _is_external(path: str) -> bool:
    for root in _EXTERNAL_ROOTS:
        if fnmatch.fnmatch(path, root) or path == root.rstrip("/**") or path.startswith(root.rstrip("*")):
            return True
    # Exact external prefixes without glob
    for prefix in (
        "context/",
        "runs/",
        "source/",
        "op_host/",
        "op_kernel/",
        "op_api/",
        "local/",
        "control/",
    ):
        if path.startswith(prefix) or path == prefix.rstrip("/"):
            return True
    return False


def _collect_producers(repo: Path) -> dict[str, set[str]]:
    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.workflows import WORKFLOWS

    producers: dict[str, set[str]] = {}

    def add(path: str, owner: str) -> None:
        path = str(path or "").replace("\\", "/").strip()
        if not path:
            return
        producers.setdefault(path, set()).add(owner)
        if path == "uo/*.uo" or path.endswith(".uo"):
            for logical in _UO_LOGICAL:
                producers.setdefault(logical, set()).add(owner)

    for contract_id, paths in OUTPUT_CONTRACT_PATHS.items():
        for rel in paths or []:
            add(rel, f"contract:{contract_id}")

    for wid, wf in WORKFLOWS.items():
        if not isinstance(wf, dict) or wf.get("reserved") or wf.get("alias_of"):
            continue
        for action in wf.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = str(action.get("id") or "")
            owner = f"{wid}/{aid}"
            for rel in action.get("allowed_write_paths") or []:
                add(str(rel), owner)
            cid = str(action.get("output_contract_id") or "")
            for rel in OUTPUT_CONTRACT_PATHS.get(cid) or []:
                add(str(rel), owner)

    # Formal product ownership even if contract list is incomplete.
    producers.setdefault("uo/*.uo", set()).add("uo-init/commit")
    for logical in _UO_LOGICAL:
        producers.setdefault(logical, set()).add("uo-init/commit")
    return producers


def _producer_covers(path: str, producers: dict[str, set[str]]) -> set[str]:
    if path in producers:
        return set(producers[path])
    owners: set[str] = set()
    for prod, who in producers.items():
        if fnmatch.fnmatch(path, prod) or fnmatch.fnmatch(prod, path):
            owners |= who
        # Directory/glob producer covering a concrete consumer
        if prod.endswith("/**") and (path.startswith(prod[:-3]) or fnmatch.fnmatch(path, prod)):
            owners |= who
        if path.endswith("/**") and prod.startswith(path[:-3]):
            owners |= who
    return owners


def check_contract_dag(repo: Path) -> list[str]:
    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS

    producers = _collect_producers(repo)
    errors: list[str] = []
    for wid, wf in WORKFLOWS.items():
        if not isinstance(wf, dict) or wf.get("reserved") or wf.get("alias_of"):
            continue
        if not str(wid).startswith("tg-"):
            continue
        for action in wf.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = str(action.get("id") or "")
            for raw in action.get("allowed_read_paths") or []:
                path = _normalize_read(str(raw))
                if not path or _is_external(path):
                    continue
                if path in _UO_LOGICAL or path == "uo/*.uo":
                    if _producer_covers(path, producers) or _producer_covers("uo/*.uo", producers):
                        continue
                owners = _producer_covers(path, producers)
                if owners:
                    continue
                # Self-reads of prior tg artifacts written by same workflow family are ok
                # when a glob producer exists under tg/
                if path.startswith("tg/") and any(
                    p.startswith("tg/") and _producer_covers(path, {p: who})
                    for p, who in producers.items()
                ):
                    continue
                if path.startswith("tg/") and any(
                    fnmatch.fnmatch(path, p) or (p.endswith("/**") and path.startswith(p[:-3]))
                    for p in producers
                ):
                    continue
                errors.append(
                    f"CONTRACT_ORPHAN_INPUT: {wid}/{aid} reads {path!r} "
                    f"(raw={raw!r}) but no producer writes it"
                )
    return sorted(set(errors))


def check_all_dags(repo: Path) -> list[str]:
    """Run legacy contract-DAG + P1 artifact producer/consumer DAG."""
    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows.artifact_dag import check_artifact_dag

    errors = list(check_contract_dag(repo))
    errors.extend(check_artifact_dag())
    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Workflow Spec producer/consumer DAG")
    parser.add_argument("--repo", type=Path, default=None)
    args = parser.parse_args(argv)
    repo = (args.repo or Path(__file__).resolve().parents[1]).expanduser().resolve()
    errors = check_all_dags(repo)
    if errors:
        contract = [e for e in errors if e.startswith("CONTRACT_ORPHAN")]
        artifact = [e for e in errors if e.startswith("ARTIFACT_ORPHAN")]
        other = [e for e in errors if e not in contract and e not in artifact]
        print(f"contract-dag: {len(errors)} orphan input(s)")
        for err in contract + artifact + other:
            print(f"  - {err}")
        return 1
    print("contract-dag: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
