# -*- coding: utf-8 -*-
"""Score PR-10335 tg-plan YAML.

Pass = path-correct + Solve-consumable. Scale counts are informational.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grade_plan import (  # noqa: E402
    Report,
    _blob,
    _load,
    _norm,
    _pred_fields,
    _s,
    _walk_preds,
)


def _int_val(pred: dict[str, Any]) -> int | None:
    try:
        return int(pred.get("value"))
    except (TypeError, ValueError):
        return None


def _cuts_is_deter(dim: dict[str, Any]) -> bool:
    vals: set[int] = set()
    for p in dim.get("partitions") or []:
        if not isinstance(p, dict):
            continue
        for pred in _walk_preds(p.get("predicate") or {}):
            if _s(pred.get("field")) == "case.is_deter" and _s(pred.get("op")) == "eq":
                n = _int_val(pred)
                if n is not None:
                    vals.add(n)
    return 0 in vals and 1 in vals


def _cuts_g_ratio(dim: dict[str, Any]) -> bool:
    pairs: list[tuple[int | None, int | None]] = []
    for p in dim.get("partitions") or []:
        if not isinstance(p, dict):
            continue
        n1 = n2 = None
        for pred in _walk_preds(p.get("predicate") or {}):
            if _s(pred.get("op")) != "eq":
                continue
            n = _int_val(pred)
            if n is None:
                continue
            if _s(pred.get("field")) == "case.N1":
                n1 = n
            elif _s(pred.get("field")) == "case.N2":
                n2 = n
        pairs.append((n1, n2))
    has_gqa = any(a is not None and b is not None and a != b and a > 0 and b > 0 for a, b in pairs)
    has_mha = any(a is not None and b is not None and a == b and a > 0 for a, b in pairs)
    return has_gqa and has_mha


def _cuts_safe_probe(dim: dict[str, Any]) -> bool:
    vals: set[int] = set()
    for p in dim.get("partitions") or []:
        if not isinstance(p, dict):
            continue
        for pred in _walk_preds(p.get("predicate") or {}):
            field = _s(pred.get("field")).replace("_", "").lower()
            if "detertndswizzlesafe" in field and _s(pred.get("op")) == "eq":
                n = _int_val(pred)
                if n is not None:
                    vals.add(n)
    return 0 in vals and 1 in vals


def _l1_ids(cover: dict[str, Any]) -> list[list[str]]:
    l1 = cover.get("L1") or []
    if isinstance(l1, dict):
        l1 = l1.get("combinations") or []
    out: list[list[str]] = []
    for combo in l1:
        if isinstance(combo, dict):
            ids = [_s(x) for x in (combo.get("dims") or []) if _s(x)]
            if ids:
                out.append(ids)
    return out


def grade(doc: dict[str, Any], rubric: dict[str, Any], init: dict[str, Any] | None = None) -> Report:
    from grade_plan import prepare_doc
    from testcase_agent.plan_fill import AssembleError

    try:
        doc = prepare_doc(doc, init)
    except AssembleError as exc:
        rep = Report()
        rep.add("R11", False, "; ".join(exc.errors)[:240])
        return rep
    rep = Report()
    scoring = rubric.get("scoring") if isinstance(rubric.get("scoring"), dict) else {}
    req_raw = _s((doc.get("requirement") or {}).get("text")).lower()
    dims = [d for d in (doc.get("dimensions") or []) if isinstance(d, dict)]
    guards = [g for g in (doc.get("guards") or []) if isinstance(g, dict)]
    targets = [t for t in (doc.get("targets") or []) if isinstance(t, dict)]
    constraints = [c for c in (doc.get("constraints") or []) if isinstance(c, dict)]
    untestable = [u for u in (doc.get("untestable") or []) if isinstance(u, dict)]
    oracle = doc.get("oracle") or []
    env = doc.get("environment") if isinstance(doc.get("environment"), dict) else {}
    cover = doc.get("coverage") if isinstance(doc.get("coverage"), dict) else {}
    l1 = cover.get("L1") or []
    if isinstance(l1, dict):
        l1 = l1.get("combinations") or []
    partitions = [p for d in dims for p in (d.get("partitions") or []) if isinstance(p, dict)]
    all_blob = _blob(doc)
    t_blob = _blob(targets)
    compact = all_blob.replace("_", "").replace("-", "")

    # R1 — unique write is IsTndSwizzle, not deterMaxRound
    t_hit = "istndswizzle" in t_blob.replace("_", "").lower()
    only_maxround = (
        "determaxround" in t_blob.replace("_", "").lower()
        and "istndswizzle" not in t_blob.replace("_", "").lower()
    )
    rep.add("R1", t_hit and not only_maxround, f"IsTndSwizzle={t_hit} only_maxround={only_maxround}")

    # R2 — is_deter=0 is a HIT arm, not a Guard
    deter_guard = False
    for g in guards:
        for pred in _walk_preds(g.get("predicate") or {}):
            if _s(pred.get("field")) != "case.is_deter":
                continue
            op = _s(pred.get("op"))
            n = _int_val(pred)
            raw = _s(pred.get("value")).lower()
            if op == "eq" and (n == 0 or raw in {"0", "false"}):
                deter_guard = True
            if op == "ne" and (n == 1 or raw in {"1", "true"}):
                deter_guard = True
    rep.add("R2", not deter_guard, "is_deter=0/off written as kill-all Guard")

    # R3 — g>1 does not kill the whole Target; do not Guard N1/N2
    g_guard = any(
        "case.n1" in {f.lower() for f in _pred_fields(g.get("predicate") or {})}
        or "case.n2" in {f.lower() for f in _pred_fields(g.get("predicate") or {})}
        for g in guards
    )
    rep.add("R3", not g_guard, "N1/N2 used as kill-all Guard; g>1 still hits via nondeter")

    # R4 — TND is HIT; non-TND / B>=129 are kill-all
    tnd_as_guard = False
    for g in guards:
        for pred in _walk_preds(g.get("predicate") or {}):
            if _s(pred.get("field")) != "case.Input_Layout":
                continue
            if _s(pred.get("op")) == "eq" and _s(pred.get("value")).upper() == "TND":
                tnd_as_guard = True
    tnd_mentioned = "tnd" in all_blob
    rep.add("R4", tnd_mentioned and not tnd_as_guard, f"tnd={tnd_mentioned} tnd_as_guard={tnd_as_guard}")

    # R5 — safety helper named; do not L1 safe/g with is_deter dim
    safety = (
        "istnddeterswizzleschedulesafe" in compact
        or "detertndswizzlesafe" in compact
        or "min(aic" in req_raw.replace(" ", "")
        or "m >= min" in req_raw
        or "m>=min" in req_raw.replace(" ", "")
    )
    by_id = {_s(d.get("id")): d for d in dims}
    dead_l1 = False
    for ids in _l1_ids(cover):
        flags = []
        for i in ids:
            d = by_id.get(i)
            if not d:
                continue
            flags.append((_cuts_is_deter(d), _cuts_g_ratio(d), _cuts_safe_probe(d)))
        if len(flags) == 2:
            a, b = flags
            if (a[0] and (b[1] or b[2])) or (b[0] and (a[1] or a[2])):
                dead_l1 = True
    rep.add("R5", safety and not dead_l1, f"safety={safety} dead_l1_arm_cross={dead_l1}")

    # R6 — kernel + probe, not opaque probeable
    kernel = "caltnddenseswizzleindex" in compact
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
    rep.add(
        "R6",
        kernel and uses_probe and not opaque_hits,
        f"kernel={kernel} uses_probe={uses_probe} opaque={opaque_hits}",
    )

    # R7 — environment; do not copy 9851 coreNum==2*aicNum
    has_aic = env.get("aicNum") is not None
    has_core = env.get("coreNum") is not None
    core2x = any("2*aic" in _blob(c) or "2 * aic" in _blob(c) for c in constraints)
    rep.add("R7", bool(has_aic and has_core and not core2x), f"env={env} core2x={core2x}")

    # R8 — scale (informational)
    n_dim, n_part, n_guard = len(dims), len(partitions), len(guards)
    l1_ok = bool(l1) and all(
        isinstance(c, dict) and c.get("dims") and _s(c.get("reason")) for c in l1 if isinstance(c, dict)
    )
    scale = (
        n_dim >= int(scoring.get("min_dimensions") or 4)
        and n_part >= int(scoring.get("min_partitions") or 8)
        and n_guard >= int(scoring.get("min_guards") or 3)
        and (not scoring.get("require_l1", True) or l1_ok)
    )
    rep.add("R8", scale, f"INFO dims={n_dim} partitions={n_part} guards={n_guard} l1={l1_ok}")

    # R9 — md5 oracle
    rep.add("R9", bool(oracle) and "md5" in _blob(oracle), f"oracle={oracle!r}"[:180])

    # R10 — unresolved not in controls
    must_gap = [_s(c) for c in (rubric.get("unresolved_must_gap") or [])]
    used_controls: set[str] = set()
    for d in dims + guards:
        for c in d.get("controls") or []:
            used_controls.add(_s(c))
        for c in ((d.get("construct_hint") or {}) or {}).get("columns") or []:
            used_controls.add(_s(c))
    leaked = [c for c in must_gap if c in used_controls]
    gap_text = _blob(untestable) + _blob(doc.get("test_harness_gap"))
    named_gap = [c for c in must_gap if c.lower() in gap_text]
    kinds_ok = True
    for u in untestable:
        if any(c.lower() in _blob(u) for c in must_gap):
            if _norm(u.get("kind")) not in {"control_gap", "harness_gap"}:
                kinds_ok = False
    rep.add(
        "R10",
        not leaked and len(named_gap) == len(must_gap) and kinds_ok,
        f"leaked={leaked} named={named_gap} kinds_ok={kinds_ok}",
    )

    # R11 — form (H1/H6/H7/guard hint); Solve-contract is R12
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
            if _s(c) and confirmed and _s(c) not in confirmed:
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
    for combo in l1 or []:
        if not isinstance(combo, dict):
            continue
        ids = combo.get("dims") or []
        field_sets = []
        for i in ids:
            d = by_id.get(_s(i))
            if not d:
                continue
            fs: set[str] = set()
            for p in d.get("partitions") or []:
                if isinstance(p, dict):
                    fs |= {f for f in _pred_fields(p.get("predicate") or {}) if f.startswith("case.")}
            field_sets.append(fs)
        for a, b in zip(field_sets, field_sets[1:]):
            overlap = a & b
            if overlap:
                form_err.append(f"H7 overlap {overlap}")
    field_re = re.compile(r"\b(case|replay|probe)\.[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
    if field_re.search(_blob(doc)):
        form_err.append("field has more than two segments")
    guard_controls: set[str] = set()
    for g in guards:
        if not (g.get("negate_hint") or {}):
            form_err.append(f"guard {g.get('id')} missing negate_hint")
        roots = _pred_fields(g.get("predicate") or {})
        if roots and not any(f.startswith("case.") for f in roots):
            form_err.append(f"guard {g.get('id')} predicate not case.*")
        for pred in _walk_preds(g.get("predicate") or {}):
            if _s(pred.get("field")) == "case.is_deter" and isinstance(pred.get("value"), str):
                if _s(pred.get("value")).lower() in {"true", "false"}:
                    form_err.append("is_deter used true/false string")
        for c in g.get("controls") or []:
            guard_controls.add(_s(c))
    for c in constraints:
        for f in _pred_fields(c.get("predicate") or {}):
            col = f.split(".", 1)[-1] if f.startswith("case.") else ""
            if col and col in guard_controls:
                form_err.append(f"constraint pins guard control {col}")
    rep.add("R11", not form_err, "; ".join(form_err)[:240])

    from solve_ready import solve_contract_errors

    fallback = [_s(c) for c in (rubric.get("confirmed_columns") or [])]
    solve_err = solve_contract_errors(doc, init, fallback_columns=fallback)
    rep.add("R12", not solve_err, "; ".join(solve_err)[:240])
    from grade_plan import add_l2_sizing_gate

    add_l2_sizing_gate(rep, doc)
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rubric", required=True, type=Path)
    ap.add_argument("--product", required=True, type=Path)
    ap.add_argument("--init", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--elapsed", type=float, default=None)
    args = ap.parse_args(argv)
    rubric = yaml.safe_load(args.rubric.read_text(encoding="utf-8")) or {}
    doc = _load(args.product)
    init = _load(args.init) if args.init else None
    rep = grade(doc, rubric, init)
    scoring = rubric.get("scoring") if isinstance(rubric.get("scoring"), dict) else {}
    info_ids = {_s(i) for i in (scoring.get("informational_ids") or ["R8"])}
    required = [_s(i) for i in (scoring.get("required_ids") or [c["id"] for c in rep.checks if c["id"] not in info_ids])]
    by_id = {c["id"]: c for c in rep.checks}
    passed = all(bool(by_id.get(i, {}).get("ok")) for i in required) if required else all(
        c["ok"] for c in rep.checks if c["id"] not in info_ids
    )
    for c in rep.checks:
        extra = f"  {c['detail']}" if not c["ok"] else ""
        tag = "INFO" if c["id"] in info_ids else ("PASS" if c["ok"] else "FAIL")
        if c["id"] in info_ids and c["ok"]:
            tag = "INFO"
        elif c["id"] not in info_ids:
            tag = "PASS" if c["ok"] else "FAIL"
        print(f"{tag} {c['id']}{extra}")
    if args.elapsed is not None:
        budget = scoring.get("budget_seconds")
        print(f"INFO elapsed_s={args.elapsed}" + (f" budget={budget}" if budget is not None else ""))
    print(f"\n=> {'PASS' if passed else 'FAIL'}")
    if args.json:
        args.json.write_text(
            json.dumps({"passed": passed, "checks": rep.checks, "elapsed_s": args.elapsed}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
