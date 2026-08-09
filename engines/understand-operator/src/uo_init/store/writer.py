# -*- coding: utf-8 -*-
"""Write a CodeMap into ``<op>.<arch>.uo`` (SQLite)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.store.schema import SCHEMA_SQL, SCHEMA_VERSION


def uo_product_dir(op_root: str | Path) -> Path:
    """``.ascendc-pilot/uo/`` — arch-neutral product directory."""
    root = Path(op_root).expanduser().resolve()
    return root / ".ascendc-pilot" / "uo"


def uo_product_path(
    op_root: str | Path,
    op_name: str,
    architecture: str,
) -> Path:
    safe_op = (op_name or "operator").replace("/", "_").replace("\\", "_")
    arch = (architecture or "arch35").strip() or "arch35"
    return uo_product_dir(op_root) / f"{safe_op}.{arch}.uo"


def write_codemap(
    codemap: CodeMap,
    path: str | Path,
    *,
    views: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist CodeMap to ``path`` (``.uo`` SQLite). Overwrites atomically."""
    dest = Path(path).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    # User-facing/queryable summaries must use the same soundness semantics as
    # uo-query and uo-dump. The legacy CodeMap.summary() fallback may infer a
    # Host→Kernel path from node presence alone, so never persist it verbatim.
    from uo_init.diagnostics.audit import audit_codemap

    strict_summary = dict(audit_codemap(codemap)["summary"])

    conn = sqlite3.connect(str(tmp))
    try:
        conn.executescript(SCHEMA_SQL)
        _write_meta(
            conn,
            {
                "schema": SCHEMA_VERSION,
                "authority": "uo",
                "op_name": codemap.op_name,
                "architecture": codemap.architecture,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "entity_count": str(len(codemap.entities)),
                "relation_count": str(len(codemap.relations)),
                **{k: _jsonable(v) for k, v in (meta or {}).items()},
                **{f"cm_{k}": _jsonable(v) for k, v in codemap.meta.items()},
            },
        )
        # Build variants.
        for ent in codemap.by_kind("BUILD_VARIANT"):
            conn.execute(
                "INSERT OR REPLACE INTO build_variant(id, name, architecture, data) VALUES (?,?,?,?)",
                (
                    ent.id,
                    ent.name,
                    codemap.architecture,
                    json.dumps(ent.to_dict(), ensure_ascii=False),
                ),
            )
        # Entities.
        for ent in codemap.entities.values():
            data = ent.to_dict()
            conn.execute(
                "INSERT OR REPLACE INTO entity("
                "id, kind, name, status, confidence, file, line_start, line_end, data"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    ent.id,
                    ent.kind_name(),
                    ent.name,
                    ent.status,
                    float(ent.confidence),
                    ent.file,
                    int(ent.line_start),
                    int(ent.line_end),
                    json.dumps(data, ensure_ascii=False),
                ),
            )
            if ent.file:
                conn.execute(
                    "INSERT OR IGNORE INTO file(id, path, sha256, role) VALUES (?,?,?,?)",
                    (ent.file, ent.file, "", ent.attrs.get("layer") or ""),
                )
                span_id = f"span:{ent.id}"
                conn.execute(
                    "INSERT OR REPLACE INTO source_span("
                    "id, entity_id, file, line_start, line_end, snippet"
                    ") VALUES (?,?,?,?,?,?)",
                    (
                        span_id,
                        ent.id,
                        ent.file,
                        int(ent.line_start),
                        int(ent.line_end or ent.line_start),
                        str(ent.attrs.get("snippet") or "")[:400],
                    ),
                )
            for key, value in ent.attrs.items():
                conn.execute(
                    "INSERT OR REPLACE INTO attribute(entity_id, key, value) VALUES (?,?,?)",
                    (ent.id, str(key), _jsonable(value)),
                )
        # Relations (defer FK: insert entities first — done).
        for rel in codemap.relations.values():
            # Skip dangling edges.
            if rel.src not in codemap.entities or rel.dst not in codemap.entities:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO relation("
                "id, kind, src, dst, status, confidence, data"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    rel.id,
                    rel.kind_name(),
                    rel.src,
                    rel.dst,
                    rel.status,
                    float(rel.confidence),
                    json.dumps(rel.to_dict(), ensure_ascii=False),
                ),
            )
        for name, payload in (views or {}).items():
            conn.execute(
                "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
                (
                    str(name),
                    str((payload or {}).get("schema") or "")
                    if isinstance(payload, dict)
                    else "",
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        # Summary view always present and semantically strict.
        conn.execute(
            "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
            ("summary", "codemap-summary/v1", json.dumps(strict_summary, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()

    if dest.exists():
        dest.unlink()
    tmp.replace(dest)
    return {
        "ok": True,
        "path": str(dest),
        "schema": SCHEMA_VERSION,
        "entities": len(codemap.entities),
        "relations": len(codemap.relations),
    }


def _write_meta(conn: sqlite3.Connection, items: dict[str, Any]) -> None:
    for key, value in items.items():
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)",
            (str(key), _jsonable(value)),
        )


def _jsonable(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)