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

