# -*- coding: utf-8 -*-
"""Score a tg-plan product against a golden rubric.

Generic on purpose: operator-specific expectations live in the rubric YAML.
Usage:
    python evals/tg_plan/grade_plan.py \
        --rubric evals/fixtures/tg-plan/pr-9851-fag-deter-band/rubric.yaml \
        --product <path to plan.md or raw YAML> \
        [--init <path to init.yaml>] \
        [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

_ENGINE = Path(__file__).resolve().parents[2] / "engines" / "testcase-generation"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


def _norm(val: Any) -> str:
    return _s(val).lower().replace("-", "_").replace(" ", "")


def _load(path: Path) -> dict[str, Any]:
    from testcase_agent.plan_fill import load_yaml

    text = path.read_text(encoding="utf-8")
    fence = _FENCE_RE.search(text)
    blob = fence.group(1) if fence else text
    return load_yaml(blob)


def _walk_preds(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("op"):
            out.append(node)
        for v in node.values():
            out.extend(_walk_preds(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_walk_preds(v))
    return out


def _pred_fields(pred: dict[str, Any]) -> set[str]:
    fields: set[str] = set()
    for p in _walk_preds(pred):
        for key in ("field", "left"):
            f = _s(p.get(key))
            if f:
                fields.add(f)
    return fields


def _blob(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_blob(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_blob(v) for v in value)
    return _s(value).lower()


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(self, cid: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"id": cid, "ok": bool(ok), "detail": detail if not ok else ""})


def add_l2_sizing_gate(rep: Report, doc: dict[str, Any]) -> None:
    """R13: L2 is a full crossing; empty exclusions = no analysis; empty leftover = over-pruned."""
    from testcase_agent.coverage.compile import ledger_counts

    ledger = ledger_counts(doc)
    full = ledger["l2_mode"] == "full_cross"
    excluded = int(ledger["l2_excluded"] or 0)
    leftover = int(ledger["l2_obligations"] or 0)
    r13_ok = full and excluded > 0 and leftover > 0 and not ledger["error"]
    rep.add(
        "R13",
        r13_ok,
        f"mode={ledger['l2_mode']} excluded={excluded} leftover={leftover} err={ledger['error'][:2]}",
    )


def _eq_value(pred: dict[str, Any], field: str, value: Any) -> bool:
    if _s(pred.get("op")) != "eq":
        return False
    if _s(pred.get("field")) != field:
        return False
    got = pred.get("value")
    try:
        return int(got) == int(value)
    except (TypeError, ValueError):
        return _s(got) == _s(value)


def _has_sparse_mode(pred: dict[str, Any], value: int) -> bool:
    return any(_eq_value(p, "case.sparse_mode", value) for p in _walk_preds(pred))


def _mod_eq(pred: dict[str, Any], field: str, divisor: int, value: int) -> bool:
    for p in _walk_preds(pred):
        if _s(p.get("op")) != "mod_eq":
            continue
        left = _s(p.get("left")) or _s(p.get("field"))
        if left != field:
            continue
        try:
            d = int(p.get("divisor"))
            v = int(p.get("value"))
        except (TypeError, ValueError):
            continue
        if d == divisor and v == value:
            return True
    return False


def _cmp(pred: dict[str, Any], field: str, ops: set[str], bound: int, *, want_below: bool) -> bool:
    for p in _walk_preds(pred):
        if _s(p.get("field")) != field or _s(p.get("op")) not in ops:
            continue
        try:
            n = int(p.get("value"))
        except (TypeError, ValueError):
            continue
        if want_below and n < bound:
            return True
        if not want_below and n >= bound:
            return True
    return False


def prepare_doc(doc: dict[str, Any], init: dict[str, Any] | None) -> dict[str, Any]:
    """Accept tg-plan-fill/v1 or tg-plan/v3. Engine expands fill-in."""
    from testcase_agent.plan_fill import ensure_v3

    return ensure_v3(doc, init)


def grade(doc: dict[str, Any], rubric: dict[str, Any], init: dict[str, Any] | None) -> Report:
    from testcase_agent.plan_fill import AssembleError

    try:
        doc = prepare_doc(doc, init)
    except AssembleError as exc:
        rep = Report()
        rep.add("R11", False, "; ".join(exc.errors)[:240])
        return rep
    rep = Report()
    scoring = rubric.get("scoring") if isinstance(rubric.get("scoring"), dict) else {}
    req_text = _blob((doc.get("requirement") or {}).get("text"))
    dims = [d for d in (doc.get("dimensions") or []) if isinstance(d, dict)]
    guards = [g for g in (doc.get("guards") or []) if isinstance(g, dict)]
    targets = [t for t in (doc.get("targets") or []) if isinstance(t, dict)]
    constraints = [c for c in (doc.get("constraints") or []) if isinstance(c, dict)]
    untestable = [u for u in (doc.get("untestable") or []) if isinstance(u, dict)]
    oracle = doc.get("oracle") or []
    env = doc.get("environment") if isinstance(doc.get("environment"), dict) else {}
    cover = doc.get("coverage") if isinstance(doc.get("coverage"), dict) else {}
    l1 = ((cover.get("L1") or {}) if isinstance(cover.get("L1"), dict) else {})
    l1_combos = l1.get("combinations") if isinstance(l1, dict) else (cover.get("L1") or [])
    if isinstance(l1_combos, dict):
        l1_combos = l1_combos.get("combinations") or []
    partitions = [p for d in dims for p in (d.get("partitions") or []) if isinstance(p, dict)]

    rdc = rubric.get("rdc_early_return") or {}
    rdc_mode = int(rdc.get("sparse_mode") or 3)
    s1_gate = int(rdc.get("s1_gate") or 1024)

    # R1 — sparse_mode=0 is a witness; sparse_mode=3 as witness must negate early return
    sm0 = any(_has_sparse_mode(p.get("predicate") or {}, 0) for p in partitions)
    sm3_parts = [p for p in partitions if _has_sparse_mode(p.get("predicate") or {}, rdc_mode)]
    pinned_even = any(_mod_eq(c.get("predicate") or {}, "case.B", 2, 0) for c in constraints)
    pinned_big = any(
        _cmp(c.get("predicate") or {}, "case.S1", {"gt", "ge"}, s1_gate, want_below=False)
        for c in constraints
    )
    sm3_dead = bool(sm3_parts) and pinned_even and pinned_big
    for p in sm3_parts:
        pred = p.get("predicate") or {}
        if _mod_eq(pred, "case.B", 2, 0) and _cmp(pred, "case.S1", {"gt", "ge"}, s1_gate, want_below=False):
            sm3_dead = True
    # Guard that bans ALL sparse_mode=3 (missing the even-B ∧ large-S1 conjunct) treats a
    # legal HIT witness as kill-all.
    for g in guards:
        pred = g.get("predicate") or {}
        if not _has_sparse_mode(pred, rdc_mode):
            continue
        if not (
            _mod_eq(pred, "case.B", 2, 0)
            and _cmp(pred, "case.S1", {"gt", "ge"}, s1_gate, want_below=False)
        ):
            sm3_dead = True
    rep.add("R1", sm0 and not sm3_dead, "missing sparse_mode=0 witness, or sparse_mode=3 witness on the early-return side")

    # R2 — negated early-return recorded
    needles = ("提前返回", "early return", "legacy", "rightdown", "right_down", "right-down", "¬", "negat")
    rep.add("R2", any(n in req_text for n in needles), "requirement.text has no early-return / negation")

    # R3 — token columns appear
    token_hit = any(
        "pre_tockens" in f.lower() or "next_tockens" in f.lower()
        for d in dims
        for f in _pred_fields(d)
    ) or any(
        "pre_tockens" in _blob(c) or "next_tockens" in _blob(c) for c in constraints
    )
    rep.add("R3", token_hit, "Pre_Tockens / Next_Tockens never appear")

    # R4 — constraints must not pin legacy isSplitByBlockIdx gates as required for mode>0
    pinned_even = any(_mod_eq(c.get("predicate") or {}, "case.B", 2, 0) for c in constraints)
    pinned_big = any(
        _cmp(c.get("predicate") or {}, "case.S1", {"gt", "ge"}, s1_gate, want_below=False)
        for c in constraints
    )
    rep.add("R4", not (pinned_even and pinned_big), "constraints pin even B AND S1>=aicNum*128 (legacy gate)")

    # R5 — environment
    has_aic = env.get("aicNum") is not None
    has_core = env.get("coreNum") is not None or "corenum" in _blob(env) or "2*aic" in _blob(env)
    rep.add("R5", bool(has_aic and has_core), f"environment={env}")

    # R6 — probeable names must not be opaque; at least one probe.* classifier
    probeable = [_norm(n) for n in (rubric.get("probeable_names") or [])]
    opaque_hits: list[str] = []
    for u in untestable:
        if _norm(u.get("kind")) != "opaque":
            continue
        text = _norm(_blob(u))
        for name in probeable:
            if name and name in text:
                opaque_hits.append(name)
    uses_probe = any(
        any(str(x).startswith("probe.") for x in (d.get("classifier") or {}).get("requires") or [])
        or any(f.startswith("probe.") for f in _pred_fields(d.get("partitions")))
        for d in dims
    )
    rep.add("R6", not opaque_hits and uses_probe, f"opaque probeable={opaque_hits} uses_probe={uses_probe}")

    # R7 — replay multi-value dimension on deterBandScheduleMode
    mode_dim = False
    for d in dims:
        raw_req = (d.get("classifier") or {}).get("requires") or []
        reqs_flat = [str(x) for x in (raw_req if isinstance(raw_req, list) else [raw_req])]
        parts = [p for p in (d.get("partitions") or []) if isinstance(p, dict)]
        fields: set[str] = set()
        for p in parts:
            fields |= _pred_fields(p.get("predicate") or {})
        if "replay.deterBandScheduleMode" not in reqs_flat and "replay.deterBandScheduleMode" not in fields:
            continue
        vals = set()
        for p in parts:
            for pred in _walk_preds(p.get("predicate") or {}):
                if _s(pred.get("field")) == "replay.deterBandScheduleMode" and _s(pred.get("op")) == "eq":
                    vals.add(_s(pred.get("value")))
        if len(vals) >= 2:
            mode_dim = True
            break
    rep.add("R7", mode_dim, "no Dimension classifies replay.deterBandScheduleMode into >=2 values")

    # R8 — scale
    n_dim = len(dims)
    n_part = len(partitions)
    n_guard = len(guards)
    l1_ok = bool(l1_combos) and all(
        isinstance(c, dict) and c.get("dims") and _s(c.get("reason"))
        for c in l1_combos
        if isinstance(c, dict)
    )
    min_d = int(scoring.get("min_dimensions") or 8)
    min_p = int(scoring.get("min_partitions") or 20)
    min_g = int(scoring.get("min_guards") or 4)
    scale_ok = n_dim >= min_d and n_part >= min_p and n_guard >= min_g
    if scoring.get("require_l1", True):
        scale_ok = scale_ok and l1_ok
    rep.add("R8", scale_ok, f"dims={n_dim} partitions={n_part} guards={n_guard} l1={l1_ok}")

    # R9 — oracle mentions md5
    oracle_text = _blob(oracle)
    rep.add("R9", bool(oracle) and "md5" in oracle_text, f"oracle={oracle!r}"[:180])

    # R10 — unresolved columns not in controls; listed as control_gap
    must_gap = [_s(c) for c in (rubric.get("unresolved_must_gap") or [])]
    used_controls: set[str] = set()
    for d in dims + guards:
        for c in d.get("controls") or []:
            used_controls.add(_s(c))
        for c in ((d.get("construct_hint") or {}) or {}).get("columns") or []:
            used_controls.add(_s(c))
    leaked = [c for c in must_gap if c in used_controls]
    gap_text = _blob(untestable) + _blob(doc.get("test_harness_gap"))
    named = [c for c in must_gap if c.lower() in gap_text]
    kinds_ok = True
    if untestable:
        # those unresolved names, if present, should be control_gap
        for u in untestable:
            if any(c.lower() in _blob(u) for c in must_gap):
                if _norm(u.get("kind")) not in {"control_gap", "harness_gap"}:
                    kinds_ok = False
    rep.add("R10", not leaked and len(named) == len(must_gap) and kinds_ok,
            f"leaked={leaked} named={named} kinds_ok={kinds_ok}")

    # R11 — form: confirmed columns, two-segment fields, targets pointed, H6/H7, guard hints
    mapping = (init or {}).get("mapping") if isinstance((init or {}).get("mapping"), dict) else {}
    confirmed: set[str] = set()
    if mapping:
        for col, row in mapping.items():
            if not isinstance(row, dict):
                continue
            conf = _norm(row.get("confidence"))
            status = _norm((row.get("control") or {}).get("status"))
            if conf == "confirmed" and status == "active":
                confirmed.add(_s(col))
    else:
        confirmed = {_s(c) for c in (rubric.get("confirmed_columns") or [])}

    form_err: list[str] = []
    for d in dims + guards:
        for c in list(d.get("controls") or []) + list(((d.get("construct_hint") or {}) or {}).get("columns") or []):
            if _s(c) and _s(c) not in confirmed:
                form_err.append(f"unconfirmed control {c}")
    pointed = {_s(d.get("target")) for d in dims}
    for t in targets:
        tid = _s(t.get("id"))
        if tid and tid not in pointed:
            form_err.append(f"orphan target {tid}")
    for d in dims:
        colsets = []
        for p in d.get("partitions") or []:
            if isinstance(p, dict):
                colsets.append(frozenset(_pred_fields(p.get("predicate") or {})))
        if colsets and any(s != colsets[0] for s in colsets):
            form_err.append(f"H6 mix {d.get('id')}")
    for combo in l1_combos or []:
        if not isinstance(combo, dict):
            continue
        ids = combo.get("dims") or []
        by_id = {_s(d.get("id")): d for d in dims}
        field_sets = []
        for i in ids:
            d = by_id.get(_s(i))
            if not d:
                continue
            fs: set[str] = set()
            for p in d.get("partitions") or []:
                if isinstance(p, dict):
                    fs |= _pred_fields(p.get("predicate") or {})
            field_sets.append(fs)
        for a, b in zip(field_sets, field_sets[1:]):
            overlap = {f for f in (a & b) if f.startswith("case.")}
            if overlap:
                form_err.append(f"H7 overlap {overlap}")
    field_re = re.compile(r"\b(case|replay|probe)\.[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
    if field_re.search(_blob(doc)):
        # three-or-more segments
        form_err.append("field has more than two segments")
    for g in guards:
        if not (g.get("negate_hint") or {}):
            form_err.append(f"guard {g.get('id')} missing negate_hint")
        roots = _pred_fields(g.get("predicate") or {})
        if roots and not any(f.startswith("case.") for f in roots):
            form_err.append(f"guard {g.get('id')} predicate not case.*")
    rep.add("R11", not form_err, "; ".join(form_err)[:240])

    from solve_ready import solve_contract_errors

    fallback = [_s(c) for c in (rubric.get("confirmed_columns") or [])]
    solve_err = solve_contract_errors(doc, init, fallback_columns=fallback)
    rep.add("R12", not solve_err, "; ".join(solve_err)[:240])
    add_l2_sizing_gate(rep, doc)
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rubric", required=True, type=Path)
    ap.add_argument("--product", required=True, type=Path)
    ap.add_argument("--init", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--elapsed", type=float, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    rubric = yaml.safe_load(args.rubric.read_text(encoding="utf-8")) or {}
    doc = _load(args.product)
    init = _load(args.init) if args.init else None
    rep = grade(doc, rubric, init)
    scoring = rubric.get("scoring") if isinstance(rubric.get("scoring"), dict) else {}
    info_ids = {_s(i) for i in (scoring.get("informational_ids") or [])}
    if scoring.get("required_ids"):
        required = [_s(i) for i in scoring.get("required_ids") or []]
    else:
        required = [c["id"] for c in rep.checks if c["id"] not in info_ids]
    by_id = {c["id"]: c for c in rep.checks}
    gates = {i: bool(by_id.get(i, {}).get("ok")) for i in required}
    budget = scoring.get("budget_seconds")
    if budget is not None and args.elapsed is not None and scoring.get("budget_required"):
        gates[f"elapsed<={budget}s"] = args.elapsed <= float(budget)
    passed = all(gates.values())
    summary = {
        "case": _s(rubric.get("case")),
        "passed": passed,
        "gates": gates,
        "failures": [f"{c['id']}: {c['detail']}" for c in rep.checks if not c["ok"] and c["id"] not in info_ids],
        "info": [f"{c['id']}: {c['detail']}" for c in rep.checks if not c["ok"] and c["id"] in info_ids],
        "elapsed_s": args.elapsed,
    }
    if not args.quiet:
        for c in rep.checks:
            extra = f"  {c['detail']}" if not c["ok"] else ""
            if c["id"] in info_ids:
                mark = "INFO"
            else:
                mark = "PASS" if c["ok"] else "FAIL"
            print(f"{mark} {c['id']}{extra}")
        if args.elapsed is not None:
            print(f"INFO elapsed_s={args.elapsed}" + (f" budget={budget}" if budget is not None else ""))
        print(f"\n=> {'PASS' if passed else 'FAIL'}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"summary": summary, "checks": rep.checks}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
