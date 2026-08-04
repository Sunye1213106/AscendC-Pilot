# -*- coding: utf-8 -*-
"""Pure YAML -> SQLite derivation for the UO knowledge graph."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from uo_init.kb_export import load_graph

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE node(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, layer TEXT, name TEXT,
  status TEXT NOT NULL, confidence REAL NOT NULL, data TEXT NOT NULL,
  source_hash TEXT
);
CREATE TABLE edge(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL,
  status TEXT NOT NULL, confidence REAL NOT NULL, data TEXT NOT NULL,
  FOREIGN KEY(src) REFERENCES node(id), FOREIGN KEY(dst) REFERENCES node(id)
);
CREATE TABLE evidence(
  id TEXT PRIMARY KEY, node_id TEXT, file TEXT NOT NULL,
  line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
  snippet TEXT, source_hash TEXT
);
CREATE TABLE node_evidence(
  node_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
  PRIMARY KEY(node_id, evidence_id),
  FOREIGN KEY(node_id) REFERENCES node(id),
  FOREIGN KEY(evidence_id) REFERENCES evidence(id)
);
CREATE TABLE domain(
  var_id TEXT PRIMARY KEY, value_type TEXT, lo INTEGER, hi INTEGER,
  values_json TEXT, completeness TEXT, source TEXT
);
CREATE TABLE predicate(
  id TEXT PRIMARY KEY, owner_id TEXT, polarity INTEGER,
  smt TEXT, status TEXT, unresolved_reason TEXT,
  FOREIGN KEY(id) REFERENCES node(id)
);
CREATE TABLE artifact(
  rel_path TEXT PRIMARY KEY, sha256 TEXT, layer TEXT,
  status TEXT, generated_at TEXT
);
CREATE INDEX idx_edge_src ON edge(src, kind);
CREATE INDEX idx_edge_dst ON edge(dst, kind);
CREATE INDEX idx_node_kind ON node(kind);
CREATE INDEX idx_ev_file ON evidence(file, line_start);
CREATE INDEX idx_node_ev_evidence ON node_evidence(evidence_id);
CREATE VIRTUAL TABLE evidence_fts USING fts5(
  evidence_id UNINDEXED, snippet, tokenize='unicode61'
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def rebuild_index(
    uo_root: str | Path, db_path: str | Path | None = None
) -> dict[str, Any]:
    """Rebuild the disposable database from authoritative YAML only."""
    root = Path(uo_root).expanduser().resolve()
    graph = load_graph(root)
    target = (
        Path(db_path).expanduser().resolve()
        if db_path is not None
        else root / "indexes" / "kb_graph.sqlite"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()

    nodes = sorted(graph.get("nodes") or [], key=lambda row: str(row.get("id")))
    edges = sorted(graph.get("edges") or [], key=lambda row: str(row.get("id")))
    evidence = sorted(
        graph.get("evidence") or [], key=lambda row: str(row.get("id"))
    )
    domains = graph.get("domains") or {}
    owners: dict[str, list[str]] = {}
    for node in nodes:
        for evidence_id in node.get("evidence_refs") or []:
            owners.setdefault(str(evidence_id), []).append(str(node["id"]))

    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO meta(key,value) VALUES(?,?)",
            ("graph_fingerprint", str(graph.get("fingerprint") or "")),
        )
        for row in nodes:
            known = {
                "id", "kind", "layer", "name", "status", "confidence",
                "evidence_refs", "source_hash",
            }
            data = {key: value for key, value in row.items() if key not in known}
            connection.execute(
                "INSERT INTO node VALUES(?,?,?,?,?,?,?,?)",
                (
                    row["id"],
                    row.get("kind", ""),
                    row.get("layer", ""),
                    row.get("name", ""),
                    row.get("status", "unresolved"),
                    float(row.get("confidence", 0.0)),
                    _json(data),
                    row.get("source_hash", ""),
                ),
            )
        for row in edges:
            known = {"id", "kind", "src", "dst", "status", "confidence"}
            data = {key: value for key, value in row.items() if key not in known}
            connection.execute(
                "INSERT INTO edge VALUES(?,?,?,?,?,?,?)",
                (
                    row["id"], row.get("kind", ""), row["src"], row["dst"],
                    row.get("status", "unresolved"),
                    float(row.get("confidence", 0.0)), _json(data),
                ),
            )
        for row in evidence:
            evidence_id = str(row["id"])
            node_ids = sorted(owners.get(evidence_id) or [])
            connection.execute(
                "INSERT INTO evidence VALUES(?,?,?,?,?,?,?)",
                (
                    evidence_id,
                    node_ids[0] if node_ids else None,
                    row.get("file", ""),
                    int(row.get("line_start", 0)),
                    int(row.get("line_end", row.get("line_start", 0))),
                    row.get("snippet", ""),
                    row.get("source_hash", ""),
                ),
            )
            connection.execute(
                "INSERT INTO evidence_fts(evidence_id,snippet) VALUES(?,?)",
                (evidence_id, row.get("snippet", "")),
            )
            for node_id in node_ids:
                connection.execute(
                    "INSERT INTO node_evidence VALUES(?,?)",
                    (node_id, evidence_id),
                )
        for var_id, domain in sorted(domains.items()):
            connection.execute(
                "INSERT INTO domain VALUES(?,?,?,?,?,?,?)",
                (
                    var_id,
                    domain.get("type", "int"),
                    domain.get("lo"),
                    domain.get("hi"),
                    _json(domain.get("domain") or []),
                    domain.get("completeness", "open"),
                    domain.get("source", ""),
                ),
            )
        for row in nodes:
            if row.get("kind") != "Predicate":
                continue
            connection.execute(
                "INSERT INTO predicate VALUES(?,?,?,?,?,?)",
                (
                    row["id"],
                    row.get("owner_id") or row.get("branch_id"),
                    int(bool(row.get("polarity", row.get("target_value", True)))),
                    _json(row.get("smt") or row.get("guard")),
                    row.get("status", "unresolved"),
                    row.get("unresolved_reason", ""),
                ),
            )
        connection.commit()
        connection.execute("PRAGMA optimize")
        connection.commit()
    finally:
        connection.close()

    if target.exists():
        target.unlink()
    temporary.replace(target)
    return {
        "ok": True,
        "database": target.as_posix(),
        "graph_fingerprint": str(graph.get("fingerprint") or ""),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "evidence_count": len(evidence),
    }


def index_summary(db_path: str | Path) -> dict[str, Any]:
    """Logical content summary used for idempotence checks."""
    connection = sqlite3.connect(Path(db_path))
    try:
        fingerprint = connection.execute(
            "SELECT value FROM meta WHERE key='graph_fingerprint'"
        ).fetchone()
        return {
            "graph_fingerprint": fingerprint[0] if fingerprint else "",
            "node_count": connection.execute("SELECT count(*) FROM node").fetchone()[0],
            "edge_count": connection.execute("SELECT count(*) FROM edge").fetchone()[0],
            "evidence_count": connection.execute(
                "SELECT count(*) FROM evidence"
            ).fetchone()[0],
            "domain_count": connection.execute("SELECT count(*) FROM domain").fetchone()[0],
            "predicate_count": connection.execute(
                "SELECT count(*) FROM predicate"
            ).fetchone()[0],
        }
    finally:
        connection.close()


# Host-view projection tables living inside kb_graph.sqlite so TG has one
# SQLite lifecycle. Populated by export_tg_host_view after rebuild_index.
HOST_VIEW_TABLES = """
CREATE TABLE IF NOT EXISTS field_writer (
  path TEXT, function TEXT, file TEXT, line INTEGER,
  rhs TEXT, via TEXT, field TEXT
);
CREATE TABLE IF NOT EXISTS field_guard (
  file TEXT, line INTEGER, function TEXT, guard TEXT
);
CREATE TABLE IF NOT EXISTS field_meta (
  name TEXT PRIMARY KEY, kind TEXT, exactness TEXT, grade TEXT
);
CREATE TABLE IF NOT EXISTS field_read (
  field TEXT, var TEXT, root TEXT
);
CREATE TABLE IF NOT EXISTS field_predicate (
  id TEXT, file TEXT, line INTEGER, function TEXT,
  condition TEXT, feature_hint TEXT
);
CREATE TABLE IF NOT EXISTS field_generation_knob (
  field TEXT, knob TEXT
);
CREATE INDEX IF NOT EXISTS idx_fw_path ON field_writer(path);
CREATE INDEX IF NOT EXISTS idx_fw_field ON field_writer(field);
CREATE INDEX IF NOT EXISTS idx_fg_loc ON field_guard(file, line);
CREATE INDEX IF NOT EXISTS idx_fp_hint ON field_predicate(feature_hint);
"""


def upsert_host_view_tables(
    uo_root: str | Path, view: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Upsert TG host-view query tables into the existing kb_graph.sqlite.

    Requires ``rebuild_index`` to have already created the DB. Does not
    recreate the graph tables — only the projection side-car tables.
    """
    root = Path(uo_root).expanduser().resolve()
    db = root / "indexes" / "kb_graph.sqlite"
    if not db.is_file():
        return {"ok": False, "error": f"missing {db}; run build_index first"}

    if view is None:
        from uo_init.host_codemap import load_tg_host_view

        view = load_tg_host_view(root)
    if not view:
        return {"ok": False, "error": "empty tg_host_view"}

    fp = str((view.get("source") or {}).get("graph_fingerprint") or "")
    connection = sqlite3.connect(str(db))
    try:
        connection.executescript(HOST_VIEW_TABLES)
        for table in (
            "field_writer", "field_guard", "field_meta",
            "field_read", "field_predicate", "field_generation_knob",
        ):
            connection.execute(f"DELETE FROM {table}")
        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
            ("host_view_fingerprint", fp),
        )
        for f in view.get("fields") or []:
            name = f.get("name")
            connection.execute(
                "INSERT OR REPLACE INTO field_meta VALUES (?,?,?,?)",
                (name, f.get("kind"), f.get("exactness"), f.get("grade")),
            )
            for r in f.get("reads") or []:
                connection.execute(
                    "INSERT INTO field_read VALUES (?,?,?)",
                    (name, r.get("var"), r.get("root")),
                )
                root_name = str(r.get("root") or "")
                if root_name:
                    connection.execute(
                        "INSERT INTO field_generation_knob VALUES (?,?)",
                        (name, root_name),
                    )
            for w in f.get("writers") or []:
                connection.execute(
                    "INSERT INTO field_writer VALUES (?,?,?,?,?,?,?)",
                    (w.get("path"), w.get("function"), w.get("file"),
                     int(w.get("line") or 0), w.get("rhs"),
                     w.get("via") or "direct", name),
                )
                for g in w.get("guards") or []:
                    connection.execute(
                        "INSERT INTO field_guard VALUES (?,?,?,?)",
                        (w.get("file"), int(w.get("line") or 0),
                         w.get("function"), str(g)),
                    )
        for p in view.get("predicates") or []:
            connection.execute(
                "INSERT INTO field_predicate VALUES (?,?,?,?,?,?)",
                (p.get("id"), p.get("file"), int(p.get("line") or 0),
                 p.get("function"), p.get("condition"), p.get("feature_hint")),
            )
        connection.commit()
        writer_count = connection.execute(
            "SELECT count(*) FROM field_writer"
        ).fetchone()[0]
        pred_count = connection.execute(
            "SELECT count(*) FROM field_predicate"
        ).fetchone()[0]
    finally:
        connection.close()
    return {
        "ok": True,
        "database": db.as_posix(),
        "host_view_fingerprint": fp,
        "field_writer_count": writer_count,
        "field_predicate_count": pred_count,
        "field_count": len(view.get("fields") or []),
    }

