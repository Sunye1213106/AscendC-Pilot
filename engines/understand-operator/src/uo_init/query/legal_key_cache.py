# -*- coding: utf-8 -*-
"""Indexed / parse-once cache for ``tiling/legal_key_index`` projections.

Avoids re-``json.loads`` of multi-MB blobs on every Agent hop.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_CACHE: dict[str, dict[str, Any]] = {}


def clear_legal_key_cache(path: str | Path | None = None) -> None:
    with _LOCK:
        if path is None:
            _CACHE.clear()
            return
        _CACHE.pop(str(Path(path).resolve()), None)


def _load_rows_from_blob(blob: Any) -> list[dict[str, Any]]:
    if isinstance(blob, dict):
        rows = blob.get("rows")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
        return []
    if isinstance(blob, list):
        return [r for r in blob if isinstance(r, dict)]
    return []


def legal_key_index_cache(product: str | Path) -> dict[str, Any]:
    """Return ``{mtime_ns, rows, by_dim}`` for the product, parse-once per mtime."""
    path = Path(product).expanduser().resolve()
    key = str(path)
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return {"mtime_ns": -1, "rows": [], "by_dim": {}}
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit.get("mtime_ns") == mtime_ns:
            return hit

    from uo_init.store.reader import load_view_blob

    blob = load_view_blob(path, "tiling/legal_key_index.jsonl")
    rows = _load_rows_from_blob(blob)
    by_dim: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        dims = row.get("dims") or row.get("dimensions") or row.get("key") or {}
        if isinstance(dims, dict):
            for dname, dval in dims.items():
                by_dim.setdefault(f"{dname}={dval}", []).append(i)
        # also index flat fields commonly present
        for k in ("key_id", "id", "packed"):
            if k in row:
                by_dim.setdefault(f"{k}={row[k]}", []).append(i)
    entry = {"mtime_ns": mtime_ns, "rows": rows, "by_dim": by_dim}
    with _LOCK:
        _CACHE[key] = entry
    return entry


def query_legal_keys(
    product: str | Path,
    *,
    pattern: str = "",
    dim: str = "",
    value: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Filter legal keys without re-parsing the full blob each call."""
    cache = legal_key_index_cache(product)
    rows: list[dict[str, Any]] = list(cache.get("rows") or [])
    needle = str(pattern or "").strip()
    dname = str(dim or "").strip()
    dval = str(value or "").strip()
    if dname and dval:
        idxs = (cache.get("by_dim") or {}).get(f"{dname}={dval}") or []
        rows = [rows[i] for i in idxs if 0 <= i < len(rows)]
    elif needle:
        low = needle.lower()
        filtered: list[dict[str, Any]] = []
        for row in rows:
            hay = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str).lower()
            if low in hay:
                filtered.append(row)
        rows = filtered
    total = len(rows)
    if offset:
        rows = rows[offset:]
    if limit and limit > 0:
        rows = rows[: int(limit)]
    return {
        "ok": True,
        "mode": "legal_key",
        "total_matched": total,
        "count": len(rows),
        "offset": int(offset or 0),
        "limit": int(limit or 0),
        "rows": rows,
        "cached": True,
    }
