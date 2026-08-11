# -*- coding: utf-8 -*-
"""D1–D4: DB authority, dump reconstruct, source locator."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from uo_init.dump import dump_view, resolve_view_name
from uo_init.ids import named_id, predicate_id
from uo_init.kb_export import export_kb, yaml_export_enabled
from uo_init.kb_index import (
    db_authority_ok,
    get_meta,
    index_summary,
    load_legal_keys_from_db,
    load_view_blob,
    rebuild_index,
)
from uo_init.kb_model import Domain, Edge, Evidence, KnowledgeBase, Node
from uo_init.source_locator import SourceLocator, open_locator
from uo_init.uo_query import open_query


def _sample_kb() -> KnowledgeBase:
    kb = KnowledgeBase("SampleOp", "arch35")
    source = "op_host/sample_tiling.cpp"
    key_ev = Evidence.at(source, 10, snippet="KEY_MODE")
    branch_ev = Evidence.at(source, 30, snippet="if (mode == 1)")
    key = Node(
        id=named_id("TilingKeyDim", "mode"),
        kind="TilingKeyDim",
        name="mode",
        layer="tiling",
        evidence=[key_ev],
    )
    variable = Node(
        id=named_id("Variable", "key_mode"),
        kind="Variable",
        name="key_mode",
        layer="variables",
        evidence=[key_ev],
    )
    branch = Node(
        id="HBR_0123456789AB",
        kind="HostBranch",
        name="mode branch",
        layer="host",
        evidence=[branch_ev],
    )
    predicate = Node(
        id=predicate_id(branch.id, True, '{"op":"eq","value":1}'),
        kind="Predicate",
        name="mode == 1",
        layer="constraints",
        data={
            "owner_id": branch.id,
            "polarity": True,
            "smt": {"op": "eq", "var": variable.id, "value": 1},
        },
        evidence=[branch_ev],
    )
    field = Node(
        id=named_id("TilingDataField", "tile.M"),
        kind="TilingDataField",
        name="tile.M",
        layer="tiling",
        data={"struct": "Tile", "ctype": "uint32_t"},
        evidence=[key_ev],
    )
    for node in (key, variable, branch, predicate, field):
        kb.add_node(node)
    kb.add_domain(
        Domain(
            var_id=variable.id,
            value_type="enum",
            values=[0, 1],
            completeness="closed",
            source="template_key",
        )
    )
    kb.add_edge(Edge.make("encodes", key.id, variable.id))
    kb.add_edge(Edge.make("controls", variable.id, branch.id))
    kb.add_edge(Edge.make("guards", predicate.id, branch.id))
    kb.notes["quality"] = {
        "source_closure": 1.0,
        "input_controllability": 1.0,
        "predicate_normalization": 1.0,
    }
    kb.notes["tiling_materialize"] = {
        "ok": True,
        "dimensions": [{"id": key.id, "name": "mode", "input_derivable": True}],
        "template_blocks": [{"id": "TB1", "product_count": 2}],
        "legal_keys": [{"id": "K0", "status": "reachable", "values": {"mode": 0}}],
        "key_field_obligations": {"mode": {"id": "COV_mode"}},
        "field_order": ["mode"],
        "key_status_counts": {"reachable": 1},
        "host_reachability": {"status": "not_computed"},
    }
    kb.notes["tiling_data_view"] = {
        "schema": "uo-view-tilingdata/v1",
        "version": 1,
        "status": "extracted",
        "structs": [{"name": "Tile", "fields": [{"name": "M"}]}],
        "constants": [],
    }
    return kb


def test_yaml_export_is_opt_in(monkeypatch):
    """The DB is the single product; a YAML copy is something to ask for."""
    monkeypatch.delenv("UO_KB_YAML", raising=False)
    assert yaml_export_enabled() is False
    monkeypatch.setenv("UO_KB_YAML", "1")
    assert yaml_export_enabled() is True
    monkeypatch.setenv("UO_KB_YAML", "0")
    assert yaml_export_enabled() is False


def test_db_only_export_writes_no_yaml_layers(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UO_KB_YAML", raising=False)
    root = tmp_path / "uo"
    receipt = export_kb(_sample_kb(), root)
    assert receipt["yaml_export"] is False
    assert Path(receipt["database"]).is_file()
    assert not list(root.glob("*.yaml"))
    assert not (root / "ir").exists()
    # Still fully reviewable: every view reconstructs from the DB.
    assert isinstance(load_view_blob(Path(receipt["database"]), "quality.yaml"), dict)


def test_export_writes_db_with_view_blobs(tmp_path: Path):
    root = tmp_path / "uo"
    receipt = export_kb(_sample_kb(), root)
    db = Path(receipt["database"])
    assert db.is_file()
    assert db_authority_ok(db)
    meta = get_meta(db)
    assert meta.get("authority") == "db"
    assert meta.get("graph_fingerprint")
    quality = load_view_blob(db, "quality.yaml")
    assert isinstance(quality, dict)
    tilingdata = load_view_blob(db, "views/tilingdata.yaml")
    assert isinstance(tilingdata, dict)
    kernel = load_view_blob(db, "views/kernel.yaml")
    assert isinstance(kernel, dict)
    legal_keys = load_legal_keys_from_db(db)
    assert legal_keys and legal_keys[0]["id"] == "K0"
    summary = index_summary(db)
    assert summary["legal_key_count"] == 1
    assert summary["view_count"] >= 5


def test_db_only_export_skips_yaml(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UO_KB_YAML", "0")
    root = tmp_path / "uo"
    receipt = export_kb(_sample_kb(), root)
    assert receipt["yaml_export"] is False
    assert not (root / "manifest.yaml").is_file()
    assert (root / "indexes" / "kb_graph.sqlite").is_file()
    # rebuild_index should accept DB authority without YAML
    out = rebuild_index(root)
    assert out.get("ok")
    assert out.get("skipped_rebuild") == "db_authority"


def test_dump_reconstructs_manifest_and_quality(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UO_KB_YAML", "0")
    root = tmp_path / "uo"
    export_kb(_sample_kb(), root)
    out = tmp_path / "manifest.yaml"
    result = dump_view(root, "manifest", out=out)
    assert result["ok"]
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert doc["authority"] == "db"
    assert resolve_view_name("tilingdata") == "views/tilingdata.yaml"
    td = dump_view(root, "tilingdata")
    assert td["payload"]["schema"] == "uo-view-tilingdata/v1"


def test_source_locator_finds_dim_branch_field(tmp_path: Path):
    root = tmp_path / "uo"
    export_kb(_sample_kb(), root)
    loc = open_locator(root)
    dims = loc.locate_dim("mode")
    assert dims
    assert dims[0].file.endswith("sample_tiling.cpp")
    assert dims[0].line_start == 10
    assert dims[0].window_sha256

    branches = loc.locate_branch("HBR_0123456789AB")
    assert branches
    assert branches[0].line_start == 30

    fields = loc.locate_field("tile.M")
    assert fields
    assert fields[0].kind == "TilingDataField"

    # UoQuery wrappers
    q = open_query(root)
    assert q.locate("mode", kinds=["TilingKeyDim"])
    assert q.locate_dim("mode")
    assert q.locate_branch("HBR_0123456789AB")
    assert q.locate_field("tile.M")


def test_in_memory_sqlite_locator_fixture(tmp_path: Path):
    """Tiny temp sqlite fixture for locate without full export YAML set."""
    from uo_init.kb_index import write_kb_database

    graph = {
        "version": 1,
        "fingerprint": "fp-test",
        "op_name": "Tiny",
        "architecture": "arch35",
        "nodes": [
            {
                "id": "KEY_MODE",
                "kind": "TilingKeyDim",
                "name": "mode",
                "layer": "tiling",
                "status": "extracted",
                "confidence": 1.0,
                "evidence_refs": ["EV1"],
            }
        ],
        "edges": [],
        "evidence": [
            {
                "id": "EV1",
                "file": "a.cpp",
                "line_start": 7,
                "line_end": 7,
                "snippet": "mode",
                "source_hash": "",
            }
        ],
        "domains": {},
        "blockers": [],
        "notes": {},
    }
    root = tmp_path / "uo"
    write_kb_database(
        root,
        graph,
        views={"manifest.yaml": {"authority": "db", "graph_fingerprint": "fp-test"}},
        meta={"authority": "db", "integrity_status": "pass"},
    )
    hits = SourceLocator(root / "indexes" / "kb_graph.sqlite").locate("mode")
    assert len(hits) == 1
    assert hits[0].file == "a.cpp"
    assert hits[0].line_start == 7
