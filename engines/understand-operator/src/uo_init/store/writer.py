# -*- coding: utf-8 -*-
"""Write a CodeMap into ``<op>.<arch>.uo`` (SQLite)."""

from __future__ import annotations

from uo_init.paths import require_architecture
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.store.schema import SCHEMA_SQL, SCHEMA_VERSION


def uo_product_dir(op_root: str | Path, *, architecture: str = "") -> Path:
    """Arch-scoped UO tree that holds the ``*.uo`` product and work files.

    ``architecture`` is required in production; when omitted, fall back to
    pilot path discovery (env / active_run / sole arch).
    """
    root = Path(op_root).expanduser().resolve()
    arch = (architecture or "").strip()
    try:
        from ascendc_pilot.paths import uo_root

        return uo_root(root, arch=arch or None)
    except Exception:
        if not arch:
            raise
        return root / ".ascendc-pilot" / arch / "uo"


def uo_product_path(op_root: str | Path, op_name: str, architecture: str) -> Path:
    safe_op = (op_name or "operator").replace("/", "_").replace("\\", "_")
    arch = require_architecture(architecture)
    return uo_product_dir(op_root, architecture=arch) / f"{safe_op}.{arch}.uo"


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


_CORE_VIEW_NAMES = (
    "ir/operator_graph.yaml",
    "ir/tg_host_view.yaml",
    "views/kernel.yaml",
    "views/tilingdata.yaml",
)


def _ensure_graph_identities(codemap: CodeMap) -> None:
    """Compute fingerprint/digest once after a canonical mutation (or pop)."""
    from uo_init.projection_provenance import canonical_graph_digest
    from uo_init.tg_views import graph_fingerprint

    if not str(codemap.meta.get("graph_fingerprint") or ""):
        codemap.meta["graph_fingerprint"] = graph_fingerprint(codemap)
    if not str(codemap.meta.get("canonical_graph_digest") or ""):
        codemap.meta["canonical_graph_digest"] = canonical_graph_digest(codemap)
    if not str(codemap.meta.get("canonical_revision") or ""):
        codemap.meta["canonical_revision"] = str(codemap.meta["canonical_graph_digest"])[:16]


def _views_match_current_identity(views: dict[str, Any] | None, codemap: CodeMap) -> bool:
    if not isinstance(views, dict):
        return False
    digest = str(codemap.meta.get("canonical_graph_digest") or "")
    if not digest:
        return False
    for name in _CORE_VIEW_NAMES:
        payload = views.get(name)
        if not isinstance(payload, dict):
            return False
        prov = payload.get("provenance")
        if not isinstance(prov, dict) or str(prov.get("canonical_graph_digest") or "") != digest:
            return False
    return True


_JSON_DUMP = {"ensure_ascii": False, "separators": (",", ":")}


def _attrs_json(attrs: dict[str, Any]) -> str:
    cleaned: dict[str, Any] = {}
    for key, value in dict(attrs or {}).items():
        if key == "type_text":
            continue
        cleaned[key] = _trim_attr(value)
    return json.dumps(cleaned, default=str, **_JSON_DUMP)


_KEEP_ATTR_KEYS = frozenset({"rhs", "condition", "expression"})


def _trim_attr(value: Any, *, depth: int = 0, key: str = "") -> Any:
    if depth > 4:
        return value
    if isinstance(value, str):
        if key in _KEEP_ATTR_KEYS:
            return value
        if len(value) > 400:
            return value[:400]
        return value
    if isinstance(value, list):
        child_key = "rhs" if key == "packing_value_sites" else key
        return [_trim_attr(item, depth=depth + 1, key=child_key) for item in value]
    if isinstance(value, dict):
        return {str(k): _trim_attr(v, depth=depth + 1, key=str(k)) for k, v in value.items()}
    return value


def _persistable_cm_meta(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    drop = {"walk_cache_stats", "gaps", "quality"}
    for key, value in dict(meta or {}).items():
        if key == "kernel_root_trace" and isinstance(value, dict):
            value = {k: v for k, v in value.items() if k not in drop}
        out[key] = value
    return out


def _entity_snippet(ent: Any) -> str:
    kind_name = ""
    if hasattr(ent, "kind_name"):
        kind_name = str(ent.kind_name() or "")
    if kind_name == "BRANCH":
        return ""
    existing = str(getattr(ent, "attrs", {}).get("snippet") or "")[:400]
    if existing.strip():
        return existing.strip()[:400]
    file = str(getattr(ent, "file", "") or "")
    line = int(getattr(ent, "line_start", 0) or 0)
    if not file or line <= 0:
        return ""
    try:
        from uo_init.passes.source_text_cache import cached_snippet

        return cached_snippet(file, line)
    except Exception:
        return ""


def detect_source_revision(root: str | Path) -> str:
    """Return ``git rev-parse HEAD`` for ``root``, or empty when git is unavailable."""
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        return ""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return ""
    if proc.returncode:
        return ""
    return str(proc.stdout or "").strip()


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

    removed = _drop_unproven_direct_selection_edges(codemap)
    # A CodeMap read from a previous product may carry its former identities.
    # Any canonical mutation invalidates those values; projection finalization
    # below recomputes all three from the post-mutation graph.
    if removed:
        for identity_key in ("graph_fingerprint", "canonical_graph_digest", "canonical_revision"):
            codemap.meta.pop(identity_key, None)

    from uo_init.projection_provenance import (
        stamp_provenance,
        validate_view_against_codemap,
    )

    _ensure_graph_identities(codemap)
    if removed == 0 and _views_match_current_identity(views, codemap):
        finalized = dict(views or {})
    else:
        finalized = _canonicalize_views(codemap, views)

    from uo_init.diagnostics.audit import audit_codemap

    if removed == 0 and summary:
        strict_summary = dict(summary)
    else:
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
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA journal_mode=OFF")
        conn.executescript(SCHEMA_SQL)
        product_meta: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "authority": "uo",
            "op_name": codemap.op_name,
            "architecture": codemap.architecture,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entity_count": str(len(codemap.entities)),
            "relation_count": str(len(codemap.relations)),
            **{k: _jsonable(v) for k, v in (meta or {}).items()},
            **{f"cm_{k}": _jsonable(v) for k, v in _persistable_cm_meta(codemap.meta).items()},
        }
        if not str(product_meta.get("source_revision") or "").strip():
            try:
                if dest.parents[2].name == ".ascendc-pilot":
                    revision = detect_source_revision(dest.parents[3])
                    if revision:
                        product_meta["source_revision"] = revision
            except IndexError:
                pass
        _write_meta(
            conn,
            product_meta,
        )
        variants = [
            (ent.id, ent.name, codemap.architecture, _attrs_json(ent.attrs))
            for ent in codemap.by_kind("BUILD_VARIANT")
        ]
        if variants:
            conn.executemany(
                "INSERT OR REPLACE INTO build_variant(id, name, architecture, data) VALUES (?,?,?,?)",
                variants,
            )
        entity_rows = []
        file_rows = []
        span_rows = []
        for ent in codemap.entities.values():
            entity_rows.append(
                (
                    ent.id,
                    ent.kind_name(),
                    ent.name,
                    ent.status,
                    float(ent.confidence),
                    ent.file,
                    int(ent.line_start),
                    int(ent.line_end),
                    _attrs_json(ent.attrs),
                )
            )
            if ent.file:
                file_rows.append(
                    (ent.file, ent.file, "", ent.attrs.get("layer") or "")
                )
                snippet = _entity_snippet(ent)
                if snippet and int(ent.line_start or 0) > 0:
                    span_rows.append(
                        (
                            f"span:{ent.id}",
                            ent.id,
                            ent.file,
                            int(ent.line_start),
                            int(ent.line_end or ent.line_start),
                            snippet,
                        )
                    )
        if entity_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO entity("
                "id, kind, name, status, confidence, file, line_start, line_end, data"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                entity_rows,
            )
        if file_rows:
            conn.executemany(
                "INSERT OR IGNORE INTO file(id, path, sha256, role) VALUES (?,?,?,?)",
                file_rows,
            )
        if span_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO source_span("
                "id, entity_id, file, line_start, line_end, snippet"
                ") VALUES (?,?,?,?,?,?)",
                span_rows,
            )
        rel_rows = [
            (
                rel.id,
                rel.kind_name(),
                rel.src,
                rel.dst,
                rel.status,
                float(rel.confidence),
                _attrs_json(rel.attrs),
            )
            for rel in codemap.relations.values()
            if rel.src in codemap.entities and rel.dst in codemap.entities
        ]
        if rel_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO relation("
                "id, kind, src, dst, status, confidence, data"
                ") VALUES (?,?,?,?,?,?,?)",
                rel_rows,
            )
        from uo_init.query.legal_key_cache import compact_legal_key_blob

        view_rows = []
        for name, payload in finalized.items():
            stored = payload
            if name == "tiling/legal_key_index.jsonl" and isinstance(payload, dict):
                stored = compact_legal_key_blob(payload)
            view_rows.append(
                (
                    str(name),
                    str((stored or {}).get("schema") or "") if isinstance(stored, dict) else "",
                    json.dumps(stored, default=str, **_JSON_DUMP),
                )
            )
        view_rows.append(
            (
                "summary",
                "codemap-summary/v1",
                json.dumps(strict_summary, default=str, **_JSON_DUMP),
            )
        )
        conn.executemany(
            "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
            view_rows,
        )
        conn.commit()
        vacuum = str(os.environ.get("UO_VACUUM_UO") or "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if vacuum:
            old_isolation = conn.isolation_level
            conn.isolation_level = None
            try:
                conn.execute("VACUUM")
            finally:
                conn.isolation_level = old_isolation
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
