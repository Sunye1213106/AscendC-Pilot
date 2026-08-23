# -*- coding: utf-8 -*-
"""Compile tg-plan/v3 coverage into a finite obligation list."""

from __future__ import annotations

from typing import Any

OBLIGATION_STATUSES = (
    "OPEN",
    "CLOSED",
    "MISS",
    "UNKNOWN",
    "REDUNDANT",
    "GUARD_LEAK",
    "PROVED_UNREACHABLE",
)


def _ids(rows: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if isinstance(row, dict):
            vid = str(row.get("id") or "").strip()
            if vid:
                out.append(vid)
        else:
            vid = str(row or "").strip()
            if vid:
                out.append(vid)
    return out


def _dim_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in plan.get("dimensions") or []:
        if isinstance(row, dict) and str(row.get("id") or "").strip():
            out[str(row["id"]).strip()] = row
    return out


def _partitions(dim: dict[str, Any]) -> list[dict[str, Any]]:
    rows = dim.get("partitions") or []
    return [row for row in rows if isinstance(row, dict) and str(row.get("id") or "").strip()]


def _coverage(plan: dict[str, Any]) -> dict[str, Any]:
    cov = plan.get("coverage")
    return cov if isinstance(cov, dict) else {}


def _l0_dim_ids(cov: dict[str, Any]) -> list[str]:
    l0 = cov.get("L0")
    if isinstance(l0, dict):
        return _ids(l0.get("dimensions") or [])
    return _ids(l0)


def _l1_combos(cov: dict[str, Any]) -> list[list[str]]:
    l1 = cov.get("L1")
    raw: Any
    if isinstance(l1, dict):
        raw = l1.get("combinations") or []
    else:
        raw = l1 or []
    out: list[list[str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            dims = _ids(item.get("dims") or item.get("dimensions") or [])
        elif isinstance(item, list):
            dims = [str(x).strip() for x in item if str(x).strip()]
        else:
            dims = []
        if len(dims) >= 2:
            out.append(dims[:2])
    return out


def _l2_tuples(cov: dict[str, Any]) -> list[list[str]]:
    l2 = cov.get("L2") or []
    if isinstance(l2, dict):
        l2 = l2.get("tuples") or l2.get("combinations") or []
    out: list[list[str]] = []
    if not isinstance(l2, list):
        return out
    for item in l2:
        if isinstance(item, dict):
            dims = _ids(item.get("dims") or item.get("dimensions") or [])
        elif isinstance(item, list):
            dims = [str(x).strip() for x in item if str(x).strip()]
        else:
            dims = []
        if len(dims) >= 3:
            out.append(dims)
    return out


def _l3_guards(cov: dict[str, Any]) -> list[str]:
    l3 = cov.get("L3")
    if isinstance(l3, dict):
        return _ids(l3.get("guards") or [])
    return _ids(l3)


def _target_id(plan: dict[str, Any], dim: dict[str, Any] | None = None) -> str:
    if dim and str(dim.get("target") or "").strip():
        return str(dim.get("target")).strip()
    targets = plan.get("targets") or []
    if targets and isinstance(targets[0], dict):
        return str(targets[0].get("id") or "").strip()
    return ""


def compile_obligations(
    plan: dict[str, Any],
    *,
    legal_keys: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic expansion. LLM must not interpret L0–L3."""
    cov = _coverage(plan)
    dims = _dim_map(plan)
    guards = {
        str(row.get("id") or "").strip(): row
        for row in (plan.get("guards") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    out: list[dict[str, Any]] = []
    n = 0

    def _next_id(prefix: str) -> str:
        nonlocal n
        n += 1
        return f"{prefix}{n}"

    enumerate_kind = str(cov.get("enumerate") or "").strip()
    if enumerate_kind == "legal_keys":
        keys = legal_keys or []
        tid = _target_id(plan)
        for raw in keys:
            if isinstance(raw, dict):
                key = raw.get("tiling_key") if raw.get("tiling_key") is not None else raw.get("key")
            else:
                key = raw
            try:
                key_i = int(key)
            except (TypeError, ValueError):
                continue
            oid = _next_id("O")
            out.append(
                {
                    "id": oid,
                    "level": "L0",
                    "kind": "legal_key",
                    "tiling_key": key_i,
                    "target": tid,
                    "expected": {"targets": {tid: "HIT"} if tid else {}},
                    "status": "OPEN",
                }
            )
    else:
        targets = [row for row in (plan.get("targets") or []) if isinstance(row, dict)]
        l0_ids = _l0_dim_ids(cov)
        if not l0_ids and not dims:
            for target in targets:
                tid = str(target.get("id") or "").strip()
                if not tid:
                    continue
                oid = _next_id("O")
                out.append(
                    {
                        "id": oid,
                        "level": "L0",
                        "kind": "target_witness",
                        "target": tid,
                        "expected": {"targets": {tid: "HIT"}},
                        "status": "OPEN",
                    }
                )
        for did in l0_ids:
            dim = dims.get(did) or {}
            tid = _target_id(plan, dim)
            for part in _partitions(dim):
                pid = str(part.get("id") or "").strip()
                oid = _next_id("O")
                out.append(
                    {
                        "id": oid,
                        "level": "L0",
                        "kind": "dimension_partition",
                        "target": tid,
                        "dimensions": {did: pid},
                        "expected": {
                            "targets": {tid: "HIT"} if tid else {},
                            "dimensions": {did: pid},
                        },
                        "status": "OPEN",
                    }
                )

        for pair in _l1_combos(cov):
            left, right = pair[0], pair[1]
            d0, d1 = dims.get(left) or {}, dims.get(right) or {}
            tid = _target_id(plan, d0) or _target_id(plan, d1)
            for p0 in _partitions(d0):
                for p1 in _partitions(d1):
                    oid = _next_id("O")
                    combo = {left: str(p0.get("id")), right: str(p1.get("id"))}
                    out.append(
                        {
                            "id": oid,
                            "level": "L1",
                            "kind": "pairwise",
                            "target": tid,
                            "dimensions": combo,
                            "expected": {
                                "targets": {tid: "HIT"} if tid else {},
                                "dimensions": combo,
                            },
                            "status": "OPEN",
                        }
                    )

        for tup in _l2_tuples(cov):
            parts_list = [_partitions(dims.get(did) or {}) for did in tup]
            if not all(parts_list):
                continue
            tid = _target_id(plan, dims.get(tup[0]))
            from itertools import product as _product

            for combo_parts in _product(*parts_list):
                combo = {tup[i]: str(combo_parts[i].get("id")) for i in range(len(tup))}
                oid = _next_id("O")
                out.append(
                    {
                        "id": oid,
                        "level": "L2",
                        "kind": "higher_order",
                        "target": tid,
                        "dimensions": combo,
                        "expected": {
                            "targets": {tid: "HIT"} if tid else {},
                            "dimensions": combo,
                        },
                        "status": "OPEN",
                    }
                )

    for gid in _l3_guards(cov):
        guard = guards.get(gid) or {}
        tid = str(guard.get("target") or _target_id(plan) or "").strip()
        fallback = guard.get("fallback") if isinstance(guard.get("fallback"), dict) else {}
        expected: dict[str, Any] = {
            "targets": {tid: "MISS"} if tid else {},
            "guards": {gid: "violated"},
        }
        fb_tid = str(fallback.get("target") or "").strip()
        if fb_tid and fallback.get("optional") is not True:
            expected["targets"][fb_tid] = "HIT"
        oid = _next_id("O")
        out.append(
            {
                "id": oid,
                "level": "L3",
                "kind": "guard_negation",
                "target": tid,
                "guard": gid,
                "expected": expected,
                "status": "OPEN",
            }
        )
    return out
