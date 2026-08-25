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


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


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


L2_FULL_CROSS_MODES = frozenset({"full_cross", "full_cartesian", "all_dimensions"})

# A full crossing is exponential in the dimension count. Past this many remaining
# cells the plan has not converged enough to hand Solve a finite ledger, so we
# refuse instead of materializing millions of rows. Nominal size is checked
# after exclusions; HARD_CAP only bounds the enumeration loop itself.
L2_FULL_CROSS_CAP = 200_000
L2_ENUMERATION_HARD_CAP = 2_000_000


def l2_is_full_cross(cov: dict[str, Any]) -> bool:
    l2 = cov.get("L2")
    if not isinstance(l2, dict):
        return False
    return str(l2.get("mode") or "").strip().lower() in L2_FULL_CROSS_MODES


def l2_exclusions(cov: dict[str, Any]) -> list[dict[str, Any]]:
    l2 = cov.get("L2")
    if not isinstance(l2, dict):
        return []
    rows = l2.get("exclusions") or []
    return [row for row in rows if isinstance(row, dict)]


def _exclusion_specs(cov: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    """Normalize L2 exclusions into partial cell assignments.

    Each spec is ``{dim_id: partition_id}``; a full-cross cell is excluded when
    it agrees with every entry of any spec.
    """
    specs: list[dict[str, str]] = []
    errors: list[str] = []
    for idx, row in enumerate(l2_exclusions(cov)):
        owner = f"coverage.L2.exclusions[{idx}]"
        parts = row.get("partitions")
        if not isinstance(parts, dict) or len(parts) < 2:
            errors.append(
                f"PLAN_INVALID: {owner}: partitions must map >=2 Dimensions to partition ids"
            )
            continue
        spec = {_s(k): _s(v) for k, v in parts.items() if _s(k) and _s(v)}
        if len(spec) < 2:
            errors.append(f"PLAN_INVALID: {owner}: partitions entries must be non-empty")
            continue
        if not _s(row.get("reason")):
            errors.append(f"PLAN_INVALID: {owner}: reason required (why the combination conflicts)")
            continue
        specs.append(spec)
    return specs, errors


def _cell_excluded(cell: dict[str, str], specs: list[dict[str, str]]) -> bool:
    for spec in specs:
        if all(cell.get(did) == pid for did, pid in spec.items()):
            return True
    return False


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

    if l2_is_full_cross(cov):
        specs, spec_errors = _exclusion_specs(cov)
        errors.extend(spec_errors)
        for did in {d for spec in specs for d in spec}:
            if did not in dims:
                errors.append(f"PLAN_INVALID: coverage.L2.exclusions unknown dimension {did}")
        # Cross every L0 dimension, grouped by Target: crossing dimensions that
        # gate different Targets has no joint HIT to observe.
        by_target: dict[str, list[str]] = {}
        for did in l0_ids:
            dim = dims.get(did)
            if dim is None:
                continue
            tid, err = _dim_target(dim, did=did)
            if err or not tid:
                continue
            if _partitions(dim):
                by_target.setdefault(tid, []).append(did)
        for tid, tdims in by_target.items():
            if len(tdims) < 2:
                continue
            parts_list = [_partitions(dims[did]) for did in tdims]
            nominal = 1
            for row in parts_list:
                nominal *= len(row)
            if nominal > L2_ENUMERATION_HARD_CAP:
                errors.append(
                    f"PLAN_INVALID: coverage.L2 full_cross for {tid} is {nominal} cells "
                    f"(enumeration cap {L2_ENUMERATION_HARD_CAP}); split the Target or "
                    "exclude conflicting Dimension pairs"
                )
                continue
            from itertools import product as _product

            kept: list[dict[str, str]] = []
            excluded_n = 0
            for combo_parts in _product(*parts_list):
                cell = {tdims[i]: str(combo_parts[i].get("id")) for i in range(len(tdims))}
                if _cell_excluded(cell, specs):
                    excluded_n += 1
                    continue
                kept.append(cell)
            remaining = len(kept)
            if remaining > L2_FULL_CROSS_CAP:
                errors.append(
                    f"PLAN_INVALID: coverage.L2 full_cross for {tid} remaining {remaining} cells "
                    f"(nominal {nominal}, excluded {excluded_n}, cap {L2_FULL_CROSS_CAP}); "
                    "split the Target or exclude conflicting Dimension pairs"
                )
                continue
            for cell in kept:
                oid = _next_id("O")
                out.append(
                    {
                        "id": oid,
                        "level": "L2",
                        "kind": "full_cross",
                        "target": tid,
                        "dimensions": cell,
                        "expected": {
                            "targets": {tid: "HIT"},
                            "dimensions": cell,
                        },
                        "status": "OPEN",
                    }
                )
        tuples: list[list[str]] = []
    else:
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


def ledger_counts(plan: dict[str, Any]) -> dict[str, Any]:
    """Mechanical L0–L3 counts plus L2 nominal/excluded. Never invents numbers.

    On compile failure, ``levels`` is empty and ``error`` carries the messages.
    """
    cov = _coverage(plan)
    dims = _dim_map(plan)
    npart = {did: len(_partitions(d)) for did, d in dims.items()}
    l0_ids = _l0_dim_ids(cov)
    by_target: dict[str, list[str]] = {}
    for did in l0_ids:
        dim = dims.get(did)
        if dim is None or not npart.get(did):
            continue
        tid = _s(dim.get("target"))
        if tid:
            by_target.setdefault(tid, []).append(did)
    l2_nominal = 0
    for tdims in by_target.values():
        if len(tdims) < 2:
            continue
        n = 1
        for did in tdims:
            n *= npart[did]
        l2_nominal += n
    try:
        obligations = compile_obligations(plan)
        error: list[str] = []
    except PlanCompileError as exc:
        obligations = []
        error = list(exc.errors)
    levels = {lv: 0 for lv in ("L0", "L1", "L2", "L3")}
    for row in obligations:
        lv = _s(row.get("level"))
        if lv in levels:
            levels[lv] += 1
    full = l2_is_full_cross(cov)
    excluded = (l2_nominal - levels["L2"]) if full else 0
    return {
        "error": error,
        "levels": levels,
        "total": sum(levels.values()),
        "l2_mode": "full_cross" if full else "tuples",
        "l2_nominal": l2_nominal,
        "l2_excluded": excluded,
        "l2_obligations": levels["L2"],
        "l2_exclusion_rules": len(l2_exclusions(cov)),
    }
