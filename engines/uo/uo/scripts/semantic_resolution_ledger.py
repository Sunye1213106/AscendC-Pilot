"""Semantic resolution ledger: patches never mutate derived graphs directly."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.evidence_score import SEMANTIC_VERIFIED, SOURCE_VERIFIED, is_verified_confidence


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


def apply_ledger_to_entrypoint_graph(graph: dict[str, Any], ledger: dict[str, Any] | None) -> dict[str, Any]:
    """Deterministically rebuild edge confidence from active ledger patches.

    Only upgrades edges explicitly referenced by ``edge_id`` or exact
    ``accepted_candidate_ids``. Never batch-upgrades by relation alone.
    """
    if not ledger:
        return graph
    out = dict(graph)
    edges = [dict(e) for e in (out.get("edges") or [])]
    by_id = {str(e.get("id")): e for e in edges}
    for patch in ledger.get("semantic_patches") or []:
        if not isinstance(patch, dict) or patch.get("status") == "stale":
            continue
        if patch.get("action") == "mark_missing":
            continue
        edge_id = patch.get("edge_id")
        accepted = [str(x) for x in (patch.get("accepted_candidate_ids") or [])]
        targets: set[str] = set()
        if edge_id:
            targets.add(str(edge_id))
        for cid in accepted:
            if cid in by_id:
                targets.add(cid)
        if not targets:
            # Refuse relation-wide upgrades — patch must name concrete candidates.
            continue
        for tid in targets:
            if tid not in by_id:
                continue
            by_id[tid]["confidence"] = SEMANTIC_VERIFIED
            by_id[tid]["verification_source"] = "llm"
            by_id[tid]["ledger_task_id"] = patch.get("task_id")
    out["edges"] = edges
    return out


def rebuild_derived_graphs(repo_root: Path, op_name: str, *, architecture: str = "arch35") -> dict[str, Any]:
    """Rebuild entrypoint/bridge/operator graphs from facts + ledger (⑦)."""
    from uo._operator.artifacts import existing_operator_root
    from uo.scripts.build_layered_kb import build_layered_kb
    from uo.scripts.evidence_score import _source_snapshot_hash
    from uo.scripts.resolve_entrypoints import collect_entrypoint_candidates

    uo_root = existing_operator_root(repo_root, op_name)
    snap = _source_snapshot_hash(uo_root)
    stale = invalidate_stale_patches(uo_root, current_source_hash=snap)
    ledger = load_ledger(uo_root)

    # Re-collect entrypoints then apply ledger upgrades.
    candidates = collect_entrypoint_candidates(repo_root, op_name, architecture=architecture)
    graph = dict(candidates.get("entrypoint_graph") or {})
    graph = apply_ledger_to_entrypoint_graph(graph, ledger)
    write_yaml(uo_root / "ir" / "entrypoint_graph.yaml", graph)

    # Rebuild layered KB from existing plan/layers when present.
    layers = {"entrypoints", "host", "kernel", "tilingkey", "bridge"}
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

    # Re-apply ledger onto operator_graph edges.
    og = read_yaml(uo_root / "ir" / "operator_graph.yaml") or layered
    og = apply_ledger_to_entrypoint_graph(og, ledger)
    write_yaml(uo_root / "ir" / "operator_graph.yaml", og)
    return {
        "ok": True,
        "stale_patches": stale,
        "source_snapshot_hash": snap,
        "node_count": len(og.get("nodes") or []),
        "edge_count": len(og.get("edges") or []),
    }


def verified_edges_only(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in edges if is_verified_confidence(e.get("confidence"))]
