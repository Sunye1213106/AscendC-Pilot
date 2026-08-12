# -*- coding: utf-8 -*-
"""Indexed / parse-once cache for ``tiling/legal_key_index`` projections.

Avoids re-``json.loads`` of multi-MB blobs on every Agent hop and refuses to
consume an unverifiable/stale projection. Structured dimension filters use an
in-memory inverted index instead of serialising every legal-key row.
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


def _pattern_filters(pattern: str) -> dict[str, str]:
    """Parse ``Dim=1,Other=0`` from the existing --pattern CLI surface.

    Keeping this in the query layer means the public ``acp uo-query`` command
    does not need a second parallel flag grammar just to reach the index.
    Free-text patterns remain supported when every comma-separated token is not
    a simple key=value pair.
    """
    text = str(pattern or "").strip()
    if not text or "=" not in text:
        return {}
    out: dict[str, str] = {}
    for part in text.split(","):
        item = part.strip()
        if not item or "=" not in item:
            return {}
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value:
            return {}
        out[name] = value
    return out


def legal_key_index_cache(product: str | Path) -> dict[str, Any]:
    """Return a freshness-checked parse-once legal-key cache for the product."""
    path = Path(product).expanduser().resolve()
    key = str(path)
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return {
            "ok": False,
            "reason_code": "UO_PRODUCT_MISSING",
            "mtime_ns": -1,
            "rows": [],
            "by_dim": {},
        }
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit.get("mtime_ns") == mtime_ns:
            return hit

    from uo_init.store.reader import load_view_blob_checked

    checked = load_view_blob_checked(
        path,
        "tiling/legal_key_index.jsonl",
        fallback_canonical=False,
    )
    if not checked.get("ok"):
        entry = {
            "ok": False,
            "reason_code": str(checked.get("reason_code") or "VIEW_STALE"),
            "mtime_ns": mtime_ns,
            "rows": [],
            "by_dim": {},
            "freshness": checked.get("check") or {},
        }
        with _LOCK:
            _CACHE[key] = entry
        return entry

    blob = checked.get("view")
    rows = _load_rows_from_blob(blob)
    by_dim: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        dims = row.get("dims") or row.get("dimensions") or row.get("key") or {}
        if isinstance(dims, dict):
            for dname, dval in dims.items():
                by_dim.setdefault(f"{dname}={dval}", []).append(i)
        for k in ("key_id", "id", "packed"):
            if k in row:
                by_dim.setdefault(f"{k}={row[k]}", []).append(i)
    entry = {
        "ok": True,
        "reason_code": "",
        "mtime_ns": mtime_ns,
        "rows": rows,
        "by_dim": by_dim,
        "freshness": checked.get("check") or {},
    }
    with _LOCK:
        _CACHE[key] = entry
    return entry


def _indexed_row_ids(
    by_dim: dict[str, list[int]],
    filters: dict[str, str],
) -> list[int]:
    """Intersect inverted-index postings for all requested dimensions."""
    postings: list[set[int]] = []
    for name, value in filters.items():
        postings.append(set(by_dim.get(f"{name}={value}") or []))
    if not postings:
        return []
    hits = postings[0]
    for p in postings[1:]:
        hits &= p
        if not hits:
            break
    return sorted(hits)


def query_legal_keys(
    product: str | Path,
    *,
    pattern: str = "",
    dim: str = "",
    value: str = "",
    filters: dict[str, str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Filter legal keys without re-parsing/scanning the full blob when structured filters exist."""
    cache = legal_key_index_cache(product)
    if not cache.get("ok"):
        return {
            "ok": False,
            "mode": "legal_key",
            "reason_code": str(cache.get("reason_code") or "VIEW_STALE"),
            "message": "legal-key projection is stale or unverifiable; rebuild/update .uo before using it",
            "rows": [],
            "count": 0,
            "total_matched": 0,
            "freshness": cache.get("freshness") or {},
        }

    all_rows: list[dict[str, Any]] = list(cache.get("rows") or [])
    rows = all_rows
    needle = str(pattern or "").strip()
    structured = {
        str(k).strip(): str(v).strip()
        for k, v in dict(filters or {}).items()
        if str(k).strip() and str(v).strip()
    }
    dname = str(dim or "").strip()
    dval = str(value or "").strip()
    if dname and dval:
        structured[dname] = dval
    if not structured:
        structured.update(_pattern_filters(needle))

    if structured:
        idxs = _indexed_row_ids(dict(cache.get("by_dim") or {}), structured)
        rows = [all_rows[i] for i in idxs if 0 <= i < len(all_rows)]
    elif needle:
        # Free-text is compatibility only; `Dim=V[,Other=V]` reaches the index.
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
        "pattern": needle,
        "filters": structured,
        "total_matched": total,
        "count": len(rows),
        "offset": int(offset or 0),
        "limit": int(limit or 0),
        "rows": rows,
        "cached": True,
        "indexed": bool(structured),
    }
