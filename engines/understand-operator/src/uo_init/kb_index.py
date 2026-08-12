# -*- coding: utf-8 -*-
"""SQLite knowledge-base product for the UO graph.

``indexes/kb_graph.sqlite`` is the on-disk authority. YAML layers are optional
exports (see ``UO_KB_YAML`` / :mod:`uo_init.dump`) reconstructed from this DB.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
  expr TEXT, status TEXT, unresolved_reason TEXT,
  FOREIGN KEY(id) REFERENCES node(id)
);
CREATE TABLE artifact(
  rel_path TEXT PRIMARY KEY, sha256 TEXT, layer TEXT,
  status TEXT, generated_at TEXT
);
CREATE TABLE view_blob(
  name TEXT PRIMARY KEY,
  schema_id TEXT,
  data TEXT NOT NULL
);
CREATE TABLE legal_key_index(
  ordinal INTEGER PRIMARY KEY,
  key_id TEXT,
  status TEXT,
  data TEXT NOT NULL
);
CREATE TABLE host_derivation_blob(
  id INTEGER PRIMARY KEY CHECK (id = 1),
  data TEXT NOT NULL
);
CREATE INDEX idx_edge_src ON edge(src, kind);
CREATE INDEX idx_edge_dst ON edge(dst, kind);
CREATE INDEX idx_node_kind ON node(kind);
CREATE INDEX idx_ev_file ON evidence(file, line_start);
CREATE INDEX idx_node_ev_evidence ON node_evidence(evidence_id);
CREATE INDEX idx_legal_key_id ON legal_key_index(key_id);
CREATE VIRTUAL TABLE evidence_fts USING fts5(
  evidence_id UNINDEXED, snippet, tokenize='unicode61'
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_json_bytes(value: Any) -> bytes:
    """Stable JSON encoding used for both view_blob storage and content hashes."""
    return _json(value).encode("utf-8")


def _meta_rows(meta: dict[str, Any] | None) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for key, value in sorted((meta or {}).items()):
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            rows.append((str(key), _json(value)))
        else:
            rows.append((str(key), str(value)))
    return rows


def write_kb_database(
    uo_root: str | Path,
    graph: dict[str, Any],
    *,
    views: dict[str, Any] | None = None,
    view_json: dict[str, str] | None = None,
    artifact_hashes: dict[str, dict[str, Any]] | None = None,
    legal_keys: list[dict[str, Any]] | None = None,
    host_derivation: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
    preserve_host_view: bool = False,
) -> dict[str, Any]:
    """Write a complete KB sqlite product (graph + view blobs + indexes).

    When ``view_json`` is provided, those pre-serialized canonical JSON strings
    are written to ``view_blob`` as-is (serialize-once). Otherwise each view in
    ``views`` is serialized with :func:`_json`.
    """
    root = Path(uo_root).expanduser().resolve()
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

    view_map = dict(views or {})
    # Always persist the canonical graph as a reconstructible blob.
    view_map.setdefault("ir/operator_graph.yaml", graph)
    # Build the final blob text once. Pre-serialized entries win.
    blob_text: dict[str, str] = {}
    if view_json:
        blob_text.update({str(k): v for k, v in view_json.items() if v is not None})
    for name, payload in view_map.items():
        key = str(name)
        if key in blob_text or payload is None:
            continue
        blob_text[key] = _json(payload)

    fingerprint = str(graph.get("fingerprint") or "")
    manifest_payload = None
    if "manifest.yaml" in blob_text:
        try:
            manifest_payload = json.loads(blob_text["manifest.yaml"])
        except json.JSONDecodeError:
            manifest_payload = None
    if not isinstance(manifest_payload, dict):
        manifest_payload = (
            view_map.get("manifest.yaml")
            if isinstance(view_map.get("manifest.yaml"), dict)
            else {}
        )
    manifest = manifest_payload if isinstance(manifest_payload, dict) else {}
    meta_out: dict[str, Any] = {
        "authority": "db",
        "graph_fingerprint": fingerprint,
        "schema": "kb_schema-v1",
        "op_name": graph.get("op_name") or manifest.get("op_name") or "",
        "architecture": graph.get("architecture") or manifest.get("architecture") or "",
        "legal_key_count": len(legal_keys or []),
        "integrity_status": "unknown",
        "hash_encoding": "canonical_json",
    }
    if isinstance(manifest, dict):
        for key in (
            "version",
            "status",
            "template_block_count",
            "schema",
            "op_name",
            "architecture",
            "legal_key_count",
        ):
            if key in manifest and manifest[key] is not None:
                meta_out[key if key != "status" else "manifest_status"] = manifest[key]
    meta_out.update(meta or {})

    host_view_snapshot: dict[str, list[tuple]] | None = None
    if preserve_host_view and target.is_file():
        host_view_snapshot = _snapshot_host_view_tables(target)

    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(SCHEMA)
        connection.executescript(HOST_VIEW_TABLES)
        for key, value in _meta_rows(meta_out):
            connection.execute(
                "INSERT INTO meta(key,value) VALUES(?,?)",
                (key, value),
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
                    _json(row.get("expr") or row.get("guard")),
                    row.get("status", "unresolved"),
                    row.get("unresolved_reason", ""),
                ),
            )

        for name, text in sorted(blob_text.items()):
            schema_id = ""
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                schema_id = str(parsed.get("schema") or parsed.get("schema_id") or "")
            connection.execute(
                "INSERT INTO view_blob(name, schema_id, data) VALUES(?,?,?)",
                (str(name), schema_id, text),
            )

        hash_rows = artifact_hashes or {}
        if not hash_rows:
            # Derive from blob bytes when caller did not pass a hash map.
            for name, text in blob_text.items():
                hash_rows[name] = {
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "status": "extracted",
                }

        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for rel_path, meta_row in sorted(hash_rows.items()):
            sha = ""
            status = "extracted"
            if isinstance(meta_row, dict):
                sha = str(meta_row.get("sha256") or "")
                status = str(meta_row.get("status") or "extracted")
            elif isinstance(meta_row, str):
                sha = meta_row
            layer = str(rel_path).split("/", 1)[0] if "/" in str(rel_path) else "root"
            connection.execute(
                "INSERT INTO artifact(rel_path, sha256, layer, status, generated_at) "
                "VALUES(?,?,?,?,?)",
                (str(rel_path), sha, layer, status, generated_at),
            )

        for ordinal, row in enumerate(legal_keys or []):
            if not isinstance(row, dict):
                continue
            connection.execute(
                "INSERT INTO legal_key_index(ordinal, key_id, status, data) VALUES(?,?,?,?)",
                (
                    ordinal,
                    str(row.get("id") or row.get("key_id") or ""),
                    str(row.get("status") or ""),
                    _json(row),
                ),
            )

        if isinstance(host_derivation, dict) and host_derivation:
            connection.execute(
                "INSERT INTO host_derivation_blob(id, data) VALUES(1, ?)",
                (_json(host_derivation),),
            )

        if host_view_snapshot:
            _restore_host_view_tables(connection, host_view_snapshot)

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
        "graph_fingerprint": fingerprint,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "evidence_count": len(evidence),
        "view_count": len(blob_text),
        "legal_key_count": len(legal_keys or []),
        "artifact_count": len(hash_rows),
        "authority": str(meta_out.get("authority") or "db"),
    }


def rebuild_index(
    uo_root: str | Path, db_path: str | Path | None = None
) -> dict[str, Any]:
    """Rebuild the KB database from YAML layers, or accept an existing DB product."""
    root = Path(uo_root).expanduser().resolve()
    target = (
        Path(db_path).expanduser().resolve()
        if db_path is not None
        else root / "indexes" / "kb_graph.sqlite"
    )
    graph_path = root / "ir" / "operator_graph.yaml"
    if graph_path.is_file():
        from uo_init.kb_export import load_graph

        graph = load_graph(root)
        views = load_yaml_view_layers(root)
        legal_keys = load_legal_key_index_rows(root)
        host_derivation = _load_yaml_dict(root / "ir" / "host_derivation.yaml")
        integrity = _load_yaml_dict(root / "checks" / "integrity.yaml")
        meta: dict[str, Any] = {"authority": "db", "rebuild_source": "yaml"}
        if integrity:
            meta["integrity_status"] = str(integrity.get("status") or "unknown")
            meta["integrity"] = integrity
        return write_kb_database(
            root,
            graph,
            views=views,
            legal_keys=legal_keys,
            host_derivation=host_derivation or None,
            meta=meta,
            db_path=target,
            preserve_host_view=True,
        )

    if target.is_file() and db_authority_ok(target):
        summary = index_summary(target)
        return {
            "ok": True,
            "database": target.as_posix(),
            "skipped_rebuild": "db_authority",
            **summary,
        }
    raise FileNotFoundError(
        f"authoritative graph missing: {graph_path} "
        f"(and no DB authority product at {target})"
    )


def load_yaml_view_layers(uo_root: str | Path) -> dict[str, Any]:
    """Load reconstructible YAML view layers from disk (best-effort)."""
    root = Path(uo_root)
    names = [
        "manifest.yaml",
        "operator.yaml",
        "quality.yaml",
        "ir/operator_graph.yaml",
        "ir/unresolved.yaml",
        "ir/host_ir.yaml",
        "ir/input_derivable.yaml",
        "ir/host_derivation.yaml",
        "ir/tg_host_view.yaml",
        "tiling/variables.yaml",
        "tiling/key_space.yaml",
        "tiling/exhaustive_key_space.yaml",
        "tiling/constraints.yaml",
        "tiling/families.yaml",
        "tiling/coverage_model.yaml",
        "tiling/data_model.yaml",
        "tiling/key_derivations.yaml",
        "views/tilingdata.yaml",
        "views/kernel.yaml",
        "views/call_graph.yaml",
        "kernel/branches.yaml",
        "kernel/paths.yaml",
        "kernel/compile_model.yaml",
        "kernel/variables.yaml",
        "kernel/resources.yaml",
        "cross_layer/tiling_to_kernel.yaml",
        "cross_layer/impact_graph.yaml",
        "cross_layer/variable_lineage.yaml",
        "flow/golden_model.yaml",
        "flow/numerical_model.yaml",
        "checks/artifact_hashes.yaml",
        "checks/integrity.yaml",
    ]
    out: dict[str, Any] = {}
    for rel in names:
        payload = _load_yaml_dict(root / rel)
        if payload is not None:
            out[rel] = payload
    return out


def load_legal_key_index_rows(uo_root: str | Path) -> list[dict[str, Any]]:
    path = Path(uo_root) / "tiling" / "legal_key_index.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _load_yaml_dict(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else None


def get_meta(db_path: str | Path) -> dict[str, str]:
    connection = sqlite3.connect(Path(db_path))
    try:
        rows = connection.execute("SELECT key, value FROM meta").fetchall()
        return {str(k): str(v) for k, v in rows}
    except sqlite3.Error:
        return {}
    finally:
        connection.close()


def db_authority_ok(db_path: str | Path) -> bool:
    """True when sqlite exists with authority=db and integrity not failing."""
    path = Path(db_path)
    if not path.is_file():
        return False
    meta = get_meta(path)
    authority = str(meta.get("authority") or "").lower()
    if authority not in {"db", "sqlite"}:
        # Legacy DBs without authority key: accept if graph_fingerprint present.
        if not meta.get("graph_fingerprint"):
            return False
    integrity = str(meta.get("integrity_status") or "").lower()
    if integrity == "fail":
        return False
    try:
        summary = index_summary(path)
    except sqlite3.Error:
        return False
    return bool(summary.get("graph_fingerprint") or summary.get("node_count"))


def materialize_lazy_view(
    db_path: str | Path, name: str, payload: Any, *, graph: dict[str, Any] | None = None
) -> Any:
    """Expand lazy projection stubs into full view documents on demand."""
    if not isinstance(payload, dict) or payload.get("status") != "lazy":
        return payload
    if graph is None:
        graph = load_view_blob_raw(db_path, "ir/operator_graph.yaml")
    if not isinstance(graph, dict):
        return payload
    edges = list(graph.get("edges") or [])
    if name == "cross_layer/impact_graph.yaml":
        return {
            "version": payload.get("version") or 1,
            "status": "extracted",
            "schema": "uo-view-impact/v1",
            "nodes": [],
            "edges": edges,
            "fingerprint": payload.get("fingerprint") or graph.get("fingerprint") or "",
            "materialized_from": "ir/operator_graph.yaml",
        }
    if name == "cross_layer/variable_lineage.yaml":
        kinds = set(payload.get("kinds") or [])
        subset = [e for e in edges if str(e.get("kind") or "") in kinds]
        return {
            "version": payload.get("version") or 1,
            "status": "extracted",
            "schema": "uo-view-lineage/v1",
            "nodes": [],
            "edges": subset,
            "fingerprint": payload.get("fingerprint") or graph.get("fingerprint") or "",
            "materialized_from": "ir/operator_graph.yaml",
        }
    return payload


def load_view_blob_raw(db_path: str | Path, name: str) -> Any | None:
    """Load a view_blob without lazy materialization."""
    connection = sqlite3.connect(Path(db_path))
    try:
        row = connection.execute(
            "SELECT data FROM view_blob WHERE name=?", (name,)
        ).fetchone()
        if not row:
            return None
        return json.loads(row[0])
    except (sqlite3.Error, json.JSONDecodeError):
        return None
    finally:
        connection.close()


def load_view_blob(db_path: str | Path, name: str) -> Any | None:
    payload = load_view_blob_raw(db_path, name)
    if payload is None:
        return None
    return materialize_lazy_view(db_path, name, payload)


def list_view_blobs(db_path: str | Path) -> list[str]:
    connection = sqlite3.connect(Path(db_path))
    try:
        rows = connection.execute(
            "SELECT name FROM view_blob ORDER BY name"
        ).fetchall()
        return [str(r[0]) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        connection.close()


def load_all_view_blobs(db_path: str | Path) -> dict[str, Any]:
    connection = sqlite3.connect(Path(db_path))
    try:
        rows = connection.execute(
            "SELECT name, data FROM view_blob ORDER BY name"
        ).fetchall()
        out: dict[str, Any] = {}
        for name, data in rows:
            try:
                out[str(name)] = json.loads(data)
            except json.JSONDecodeError:
                out[str(name)] = data
        graph = out.get("ir/operator_graph.yaml")
        if isinstance(graph, dict):
            for name, payload in list(out.items()):
                out[name] = materialize_lazy_view(
                    db_path, name, payload, graph=graph
                )
        return out
    except sqlite3.Error:
        return {}
    finally:
        connection.close()


def load_legal_keys_from_db(db_path: str | Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(Path(db_path))
    try:
        rows = connection.execute(
            "SELECT data FROM legal_key_index ORDER BY ordinal"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for (data,) in rows:
            try:
                row = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out
    except sqlite3.Error:
        return []
    finally:
        connection.close()


def load_host_derivation_from_db(db_path: str | Path) -> dict[str, Any] | None:
    connection = sqlite3.connect(Path(db_path))
    try:
        row = connection.execute(
            "SELECT data FROM host_derivation_blob WHERE id=1"
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row[0])
        return payload if isinstance(payload, dict) else None
    except (sqlite3.Error, json.JSONDecodeError):
        return None
    finally:
        connection.close()


def set_meta_values(db_path: str | Path, values: dict[str, Any]) -> None:
    connection = sqlite3.connect(Path(db_path))
    try:
        for key, value in _meta_rows(values):
            connection.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                (key, value),
            )
        connection.commit()
    finally:
        connection.close()


def index_summary(db_path: str | Path) -> dict[str, Any]:
    """Logical content summary used for idempotence checks."""
    connection = sqlite3.connect(Path(db_path))
    try:
        fingerprint = connection.execute(
            "SELECT value FROM meta WHERE key='graph_fingerprint'"
        ).fetchone()
        authority = connection.execute(
            "SELECT value FROM meta WHERE key='authority'"
        ).fetchone()
        integrity = connection.execute(
            "SELECT value FROM meta WHERE key='integrity_status'"
        ).fetchone()
        try:
            view_count = connection.execute(
                "SELECT count(*) FROM view_blob"
            ).fetchone()[0]
        except sqlite3.Error:
            view_count = 0
        try:
            legal_count = connection.execute(
                "SELECT count(*) FROM legal_key_index"
            ).fetchone()[0]
        except sqlite3.Error:
            legal_count = 0
        return {
            "graph_fingerprint": fingerprint[0] if fingerprint else "",
            "authority": authority[0] if authority else "",
            "integrity_status": integrity[0] if integrity else "",
            "node_count": connection.execute("SELECT count(*) FROM node").fetchone()[0],
            "edge_count": connection.execute("SELECT count(*) FROM edge").fetchone()[0],
            "evidence_count": connection.execute(
                "SELECT count(*) FROM evidence"
            ).fetchone()[0],
            "domain_count": connection.execute("SELECT count(*) FROM domain").fetchone()[0],
            "predicate_count": connection.execute(
                "SELECT count(*) FROM predicate"
            ).fetchone()[0],
            "view_count": view_count,
            "legal_key_count": legal_count,
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

_HOST_VIEW_TABLE_NAMES = (
    "field_writer",
    "field_guard",
    "field_meta",
    "field_read",
    "field_predicate",
    "field_generation_knob",
)


def _snapshot_host_view_tables(db_path: Path) -> dict[str, list[tuple]] | None:
    connection = sqlite3.connect(str(db_path))
    try:
        names = {
            str(r[0])
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "field_meta" not in names:
            return None
        out: dict[str, list[tuple]] = {}
        for table in _HOST_VIEW_TABLE_NAMES:
            if table not in names:
                continue
            out[table] = list(connection.execute(f"SELECT * FROM {table}").fetchall())
        fp = connection.execute(
            "SELECT value FROM meta WHERE key='host_view_fingerprint'"
        ).fetchone()
        if fp:
            out["__meta_host_view_fingerprint__"] = [(fp[0],)]
        return out
    except sqlite3.Error:
        return None
    finally:
        connection.close()


def _restore_host_view_tables(
    connection: sqlite3.Connection, snapshot: dict[str, list[tuple]]
) -> None:
    for table in _HOST_VIEW_TABLE_NAMES:
        rows = snapshot.get(table) or []
        if not rows:
            continue
        placeholders = ",".join("?" for _ in rows[0])
        connection.executemany(
            f"INSERT INTO {table} VALUES ({placeholders})",
            rows,
        )
    fp_rows = snapshot.get("__meta_host_view_fingerprint__") or []
    if fp_rows:
        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
            ("host_view_fingerprint", fp_rows[0][0]),
        )


def upsert_host_view_tables(
    uo_root: str | Path, view: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Upsert TG host-view query tables into the existing kb_graph.sqlite.

    Requires ``rebuild_index`` / ``write_kb_database`` to have already created
    the DB. Does not recreate the graph tables — only the projection side-car
    tables. Also stores the full tg_host_view document as a view_blob.
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
        # Ensure view_blob exists on legacy DBs built before D1.
        connection.execute(
            "CREATE TABLE IF NOT EXISTS view_blob("
            "name TEXT PRIMARY KEY, schema_id TEXT, data TEXT NOT NULL)"
        )
        for table in _HOST_VIEW_TABLE_NAMES:
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
        connection.execute(
            "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES(?,?,?)",
            (
                "ir/tg_host_view.yaml",
                str(view.get("schema") or "uo-view-tg-host/v1"),
                _json(view),
            ),
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
