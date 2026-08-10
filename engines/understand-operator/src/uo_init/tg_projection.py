# -*- coding: utf-8 -*-
"""Backfill TG view blobs into an existing ``.uo`` without a full re-extract.

Used when an older CodeMap product has entities/relations but only a ``summary``
view_blob. Parses the operator TPL header from source (or an explicit path),
projects host/graph views from the stored CodeMap, and rewrites the product.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from uo_init.passes.tpl_schema import run as run_tpl_schema
from uo_init.store.reader import find_uo_product, read_codemap, read_meta
from uo_init.store.writer import write_codemap
from uo_init.tg_views import finalize_tg_views


def backfill_from_source(
    project_root: str | Path,
    *,
    op_name: str = "",
    architecture: str = "",
    tiling_key_header: str | Path | None = None,
    uo_path: str | Path | None = None,
) -> dict[str, Any]:
    """Materialize TPL/D + TG views into ``.uo`` view_blob tables."""
    root = Path(project_root).expanduser().resolve()
    product = Path(uo_path).expanduser().resolve() if uo_path else find_uo_product(
        root, op_name=op_name, architecture=architecture
    )
    if product is None or not product.is_file() or product.suffix != ".uo":
        return {"ok": False, "error": "missing .uo CodeMap product"}

    meta = read_meta(product)
    op = op_name or str(meta.get("op_name") or "")
    arch = architecture or str(meta.get("architecture") or "arch35")
    cm = read_codemap(product)
    if not cm.op_name:
        cm.op_name = op
    if not cm.architecture:
        cm.architecture = arch

    ctx: dict[str, Any] = {
        "op_root": str(root),
        "architecture": arch,
        "op_name": op,
        "tg_views": {},
    }
    if tiling_key_header:
        ctx["tiling_key_header"] = str(Path(tiling_key_header).expanduser().resolve())

    cm = run_tpl_schema(cm, context=ctx)
    views = finalize_tg_views(cm, existing=dict(ctx.get("tg_views") or {}))
    if int((views.get("tiling/exhaustive_key_space.yaml") or {}).get("legal_key_count") or 0) <= 0:
        return {
            "ok": False,
            "error": "TPL ARGS_SEL expansion produced empty D (header missing?)",
            "path": str(product),
            "header": ctx.get("tiling_key_header") or (cm.meta.get("tpl_schema") or {}).get("header"),
        }

    written = write_codemap(cm, product, views=views)
    digest = hashlib.sha256(product.read_bytes()).hexdigest()
    return {
        "ok": True,
        "path": str(product),
        "sha256": digest,
        "legal_key_count": int(cm.meta.get("legal_key_count") or 0),
        "args_sel_group_count": int(cm.meta.get("args_sel_group_count") or 0),
        "views": sorted(views),
        "graph_fingerprint": str(cm.meta.get("graph_fingerprint") or ""),
        "uo": written,
    }


def load_tg_view(
    uo_path: str | Path,
    name: str,
) -> dict[str, Any] | list[Any] | None:
    """Load one TG view blob from ``.uo`` (None if missing)."""
    from uo_init.store.reader import load_view_blob

    return load_view_blob(uo_path, name)


def legal_key_rows(uo_path: str | Path) -> list[dict[str, Any]]:
    blob = load_tg_view(uo_path, "tiling/legal_key_index.jsonl")
    if isinstance(blob, dict):
        rows = blob.get("rows")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    if isinstance(blob, list):
        return [r for r in blob if isinstance(r, dict)]
    return []


def legal_key_count(uo_path: str | Path) -> int:
    space = load_tg_view(uo_path, "tiling/exhaustive_key_space.yaml")
    if isinstance(space, dict):
        n = int(space.get("legal_key_count") or 0)
        if n > 0:
            return n
    return len(legal_key_rows(uo_path))


def ensure_tg_views(
    project_root: str | Path,
    *,
    op_name: str = "",
    architecture: str = "",
    tiling_key_header: str | Path | None = None,
) -> dict[str, Any]:
    """Return ready TG views; backfill from source when blobs are missing."""
    root = Path(project_root).expanduser().resolve()
    product = find_uo_product(root, op_name=op_name, architecture=architecture)
    if product is None:
        return {"ok": False, "error": "missing .uo CodeMap product"}
    count = legal_key_count(product)
    host = load_tg_view(product, "ir/tg_host_view.yaml")
    graph = load_tg_view(product, "ir/operator_graph.yaml")
    if count > 0 and isinstance(host, dict) and isinstance(graph, dict):
        return {
            "ok": True,
            "path": str(product),
            "legal_key_count": count,
            "backfilled": False,
            "graph_fingerprint": str((graph or {}).get("fingerprint") or ""),
        }
    return {
        **backfill_from_source(
            root,
            op_name=op_name,
            architecture=architecture,
            tiling_key_header=tiling_key_header,
            uo_path=product,
        ),
        "backfilled": True,
    }


def list_view_names(uo_path: str | Path) -> list[str]:
    conn = sqlite3.connect(str(uo_path))
    try:
        return [str(r[0]) for r in conn.execute("SELECT name FROM view_blob ORDER BY name")]
    finally:
        conn.close()
