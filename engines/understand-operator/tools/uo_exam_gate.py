#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FAG arch35 OpenCode exam recipe gate.

    freeze:  python tools/uo_exam_gate.py --freeze
    check:   python tools/uo_exam_gate.py --check
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]

from uo_init.query.exam_gate import compare, score_question  # noqa: E402

DEFAULT_OP = Path(
    r"d:\PR-review\TEST\.ascendc-pr\gitcode.com--cann--ops-transformer--pr-10546"
    r"\attention\flash_attention_score_grad"
)
DEFAULT_RECIPES = (
    REPO
    / "engines"
    / "understand-operator"
    / "tests"
    / "baselines"
    / "fag_arch35_exam_recipes.json"
)
DEFAULT_GOLDEN = (
    REPO
    / "engines"
    / "understand-operator"
    / "tests"
    / "baselines"
    / "fag_arch35_exam_baseline.json"
)
ARTIFACT_DIR = REPO / "artifacts" / "uo-exam-gate"


def collect(op: Path, arch: str, recipes: dict[str, Any]) -> dict[str, Any]:
    from uo_init.uo_query import open_query

    q = open_query(op, architecture=arch)
    questions: list[dict[str, Any]] = []
    try:
        for spec in recipes.get("questions") or []:
            payloads: list[dict[str, Any]] = []
            t0 = time.perf_counter()
            for query in spec.get("queries") or []:
                argv = {
                    "pattern": str(query.get("pattern") or ""),
                    "file": str(query.get("file") or ""),
                    "line": int(query.get("line") or 0),
                }
                payloads.append(q.agent_query(**argv))
            ms = (time.perf_counter() - t0) * 1000
            scored = score_question(spec, payloads, ms)
            scored["n_queries"] = len(payloads)
            questions.append(scored)
    finally:
        q.close()
    ms_list = [float(row.get("ms") or 0) for row in questions]
    return {
        "schema": "uo-exam-gate/v1",
        "arch": arch,
        "op": str(op),
        "questions": questions,
        "totals": {
            "gold_hits": sum(int(r.get("gold_hits") or 0) for r in questions),
            "gold_total": sum(int(r.get("gold_total") or 0) for r in questions),
            "noise": sum(int(r.get("noise") or 0) for r in questions),
            "tokens": sum(int(r.get("tokens") or 0) for r in questions),
            "ms": round(sum(ms_list), 1),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FAG arch35 uo-query exam recipe gate")
    parser.add_argument("--op", type=Path, default=Path(os.environ.get("UO_OP_DIR") or DEFAULT_OP))
    parser.add_argument("--arch", default=os.environ.get("UO_ARCH") or "arch35")
    parser.add_argument("--recipes", type=Path, default=DEFAULT_RECIPES)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.freeze and not args.check:
        args.check = True
    if not args.op.is_dir():
        print(f"operator not found: {args.op}", flush=True)
        return 2
    recipes = json.loads(args.recipes.read_text(encoding="utf-8"))
    current = collect(args.op, args.arch, recipes)
    tot = current["totals"]
    print(
        f"exam questions={len(current['questions'])} gold={tot['gold_hits']}/{tot['gold_total']} "
        f"noise={tot['noise']} tokens={tot['tokens']} ms={tot['ms']}",
        flush=True,
    )
    for row in current["questions"]:
        print(
            f"  {row['id']}: gold {row['gold_hits']}/{row['gold_total']} "
            f"noise={row['noise']} {row['ms']}ms tokens={row['tokens']}",
            flush=True,
        )
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    report = args.report or ARTIFACT_DIR / ("baseline.json" if args.freeze else "current.json")
    report.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {report}", flush=True)
    if args.freeze:
        args.golden.parent.mkdir(parents=True, exist_ok=True)
        args.golden.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"froze golden {args.golden}", flush=True)
        return 0
    if not args.golden.is_file():
        print(f"golden missing: {args.golden} (run --freeze first)", flush=True)
        return 2
    gold = json.loads(args.golden.read_text(encoding="utf-8"))
    diffs = compare(gold, current)
    if not diffs:
        print("EXAM GATE PASS: gold_hits held, noise did not rise, latency in band", flush=True)
        return 0
    print(f"EXAM GATE FAIL: {len(diffs)} regressions — revert this change", flush=True)
    for line in diffs:
        print(f"  {line}", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
