# -*- coding: utf-8 -*-
"""UO Product Handle — explicit handle for delegated Task(actor=uo-query)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def build_uo_product_handle(
    project_root: str | Path,
    *,
    op_name: str = "",
    architecture: str = "",
    uo_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build an explicit handle parents must pass to Task(actor=uo-query).

    Subagents must not search for ``.uo`` themselves when a handle is provided.
    """
    from uo_init.store.reader import find_uo_product, read_meta

    root = Path(project_root).expanduser().resolve()
    product = Path(uo_path).expanduser().resolve() if uo_path else None
    if product is None or not product.is_file():
        product = find_uo_product(root, op_name=op_name, architecture=architecture)
    if product is None or not product.is_file():
        return {
            "ok": False,
            "error": "UO_PRODUCT_REQUIRED",
            "message_zh": "缺少已 commit 的 .uo；请先 /uo-init 或传入显式路径",
        }
    meta = read_meta(product)
    digest = ""
    try:
        digest = hashlib.sha256(product.read_bytes()).hexdigest()[:16]
    except OSError:
        digest = ""
    return {
        "ok": True,
        "schema": "uo-product-handle/v1",
        "op_name": op_name or str(meta.get("op_name") or ""),
        "architecture": architecture or str(meta.get("architecture") or ""),
        "path": product.as_posix(),
        "schema_version": str(meta.get("schema") or ""),
        "graph_fingerprint": str(meta.get("cm_graph_fingerprint") or meta.get("graph_fingerprint") or ""),
        "canonical_graph_digest": str(
            meta.get("cm_canonical_graph_digest") or meta.get("canonical_graph_digest") or ""
        ),
        "entity_count": str(meta.get("entity_count") or ""),
        "relation_count": str(meta.get("relation_count") or ""),
        "content_sha16": digest,
    }


def format_handle_for_task(handle: dict[str, Any]) -> str:
    """Compact block to prepend to a delegated Task prompt."""
    if not handle.get("ok"):
        return f"UO_PRODUCT_HANDLE_ERROR: {handle.get('error')}"
    lines = [
        "UO_PRODUCT_HANDLE:",
        f"  op_name: {handle.get('op_name')}",
        f"  architecture: {handle.get('architecture')}",
        f"  path: {handle.get('path')}",
        f"  schema: {handle.get('schema_version')}",
        f"  fingerprint: {handle.get('graph_fingerprint')}",
        f"  digest: {handle.get('canonical_graph_digest')}",
        "  rule: use this product only; do not search for another .uo",
    ]
    return "\n".join(lines)
