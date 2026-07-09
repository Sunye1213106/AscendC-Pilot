from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from understand_operator._operator.artifacts import operator_root, read_text, safe_op_name, write_json


PHASE_HOST_FLOW = "host_flow"
PHASE_KERNEL_PATH = "kernel_path"

HOST_FLOW_ARTIFACTS = [
    "tiling/tiling_frontier.yaml",
    "tiling/dispatch_variables.yaml",
    "tiling/tiling_predicate_space.yaml",
    "tiling/tiling_branch_families.yaml",
    "tiling/tiling_route.yaml",
    "tiling/tiling_key.yaml",
    "tiling/tiling_data_signature.yaml",
    "tiling/tiling_data_map.yaml",
    "tiling/branch_matrix.yaml",
    "tiling/tiling_decision_tree.md",
]

FLOW_ARTIFACTS = [
    "flows/compute_flow.yaml",
    "flows/compute_flow.md",
    "flows/dataflow.yaml",
    "flows/dataflow.md",
]

HOST_FLOW_COMPLETION = "tiling/.uo_host_extraction_complete.json"
FLOW_COMPLETION = "flows/.uo_flow_extraction_complete.json"


@dataclass
class BarrierResult:
    ok: bool
    phase: str
    missing: list[str]
    stale: list[str]
    message: str


def _approved_task_ids(uo_root: Path) -> list[str]:
    path = uo_root / "kernel" / "kernel_dispatch_review.yaml"
    if not path.exists():
        return []
    ids: list[str] = []
    in_block = False
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if stripped.startswith("approved_task_ids:"):
            in_block = True
            continue
        if in_block:
            if stripped.startswith("- "):
                ids.append(stripped[2:].strip().strip('"').strip("'"))
            elif stripped and not line.startswith((" ", "\t")):
                break
    return ids


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_placeholder(rel_path: str, text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if rel_path.endswith(".md") and stripped in {"# Tiling Decision Tree\n\nunknown", "# Compute Flow\n\nunknown", "# Dataflow\n\nunknown"}:
        return True
    placeholders = {
        "tiling/tiling_frontier.yaml": {
            "version: 1\nstatus: pending\nfrontier_nodes: []\nunresolved_frontier: []",
        },
        "tiling/dispatch_variables.yaml": {
            "version: 1\nstatus: pending\nvariables: []\nunknown_variables: []",
        },
        "tiling/tiling_predicate_space.yaml": {
            "version: 1\nstatus: pending\npredicate_atoms: []\npredicate_relations: []",
        },
        "tiling/tiling_branch_families.yaml": {
            "version: 1\nstatus: pending\nfamilies: []\nexcluded_families: []\nblocking_questions: []",
        },
        "tiling/tiling_route.yaml": {
            "version: 1\nstatus: pending\nroutes: []\nrouting_summary:\n  normal_count: 0\n  needs_review_count: 0\n  excluded_count: 0\n  unknown_count: 0",
        },
        "tiling/tiling_key.yaml": {
            "tiling_keys: []\nunresolved_symbols: []",
            "version: 1\nstatus: pending\ntiling_keys: []\nunresolved_symbols: []",
        },
        "tiling/tiling_data_signature.yaml": {
            "signatures: []\nunresolved_symbols: []",
            "version: 1\nstatus: pending\nsignatures: []\nunresolved_symbols: []",
        },
        "tiling/tiling_data_map.yaml": {
            "tiling_data_fields: []\nwriter_reader_alignment: []",
            "version: 1\nstatus: pending\ntiling_data_fields: []\nwriter_reader_alignment: []",
        },
        "tiling/branch_matrix.yaml": {
            "branches: []\nunresolved_symbols: []\nblocking_questions: []",
            "version: 1\nstatus: pending\nbranches: []\nunresolved_symbols: []\nblocking_questions: []",
        },
        "flows/compute_flow.yaml": {
            "compute_steps: []\nrisks: []",
        },
        "flows/dataflow.yaml": {
            "dataflow_edges: []\nbuffers: []\nsync_events: []",
        },
    }
    return stripped in placeholders.get(rel_path, set())


def _completion_ok(path: Path, expected_subagent: str) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing completion manifest: {path.as_posix()}"
    data = _load_json(path)
    if data.get("status") != "complete":
        return False, f"incomplete manifest: {path.as_posix()} status={data.get('status')!r}"
    if data.get("subagent") != expected_subagent:
        return False, f"unexpected subagent in {path.name}: {data.get('subagent')!r}"
    return True, ""


def verify_host_flow_barrier(uo_root: Path) -> BarrierResult:
    missing: list[str] = []
    stale: list[str] = []

    for rel in HOST_FLOW_ARTIFACTS + FLOW_ARTIFACTS:
        path = uo_root / rel
        if not path.exists():
            missing.append(rel)
            continue
        text = read_text(path)
        if _is_placeholder(rel, text):
            stale.append(rel)

    for rel, expected in (
        (HOST_FLOW_COMPLETION, "uo-host-extraction"),
        (FLOW_COMPLETION, "uo-flow-extraction"),
    ):
        ok, reason = _completion_ok(uo_root / rel, expected)
        if not ok:
            missing.append(reason)

    ok = not missing and not stale
    if ok:
        message = "host_flow barrier passed"
    else:
        parts = []
        if missing:
            parts.append(f"missing: {', '.join(missing)}")
        if stale:
            parts.append(f"still placeholder: {', '.join(stale)}")
        message = "; ".join(parts)
    return BarrierResult(ok, PHASE_HOST_FLOW, missing, stale, message)


def verify_kernel_path_barrier(uo_root: Path, task_ids: list[str]) -> BarrierResult:
    missing: list[str] = []
    stale: list[str] = []

    for task_id in task_ids:
        task_id = task_id.strip()
        if not task_id:
            continue
        yaml_rel = f"kernel/paths/{task_id}_kernel_path.yaml"
        md_rel = f"kernel/paths/{task_id}_kernel_path.md"
        completion_rel = f"kernel/paths/.uo_kernel_path_{task_id}_complete.json"
        for rel in (yaml_rel, md_rel):
            path = uo_root / rel
            if not path.exists() or not read_text(path).strip():
                missing.append(rel)
        ok, reason = _completion_ok(uo_root / completion_rel, "uo-kernel-path")
        if not ok:
            missing.append(reason)
        manifest = _load_json(uo_root / completion_rel)
        if manifest.get("task_id") and manifest.get("task_id") != task_id:
            stale.append(f"{completion_rel} task_id mismatch")

    ok = not missing and not stale
    message = "kernel_path barrier passed" if ok else f"missing: {', '.join(missing + stale)}"
    return BarrierResult(ok, PHASE_KERNEL_PATH, missing, stale, message)


def write_barrier_report(uo_root: Path, result: BarrierResult) -> Path:
    report = {
        "phase": result.phase,
        "ok": result.ok,
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "missing": result.missing,
        "stale": result.stale,
        "message": result.message,
    }
    out = uo_root / "summary" / f"barrier_{result.phase}.json"
    write_json(out, report)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify subagent completion before host continues.")
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--phase", choices=[PHASE_HOST_FLOW, PHASE_KERNEL_PATH], required=True)
    parser.add_argument("--task-ids", help="Comma-separated task ids for kernel_path phase")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = operator_root(repo_root, op_name)

    if args.phase == PHASE_HOST_FLOW:
        result = verify_host_flow_barrier(uo_root)
    else:
        task_ids = [item.strip() for item in (args.task_ids or "").split(",") if item.strip()]
        if not task_ids:
            task_ids = _approved_task_ids(uo_root)
        if not task_ids:
            result = BarrierResult(False, PHASE_KERNEL_PATH, ["approved_task_ids"], [], "no approved task ids")
        else:
            result = verify_kernel_path_barrier(uo_root, task_ids)

    report_path = write_barrier_report(uo_root, result)
    print(json.dumps({"ok": result.ok, "phase": result.phase, "message": result.message, "report": str(report_path)}, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
