# -*- coding: utf-8 -*-
"""Score PR-10335 tg-plan YAML against evals/fixtures/tg-plan/pr-10335-fag-tnd-dense-swizzle/rubric.yaml."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

# Reuse YAML loader from the 9851 grader.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from grade_plan import Report, _blob, _load, _s, _walk_preds  # noqa: E402


def grade(doc: dict[str, Any], rubric: dict[str, Any], init: dict[str, Any] | None = None) -> Report:
    rep = Report()
    want = rubric.get("must") or {}
    req = _blob((doc.get("requirement") or {}).get("text"))
    dims = [d for d in (doc.get("dimensions") or []) if isinstance(d, dict)]
    guards = [g for g in (doc.get("guards") or []) if isinstance(g, dict)]
    targets = [t for t in (doc.get("targets") or []) if isinstance(t, dict)]
    oracle = doc.get("oracle") or []
    env = doc.get("environment") if isinstance(doc.get("environment"), dict) else {}
    cover = doc.get("coverage") if isinstance(doc.get("coverage"), dict) else {}
    l1 = cover.get("L1") or []
    if isinstance(l1, dict):
        l1 = l1.get("combinations") or []
    parts = [p for d in dims for p in (d.get("partitions") or []) if isinstance(p, dict)]
    all_blob = _blob(doc)

    def mentions(*needles: str) -> bool:
        text = all_blob
        return any(n.lower() in text for n in needles)

    # Target / observation of the unlocked flag
    t_blob = _blob(targets) + _blob(dims)
    fields = want.get("target_fields_any") or ["isTndSwizzle"]
    hit = any(f.lower() in t_blob for f in fields)
    rep.add("T-field", hit, f"targets/dims missing {fields}")

    probe_ok = "probe.istndswizzle" in t_blob or "probe.dertndswizzlesafe" in t_blob.replace(" ", "")
    probe_ok = probe_ok or "probe.isTndSwizzle".lower() in t_blob or "probe.deterTndSwizzleSafe".lower() in t_blob
    replay_ok = "replay.istndswizzle" in t_blob.replace("_", "")
    # simpler
    probe_ok = "probe." in t_blob and ("istnd" in t_blob or "swizzle" in t_blob)
    rep.add("T-observe", "isTndSwizzle".lower() in t_blob or "deterTndSwizzleSafe".lower() in t_blob,
            "no isTndSwizzle / deterTndSwizzleSafe observation")

    rep.add("TND", want.get("layout_tnd_mentioned", True) and ("tnd" in all_blob), "TND layout never mentioned")
    rep.add("deter", "is_deter" in all_blob, "is_deter gate missing")
    gqa = "n1" in all_blob and ("n2" in all_blob or "g==1" in req or "g == 1" in req or "g=1" in req)
    rep.add("g==1", gqa, "g==1 / N1==N2 filter missing")
    dense = "deter_dense" in all_blob or "sparse_mode" in all_blob
    rep.add("DENSE", dense, "DETER_DENSE / sparse_mode path missing")
    kernel = "caltnddenseswizzleindex" in all_blob
    rep.add("kernel-index", kernel, "CalTNDDenseSwizzleIndex not mentioned")
    rep.add("not-disabled", "&& false" not in req and "and false" not in req,
            "requirement still describes the path as compiled-out")
    rep.add("oracle-md5", bool(oracle) and "md5" in _blob(oracle), f"oracle={oracle!r}"[:160])
    has_aic = env.get("aicNum") is not None
    has_core = env.get("coreNum") is not None
    rep.add("env", bool(has_aic and has_core), f"environment={env}")

    n_dim, n_part, n_guard = len(dims), len(parts), len(guards)
    l1_ok = bool(l1) and all(isinstance(c, dict) and c.get("dims") and _s(c.get("reason")) for c in l1 if isinstance(c, dict))
    scale = (
        n_dim >= int(want.get("min_dimensions") or 5)
        and n_part >= int(want.get("min_partitions") or 12)
        and n_guard >= int(want.get("min_guards") or 3)
        and (not want.get("require_l1", True) or l1_ok)
    )
    rep.add("scale", scale, f"dims={n_dim} partitions={n_part} guards={n_guard} l1={l1_ok}")

    must_gap = [_s(c) for c in (rubric.get("unresolved_must_gap") or [])]
    used = set()
    for d in dims + guards:
        for c in d.get("controls") or []:
            used.add(_s(c))
    leaked = [c for c in must_gap if c in used]
    gap_text = _blob(doc.get("untestable")) + _blob(doc.get("test_harness_gap"))
    named = [c for c in must_gap if c.lower() in gap_text]
    rep.add("unresolved", not leaked and len(named) == len(must_gap), f"leaked={leaked} named={named}")

    rep.add("safety-fn", "istnddeterswizzleschedulesafe" in all_blob or "m <" in req or "min(k" in req or "min(aic" in req,
            "IsTndDeterSwizzleScheduleSafe / m>=min(k,n) not covered")

    from solve_ready import solve_contract_errors

    solve_err = solve_contract_errors(doc, init)
    rep.add("solve-contract", not solve_err, "; ".join(solve_err)[:240])
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
    passed = all(c["ok"] for c in rep.checks)
    for c in rep.checks:
        extra = f"  {c['detail']}" if not c["ok"] else ""
        print(f"{'PASS' if c['ok'] else 'FAIL'} {c['id']}{extra}")
    print(f"\n=> {'PASS' if passed else 'FAIL'}")
    if args.json:
        args.json.write_text(json.dumps({"passed": passed, "checks": rep.checks}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
