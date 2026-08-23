# -*- coding: utf-8 -*-
"""Classify Target / Dimension / Guard from a replay observe bundle."""

from __future__ import annotations

from typing import Any

from .predicate import Truth, evaluate, flatten_observe

HIT = "HIT"
MISS = "MISS"
UNKNOWN = "UNKNOWN"
SATISFIED = "satisfied"
VIOLATED = "violated"


def _truth_to_hit(result: Truth) -> str:
    if result is Truth.TRUE:
        return HIT
    if result is Truth.FALSE:
        return MISS
    return UNKNOWN


def classify_target(target: dict[str, Any], observe: dict[str, Any]) -> dict[str, Any]:
    values = flatten_observe(observe)
    evidence = target.get("evidence") if isinstance(target.get("evidence"), dict) else {}
    kind = str(evidence.get("kind") or "").strip()
    field = str(evidence.get("field") or "").strip()
    expected = evidence.get("expected")
    actual = values.get(field) if field else None
    if kind in {"replay_field", "probe"}:
        if field not in values:
            return {"status": UNKNOWN, "actual": None, "expected": expected}
        expr = {"op": "eq", "field": field, "value": expected}
        ev = evaluate(expr, values)
        return {"status": _truth_to_hit(ev.result), "actual": actual, "expected": expected, "trace": ev.trace}
    if kind == "derived":
        pred = evidence.get("predicate") or evidence.get("expr")
        ev = evaluate(pred, values)
        return {"status": _truth_to_hit(ev.result), "actual": None, "expected": True, "trace": ev.trace}
    if kind == "source_proof":
        return {"status": UNKNOWN, "actual": None, "expected": expected, "reason": "source_proof_not_runtime"}
    state = target.get("state") if isinstance(target.get("state"), dict) else {}
    symbol = str(state.get("symbol") or field or "").strip()
    if symbol and symbol in values:
        ev = evaluate({"op": "eq", "field": symbol, "value": state.get("expected", expected)}, values)
        return {"status": _truth_to_hit(ev.result), "actual": values.get(symbol), "expected": state.get("expected", expected)}
    return {"status": UNKNOWN, "actual": actual, "expected": expected, "reason": "unobservable"}


def classify_dimension(dim: dict[str, Any], observe: dict[str, Any]) -> dict[str, Any]:
    values = flatten_observe(observe)
    parts = dim.get("partitions") or []
    matched: list[str] = []
    unknown = False
    for part in parts:
        if not isinstance(part, dict):
            continue
        pid = str(part.get("id") or "").strip()
        pred = part.get("predicate")
        ev = evaluate(pred, values)
        if ev.result is Truth.TRUE:
            matched.append(pid)
        elif ev.result in {Truth.UNKNOWN, Truth.UNSUPPORTED}:
            unknown = True
    if len(matched) == 1:
        return {"partition": matched[0], "status": "classified"}
    if unknown and not matched:
        return {"partition": None, "status": UNKNOWN}
    if not matched:
        return {"partition": None, "status": MISS}
    return {"partition": None, "status": UNKNOWN, "matched": matched}


def classify_guard(guard: dict[str, Any], observe: dict[str, Any]) -> dict[str, Any]:
    values = flatten_observe(observe)
    pred = guard.get("predicate")
    ev = evaluate(pred, values)
    if ev.result is Truth.TRUE:
        status = SATISFIED
    elif ev.result is Truth.FALSE:
        status = VIOLATED
    else:
        status = UNKNOWN
    return {"status": status, "trace": ev.trace}


def evaluate_obligation(
    obligation: dict[str, Any],
    plan: dict[str, Any],
    observe: dict[str, Any],
    *,
    seen_signatures: set[str] | None = None,
) -> dict[str, Any]:
    targets = {
        str(row.get("id") or "").strip(): row
        for row in (plan.get("targets") or [])
        if isinstance(row, dict)
    }
    dimensions = {
        str(row.get("id") or "").strip(): row
        for row in (plan.get("dimensions") or [])
        if isinstance(row, dict)
    }
    guards = {
        str(row.get("id") or "").strip(): row
        for row in (plan.get("guards") or [])
        if isinstance(row, dict)
    }
    expected = obligation.get("expected") if isinstance(obligation.get("expected"), dict) else {}
    target_got: dict[str, Any] = {}
    dim_got: dict[str, Any] = {}
    guard_got: dict[str, Any] = {}

    for tid, want in (expected.get("targets") or {}).items():
        got = classify_target(targets.get(str(tid)) or {"id": tid}, observe)
        target_got[str(tid)] = got
    for did, want in (expected.get("dimensions") or {}).items():
        got = classify_dimension(dimensions.get(str(did)) or {"id": did}, observe)
        dim_got[str(did)] = got
    for gid, want in (expected.get("guards") or {}).items():
        got = classify_guard(guards.get(str(gid)) or {"id": gid}, observe)
        guard_got[str(gid)] = got

    unknown = False
    miss = False
    leak = False
    for tid, want in (expected.get("targets") or {}).items():
        status = str((target_got.get(str(tid)) or {}).get("status") or UNKNOWN)
        if status == UNKNOWN:
            unknown = True
        elif str(want).upper() == HIT and status != HIT:
            miss = True
        elif str(want).upper() == MISS and status == HIT:
            leak = True
        elif str(want).upper() == MISS and status != MISS:
            miss = True
    for did, want in (expected.get("dimensions") or {}).items():
        got = dim_got.get(str(did)) or {}
        if got.get("status") == UNKNOWN or got.get("partition") is None:
            unknown = True
        elif str(got.get("partition") or "") != str(want):
            miss = True
    for gid, want in (expected.get("guards") or {}).items():
        status = str((guard_got.get(str(gid)) or {}).get("status") or UNKNOWN)
        if status == UNKNOWN:
            unknown = True
        elif str(want) == VIOLATED and status == SATISFIED:
            leak = True
        elif str(want) != status:
            miss = True

    if obligation.get("kind") == "legal_key":
        replay = (observe.get("replay") if isinstance(observe.get("replay"), dict) else {}) or {}
        actual_key = replay.get("tiling_key")
        if actual_key is None:
            actual_key = replay.get("key")
        try:
            actual_i = int(actual_key)
        except (TypeError, ValueError):
            actual_i = None
        want_key = obligation.get("tiling_key")
        if actual_i is None:
            unknown = True
        elif int(want_key) != actual_i:
            miss = True

    from .signature import semantic_signature

    signature = semantic_signature(plan, observe, obligation=obligation)
    status = "CLOSED"
    if leak and str(obligation.get("level") or "") == "L3":
        status = "GUARD_LEAK"
    elif unknown:
        status = "UNKNOWN"
    elif miss:
        status = "MISS"
    elif seen_signatures is not None and signature in seen_signatures and status == "CLOSED":
        status = "REDUNDANT"
    return {
        "obligation": str(obligation.get("id") or ""),
        "status": status,
        "targets": target_got,
        "dimensions": dim_got,
        "guards": guard_got,
        "signature": signature,
    }
