from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .init import TgInitError, tg_init
from .planner import TgPlanError, tg_plan
from .solve import TgSolveError, tg_solve


def init_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize TestAgent from Understand testcase-contract view")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--op-name", required=True)
    args = parser.parse_args(argv)
    try:
        result = tg_init(args.project_root, args.op_name)
    except TgInitError as exc:
        print(json.dumps({"status": "fail", "message": str(exc), "report": exc.report}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"status": result["run"]["status"], "snapshot_hash": result["snapshot"]["snapshot_hash"]}, ensure_ascii=False, indent=2))
    return 0


def plan_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build TestAgent coverage obligations from frozen Understand snapshot")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--level", choices=["L0", "L1", "L2"], default="L1")
    parser.add_argument("--focus", default="")
    args = parser.parse_args(argv)
    try:
        result = tg_plan(args.project_root, args.op_name, level=args.level, focus=args.focus)
    except TgPlanError as exc:
        print(json.dumps({"status": "fail", "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": result["unresolved"]["status"],
                "test_level": result["test_level"],
                "plan_hash": result["plan_hash"],
                "obligations": len(result["obligations"]),
                "manual_gate": ["approve", "revise", "supplement", "stop"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def solve_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Solve abstract TestAgent candidates from approved phase-one plan")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    args = parser.parse_args(argv)
    try:
        result = tg_solve(args.project_root, args.op_name, timeout_ms=args.timeout_ms)
    except TgSolveError as exc:
        print(json.dumps({"status": "fail", "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    report = result["solver_report"]
    print(
        json.dumps(
            {
                "status": "complete",
                "sat": report["status_counts"]["sat"],
                "unsat": report["status_counts"]["unsat"],
                "unknown": report["status_counts"]["unknown"],
                "selected_candidates": report["selected_candidate_count"],
                "next": "stop_before_real_generation",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(init_main())
