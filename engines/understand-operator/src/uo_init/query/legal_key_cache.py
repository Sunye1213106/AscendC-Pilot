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


def compact_legal_key_blob(blob: dict[str, Any]) -> dict[str, Any]:
    """Store dim names once; each row is ``[index, key, hex, values, sel, status]``."""
    rows = blob.get("rows") if isinstance(blob, dict) else None
    if not isinstance(rows, list) or not rows:
        return blob
    if isinstance(rows[0], (list, tuple)):
        return blob
    first = next((r for r in rows if isinstance(r, dict)), None)
    if not isinstance(first, dict) or not isinstance(first.get("dims"), dict):
        return blob
    dim_order = list(first["dims"].keys())
    compact_rows: list[list[Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dims = row.get("dims") if isinstance(row.get("dims"), dict) else {}
        compact_rows.append(
            [
                row.get("index", len(compact_rows)),
                row.get("tiling_key"),
                row.get("tiling_key_hex") or "",
                [dims.get(name) for name in dim_order],
                row.get("sel_group_id") or "",
                row.get("status") or "template_admissible",
            ]
        )
    out = dict(blob)
    out["dim_order"] = dim_order
    out["rows"] = compact_rows
    return out


def expand_legal_key_rows(blob: Any) -> list[dict[str, Any]]:
    """Expand compact or legacy legal-key blobs into dict rows with ``dims``."""
    if isinstance(blob, list):
        return [row for row in blob if isinstance(row, dict)]
    if not isinstance(blob, dict):
        return []
    rows = blob.get("rows")
    if not isinstance(rows, list):
        return []
    dim_order = [str(n) for n in (blob.get("dim_order") or [])]
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
            continue
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            continue
        values = row[3] if isinstance(row[3], list) else []
        dims = {
            dim_order[i]: values[i]
            for i in range(min(len(dim_order), len(values)))
        }
        out.append(
            {
                "index": row[0],
                "tiling_key": row[1],
                "tiling_key_hex": row[2] if len(row) > 2 else "",
                "dims": dims,
                "sel_group_id": row[4] if len(row) > 4 else "",
                "status": row[5] if len(row) > 5 else "template_admissible",
            }
        )
    return out


def _load_rows_from_blob(blob: Any) -> list[dict[str, Any]]:
    return expand_legal_key_rows(blob)


def normalize_cover_pattern(pattern: str) -> tuple[str, str | None]:
    """Split cover sugar from combo filters.

    ``Dim=S2TemplateNum`` (no further ``=``) is a dim-only coverage list.
    ``Dim=IsTnd=1`` / ``Dim=A=1,B=2`` drop the ``Dim=`` prefix so the first
    ``=`` split stays ``Name=Value``. Bare ``IsTnd=1`` is unchanged.
    """
    text = str(pattern or "").strip()
    if not text:
        return "", None
    while len(text) >= 4 and text[:4].lower() == "dim=":
        rest = text[4:].strip()
        if "=" not in rest:
            return "", rest or None
        text = rest
    return text, None


def _pattern_filters(pattern: str) -> dict[str, str]:
    """Parse ``Name=Value[,Other=Value]`` from the existing --pattern CLI surface.

    ``Dim=`` sugar is stripped by :func:`normalize_cover_pattern` first.
    Free-text patterns remain supported when every comma-separated token is not
    a simple key=value pair.
    """
    text, _dim_only = normalize_cover_pattern(pattern)
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


def _sel_group_ids(rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        gid = str(row.get("sel_group_id") or "").strip()
        if not gid or gid in seen:
            continue
        seen.add(gid)
        out.append(gid)
    return out


def _dim_values_from_index(by_dim: dict[str, list[int]], dim_name: str) -> list[str]:
    prefix = f"{dim_name}="
    values: list[str] = []
    seen: set[str] = set()
    for key in by_dim:
        if not str(key).startswith(prefix):
            continue
        val = str(key)[len(prefix) :]
        if val in seen:
            continue
        seen.add(val)
        values.append(val)
    return sorted(values)


def _legal_key_nearby(
    by_dim: dict[str, list[int]],
    filters: dict[str, str],
) -> list[dict[str, Any]]:
    """When a combo misses, drop one dim at a time using the inverted index."""
    nearby: list[dict[str, Any]] = []
    for dropped in filters:
        remaining = {k: v for k, v in filters.items() if k != dropped}
        if remaining:
            remaining_ids = set(_indexed_row_ids(by_dim, remaining))
            total = len(remaining_ids)
            prefix = f"{dropped}="
            values: list[str] = []
            for key, posting in by_dim.items():
                if not str(key).startswith(prefix):
                    continue
                if remaining_ids & set(posting):
                    values.append(str(key)[len(prefix) :])
            values = sorted(set(values))
        else:
            total = 0
            values = _dim_values_from_index(by_dim, dropped)
        nearby.append(
            {
                "dropped": dropped,
                "remaining_filters": remaining,
                "total_matched": total,
                "values": values,
            }
        )
    return nearby


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
    sel_group_ids = _sel_group_ids(rows) if structured else []
    nearby: list[dict[str, Any]] = []
    if structured and total == 0:
        nearby = _legal_key_nearby(dict(cache.get("by_dim") or {}), structured)
    if offset:
        rows = rows[offset:]
    if limit and limit > 0:
        rows = rows[: int(limit)]
    from uo_init.query.hints import attach_query_hints

    payload = {
        "ok": True,
        "mode": "legal_key",
        "pattern": needle,
        "filters": structured,
        "total_matched": total,
        "count": len(rows),
        "offset": int(offset or 0),
        "limit": int(limit or 0),
        "rows": rows,
        "sel_group_ids": sel_group_ids,
        "cached": True,
        "indexed": bool(structured),
    }
    if nearby:
        payload["nearby"] = nearby
    attach_query_hints(payload, needle, count=total, indexed=bool(structured) if needle else None)
    return payload
