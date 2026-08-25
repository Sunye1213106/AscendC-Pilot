# -*- coding: utf-8 -*-
"""Dump engine-owned Solve index from a Plan fill/v3 + init."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parents[2] / "engines" / "testcase-generation"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))


def main() -> None:
    from testcase_agent.coverage.compile import compile_obligations, ledger_counts
    from testcase_agent.plan_fill import ensure_v3, load_yaml
    from testcase_agent.solve_fill import index_plan

    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--init", required=True)
    args = ap.parse_args()
    plan = ensure_v3(load_yaml(Path(args.plan).read_text(encoding="utf-8")), load_yaml(Path(args.init).read_text(encoding="utf-8")))
    init = load_yaml(Path(args.init).read_text(encoding="utf-8"))
    idx = index_plan(plan, init)
    obls = compile_obligations(plan)
    counts = ledger_counts(plan)
    print(json.dumps({
        "needs_hit": idx["needs_hit"],
        "auto_arms": len(idx["auto"]),
        "guards": idx["guards"],
        "obligations": len(obls),
        "ledger": counts,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
