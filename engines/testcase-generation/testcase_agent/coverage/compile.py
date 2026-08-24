# -*- coding: utf-8 -*-
"""Compile tg-plan/v3 coverage into a finite obligation list.

Mechanical expansion only. Invalid Plan raises PlanCompileError — no truncation,
no Target fallback, no skipped dimensions.
"""

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


class PlanCompileError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = [str(e) for e in errors if str(e).strip()]
        super().__init__("; ".join(self.errors) or "PLAN_INVALID")


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


def _combo_dim_ids(item: Any) -> list[str]:
    if isinstance(item, dict):
        return _ids(item.get("dims") or item.get("dimensions") or [])
    if isinstance(item, list):
        return [str(x).strip() for x in item if str(x).strip()]
    return []


def _l1_combos(cov: dict[str, Any]) -> tuple[list[list[str]], list[str]]:
    l1 = cov.get("L1")
    raw: Any
    if isinstance(l1, dict):
        raw = l1.get("combinations") or []
    else:
        raw = l1 or []
    out: list[list[str]] = []
    errors: list[str] = []
    if not isinstance(raw, list):
        return out, errors
    for item in raw:
        dims = _combo_dim_ids(item)
        if not dims:
            continue
        if len(dims) != 2 or len(set(dims)) != 2:
            errors.append(f"PLAN_INVALID: L1 must name exactly two unique Dimensions, got {dims}")
            continue
        out.append(dims)
    return out, errors


def _l2_tuples(cov: dict[str, Any]) -> tuple[list[list[str]], list[str]]:
    l2 = cov.get("L2") or []
    if isinstance(l2, dict):
        l2 = l2.get("tuples") or l2.get("combinations") or []
    out: list[list[str]] = []
    errors: list[str] = []
    if not isinstance(l2, list):
        return out, errors
    for item in l2:
        dims = _combo_dim_ids(item)
        if not dims:
            continue
        if len(dims) < 3 or len(set(dims)) != len(dims):
            errors.append(f"PLAN_INVALID: L2 must name unique Dimensions (len>=3), got {dims}")
            continue
        out.append(dims)
    return out, errors


def _l3_guards(cov: dict[str, Any]) -> list[str]:
    l3 = cov.get("L3")
    if isinstance(l3, dict):
        return _ids(l3.get("guards") or [])
    return _ids(l3)


def _declared_targets(plan: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for row in plan.get("targets") or []:
        if isinstance(row, dict):
            tid = str(row.get("id") or "").strip()
            if tid:
                out.append(tid)
    return out


def _dim_target(dim: dict[str, Any], *, did: str) -> tuple[str, str | None]:
    tid = str(dim.get("target") or "").strip()
    if not tid:
        return "", f"PLAN_INVALID: {did}: target required (compiler will not guess)"
    return tid, None


def compile_obligations(
    plan: dict[str, Any],
    *,
    legal_keys: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic expansion. LLM must not interpret L0–L3. No semantic repair."""
    cov = _coverage(plan)
    dims = _dim_map(plan)
    errors: list[str] = []
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
    declared = _declared_targets(plan)
    if enumerate_kind == "legal_keys":
        if len(declared) != 1:
            errors.append("PLAN_INVALID: legal_keys coverage requires exactly one Target")
        tid = declared[0] if len(declared) == 1 else ""
        keys = legal_keys or []
        for raw in keys:
            if isinstance(raw, dict):
                key = raw.get("tiling_key") if raw.get("tiling_key") is not None else raw.get("key")
            else:
                key = raw
            try:
                key_i = int(key)
            except (TypeError, ValueError):
                errors.append(f"PLAN_INVALID: legal_keys entry is not an int: {raw!r}")
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
        if errors:
            raise PlanCompileError(errors)
        return out

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
        dim = dims.get(did)
        if dim is None:
            errors.append(f"PLAN_INVALID: coverage.L0 unknown dimension {did}")
            continue
        tid, err = _dim_target(dim, did=did)
        if err:
            errors.append(err)
            continue
        parts = _partitions(dim)
        if not parts:
            errors.append(f"PLAN_INVALID: {did}: partitions empty")
            continue
        for part in parts:
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

    pairs, l1_errors = _l1_combos(cov)
    errors.extend(l1_errors)
    for pair in pairs:
        left, right = pair[0], pair[1]
        d0, d1 = dims.get(left), dims.get(right)
        if d0 is None or d1 is None:
            errors.append(f"PLAN_INVALID: coverage.L1 unknown dimension in {pair}")
            continue
        t0, e0 = _dim_target(d0, did=left)
        t1, e1 = _dim_target(d1, did=right)
        if e0:
            errors.append(e0)
        if e1:
            errors.append(e1)
        if e0 or e1:
            continue
        if t0 != t1:
            errors.append(
                f"PLAN_INVALID: L1 {pair} Dimensions belong to different Targets {[t0, t1]}"
            )
            continue
        p0, p1 = _partitions(d0), _partitions(d1)
        if not p0 or not p1:
            errors.append(f"PLAN_INVALID: L1 {pair} has a Dimension with empty partitions")
            continue
        for a in p0:
            for b in p1:
                oid = _next_id("O")
                combo = {left: str(a.get("id")), right: str(b.get("id"))}
                out.append(
                    {
                        "id": oid,
                        "level": "L1",
                        "kind": "pairwise",
                        "target": t0,
                        "dimensions": combo,
                        "expected": {
                            "targets": {t0: "HIT"} if t0 else {},
                            "dimensions": combo,
                        },
                        "status": "OPEN",
                    }
                )

    tuples, l2_errors = _l2_tuples(cov)
    errors.extend(l2_errors)
    for tup in tuples:
        missing = [did for did in tup if did not in dims]
        if missing:
            errors.append(f"PLAN_INVALID: coverage.L2 unknown dimension {missing}")
            continue
        tset: list[str] = []
        bad = False
        for did in tup:
            tid, err = _dim_target(dims[did], did=did)
            if err:
                errors.append(err)
                bad = True
            else:
                tset.append(tid)
        if bad:
            continue
        if len(set(tset)) != 1:
            errors.append(f"PLAN_INVALID: L2 {tup} Dimensions belong to different Targets {tset}")
            continue
        parts_list = [_partitions(dims[did]) for did in tup]
        if not all(parts_list):
            errors.append(f"PLAN_INVALID: L2 {tup} has a Dimension with empty partitions")
            continue
        tid = tset[0]
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
        guard = guards.get(gid)
        if guard is None:
            errors.append(f"PLAN_INVALID: coverage.L3 unknown guard {gid}")
            continue
        tid = str(guard.get("target") or "").strip()
        if not tid:
            errors.append(f"PLAN_INVALID: {gid}: target required (compiler will not guess)")
            continue
        fallback = guard.get("fallback") if isinstance(guard.get("fallback"), dict) else {}
        expected: dict[str, Any] = {
            "targets": {tid: "MISS"},
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
    if errors:
        raise PlanCompileError(errors)
    return out
