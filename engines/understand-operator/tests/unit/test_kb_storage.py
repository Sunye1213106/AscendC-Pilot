# -*- coding: utf-8 -*-
import hashlib
import json
import sqlite3
from pathlib import Path

import yaml

from uo_init.ids import named_id, predicate_id
from uo_init.kb_export import canonical_json_bytes, export_kb
from uo_init.kb_index import index_summary, rebuild_index
from uo_init.kb_model import Domain, Edge, Evidence, KnowledgeBase, Node
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
            "expr": {"op": "eq", "var": variable.id, "value": 1},
        },
        evidence=[branch_ev],
    )
    for node in (key, variable, branch, predicate):
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
    return kb


def test_db_is_authority_and_sqlite_rebuild_is_idempotent(tmp_path: Path):
    root = tmp_path / "uo"
    receipt = export_kb(_sample_kb(), root)
    first = rebuild_index(root)
    first_summary = index_summary(first["database"])
    second = rebuild_index(root)
    assert index_summary(second["database"]) == first_summary
    assert receipt["graph_fingerprint"] == first_summary["graph_fingerprint"]
    assert first_summary.get("authority") == "db"
    assert receipt.get("authority") == "db"

    from uo_init.kb_index import load_view_blob

    db = Path(first["database"])
    manifest = load_view_blob(db, "manifest.yaml")
    assert manifest["authority"] == "db"
    assert manifest["derived_index"] == "indexes/kb_graph.sqlite"
    hashes = load_view_blob(db, "checks/artifact_hashes.yaml")
    assert isinstance(hashes.get("hashes"), dict) and hashes["hashes"]
    assert "tiling/variables.yaml" in hashes["hashes"]
    assert hashes.get("encoding") == "canonical_json"
    assert receipt.get("hash_encoding") == "canonical_json"

    # Serialize-once: artifact table sha256 matches view_blob bytes.
    conn = sqlite3.connect(db)
    try:
        blob = conn.execute(
            "SELECT data FROM view_blob WHERE name = ?",
            ("tiling/variables.yaml",),
        ).fetchone()[0]
        art = conn.execute(
            "SELECT sha256 FROM artifact WHERE rel_path = ?",
            ("tiling/variables.yaml",),
        ).fetchone()
        assert art is not None
        assert art[0] == hashlib.sha256(blob.encode("utf-8")).hexdigest()
        assert art[0] == hashes["hashes"]["tiling/variables.yaml"]
        assert get_meta_hash_encoding(conn) == "canonical_json"
    finally:
        conn.close()


def get_meta_hash_encoding(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ?", ("hash_encoding",)
    ).fetchone()
    return row[0] if row else ""


def test_canonical_json_bytes_stable():
    payload = {"b": 2, "a": [1, {"z": 0}]}
    raw = canonical_json_bytes(payload)
    assert raw == json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def test_lazy_impact_graph_materializes_from_edges(tmp_path: Path):
    from uo_init.kb_index import load_view_blob, load_view_blob_raw

    root = tmp_path / "uo"
    export_kb(_sample_kb(), root)
    db = root / "indexes" / "kb_graph.sqlite"
    stub = load_view_blob_raw(db, "cross_layer/impact_graph.yaml")
    assert isinstance(stub, dict) and stub.get("status") == "lazy"
    full = load_view_blob(db, "cross_layer/impact_graph.yaml")
    assert isinstance(full, dict)
    assert full.get("status") == "extracted"
    assert isinstance(full.get("edges"), list) and full["edges"]
    assert full.get("materialized_from") == "ir/operator_graph.yaml"


def test_fixed_queries_return_evidence_and_recursive_impact(tmp_path: Path):
    root = tmp_path / "uo"
    kb = _sample_kb()
    export_kb(kb, root)
    rebuild_index(root)
    query = open_query(root)

    key_id = named_id("TilingKeyDim", "mode")
    branches = query.branches_for_key(key_id)
    assert [row["kind"] for row in branches] == ["HostBranch"]
    assert branches[0]["evidence_refs"]

    impacted = query.impact_of("op_host/sample_tiling.cpp", (10, 10))
    assert {row["kind"] for row in impacted} >= {
        "TilingKeyDim",
        "Variable",
        "HostBranch",
        "Predicate",
    }
    assert all("evidence_refs" in row for row in impacted)
