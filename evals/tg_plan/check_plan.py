# -*- coding: utf-8 -*-
"""Self-check a tg-plan/v3 draft before handing it in.

Operator-agnostic. Runs the same validation Solve runs, plus the sizing gates,
and prints one actionable line per problem. Exit 0 means the draft is
structurally ready; remaining quality is a matter of semantics.

Usage:
    python evals/tg_plan/check_plan.py --product <draft.yaml> [--init <init.yaml>]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from sizing import load_plan, size_plan  # noqa: E402


def _init_doc(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else None


def check(plan: dict[str, Any], init: dict[str, Any] | None) -> list[str]:
    """Return a list of problems. Empty means structurally ready."""
    from solve_ready import solve_contract_errors

    from testcase_agent.plan_fill import AssembleError, ensure_v3

    try:
        plan = ensure_v3(plan, init)
    except AssembleError as exc:
        return [f"FILL: {e}" for e in exc.errors]
    problems = [f"CONTRACT: {e}" for e in solve_contract_errors(plan, init)]

    rep = size_plan(plan)
    for err in rep["compile_error"]:
        problems.append(f"COMPILE: {err}")

    if rep["l2_mode"] != "full_cross":
        problems.append(
            "SIZING: coverage.L2 needs `mode: full_cross` plus an exclusions list"
        )
    else:
        if rep["l2_excluded"] <= 0:
            problems.append(
                f"SIZING: L2 excluded 0 of {rep['l2_nominal']} cells -- a raw cartesian "
                "product means no reachability analysis was done"
            )
        if rep["l2_nominal"] and rep["l2_obligations"] <= 0:
            problems.append(
                f"SIZING: L2 exclusions removed all {rep['l2_nominal']} cells, leaving "
                "Solve nothing to prove -- exclude only combinations that truly cannot "
                "hold, and leave the uncertain ones in"
            )

    for did, n in sorted(rep["partitions_by_dimension"].items()):
        if n < 2:
            problems.append(f"SIZING: {did} has {n} partition(s); every Dimension needs >=2")

    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--product", required=True, type=Path)
    ap.add_argument("--init", type=Path, default=None)
    args = ap.parse_args(argv)

    try:
        plan = load_plan(args.product)
    except yaml.YAMLError as exc:
        print("YAML DID NOT PARSE -- fix this first:")
        print(f"  {exc}")
        print(
            "\nMost common cause: a `text: >` block whose lines are not all indented "
            "to the same depth. Every line of a block scalar needs identical leading "
            "spaces."
        )
        return 1

    init = _init_doc(args.init)
    from testcase_agent.plan_fill import AssembleError, ensure_v3

    try:
        plan = ensure_v3(plan, init)
    except AssembleError as exc:
        print("FILL DID NOT ASSEMBLE -- fix this first:")
        for e in exc.errors:
            print(f"  {e}")
        return 1
    problems = check(plan, init)
    rep = size_plan(plan)
    lv = rep["levels"]

    print(f"dimensions={rep['dimensions']} partitions={rep['partitions_total']}")
    print(f"L0={lv['L0']} L1={lv['L1']} L2={lv['L2']} L3={lv['L3']}  total={rep['total_obligations']}")
    if rep["l2_mode"] == "full_cross":
        print(
            f"L2 full_cross: nominal={rep['l2_nominal']} - excluded={rep['l2_excluded']} "
            f"= to_prove_by_solve={rep['l2_obligations']}"
        )
    print()

    if not problems:
        print("READY -- no structural problems.")
        return 0
    print(f"{len(problems)} problem(s) to fix:")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
