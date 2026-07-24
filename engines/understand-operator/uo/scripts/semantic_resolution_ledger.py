"""Semantic resolution ledger: patches never mutate derived graphs directly."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.evidence_score import SEMANTIC_VERIFIED, SOURCE_VERIFIED, is_verified_confidence


class LedgerTargetTypeMismatch(Exception):
    """Patch target is a candidate node id, not a graph edge id."""

    code = "LEDGER_TARGET_TYPE_MISMATCH"


def load_ledger(uo_root: Path) -> dict[str, Any]:
    path = uo_root / "ir" / "semantic_resolution_ledger.yaml"
    data = read_yaml(path) or {}
    if not data:
        data = {"version": 1, "semantic_patches": []}
    data.setdefault("version", 1)
    data.setdefault("semantic_patches", [])
    return data


def save_ledger(uo_root: Path, payload: dict[str, Any]) -> Path:
    path = uo_root / "ir" / "semantic_resolution_ledger.yaml"
    write_yaml(path, payload)
    return path


def append_semantic_patch(uo_root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    doc = load_ledger(uo_root)
    record = dict(entry)
    record.setdefault("applied_at", datetime.now(timezone.utc).isoformat())
    record.setdefault("confidence", SEMANTIC_VERIFIED)
    record.setdefault("verification_source", "llm")
    doc["semantic_patches"].append(record)
    save_ledger(uo_root, doc)
    return record


def _is_candidate_node_id(value: Any) -> bool:
    s = str(value or "").strip()
    return s.startswith("cand_") or s.startswith("cand_EP_")


def _patch_targets(patch: dict[str, Any], *, by_id: dict[str, dict[str, Any]]) -> set[str]:
    edge_id = patch.get("edge_id")
    if edge_id:
        if _is_candidate_node_id(edge_id):
            raise LedgerTargetTypeMismatch(str(edge_id))
        return {str(edge_id)}
    accepted = [str(x) for x in (patch.get("accepted_candidate_ids") or [])]
    targets: set[str] = set()
    for cid in accepted:
        if cid in by_id:
            targets.add(cid)
    return targets


def _upgrade_edge(edge: dict[str, Any], patch: dict[str, Any]) -> None:
    edge["confidence"] = SEMANTIC_VERIFIED
    edge["verification_source"] = "llm"
    edge["ledger_task_id"] = patch.get("task_id")
    ptype = patch.get("patch_type")
    if ptype:
        edge["ledger_patch_type"] = ptype


def apply_ledger_to_entrypoint_graph(
    graph: dict[str, Any],
    ledger: dict[str, Any] | None,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Deterministically rebuild edge confidence from active ledger patches."""
    if not ledger:
        return graph
    out = dict(graph)
    edges = [dict(e) for e in (out.get("edges") or [])]
    by_id = {str(e.get("id")): e for e in edges if e.get("id")}
    nodes = {str(n.get("id")): n for n in (out.get("nodes") or []) if isinstance(n, dict) and n.get("id")}

    for patch in ledger.get("semantic_patches") or []:
        if not isinstance(patch, dict) or patch.get("status") == "stale":
            continue
        action = str(patch.get("action") or "")
        if action == "mark_missing":
            continue
        ptype = str(patch.get("patch_type") or "")
        try:
            targets = _patch_targets(patch, by_id=by_id)
        except LedgerTargetTypeMismatch as exc:
            if strict:
                raise
            patch["apply_status"] = "invalid"
            patch["apply_error"] = LedgerTargetTypeMismatch.code
            continue
        if not targets:
            continue

        if ptype in {"entrypoint_node_resolution", "template_instance_resolution"}:
            for tid in targets:
                if tid in nodes:
                    nodes[tid]["status"] = "verified"
                    nodes[tid]["confidence"] = SEMANTIC_VERIFIED
                    nodes[tid]["verification_source"] = "llm"
                    nodes[tid]["ledger_task_id"] = patch.get("task_id")
            continue

        for tid in targets:
            if tid not in by_id:
                if strict and patch.get("edge_id"):
                    raise LedgerTargetTypeMismatch(str(patch.get("edge_id")))
                continue
            _upgrade_edge(by_id[tid], patch)

    out["edges"] = edges
    if nodes and out.get("nodes"):
        out["nodes"] = [
            nodes.get(str(n.get("id")), n) if isinstance(n, dict) else n for n in (out.get("nodes") or [])
        ]
    return out


def _verify_patch_materialization(
    graph: dict[str, Any],
    ledger: dict[str, Any],
) -> tuple[dict[str, Any], int, int]:
    """Classify active patches; mutates patch apply_status on ledger copies."""
    edges = {str(e.get("id")): e for e in (graph.get("edges") or []) if isinstance(e, dict) and e.get("id")}
    nodes = {str(n.get("id")): n for n in (graph.get("nodes") or []) if isinstance(n, dict) and n.get("id")}
    materialized = 0
    unconsumed = 0
    report: dict[str, Any] = {"patches": []}

    for patch in ledger.get("semantic_patches") or []:
        if not isinstance(patch, dict):
            continue
        if patch.get("status") == "stale":
            patch["apply_status"] = "stale"
            continue
        action = str(patch.get("action") or "")
        if action == "mark_missing":
            patch["apply_status"] = "unconsumed"
            report["patches"].append({"task_id": patch.get("task_id"), "apply_status": "unconsumed"})
            unconsumed += 1
            continue
        if patch.get("apply_status") == "invalid":
            report["patches"].append({"task_id": patch.get("task_id"), "apply_status": "invalid"})
            continue
        ptype = str(patch.get("patch_type") or "")
        try:
            targets = _patch_targets(patch, by_id=edges)
        except LedgerTargetTypeMismatch:
            patch["apply_status"] = "invalid"
            patch["apply_error"] = LedgerTargetTypeMismatch.code
            report["patches"].append({"task_id": patch.get("task_id"), "apply_status": "invalid"})
            continue
        if not targets:
            patch["apply_status"] = "unconsumed"
            unconsumed += 1
            report["patches"].append({"task_id": patch.get("task_id"), "apply_status": "unconsumed"})
            continue
        hit = False
        if ptype in {"entrypoint_node_resolution", "template_instance_resolution"}:
            for tid in targets:
                node = nodes.get(tid)
                if node and is_verified_confidence(node.get("confidence")):
                    hit = True
        else:
            for tid in targets:
                edge = edges.get(tid)
                if edge and is_verified_confidence(edge.get("confidence")):
                    hit = True
        if hit:
            patch["apply_status"] = "materialized"
            materialized += 1
            report["patches"].append({"task_id": patch.get("task_id"), "apply_status": "materialized"})
        else:
            patch["apply_status"] = "unconsumed"
            unconsumed += 1
            report["patches"].append({"task_id": patch.get("task_id"), "apply_status": "unconsumed"})

    return report, materialized, unconsumed


def rebuild_derived_graphs(repo_root: Path, op_name: str, *, architecture: str = "arch35") -> dict[str, Any]:
    """Rebuild entrypoint/bridge/operator graphs from facts + ledger (⑦)."""
    from uo._operator.artifacts import existing_operator_root
    from uo.scripts.build_layered_kb import build_layered_kb
    from uo.scripts.evidence_score import _source_snapshot_hash
    from uo.scripts.resolve_entrypoints import (
        _apply_link_status,
        _build_extraction_units,
        _evaluate_closure,
        collect_entrypoint_candidates,
    )

    uo_root = existing_operator_root(repo_root, op_name)
    snap = _source_snapshot_hash(uo_root)
    stale = invalidate_stale_patches(uo_root, current_source_hash=snap)
    ledger = load_ledger(uo_root)

    candidates = collect_entrypoint_candidates(repo_root, op_name, architecture=architecture)
    graph = dict(candidates.get("entrypoint_graph") or {})
    try:
        graph = apply_ledger_to_entrypoint_graph(graph, ledger, strict=True)
    except LedgerTargetTypeMismatch as exc:
        return {"ok": False, "error": LedgerTargetTypeMismatch.code, "detail": str(exc), "stale_patches": stale}

    apply_report, materialized, unconsumed = _verify_patch_materialization(graph, ledger)
    write_yaml(uo_root / "ir" / "semantic_apply_report.yaml", apply_report)
    save_ledger(uo_root, ledger)

    nodes = {n["id"]: dict(n) for n in graph.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    edges = [dict(e) for e in (graph.get("edges") or []) if isinstance(e, dict)]
    _apply_link_status(nodes, edges)
    closure = _evaluate_closure(nodes, edges, architecture)
    extraction_units = _build_extraction_units(nodes, edges, architecture)
    graph["nodes"] = sorted(nodes.values(), key=lambda n: (n.get("role") or "", n.get("id") or ""))
    graph["edges"] = edges
    graph["closure"] = closure
    graph["extraction_units"] = extraction_units

    layers = {"host", "kernel", "tilingkey", "bridge"}
    try:
        layered = build_layered_kb(
            repo_root,
            op_name,
            architecture=architecture,
            layers=layers,
            allow_empty_plan=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300], "stale_patches": stale}

    og = read_yaml(uo_root / "ir" / "operator_graph.yaml") or layered
    try:
        og = apply_ledger_to_entrypoint_graph(og, ledger, strict=True)
    except LedgerTargetTypeMismatch as exc:
        return {"ok": False, "error": LedgerTargetTypeMismatch.code, "detail": str(exc), "stale_patches": stale}

    write_yaml(uo_root / "ir" / "entrypoint_graph.yaml", graph)
    write_yaml(uo_root / "ir" / "operator_graph.yaml", og)
    return {
        "ok": True,
        "stale_patches": stale,
        "source_snapshot_hash": snap,
        "node_count": len(og.get("nodes") or []),
        "edge_count": len(og.get("edges") or []),
        "closure": closure,
        "materialized_patch_count": materialized,
        "unconsumed_patch_count": unconsumed,
        "apply_report": apply_report,
    }


def invalidate_stale_patches(uo_root: Path, *, current_source_hash: str) -> list[str]:
    """Mark ledger patches stale when source snapshot no longer matches."""
    doc = load_ledger(uo_root)
    stale_ids: list[str] = []
    for patch in doc.get("semantic_patches") or []:
        if not isinstance(patch, dict):
            continue
        if patch.get("source_snapshot_hash") and patch["source_snapshot_hash"] != current_source_hash:
            patch["status"] = "stale"
            stale_ids.append(str(patch.get("task_id") or ""))
        else:
            patch.setdefault("status", "active")
    save_ledger(uo_root, doc)
    return stale_ids


def verified_edges_only(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in edges if is_verified_confidence(e.get("confidence"))]
