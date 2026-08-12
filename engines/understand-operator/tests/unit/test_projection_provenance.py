# -*- coding: utf-8 -*-
"""Projection provenance / VIEW_STALE regression (FAG-style count drift)."""

from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import Relation, RelationKind
from uo_init.projection_provenance import (
    LEGACY_VIEW_UNVERIFIED,
    VIEW_STALE,
    canonical_graph_digest,
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
            attrs={},
        )
    cm.relations["R_ok"] = Relation(
        id="R_ok",
        kind=RelationKind.SELECTS,
        src="TK_SA",
        dst="K_main",
        attrs={"provenance": "test"},
    )
    return cm


def test_legacy_projection_is_not_treated_as_fresh() -> None:
    cm = _cm_with_unproven_edges(n_drop=13)
    stale_view = project_operator_graph(cm)
    for rid in list(cm.relations):
        if rid.startswith("R_unproven_"):
            cm.relations.pop(rid)
    stale_view["fingerprint"] = "same-fp"
    cm.meta["graph_fingerprint"] = "same-fp"
    assert stale_view["edge_count"] == 14
    assert len(cm.relations) == 1
    check = validate_view_against_codemap(stale_view, cm)
    assert check["ok"] is False
    assert check["reason_code"] == LEGACY_VIEW_UNVERIFIED


def test_semantic_digest_detects_rewired_graph_with_same_counts() -> None:
    left = CodeMap(op_name="toy", architecture="arch35")
    right = CodeMap(op_name="toy", architecture="arch35")
    for cm in (left, right):
        cm.add_entity(Entity(id="A", kind=EntityKind.FUNCTION, name="A", attrs={}))
        cm.add_entity(Entity(id="B", kind=EntityKind.FUNCTION, name="B", attrs={}))
        cm.add_entity(Entity(id="C", kind=EntityKind.FUNCTION, name="C", attrs={}))
    left.relations["R"] = Relation(
        id="R", kind=RelationKind.CALLS, src="A", dst="B", attrs={"provenance": "test"}
    )
    right.relations["R"] = Relation(
        id="R", kind=RelationKind.CALLS, src="A", dst="C", attrs={"provenance": "test"}
    )
    assert len(left.entities) == len(right.entities)
    assert len(left.relations) == len(right.relations)
    assert canonical_graph_digest(left) != canonical_graph_digest(right)


def test_semantic_digest_includes_projection_driving_meta() -> None:
    left = CodeMap(op_name="toy", architecture="arch35")
    right = CodeMap(op_name="toy", architecture="arch35")
    left.meta["legal_key_count"] = 1
    right.meta["legal_key_count"] = 2
    assert canonical_graph_digest(left) != canonical_graph_digest(right)


def test_semantically_stale_stamped_projection_is_view_stale() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(Entity(id="A", kind=EntityKind.FUNCTION, name="A", attrs={}))
    cm.add_entity(Entity(id="B", kind=EntityKind.FUNCTION, name="B", attrs={}))
    cm.add_entity(Entity(id="C", kind=EntityKind.FUNCTION, name="C", attrs={}))
    cm.relations["R"] = Relation(
        id="R", kind=RelationKind.CALLS, src="A", dst="B", attrs={"provenance": "test"}
    )
    stamped = stamp_provenance(project_operator_graph(cm), cm)
    cm.relations["R"] = Relation(
        id="R", kind=RelationKind.CALLS, src="A", dst="C", attrs={"provenance": "test"}
    )
    check = validate_view_against_codemap(stamped, cm)
    assert check["ok"] is False
    assert check["reason_code"] == VIEW_STALE
    assert "canonical_graph_digest" in check["mismatches"]


def test_write_codemap_reprojects_after_drop(tmp_path: Path) -> None:
    cm = _cm_with_unproven_edges(n_drop=13)
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
    assert graph["provenance"]["canonical_graph_digest"]
    assert graph["provenance"]["canonical_revision"] == graph["provenance"]["canonical_graph_digest"][:16]
    summary = load_view_blob(product, "summary")
    assert isinstance(summary, dict)
    assert summary["provenance"]["relation_count"] == 1
    check = validate_view_against_codemap(graph, cm)
    assert check["ok"] is True


def test_load_view_blob_checked_falls_back_and_hides_stale_blob(tmp_path: Path) -> None:
    cm = CodeMap(op_name="demo", architecture="arch35")
    cm.add_entity(Entity(id="E1", kind=EntityKind.VARIABLE, name="x", attrs={}))
    product = tmp_path / "demo.arch35.uo"
    write_codemap(cm, product)
    import json
    import sqlite3

    stale = {
        "schema": "uo-operator-graph/v1",
        "fingerprint": "same-fp",
        "node_count": 99,
        "edge_count": 99,
    }
    conn = sqlite3.connect(str(product))
    conn.execute(
        "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
        ("ir/operator_graph.yaml", "uo-operator-graph/v1", json.dumps(stale)),
    )
    conn.commit()
    conn.close()
    cm2 = __import__("uo_init.store.reader", fromlist=["read_codemap"]).read_codemap(product)
    out = load_view_blob_checked(product, "ir/operator_graph.yaml", codemap=cm2)
    assert out["reason_code"] == LEGACY_VIEW_UNVERIFIED
    assert out.get("fallback") == "canonical"
    assert out["view"]["edge_count"] == len(cm2.relations)
    assert out["view"]["provenance"]["relation_count"] == len(cm2.relations)
    assert out["stale_blob"]["edge_count"] == 99


def test_unrebuildable_legacy_projection_has_no_usable_view(tmp_path: Path) -> None:
    cm = CodeMap(op_name="demo", architecture="arch35")
    cm.add_entity(Entity(id="E1", kind=EntityKind.VARIABLE, name="x", attrs={}))
    product = tmp_path / "demo.arch35.uo"
    write_codemap(cm, product)
    import json
    import sqlite3

    conn = sqlite3.connect(str(product))
    conn.execute(
        "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
        ("custom/view.json", "custom/v1", json.dumps({"value": 2})),
    )
    conn.commit()
    conn.close()
    out = load_view_blob_checked(product, "custom/view.json")
    assert out["ok"] is False
    assert out["reason_code"] == LEGACY_VIEW_UNVERIFIED
    assert out["view"] is None
    assert out["stale_blob"] == {"value": 2}
