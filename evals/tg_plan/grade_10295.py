# -*- coding: utf-8 -*-
"""Score PR-10295 tg-plan YAML against evals/fixtures/tg-plan/pr-10295-fag-gqa-dense-swizzle/rubric.yaml."""
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
    _eq_value,
    _has_sparse_mode,
    _load,
    _norm,
    _pred_fields,
    _s,
    _walk_preds,
)


def _guard_sparse_modes(guards: list[dict[str, Any]]) -> set[int]:
    out: set[int] = set()
    for g in guards:
        for p in _walk_preds(g.get("predicate") or {}):
            if _s(p.get("op")) != "eq" or _s(p.get("field")) != "case.sparse_mode":
                continue
            try:
                out.add(int(p.get("value")))
            except (TypeError, ValueError):
                continue
    return out


def _dim_is_g1_off(dim: dict[str, Any]) -> bool:
    """True if a Dimension's partitions look like g>1 HIT vs g==1 HIT (wrong)."""
    parts = [p for p in (dim.get("partitions") or []) if isinstance(p, dict)]
    if len(parts) < 2:
        return False
    eq_pairs: list[tuple[int | None, int | None]] = []
    for p in parts:
        n1 = n2 = None
        for pred in _walk_preds(p.get("predicate") or {}):
            if _s(pred.get("op")) != "eq":
                continue
            field = _s(pred.get("field"))
            try:
                val = int(pred.get("value"))
            except (TypeError, ValueError):
                continue
            if field == "case.N1":
                n1 = val
            elif field == "case.N2":
                n2 = val
        eq_pairs.append((n1, n2))
    has_gqa = any(a is not None and b is not None and a != b and a > 0 and b > 0 for a, b in eq_pairs)
    has_mha = any(a is not None and b is not None and a == b and a > 0 for a, b in eq_pairs)
    return has_gqa and has_mha


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
    req_text = _blob((doc.get("requirement") or {}).get("text"))
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
    t_blob = _blob(targets) + _blob(dims)

    # R1 — sparse_mode=0 is a witness; do not invert 9851 token polarity; do not
    # Guard DENSE-legal sparse modes 1–4.
    sm0 = any(_has_sparse_mode(p.get("predicate") or {}, 0) for p in partitions)
    # 9851 HIT polarity copied as *this* DENSE target's necessary condition.
    # Mentions of the BAND fact, or explicit "don't copy 9851", must not fail.
    compact = req_raw.replace(" ", "")
    copied_invert = (
        ("不覆盖全长才" in req_raw or "需token不覆盖" in compact or "需要token不覆盖" in compact)
        and "不能抄" not in req_raw
        and "不要把" not in req_raw
        and "不要抄" not in req_raw
    )
    g_sm = _guard_sparse_modes(guards)
    bad_dense_guard = bool(g_sm & {1, 2, 3, 4})
    token_guard = any(
        "pre_tockens" in _blob(g.get("predicate")) or "next_tockens" in _blob(g.get("predicate"))
        for g in guards
    )
    rep.add(
        "R1",
        sm0 and not copied_invert and not bad_dense_guard and not token_guard,
        f"sm0={sm0} copied_invert={copied_invert} guard_sm={sorted(g_sm)} token_guard={token_guard}",
    )

    # R2 — g>1 / TND; g==1 is Guard not Dimension off-cell; no N1=N2=1 pin
    g_gt1 = "g>1" in req_raw.replace(" ", "") or "g > 1" in req_raw or ("gqa" in all_blob and "n1" in all_blob)
    g1_kill = (
        "g==1" in req_raw.replace(" ", "")
        or "g = 1" in req_raw
        or "g<=1" in req_raw.replace(" ", "")
        or "g <= 1" in req_raw
        or "g==1" in all_blob.replace(" ", "")
    )
    tnd = "tnd" in all_blob
    g1_as_dim = any(_dim_is_g1_off(d) for d in dims)
    n1_pin = any(_eq_value(c.get("predicate") or {}, "case.N1", 1) for c in constraints)
    n2_pin = any(_eq_value(c.get("predicate") or {}, "case.N2", 1) for c in constraints)
    rep.add(
        "R2",
        g_gt1 and g1_kill and tnd and not g1_as_dim and not (n1_pin and n2_pin),
        f"g_gt1={g_gt1} g1_kill={g1_kill} tnd={tnd} g1_as_dim={g1_as_dim} pin_n1n2={n1_pin and n2_pin}",
    )

    # R3 — ALL_MASK / sparse_mode=1 must not be a Guard
    rep.add("R3", 1 not in g_sm, f"guards on sparse_mode={sorted(g_sm)}")

    # R4 — Target must identify SelectGQADenseSchedule, not only deterMaxRound>0
    selected = "selectedround" in t_blob.replace("_", "")
    helper = "selectgqadenseschedule" in all_blob.replace("_", "")
    only_maxround = (
        "determaxround" in t_blob.replace("_", "")
        and "selectedround" not in t_blob.replace("_", "")
        and "selectgqadenseschedule" not in t_blob.replace("_", "")
    )
    sibling_band = "deterbandschedulemode" in t_blob.replace("_", "")
    rep.add(
        "R4",
        selected and helper and not only_maxround and not sibling_band,
        f"selected={selected} helper={helper} only_maxround={only_maxround} sibling_band={sibling_band}",
    )

    # R5 — selector internals named; four bools not unique-class on all HIT rows
    need = ("baseround", "candidateround", "roundcostok", "invalidcostok", "localitybetter", "rowoffsetenough")
    named = all(n in all_blob.replace("_", "").replace("%", "") for n in need) or (
        "baseRound % g" in _s((doc.get("requirement") or {}).get("text"))
        and "roundCostOk" in _s((doc.get("requirement") or {}).get("text"))
        and "invalidCostOk" in _s((doc.get("requirement") or {}).get("text"))
        and "localityBetter" in _s((doc.get("requirement") or {}).get("text"))
        and "rowOffsetEnough" in _s((doc.get("requirement") or {}).get("text"))
    )
    req_compact = req_raw.replace(" ", "").replace("_", "")
    named = (
        "baseround" in req_compact
        and ("candidateround" in req_compact or "candidate" in req_compact)
        and "roundcostok" in req_compact
        and "invalidcostok" in req_compact
        and "localitybetter" in req_compact
        and "rowoffsetenough" in req_compact
    )
    banned = [_norm(n) for n in (rubric.get("unaligned_only_bools") or [])]
    bool_dim = False
    for d in dims:
        blob = _blob(d)
        if any(n and n in blob.replace("_", "") for n in banned):
            bool_dim = True
            break
    rep.add("R5", named and not bool_dim, f"named={named} unaligned_bool_dim={bool_dim}")

    # R6 — not opaque; kernel name; uses probe
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
    kernel = "calgqadenseindex" in all_blob.replace("_", "")
    rep.add(
        "R6",
        not opaque_hits and uses_probe and kernel,
        f"opaque={opaque_hits} uses_probe={uses_probe} kernel={kernel}",
    )

    # R7 — environment aicNum+coreNum; k is aicNum; no 9851 coreNum==2*aicNum constraint
    has_aic = env.get("aicNum") is not None
    has_core = env.get("coreNum") is not None
    k_is_aic = "aicnum" in req_compact and ("k=min(aic" in req_compact or "k = min(aic" in req_raw.replace(" ", "") or "aicnum" in req_compact)
    core2x = any("2*aic" in _blob(c) or "2 * aic" in _blob(c) for c in constraints)
    rep.add("R7", bool(has_aic and has_core and k_is_aic and not core2x), f"env={env} k_is_aic={k_is_aic} core2x={core2x}")

    # R8 — scale
    n_dim, n_part, n_guard = len(dims), len(partitions), len(guards)
    l1_ok = bool(l1) and all(
        isinstance(c, dict) and c.get("dims") and _s(c.get("reason")) for c in l1 if isinstance(c, dict)
    )
    scale = (
        n_dim >= int(scoring.get("min_dimensions") or 5)
        and n_part >= int(scoring.get("min_partitions") or 12)
        and n_guard >= int(scoring.get("min_guards") or 4)
        and (not scoring.get("require_l1", True) or l1_ok)
    )
    rep.add("R8", scale, f"dims={n_dim} partitions={n_part} guards={n_guard} l1={l1_ok}")

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

    # R11 — form
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
        by_id = {_s(d.get("id")): d for d in dims}
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
    guard_controls = set()
    for g in guards:
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
    passed = all(bool(by_id.get(i, {}).get("ok")) for i in required) if required else all(
        c["ok"] for c in rep.checks if c["id"] not in info_ids
    )
    for c in rep.checks:
        extra = f"  {c['detail']}" if not c["ok"] else ""
        if c["id"] in info_ids:
            mark = "INFO"
        else:
            mark = "PASS" if c["ok"] else "FAIL"
        print(f"{mark} {c['id']}{extra}")
    print(f"\n=> {'PASS' if passed else 'FAIL'}")
    if args.json:
        args.json.write_text(
            json.dumps({"passed": passed, "checks": rep.checks}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
