# -*- coding: utf-8 -*-
"""Backfill TG view blobs into an existing ``.uo`` without a full re-extract."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from uo_init.passes.tpl_schema import run as run_tpl_schema
from uo_init.store.reader import find_uo_product, read_codemap, read_meta
from uo_init.store.writer import write_codemap
from uo_init.tg_views import finalize_tg_views

REQUIRED_TG_VIEWS = (
    "tiling/exhaustive_key_space.yaml",
    "tiling/legal_key_index.jsonl",
    "ir/tg_host_view.yaml",
    "ir/operator_graph.yaml",
    "views/kernel.yaml",
    "views/tilingdata.yaml",
)


def backfill_from_source(project_root: str | Path, *, op_name: str = "", architecture: str = "", tiling_key_header: str | Path | None = None, uo_path: str | Path | None = None) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    product = Path(uo_path).expanduser().resolve() if uo_path else find_uo_product(root, op_name=op_name, architecture=architecture)
    if product is None or not product.is_file() or product.suffix != ".uo":
        return {"ok": False, "error": "missing .uo CodeMap product"}
    meta = read_meta(product)
    op = op_name or str(meta.get("op_name") or "")
    arch = architecture or str(meta.get("architecture") or "arch35")
    cm = read_codemap(product)
    cm.op_name = cm.op_name or op
    cm.architecture = cm.architecture or arch
    ctx: dict[str, Any] = {"op_root": str(root), "architecture": arch, "op_name": op, "tg_views": {}}
    if tiling_key_header:
        ctx["tiling_key_header"] = str(Path(tiling_key_header).expanduser().resolve())
    cm = run_tpl_schema(cm, context=ctx)
    views = finalize_tg_views(cm, existing=dict(ctx.get("tg_views") or {}))
    if int((views.get("tiling/exhaustive_key_space.yaml") or {}).get("legal_key_count") or 0) <= 0:
        return {"ok": False, "error": "TPL ARGS_SEL expansion produced empty D (header missing?)", "path": str(product), "header": ctx.get("tiling_key_header") or (cm.meta.get("tpl_schema") or {}).get("header")}
    missing = [name for name in REQUIRED_TG_VIEWS if name not in views]
    if missing:
        return {"ok": False, "error": "TG_VIEW_INCOMPLETE", "missing": missing, "path": str(product)}
    written = write_codemap(cm, product, views=views)
    return {"ok": True, "path": str(product), "sha256": hashlib.sha256(product.read_bytes()).hexdigest(), "legal_key_count": int(cm.meta.get("legal_key_count") or 0), "args_sel_group_count": int(cm.meta.get("args_sel_group_count") or 0), "views": sorted(views), "graph_fingerprint": str(cm.meta.get("graph_fingerprint") or ""), "uo": written}


def load_tg_view(uo_path: str | Path, name: str) -> dict[str, Any] | list[Any] | None:
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


def ensure_tg_views(project_root: str | Path, *, op_name: str = "", architecture: str = "", tiling_key_header: str | Path | None = None) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    product = find_uo_product(root, op_name=op_name, architecture=architecture)
    if product is None:
        return {"ok": False, "error": "missing .uo CodeMap product"}
    docs = {name: load_tg_view(product, name) for name in REQUIRED_TG_VIEWS}
    count = legal_key_count(product)
    if count > 0 and all(doc is not None for doc in docs.values()):
        graph = docs["ir/operator_graph.yaml"] if isinstance(docs["ir/operator_graph.yaml"], dict) else {}
        return {"ok": True, "path": str(product), "legal_key_count": count, "backfilled": False, "graph_fingerprint": str(graph.get("fingerprint") or ""), "views": list(REQUIRED_TG_VIEWS)}
    result = backfill_from_source(root, op_name=op_name, architecture=architecture, tiling_key_header=tiling_key_header, uo_path=product)
    return {**result, "backfilled": True}


def list_view_names(uo_path: str | Path) -> list[str]:
    conn = sqlite3.connect(str(uo_path))
    try:
        return [str(r[0]) for r in conn.execute("SELECT name FROM view_blob ORDER BY name")]
    finally:
        conn.close()
