# -*- coding: utf-8 -*-
"""Read CodeMap / views from a ``.uo`` SQLite product."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import Relation, RelationKind


def open_uo(path: str | Path) -> sqlite3.Connection:
    db = Path(path).expanduser().resolve()
    if not db.is_file():
        raise FileNotFoundError(f"missing .uo product: {db}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def read_meta(path: str | Path) -> dict[str, str]:
    conn = open_uo(path)
    try:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
        return {str(r["key"]): str(r["value"]) for r in rows}
    finally:
        conn.close()


def read_codemap(path: str | Path) -> CodeMap:
    conn = open_uo(path)
    try:
        meta = {str(r["key"]): str(r["value"]) for r in conn.execute("SELECT key, value FROM meta")}
        cm = CodeMap(
            op_name=meta.get("op_name") or "",
            architecture=meta.get("architecture") or "",
        )
        cm.meta = {k[3:]: _maybe_json(v) for k, v in meta.items() if k.startswith("cm_")}
        for row in conn.execute(
            "SELECT id, kind, name, status, confidence, file, line_start, line_end, data FROM entity"
        ):
            data = json.loads(row["data"] or "{}")
            attrs = {
                k: v
                for k, v in data.items()
                if k
                not in {
                    "id",
                    "kind",
                    "name",
                    "status",
                    "confidence",
                    "file",
                    "line_start",
                    "line_end",
                }
            }
            kind_name = str(row["kind"])
            try:
                kind: EntityKind | str = EntityKind(kind_name)
            except ValueError:
                kind = kind_name
            cm.add_entity(
                Entity(
                    id=str(row["id"]),
                    kind=kind,
                    name=str(row["name"] or ""),
                    attrs=attrs,
                    file=str(row["file"] or ""),
                    line_start=int(row["line_start"] or 0),
                    line_end=int(row["line_end"] or 0),
                    status=str(row["status"] or "extracted"),
                    confidence=float(row["confidence"] or 1.0),
                )
            )
        for row in conn.execute(
            "SELECT id, kind, src, dst, status, confidence, data FROM relation"
        ):
            data = json.loads(row["data"] or "{}")
            attrs = {
                k: v
                for k, v in data.items()
                if k not in {"id", "kind", "src", "dst", "status", "confidence"}
            }
            kind_name = str(row["kind"])
            try:
                rkind: RelationKind | str = RelationKind(kind_name)
            except ValueError:
                rkind = kind_name
            cm.relations[str(row["id"])] = Relation(
                id=str(row["id"]),
                kind=rkind,
                src=str(row["src"]),
                dst=str(row["dst"]),
                attrs=attrs,
                status=str(row["status"] or "extracted"),
                confidence=float(row["confidence"] or 1.0),
            )
        return cm
    finally:
        conn.close()


def load_view_blob(path: str | Path, name: str) -> Any | None:
    conn = open_uo(path)
    try:
        row = conn.execute(
            "SELECT data FROM view_blob WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["data"])
    finally:
        conn.close()


def load_view_blob_checked(
    path: str | Path,
    name: str,
    *,
    codemap: CodeMap | None = None,
    fallback_canonical: bool = True,
) -> dict[str, Any]:
    """Load a projection with provenance check.

    On mismatch returns ``reason_code=VIEW_STALE`` and, when possible, a
    canonical rebuild of known TG views (engine-side; not LLM).
    """
    from uo_init.projection_provenance import VIEW_STALE, validate_view_against_codemap
    from uo_init.tg_views import (
        finalize_tg_views,
        project_kernel_view,
        project_operator_graph,
        project_tilingdata_view,
        project_tg_host_view,
    )

    blob = load_view_blob(path, name)
    cm = codemap if codemap is not None else read_codemap(path)
    if blob is None:
        return {"ok": False, "reason_code": "VIEW_MISSING", "name": name, "view": None}
    check = validate_view_against_codemap(blob, cm)
    if check.get("ok"):
        return {"ok": True, "reason_code": "", "name": name, "view": blob}
    result: dict[str, Any] = {
        "ok": False,
        "reason_code": check.get("reason_code") or VIEW_STALE,
        "name": name,
        "view": blob,
        "check": check,
    }
    if not fallback_canonical:
        return result
    rebuilt: Any = None
    if name == "ir/operator_graph.yaml":
        rebuilt = project_operator_graph(cm)
    elif name == "ir/tg_host_view.yaml":
        rebuilt = project_tg_host_view(cm)
    elif name == "views/kernel.yaml":
        rebuilt = project_kernel_view(cm)
    elif name == "views/tilingdata.yaml":
        rebuilt = project_tilingdata_view(cm)
    elif name == "summary":
        rebuilt = {
            "entity_count": len(cm.entities),
            "relation_count": len(cm.relations),
            "graph_fingerprint": cm.meta.get("graph_fingerprint"),
        }
    if rebuilt is not None:
        from uo_init.projection_provenance import stamp_provenance

        # Ensure fingerprint meta exists for stamp
        if not cm.meta.get("graph_fingerprint"):
            finalize_tg_views(cm, existing={})
        result["ok"] = True
        result["fallback"] = "canonical"
        result["view"] = stamp_provenance(rebuilt, cm)
        result["stale_blob"] = blob
    return result


def list_views(path: str | Path) -> list[str]:
    conn = open_uo(path)
    try:
        return [str(r["name"]) for r in conn.execute("SELECT name FROM view_blob ORDER BY name")]
    finally:
        conn.close()


def find_uo_product(
    op_root: str | Path,
    *,
    op_name: str = "",
    architecture: str = "",
) -> Path | None:
    """Locate the CodeMap product ``.ascendc-pilot/uo/<op>.<arch>.uo``."""
    from uo_init.store.writer import uo_product_dir, uo_product_path

    root = Path(op_root).expanduser().resolve()
    if op_name and architecture:
        p = uo_product_path(root, op_name, architecture)
        if p.is_file():
            return p
    product_dir = uo_product_dir(root)
    if product_dir.is_dir():
        arch = (architecture or "").strip()
        candidates = sorted(product_dir.glob("*.uo"))
        if arch:
            narrowed = [c for c in candidates if c.name.endswith(f".{arch}.uo")]
            if narrowed:
                if op_name:
                    for c in narrowed:
                        if c.name.startswith(f"{op_name}."):
                            return c
                return narrowed[0]
        if op_name:
            for c in candidates:
                if c.name.startswith(f"{op_name}."):
                    return c
        if candidates:
            return candidates[0]
    return None


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return text
