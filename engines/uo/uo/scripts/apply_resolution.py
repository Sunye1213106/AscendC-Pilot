from __future__ import annotations

import argparse
import re
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
VALID_STATUSES = frozenset({"resolved", "accepted", "false_positive", "alias"})

_NUM_FAMILY_RE = re.compile(
    r"^(former|singlecore|tailcore).*(num|nums)$",
    re.IGNORECASE,
)


def apply_resolution(
    repo_root: Path,
    op_name: str,
    patch: dict[str, Any] | None = None,
    *,
    dry_run: bool = False,
    propagate: bool = False,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    graph = read_yaml(uo_root / "ir" / "operator_graph.yaml")
    unresolved = read_yaml(uo_root / "ir" / "unresolved.yaml")
    patch = _normalize_patch(patch or read_yaml(uo_root / "ir" / "resolution_patch.yaml"))
    if not graph:
        raise FileNotFoundError("ir/operator_graph.yaml missing; run build_layered_kb first")

    nodes_by_id = {str(n.get("id")): n for n in graph.get("nodes") or [] if n.get("id")}
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    ledger_entries: list[dict[str, Any]] = []

    # KEY hard reject: empty-only / missing triage+receipt (Harness authority)
    try:
        from ascendc_harness.gates import reject_key_patch_batch

        key_items = list(patch.get("unresolved_resolutions") or [])
        # Also scan freeform items list if present
        for it in patch.get("items") or []:
            if isinstance(it, dict):
                key_items.append(it)
        for row in reject_key_patch_batch(repo_root, uo_root, key_items):
            rejected.append(row)
        blocked_ids = {str(r.get("id") or "") for r in rejected}
    except ImportError:
        blocked_ids = set()

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
    unresolved_by_id = {str(item.get("id")): dict(item) for item in unresolved_items if item.get("id")}
    for item in patch.get("unresolved_resolutions") or []:
        uid = str(item.get("id") or "")
        if uid in blocked_ids:
            # already recorded in rejected
            continue
        if uid not in unresolved_by_id:
            rejected.append({"id": uid, "reason": "unknown_unresolved"})
            continue
        status = _coerce_status(item)
        action = str(item.get("action") or item.get("action_type") or "").lower()
        # Graph-mutating / accept actions must cite a candidate or produce field changes.
        if action in {"accept", "select", "accept_edge", "select_edge", "resolve_edge"}:
            cited = item.get("candidate_id") or item.get("candidate_ids") or item.get("edge_id")
            has_graph_change = bool(
                item.get("edge")
                or item.get("edges")
                or item.get("node_patch")
                or item.get("set")
                or any(k in item for k in WHITELIST_NODE_FIELDS)
            )
            if not cited and not has_graph_change:
                rejected.append(
                    {
                        "id": uid,
                        "reason": "empty_accept_without_candidate",
                        "action": action,
                    }
                )
                continue
        if status in VALID_STATUSES:
            # Status-only accept without rationale / resolution detail is a no-op fake resolve.
            if status in {"resolved", "accepted"} and not (
                item.get("rationale")
                or item.get("resolution")
                or item.get("candidate_id")
                or item.get("candidate_ids")
                or item.get("edge")
                or item.get("edges")
                or any(k in item for k in WHITELIST_DIAG_FIELDS if k not in {"status"})
            ):
                rejected.append({"id": uid, "reason": "status_only_without_evidence", "status": status})
                continue
            unresolved_by_id[uid]["status"] = status
            for key in WHITELIST_DIAG_FIELDS:
                if key in item:
                    unresolved_by_id[uid][key] = item[key]
            unresolved_by_id[uid]["status"] = status
            applied.append({"id": uid, "changes": {"status": status}})
            ledger_entries.append(
                _ledger_row(unresolved_by_id[uid], source="llm", propagated_from=None)
            )
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

    propagated = 0
    if propagate and not dry_run:
        propagated = _propagate_by_pattern(unresolved_by_id, ledger_entries, applied)

    remaining = [
        item
        for item in unresolved_by_id.values()
        if item.get("status") not in VALID_STATUSES
    ]
    resolution = {
        "applied_count": len(applied),
        "rejected_count": len(rejected),
        "propagated_count": propagated,
        "applied": applied,
        "rejected": rejected,
        "dry_run": dry_run,
        "propagate": propagate,
    }
    if dry_run:
        return {
            "version": graph.get("version", 1),
            "op_name": op_name,
            "unresolved": remaining,
            "resolution": resolution,
            "nodes": list(nodes_by_id.values()),
        }

    graph["nodes"] = list(nodes_by_id.values())
    graph["unresolved"] = remaining
    graph["resolution"] = resolution
    write_yaml(uo_root / "ir" / "operator_graph.yaml", graph)
    write_yaml(uo_root / "ir" / "unresolved.yaml", {"version": 1, "op_name": op_name, "items": remaining})
    _write_resolution_ledger(uo_root, op_name, ledger_entries, remaining)
    return graph


def _pattern_key(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "unknown")
    resolution = item.get("resolution")
    label = ""
    if isinstance(resolution, dict):
        label = str(resolution.get("label") or "").strip()
    if label:
        return f"{kind}::{label}"
    snippet = str(item.get("snippet") or item.get("message") or "")
    family = _snippet_family(snippet, kind)
    return f"{kind}::{family}"


def _snippet_family(snippet: str, kind: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]", "", snippet or "").lower()
    if kind == "unused_tiling_field":
        return "unused_host_field"
    if kind == "missing_tiling_field_producer":
        if "isrope" in s or s.endswith("rope") or "ropenum" in s:
            # keep rope nums with empty-tensor family when former/single/tail
            if _NUM_FAMILY_RE.match(s) or any(x in s for x in ("former", "singlecore", "tailcore")):
                return "empty_tensor_num_field"
            return "rope_flag_field"
        if _NUM_FAMILY_RE.match(s) or any(x in s for x in ("former", "singlecore", "tailcore")):
            return "empty_tensor_num_field"
        return f"missing:{s or 'other'}"
    return kind


def _propagate_by_pattern(
    unresolved_by_id: dict[str, dict[str, Any]],
    ledger_entries: list[dict[str, Any]],
    applied: list[dict[str, Any]],
) -> int:
    """Apply the same disposition to open siblings sharing a pattern key."""
    representatives: dict[str, dict[str, Any]] = {}
    for item in unresolved_by_id.values():
        status = item.get("status")
        if status not in VALID_STATUSES:
            continue
        key = _pattern_key(item)
        representatives.setdefault(key, item)

    # Also index by kind alone when label present on any resolved of that kind
    # so EmptyTensor label covers siblings that lack the label yet.
    by_kind_label: dict[str, dict[str, Any]] = {}
    for item in unresolved_by_id.values():
        if item.get("status") not in VALID_STATUSES:
            continue
        resolution = item.get("resolution")
        label = ""
        if isinstance(resolution, dict):
            label = str(resolution.get("label") or "").strip()
        if label:
            by_kind_label[f"{item.get('kind')}::{label}"] = item

    count = 0
    for uid, item in list(unresolved_by_id.items()):
        if item.get("status") in VALID_STATUSES:
            continue
        key = _pattern_key(item)
        rep = representatives.get(key)
        if rep is None:
            # Try matching via known labels for same kind (e.g. empty_tensor_tiling_producer)
            kind = str(item.get("kind") or "")
            for lk, candidate in by_kind_label.items():
                if not lk.startswith(kind + "::"):
                    continue
                # Only auto-apply EmptyTensor / host-unused style labels
                label = lk.split("::", 1)[-1]
                if label in {
                    "empty_tensor_tiling_producer",
                    "direct_field_assignment_producer",
                } or kind == "unused_tiling_field":
                    # For unused, any accepted unused rep applies via family key already;
                    # for missing, require empty_tensor family on open item.
                    if kind == "missing_tiling_field_producer":
                        fam = _snippet_family(str(item.get("snippet") or ""), kind)
                        if fam != "empty_tensor_num_field" and label != "direct_field_assignment_producer":
                            continue
                        if label == "direct_field_assignment_producer" and fam != "rope_flag_field":
                            continue
                    rep = candidate
                    break
        if rep is None:
            continue
        status = rep.get("status")
        if status not in VALID_STATUSES:
            continue
        item["status"] = status
        item["rationale"] = (
            f"{rep.get('rationale') or ''}（propagated_from={rep.get('id')}）"
        ).strip()
        if isinstance(rep.get("resolution"), dict):
            item["resolution"] = dict(rep["resolution"])
        applied.append({"id": uid, "changes": {"status": status}, "via": "propagate"})
        ledger_entries.append(
            _ledger_row(item, source="propagated", propagated_from=str(rep.get("id")))
        )
        count += 1
    return count


def _ledger_row(
    item: dict[str, Any],
    *,
    source: str,
    propagated_from: str | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "status": item.get("status"),
        "rationale": item.get("rationale") or "",
        "snippet": item.get("snippet"),
        "source": source,
    }
    if propagated_from:
        row["propagated_from"] = propagated_from
    if isinstance(item.get("resolution"), dict):
        row["resolution"] = item["resolution"]
    return row


def _write_resolution_ledger(
    uo_root: Path,
    op_name: str,
    ledger_entries: list[dict[str, Any]],
    remaining: list[dict[str, Any]],
) -> None:
    # Merge with prior ledger so multi-round resolve accumulates.
    prior = read_yaml(uo_root / "ir" / "resolution_ledger.yaml") or {}
    by_id: dict[str, dict[str, Any]] = {}
    for row in prior.get("items") or []:
        if isinstance(row, dict) and row.get("id"):
            by_id[str(row["id"])] = row
    for row in ledger_entries:
        if row.get("id"):
            by_id[str(row["id"])] = row
    counts: dict[str, int] = {}
    for row in by_id.values():
        st = str(row.get("status") or "unknown")
        counts[st] = counts.get(st, 0) + 1
    write_yaml(
        uo_root / "ir" / "resolution_ledger.yaml",
        {
            "version": 1,
            "op_name": op_name,
            "counts": counts,
            "open_unresolved_count": len(remaining),
            "items": sorted(by_id.values(), key=lambda r: str(r.get("id") or "")),
        },
    )


DECISION_TO_STATUS = {
    "resolve": "resolved",
    "resolved": "resolved",
    "accept_warning": "accepted",
    "accepted": "accepted",
    "warning": "accepted",
    "false_positive": "false_positive",
    "suppress": "false_positive",
    "alias": "alias",
}


def _coerce_status(item: dict[str, Any]) -> str | None:
    raw = item.get("status")
    if isinstance(raw, str) and raw.strip():
        return DECISION_TO_STATUS.get(raw.strip().lower(), raw.strip().lower())
    decision = item.get("decision")
    if isinstance(decision, str) and decision.strip():
        return DECISION_TO_STATUS.get(decision.strip().lower())
    # Legacy: resolution as a status string (not the optional dict evidence block).
    resolution = item.get("resolution")
    if isinstance(resolution, str) and resolution.strip():
        return DECISION_TO_STATUS.get(resolution.strip().lower())
    return None


def _normalize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Accept legacy freeform LLM shapes; always emit unresolved_resolutions."""
    if not isinstance(patch, dict):
        return {}
    out = dict(patch)
    out.setdefault("node_patches", list(patch.get("node_patches") or []))
    out.setdefault("consistency_diffs", list(patch.get("consistency_diffs") or []))
    resolutions: list[dict[str, Any]] = []
    # Prefer canonical key; fall back to freeform aliases (first non-empty wins).
    for key in ("unresolved_resolutions", "residuals", "resolutions"):
        blob = patch.get(key)
        if not isinstance(blob, list) or not blob:
            continue
        for item in blob:
            if not isinstance(item, dict):
                continue
            status = _coerce_status(item)
            if not status:
                continue
            normalized: dict[str, Any] = {
                "id": item.get("id"),
                "status": status,
                "rationale": item.get("rationale") or "",
            }
            evidence = item.get("resolution")
            if isinstance(evidence, dict):
                normalized["resolution"] = evidence
            resolutions.append(normalized)
        break
    out["unresolved_resolutions"] = resolutions
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply whitelist LLM resolution patches into operator_graph IR")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--patch", help="Path to resolution_patch.yaml")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate patch against unresolved ids without writing IR (dry-run)",
    )
    parser.add_argument(
        "--no-propagate",
        action="store_true",
        help="Disable pattern propagation (default: propagate same-pattern siblings)",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    patch = read_yaml(Path(args.patch)) if args.patch else None
    do_propagate = not bool(args.no_propagate) and not bool(args.check)
    graph = apply_resolution(
        repo_root,
        op_name,
        patch,
        dry_run=bool(args.check),
        propagate=do_propagate,
    )
    res = graph.get("resolution") or {}
    mode = "check" if args.check else "apply"
    print(
        f"{mode} applied={res.get('applied_count')} rejected={res.get('rejected_count')} "
        f"propagated={res.get('propagated_count', 0)} "
        f"remaining_unresolved={len(graph.get('unresolved') or [])}"
    )
    if res.get("rejected"):
        sample = res["rejected"][:8]
        print(f"rejected_sample={sample}")
    return 1 if args.check and int(res.get("rejected_count") or 0) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
