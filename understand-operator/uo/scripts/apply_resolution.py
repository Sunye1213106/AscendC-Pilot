from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, write_yaml

# LLM may only patch these fields on existing nodes / unresolved items.
WHITELIST_NODE_FIELDS = {
    "name",
    "node_type",
    "binding_time",
    "determinant_source",
    "determinant_ref",
    "domain",
    "condition",
    "semantic_label",
    "rationale",
}
WHITELIST_DIAG_FIELDS = {"severity", "status", "rationale", "resolution"}


def apply_resolution(repo_root: Path, op_name: str, patch: dict[str, Any] | None = None) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    graph = read_yaml(uo_root / "ir" / "operator_graph.yaml")
    unresolved = read_yaml(uo_root / "ir" / "unresolved.yaml")
    patch = _normalize_patch(patch or read_yaml(uo_root / "ir" / "resolution_patch.yaml"))
    if not graph:
        raise FileNotFoundError("ir/operator_graph.yaml missing; run build_layered_kb first")

    nodes_by_id = {str(n.get("id")): n for n in graph.get("nodes") or [] if n.get("id")}
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for item in patch.get("node_patches") or []:
        node_id = str(item.get("id") or "")
        if node_id not in nodes_by_id:
            rejected.append({"id": node_id, "reason": "unknown_node"})
            continue
        changes = {}
        for key, value in item.items():
            if key in WHITELIST_NODE_FIELDS:
                nodes_by_id[node_id][key] = value
                changes[key] = value
        if changes:
            applied.append({"id": node_id, "changes": changes})
        else:
            rejected.append({"id": node_id, "reason": "no_whitelisted_fields"})

    unresolved_items = list(unresolved.get("items") or graph.get("unresolved") or [])
    unresolved_by_id = {str(item.get("id")): item for item in unresolved_items if item.get("id")}
    for item in patch.get("unresolved_resolutions") or []:
        uid = str(item.get("id") or "")
        if uid not in unresolved_by_id:
            rejected.append({"id": uid, "reason": "unknown_unresolved"})
            continue
        status = item.get("status") or item.get("resolution")
        if status in {"resolved", "accepted", "false_positive", "alias"}:
            unresolved_by_id[uid]["status"] = status
            for key in WHITELIST_DIAG_FIELDS:
                if key in item:
                    unresolved_by_id[uid][key] = item[key]
            applied.append({"id": uid, "changes": {"status": status}})
        else:
            rejected.append({"id": uid, "reason": "invalid_resolution_status", "got": status})

    # consistency diffs may flip binding_time etc.
    for item in patch.get("consistency_diffs") or []:
        node_id = str(item.get("id") or "")
        if node_id not in nodes_by_id:
            rejected.append({"id": node_id, "reason": "unknown_node_in_diff"})
            continue
        changes = {}
        for key, value in (item.get("set") or item).items():
            if key in WHITELIST_NODE_FIELDS:
                nodes_by_id[node_id][key] = value
                changes[key] = value
        if changes:
            applied.append({"id": node_id, "changes": changes, "via": "consistency_diff"})

    remaining = [item for item in unresolved_by_id.values() if item.get("status") not in {"resolved", "accepted", "false_positive", "alias"}]
    graph["nodes"] = list(nodes_by_id.values())
    graph["unresolved"] = remaining
    graph["resolution"] = {
        "applied_count": len(applied),
        "rejected_count": len(rejected),
        "applied": applied,
        "rejected": rejected,
    }
    write_yaml(uo_root / "ir" / "operator_graph.yaml", graph)
    write_yaml(uo_root / "ir" / "unresolved.yaml", {"version": 1, "op_name": op_name, "items": remaining})
    return graph


DECISION_TO_STATUS = {
    "resolve": "resolved",
    "resolved": "resolved",
    "accept_warning": "accepted",
    "accepted": "accepted",
    "false_positive": "false_positive",
    "suppress": "false_positive",
    "alias": "alias",
}


def _normalize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Accept legacy `resolutions`/`decision` shapes from freeform LLM prompts."""
    if not isinstance(patch, dict):
        return {}
    out = dict(patch)
    out.setdefault("node_patches", list(patch.get("node_patches") or []))
    out.setdefault("consistency_diffs", list(patch.get("consistency_diffs") or []))
    resolutions = list(patch.get("unresolved_resolutions") or [])
    legacy = patch.get("resolutions")
    if isinstance(legacy, list):
        for item in legacy:
            if not isinstance(item, dict):
                continue
            decision = str(item.get("decision") or item.get("status") or "").strip().lower()
            status = DECISION_TO_STATUS.get(decision)
            if not status:
                continue
            normalized = {
                "id": item.get("id"),
                "status": status,
                "rationale": item.get("rationale") or "",
            }
            if isinstance(item.get("resolution"), dict):
                normalized["resolution"] = item["resolution"]
            resolutions.append(normalized)
    out["unresolved_resolutions"] = resolutions
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply whitelist LLM resolution patches into operator_graph IR")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--patch", help="Path to resolution_patch.yaml")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    patch = read_yaml(Path(args.patch)) if args.patch else None
    graph = apply_resolution(repo_root, op_name, patch)
    res = graph.get("resolution") or {}
    print(
        f"applied={res.get('applied_count')} rejected={res.get('rejected_count')} "
        f"remaining_unresolved={len(graph.get('unresolved') or [])}"
    )
    if res.get("rejected"):
        sample = res["rejected"][:5]
        print(f"rejected_sample={sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
