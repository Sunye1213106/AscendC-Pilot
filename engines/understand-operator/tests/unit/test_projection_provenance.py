# -*- coding: utf-8 -*-
"""Projection provenance / VIEW_STALE regression (FAG-style count drift)."""

from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import Relation, RelationKind
from uo_init.projection_provenance import (
    VIEW_STALE,
    stamp_provenance,
    validate_view_against_codemap,
)
from uo_init.store.reader import load_view_blob, load_view_blob_checked
from uo_init.store.writer import write_codemap
from uo_init.tg_views import finalize_tg_views, project_operator_graph


def _cm_with_unproven_edges(*, n_drop: int = 13) -> CodeMap:
    cm = CodeMap(op_name="FlashAttentionScoreGrad", architecture="arch35")
    cm.add_entity(Entity(id="TK_SA", kind=EntityKind.TILING_KEY, name="SplitAxis", attrs={"source_declared": True}))
    cm.add_entity(Entity(id="K_main", kind=EntityKind.KERNEL, name="main", attrs={}))
    for i in range(n_drop):
        cm.relations[f"R_unproven_{i}"] = Relation(
            id=f"R_unproven_{i}",
            kind=RelationKind.SELECTS,
            src="TK_SA",
            dst="K_main",
            attrs={},  # no provenance → dropped on write
        )
    # one proven edge retained
    cm.relations["R_ok"] = Relation(
        id="R_ok",
        kind=RelationKind.SELECTS,
        src="TK_SA",
        dst="K_main",
        attrs={"provenance": "test"},
    )
    return cm


def test_validate_detects_fingerprint_same_count_drift() -> None:
    """Same fingerprint field + mismatched edge_count → VIEW_STALE (13-edge class)."""
    cm = _cm_with_unproven_edges(n_drop=13)
    # Simulate legacy bad commit: stamp graph *before* drop, then drop edges.
    stale_view = project_operator_graph(cm)
    for rid in list(cm.relations):
        if rid.startswith("R_unproven_"):
            cm.relations.pop(rid)
    # Fingerprint kind-hist may change; force equal fingerprint to mimic observed bug.
    stale_view["fingerprint"] = "same-fp"
    cm.meta["graph_fingerprint"] = "same-fp"
    stale_view["edge_count"] = int(stale_view["edge_count"])  # pre-drop
    assert stale_view["edge_count"] == 14  # 13 unproven + 1 proven
    assert len(cm.relations) == 1
    check = validate_view_against_codemap(stale_view, cm)
    assert check["ok"] is False
    assert check["reason_code"] == VIEW_STALE
    assert "relation_count" in (check.get("mismatches") or [])


def test_write_codemap_reprojects_after_drop(tmp_path: Path) -> None:
    cm = _cm_with_unproven_edges(n_drop=13)
    # Pre-drop finalize (caller mistake); write must still align.
    views = finalize_tg_views(cm, existing={})
    assert views["ir/operator_graph.yaml"]["edge_count"] == 14
    product = tmp_path / "FlashAttentionScoreGrad.arch35.uo"
    written = write_codemap(cm, product, views=views)
    assert written["ok"]
    assert written["relations"] == 1
    graph = load_view_blob(product, "ir/operator_graph.yaml")
    assert isinstance(graph, dict)
    assert graph["edge_count"] == 1
    assert graph["provenance"]["relation_count"] == 1
    summary = load_view_blob(product, "summary")
    assert isinstance(summary, dict)
    assert summary["provenance"]["relation_count"] == 1
    check = validate_view_against_codemap(graph, cm)
    assert check["ok"] is True


def test_load_view_blob_checked_falls_back(tmp_path: Path) -> None:
    cm = CodeMap(op_name="demo", architecture="arch35")
    cm.add_entity(Entity(id="E1", kind=EntityKind.VARIABLE, name="x", attrs={}))
    product = tmp_path / "demo.arch35.uo"
    write_codemap(cm, product)
    # Inject stale operator_graph manually
    import json
    import sqlite3

    stale = {
        "schema": "uo-operator-graph/v1",
        "fingerprint": "same-fp",
        "node_count": 99,
        "edge_count": 99,
    }
    cm2 = __import__("uo_init.store.reader", fromlist=["read_codemap"]).read_codemap(product)
    cm2.meta["graph_fingerprint"] = "same-fp"
    conn = sqlite3.connect(str(product))
    conn.execute(
        "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
        ("ir/operator_graph.yaml", "uo-operator-graph/v1", json.dumps(stale)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)",
        ("cm_graph_fingerprint", "same-fp"),
    )
    conn.commit()
    conn.close()
    cm2 = __import__("uo_init.store.reader", fromlist=["read_codemap"]).read_codemap(product)
    out = load_view_blob_checked(product, "ir/operator_graph.yaml", codemap=cm2)
    assert out["reason_code"] == VIEW_STALE or out.get("fallback") == "canonical"
    assert out.get("fallback") == "canonical"
    assert out["view"]["edge_count"] == len(cm2.relations)
    assert out["view"]["provenance"]["relation_count"] == len(cm2.relations)
