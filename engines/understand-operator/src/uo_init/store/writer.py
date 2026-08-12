# -*- coding: utf-8 -*-
"""Write a CodeMap into ``<op>.<arch>.uo`` (SQLite)."""

from __future__ import annotations

from uo_init.paths import require_architecture
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.store.schema import SCHEMA_SQL, SCHEMA_VERSION


def uo_product_dir(op_root: str | Path) -> Path:
    root = Path(op_root).expanduser().resolve()
    return root / ".ascendc-pilot" / "uo"


def uo_product_path(op_root: str | Path, op_name: str, architecture: str) -> Path:
    safe_op = (op_name or "operator").replace("/", "_").replace("\\", "_")
    arch = require_architecture(architecture)
    return uo_product_dir(op_root) / f"{safe_op}.{arch}.uo"


def _drop_unproven_direct_selection_edges(codemap: CodeMap) -> int:
    """Prevent legacy Cartesian TilingKey→Kernel edges entering the product."""
    removed: list[str] = []
    for rid, rel in list(codemap.relations.items()):
        if rel.kind_name() not in {RelationKind.SELECTS.value, RelationKind.LAUNCHES.value}:
            continue
        src = codemap.entities.get(rel.src)
        dst = codemap.entities.get(rel.dst)
        if not src or not dst:
            continue
        if src.kind_name() != EntityKind.TILING_KEY.value or dst.kind_name() != EntityKind.KERNEL.value:
            continue
        if rel.attrs.get("provenance") or rel.attrs.get("legacy_kind") or rel.attrs.get("evidence"):
            continue
        removed.append(rid)
    for rid in removed:
        codemap.relations.pop(rid, None)
    if removed:
        codemap.meta["dropped_unproven_direct_key_kernel_edges"] = len(removed)
    return len(removed)


def _canonicalize_views(codemap: CodeMap, views: dict[str, Any] | None) -> dict[str, Any]:
    """Return only projections that are safe to stamp with current authority."""
    from uo_init.canonical_tpl_projection import TPL_VIEW_NAMES, project_tpl_views_from_codemap
    from uo_init.projection_provenance import validate_view_against_codemap
    from uo_init.tg_views import finalize_tg_views

    incoming = dict(views or {})
    rebuilt_names = {
        "ir/operator_graph.yaml",
        "ir/tg_host_view.yaml",
        "views/kernel.yaml",
        "views/tilingdata.yaml",
        *TPL_VIEW_NAMES,
    }
    seed: dict[str, Any] = {}

    tpl_views = project_tpl_views_from_codemap(codemap)
    if tpl_views:
        seed.update(tpl_views)
    elif any(name in incoming for name in TPL_VIEW_NAMES):
        # A caller supplied a materialized TPL domain but the canonical graph
        # cannot reproduce it.  Never drop/re-stamp that D silently: require a
        # TPL re-extract/backfill so the authority becomes self-contained.
        raise ValueError(
            "TPL_CANONICAL_FACTS_INCOMPLETE: caller supplied TPL views but canonical "
            "TILING_KEY/ARGS_SEL TEMPLATE facts cannot rebuild them"
        )

    for name, payload in incoming.items():
        if name in rebuilt_names or name == "summary":
            continue
        check = validate_view_against_codemap(payload, codemap)
        if not check.get("ok"):
            raise ValueError(
                "VIEW_STALE_ON_COMMIT: extension projection cannot be proven fresh: "
                + json.dumps({"name": name, **check}, ensure_ascii=False)[:800]
            )
        seed[name] = payload

    return finalize_tg_views(codemap, existing=seed)


def write_codemap(
    codemap: CodeMap,
    path: str | Path,
    *,
    views: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist CodeMap to ``path`` (``.uo`` SQLite). Overwrites atomically.

    Commit order: canonical mutation → clear stale graph identity → rebuild all
    canonical projections → semantic digest/provenance validation → atomic
    replace. Caller-provided materialized views never acquire a new digest
    unless rebuilt or already proven against the current canonical graph.
    """
    dest = Path(path).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    _drop_unproven_direct_selection_edges(codemap)
    # A CodeMap read from a previous product may carry its former identities.
    # Any canonical mutation invalidates those values; projection finalization
    # below recomputes all three from the post-mutation graph.
    for identity_key in ("graph_fingerprint", "canonical_graph_digest", "canonical_revision"):
        codemap.meta.pop(identity_key, None)

    from uo_init.projection_provenance import (
        stamp_provenance,
        validate_view_against_codemap,
    )

    finalized = _canonicalize_views(codemap, views)

    from uo_init.diagnostics.audit import audit_codemap

    strict_summary = dict(summary or {})
    strict_summary.update(dict(audit_codemap(codemap)["summary"]))
    strict_summary = stamp_provenance(strict_summary, codemap)

    stale: list[dict[str, Any]] = []
    for name, payload in finalized.items():
        check = validate_view_against_codemap(payload, codemap)
        if not check.get("ok"):
            stale.append({"name": name, **check})
    summary_check = validate_view_against_codemap(strict_summary, codemap)
    if not summary_check.get("ok"):
        stale.append({"name": "summary", **summary_check})
    if stale:
        raise ValueError(
            "VIEW_STALE_ON_COMMIT: projections drifted from canonical before write: "
            + json.dumps(stale[:5], ensure_ascii=False)[:800]
        )

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
        for ent in codemap.by_kind("BUILD_VARIANT"):
            conn.execute(
                "INSERT OR REPLACE INTO build_variant(id, name, architecture, data) VALUES (?,?,?,?)",
                (ent.id, ent.name, codemap.architecture, json.dumps(ent.to_dict(), ensure_ascii=False)),
            )
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
                conn.execute(
                    "INSERT OR REPLACE INTO source_span("
                    "id, entity_id, file, line_start, line_end, snippet"
                    ") VALUES (?,?,?,?,?,?)",
                    (
                        f"span:{ent.id}",
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
        for rel in codemap.relations.values():
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
        for name, payload in finalized.items():
            conn.execute(
                "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
                (
                    str(name),
                    str((payload or {}).get("schema") or "") if isinstance(payload, dict) else "",
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
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
