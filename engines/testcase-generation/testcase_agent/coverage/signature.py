# -*- coding: utf-8 -*-
"""Semantic signature: plan-related states only, never raw B/N/S values."""

from __future__ import annotations

from typing import Any

from .eval import classify_dimension, classify_guard, classify_target
from .predicate import flatten_observe


def semantic_signature(
    plan: dict[str, Any],
    observe: dict[str, Any],
    *,
    obligation: dict[str, Any] | None = None,
) -> str:
    parts: list[str] = []
    expected = (obligation or {}).get("expected") if isinstance((obligation or {}).get("expected"), dict) else {}
    target_ids = list((expected.get("targets") or {}).keys()) or [
        str(row.get("id") or "").strip()
        for row in (plan.get("targets") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]
    dim_ids = list((expected.get("dimensions") or {}).keys()) or [
        str(row.get("id") or "").strip()
        for row in (plan.get("dimensions") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]
    guard_ids = list((expected.get("guards") or {}).keys())
    targets = {str(r.get("id")): r for r in (plan.get("targets") or []) if isinstance(r, dict)}
    dimensions = {str(r.get("id")): r for r in (plan.get("dimensions") or []) if isinstance(r, dict)}
    guards = {str(r.get("id")): r for r in (plan.get("guards") or []) if isinstance(r, dict)}
    for tid in target_ids:
        got = classify_target(targets.get(str(tid)) or {"id": tid}, observe)
        parts.append(f"{tid}:{got.get('status')}")
    for did in dim_ids:
        got = classify_dimension(dimensions.get(str(did)) or {"id": did}, observe)
        parts.append(f"{did}:{got.get('partition') or got.get('status')}")
    for gid in guard_ids:
        got = classify_guard(guards.get(str(gid)) or {"id": gid}, observe)
        parts.append(f"{gid}:{got.get('status')}")
    values = flatten_observe(observe)
    key = values.get("replay.tiling_key")
    if key is None:
        key = values.get("tiling_key")
    if key is not None and str(key) != "":
        parts.append(f"tiling_key:{key}")
    return "|".join(str(p) for p in parts if p)
