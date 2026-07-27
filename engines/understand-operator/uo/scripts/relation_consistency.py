"""Relation Graph 与 materialized plan / ledger 一致性门禁。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.semantic_relations import index_relations_by_type


def run_relation_consistency_gate(
    uo_root: Path,
    *,
    plan: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """detect_score_post / recheck 共用的 Relation 一致性检查。"""
    uo_root = Path(uo_root)
    ir = uo_root / "ir"
    errors: list[str] = []
    if plan is None:
        plan = read_yaml(ir / "extract_plan.yaml") if (ir / "extract_plan.yaml").is_file() else {}
    if graph is None:
        graph = (
            read_yaml(ir / "semantic_relations.yaml")
            if (ir / "semantic_relations.yaml").is_file()
            else {}
        )
    if not isinstance(plan, dict):
        plan = {}
    if not isinstance(graph, dict):
        return {"ok": False, "errors": ["缺少 semantic_relations.yaml"], "checks": {}}

    by_type = index_relations_by_type(graph)
    writes = by_type.get("WRITES") or []
    composes = by_type.get("COMPOSES_KEY") or []
    binds = by_type.get("BINDS") or []
    contributes = by_type.get("CONTRIBUTES_TO_KEY") or []

    writer_names = {
        str(w.get("name") or "").strip()
        for w in (plan.get("writers") or [])
        if isinstance(w, dict) and w.get("name")
    }
    for name in writer_names:
        has = any(
            name in str(r.get("subject") or "") or name == str(r.get("subject") or "").split(":")[-1]
            for r in writes + composes
        )
        if not has:
            errors.append(f"writer {name} 缺少 WRITES/COMPOSES_KEY")

    bindings_doc = read_yaml(ir / "receiver_bindings.yaml") if (ir / "receiver_bindings.yaml").is_file() else {}
    bindings = (bindings_doc or {}).get("bindings") if isinstance(bindings_doc, dict) else {}
    if isinstance(bindings, dict):
        for bref, b in bindings.items():
            if not isinstance(b, dict):
                continue
            recv = str(b.get("receiver") or "")
            if recv and not any(recv in str(r.get("subject") or "") for r in binds):
                errors.append(f"receiver binding {bref}/{recv} 缺少 BINDS")

    # key dimensions 应可达 input root
    roots = set(graph.get("input_roots") or [])
    for r in contributes:
        if not isinstance(r, dict):
            continue
        sub = str(r.get("subject") or "")
        # soft：若存在 CONTRIBUTES 但无任何 GROUNDED_IN 到 roots，记警告
        grounded = any(
            str(g.get("subject") or "") == sub and str(g.get("object") or "") in roots
            for g in (by_type.get("GROUNDED_IN") or [])
            if isinstance(g, dict)
        )
        if roots and not grounded:
            errors.append(f"key dimension {sub} 未 grounding 到真实 input_root")

    # unknown entities
    for e in graph.get("entities") or []:
        if isinstance(e, dict) and str(e.get("kind") or "") == "unknown":
            errors.append(f"unknown entity: {e.get('id')}")

    for u in graph.get("unresolved") or []:
        if isinstance(u, dict) and str(u.get("status") or "") == "conflict":
            errors.append(f"relation conflict: {u.get('obligation_id')}")

    return {
        "ok": not errors,
        "errors": errors,
        "checks": {
            "writer_count": len(writer_names),
            "writes": len(writes),
            "binds": len(binds),
            "composes": len(composes),
        },
    }


def reconcile_semantic_relations_from_ledger(uo_root: Path) -> dict[str, Any]:
    """rebuild_from_ledger 后：确保 semantic_relations 与 Host/Kernel 补丁一致戳记。"""
    uo_root = Path(uo_root)
    ir = uo_root / "ir"
    graph_path = ir / "semantic_relations.yaml"
    if not graph_path.is_file():
        return {"ok": False, "error": "缺少 semantic_relations.yaml"}
    graph = read_yaml(graph_path) or {}
    if not isinstance(graph, dict):
        return {"ok": False, "error": "semantic_relations.yaml 损坏"}
    ledger = read_yaml(ir / "confirmation_ledger.yaml") if (ir / "confirmation_ledger.yaml").is_file() else {}
    host = read_yaml(ir / "host_subgraph.yaml") if (ir / "host_subgraph.yaml").is_file() else {}
    stamp = {
        "version": 1,
        "reconciled": True,
        "ledger_present": isinstance(ledger, dict) and bool(ledger),
        "host_node_count": len((host or {}).get("nodes") or []) if isinstance(host, dict) else 0,
        "relation_count": len(graph.get("relations") or []),
    }
    graph.setdefault("meta", {})
    if isinstance(graph["meta"], dict):
        graph["meta"]["ledger_reconcile"] = stamp
    write_yaml(graph_path, graph)
    gate = run_relation_consistency_gate(uo_root, graph=graph)
    return {"ok": bool(gate.get("ok")), "stamp": stamp, "gate": gate}


__all__ = [
    "run_relation_consistency_gate",
    "reconcile_semantic_relations_from_ledger",
]
