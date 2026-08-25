# -*- coding: utf-8 -*-
"""Grade a tg-solve-fill/v1 product against its Plan + init."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_EVALS = _HERE.parent
_ENGINE = _HERE.parents[1] / "engines" / "testcase-generation"
for p in (_EVALS / "tg_plan", _ENGINE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


def grade(fill: dict[str, Any], plan: dict[str, Any], init: dict[str, Any]) -> list[tuple[str, bool, str]]:
    from testcase_agent.plan_fill import AssembleError, ensure_v3
    from testcase_agent.solve_fill import assemble_solve, index_plan, is_solve_fill

    rows_out: list[tuple[str, bool, str]] = []
    is_fill = is_solve_fill(fill)
    rows_out.append(("R1", is_fill and "rows" not in fill, f"fill={is_fill} has_rows={'rows' in fill}"))
    plan_v3 = ensure_v3(plan, init)
    idx = index_plan(plan_v3, init)
    hit_keys = {
        (_s(r.get("dim")), _s(r.get("arm")))
        for r in (fill.get("hits") or [])
        if isinstance(r, dict)
    }
    missing = [
        f"{n['dim']}.{n['arm']}"
        for n in idx["needs_hit"]
        if (n["dim"], n["arm"]) not in hit_keys
        or not any(
            isinstance(r, dict)
            and _s(r.get("dim")) == n["dim"]
            and _s(r.get("arm")) == n["arm"]
            and isinstance(r.get("seed"), dict)
            and r.get("seed")
            for r in (fill.get("hits") or [])
        )
    ]
    rows_out.append(("R2", not missing, f"missing_hits={missing}"))
    need_g = [g["id"] for g in idx["guards"] if not g.get("auto")]
    have_g = {_s(r.get("id")) for r in (fill.get("guard_hits") or []) if isinstance(r, dict)}
    miss_g = [g for g in need_g if g not in have_g]
    rows_out.append(("R3", not miss_g, f"missing_guard_hits={miss_g}"))
    baseline = fill.get("baseline") if isinstance(fill.get("baseline"), dict) else {}
    rows_out.append(("R4", bool(baseline), f"baseline_keys={list(baseline)}"))
    try:
        out = assemble_solve(fill, plan_v3, init)
        err = ""
    except AssembleError as exc:
        out = {"stats": {"obligations": 0, "rows": 0, "unreachable": 0}, "rows": []}
        err = str(exc)
    stats = out.get("stats") or {}
    accounted = int(stats.get("rows") or 0) + int(stats.get("unreachable") or 0)
    total = int(stats.get("obligations") or 0)
    rows_out.append(("R5", bool(err == "" and total and accounted == total), f"{err or stats}"))
    rows_out.append(("R6", int(stats.get("rows") or 0) > 0, f"rows={stats.get('rows')}"))
    cols = [c["name"] if isinstance(c, dict) else str(c) for c in (init.get("columns") or [])]
    sample = (out.get("rows") or [{}])[0] if out.get("rows") else {}
    missing_cols = [c for c in cols if c and c not in sample] if sample else cols
    rows_out.append(("R7", not sample or not missing_cols, f"missing_cols={missing_cols[:8]}"))
    return rows_out


def main() -> int:
    from testcase_agent.plan_fill import load_yaml

    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--init", required=True)
    args = ap.parse_args()
    fill = load_yaml(Path(args.product).read_text(encoding="utf-8"))
    plan = load_yaml(Path(args.plan).read_text(encoding="utf-8"))
    init = load_yaml(Path(args.init).read_text(encoding="utf-8"))
    failed = False
    for rid, ok, note in grade(fill, plan, init):
        print(f"{'PASS' if ok else 'FAIL'} {rid}  {note}")
        failed = failed or not ok
    print("\n=>", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
