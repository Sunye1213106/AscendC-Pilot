"""TG built_kb_ready / load_built_kb accept DB-only UO products."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from testcase_agent.understand import built_kb_ready, load_built_kb


def _write_db_product(uo: Path) -> Path:
    db = uo / "indexes" / "kb_graph.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    schema = """
    CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE node(
      id TEXT PRIMARY KEY, kind TEXT NOT NULL, layer TEXT, name TEXT,
      status TEXT NOT NULL, confidence REAL NOT NULL, data TEXT NOT NULL,
      source_hash TEXT
    );
    CREATE TABLE edge(
      id TEXT PRIMARY KEY, kind TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL,
      status TEXT NOT NULL, confidence REAL NOT NULL, data TEXT NOT NULL
    );
    CREATE TABLE evidence(
      id TEXT PRIMARY KEY, node_id TEXT, file TEXT NOT NULL,
      line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
      snippet TEXT, source_hash TEXT
    );
    CREATE TABLE node_evidence(
      node_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
      PRIMARY KEY(node_id, evidence_id)
    );
    CREATE TABLE domain(
      var_id TEXT PRIMARY KEY, value_type TEXT, lo INTEGER, hi INTEGER,
      values_json TEXT, completeness TEXT, source TEXT
    );
    CREATE TABLE predicate(
      id TEXT PRIMARY KEY, owner_id TEXT, polarity INTEGER,
      expr TEXT, status TEXT, unresolved_reason TEXT
    );
    CREATE TABLE artifact(
      rel_path TEXT PRIMARY KEY, sha256 TEXT, layer TEXT,
      status TEXT, generated_at TEXT
    );
    CREATE TABLE view_blob(
      name TEXT PRIMARY KEY, schema_id TEXT, data TEXT NOT NULL
    );
    CREATE TABLE legal_key_index(
      ordinal INTEGER PRIMARY KEY, key_id TEXT, status TEXT, data TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE evidence_fts USING fts5(
      evidence_id UNINDEXED, snippet, tokenize='unicode61'
    );
    """
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(schema)
        for key, value in (
            ("authority", "db"),
            ("graph_fingerprint", "fp-tg"),
            ("integrity_status", "pass"),
            ("op_name", "TinyOp"),
        ):
            conn.execute("INSERT INTO meta(key,value) VALUES(?,?)", (key, value))
        views = {
            "quality.yaml": {"version": 1, "status": "pass"},
            "tiling/variables.yaml": {"version": 1, "status": "extracted", "variables": {}},
            "tiling/key_space.yaml": {
                "version": 1,
                "status": "extracted",
                "dimensions": [{"name": "mode"}],
            },
            "tiling/exhaustive_key_space.yaml": {
                "version": 1,
                "status": "extracted",
                "template_blocks": [{"id": "TB1"}],
            },
            "tiling/constraints.yaml": {"version": 1, "status": "extracted"},
            "tiling/families.yaml": {
                "version": 1,
                "status": "extracted",
                "nodes": [{"id": "FAM_DEFAULT", "kind": "Family"}],
            },
            "tiling/coverage_model.yaml": {
                "version": 1,
                "status": "extracted",
                "key_field_obligations": {"mode": {"id": "COV_mode"}},
            },
            "kernel/branches.yaml": {"version": 1, "status": "extracted", "branches": []},
            "kernel/variables.yaml": {"version": 1, "status": "extracted"},
            "kernel/paths.yaml": {"version": 1, "status": "extracted"},
            "kernel/compile_model.yaml": {"version": 1, "status": "extracted"},
            "cross_layer/impact_graph.yaml": {"version": 1, "status": "extracted"},
            "cross_layer/tiling_to_kernel.yaml": {"version": 1, "status": "extracted"},
            "checks/artifact_hashes.yaml": {
                "version": 1,
                "hashes": {"quality.yaml": "a" * 64},
            },
            "manifest.yaml": {
                "version": 1,
                "authority": "db",
                "graph_fingerprint": "fp-tg",
            },
        }
        for name, payload in views.items():
            conn.execute(
                "INSERT INTO view_blob(name, schema_id, data) VALUES(?,?,?)",
                (name, "", json.dumps(payload, sort_keys=True)),
            )
        conn.commit()
    finally:
        conn.close()
    return db


def test_built_kb_ready_accepts_db_only(tmp_path: Path, monkeypatch) -> None:
    uo = tmp_path / "uo"
    _write_db_product(uo)
    # Point import path at in-tree uo_init.
    src = Path(__file__).resolve().parents[2] / "understand-operator" / "src"
    monkeypatch.syspath_prepend(str(src))
    assert built_kb_ready(uo) is True
    payload = load_built_kb(uo, "TinyOp")
    assert payload["intake_mode"] == "built_kb_db"
    assert "tiling/coverage_model.yaml" in payload["files"]
    assert payload["files"]["manifest.yaml"]["authority"] == "db"


def test_tg_source_locator_wrapper(tmp_path: Path, monkeypatch) -> None:
    from testcase_agent import source_locator as sl

    uo = tmp_path / "uo"
    db = _write_db_product(uo)
    # Add a node+evidence so locate returns something.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO node VALUES(?,?,?,?,?,?,?,?)",
            ("KEY_MODE", "TilingKeyDim", "tiling", "mode", "extracted", 1.0, "{}", ""),
        )
        conn.execute(
            "INSERT INTO evidence VALUES(?,?,?,?,?,?,?)",
            ("EV1", "KEY_MODE", "x.cpp", 3, 3, "mode", ""),
        )
        conn.execute("INSERT INTO node_evidence VALUES(?,?)", ("KEY_MODE", "EV1"))
        conn.commit()
    finally:
        conn.close()
    src = Path(__file__).resolve().parents[2] / "understand-operator" / "src"
    monkeypatch.syspath_prepend(str(src))
    hits = sl.locate("mode", uo_root=uo, kinds=["TilingKeyDim"])
    assert hits
    assert hits[0]["file"] == "x.cpp"
    assert hits[0]["line_start"] == 3
