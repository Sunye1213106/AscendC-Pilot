# -*- coding: utf-8 -*-
"""Test-space sizing for a tg-plan/v3 coverage IR.

Mechanical and operator-agnostic. Counts come from the engine's own expansion
(``coverage/compile.py``) so the plan never has to hand-compute them, and so the
numbers cannot drift from what Solve will actually consume.

The L2 level is a full crossing of the Dimensions of each Target. The plan's
analysis shows up as ``coverage.L2.exclusions``: cells already proven
impossible. Empty exclusions is valid. ``l2_nominal`` is what a raw cartesian
product would cost, ``l2_excluded`` is what the plan removed, and
``l2_obligations`` is what Solve still has to prove reachable or unreachable.

Usage:
    python evals/tg_plan/sizing.py --product <plan.md or plan.yaml> [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from math import prod
from pathlib import Path
from typing import Any

import yaml

_ENGINE = Path(__file__).resolve().parents[2] / "engines" / "testcase-generation"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


def load_plan(path: Path) -> dict[str, Any]:
    from testcase_agent.plan_fill import load_yaml

    text = path.read_text(encoding="utf-8")
    fence = _FENCE_RE.search(text)
    return load_yaml(fence.group(1) if fence else text)


def _ids(rows: Any) -> list[str]:
    out: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        vid = _s(row.get("id")) if isinstance(row, dict) else _s(row)
        if vid:
            out.append(vid)
    return out


def _l0_dims(cov: dict[str, Any]) -> list[str]:
    node = cov.get("L0")
    return _ids(node.get("dimensions") if isinstance(node, dict) else node)


def size_plan(plan: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent.coverage.compile import ledger_counts

    cov = plan.get("coverage") if isinstance(plan.get("coverage"), dict) else {}
    dims = {
        _s(d.get("id")): d
        for d in (plan.get("dimensions") or [])
        if isinstance(d, dict) and _s(d.get("id"))
    }
    npart = {
        did: len([p for p in (d.get("partitions") or []) if isinstance(p, dict) and _s(p.get("id"))])
        for did, d in dims.items()
    }
    ledger = ledger_counts(plan)
    by_target: dict[str, list[str]] = {}
    for did in _l0_dims(cov):
        dim = dims.get(did)
        if dim is None or not npart.get(did):
            continue
        tid = _s(dim.get("target"))
        if tid:
            by_target.setdefault(tid, []).append(did)
    l2_nominal_by_target = {
        tid: prod(npart[d] for d in tdims)
        for tid, tdims in by_target.items()
        if len(tdims) >= 2
    }
    return {
        "compile_error": ledger["error"],
        "dimensions": len(dims),
        "partitions_total": sum(npart.values()),
        "partitions_by_dimension": npart,
        "targets": sorted(by_target),
        "levels": ledger["levels"],
        "total_obligations": ledger["total"],
        "l2_mode": ledger["l2_mode"],
        "l2_nominal": ledger["l2_nominal"],
        "l2_nominal_by_target": l2_nominal_by_target,
        "l2_excluded": ledger["l2_excluded"],
        "l2_obligations": ledger["l2_obligations"],
        "l2_exclusion_rules": ledger["l2_exclusion_rules"],
        "converged": bool(ledger["l2_mode"] == "full_cross" and ledger["l2_excluded"] > 0),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--product", required=True, type=Path)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    rep = size_plan(load_plan(args.product))
    if rep["compile_error"]:
        print("COMPILE ERROR:")
        for err in rep["compile_error"]:
            print(f"  {err}")
    lv = rep["levels"]
    print(f"dimensions={rep['dimensions']} partitions={rep['partitions_total']} targets={len(rep['targets'])}")
    print(f"L0={lv['L0']} L1={lv['L1']} L2={lv['L2']} L3={lv['L3']}  total={rep['total_obligations']}")
    print(f"L2 mode={rep['l2_mode']}")
    if rep["l2_mode"] == "full_cross":
        print(
            f"  nominal={rep['l2_nominal']} - excluded={rep['l2_excluded']} "
            f"= to_prove_by_solve={rep['l2_obligations']}"
            f"  ({rep['l2_exclusion_rules']} exclusion rules)"
        )
        print(f"  converged={rep['converged']}")
    else:
        print(f"  nominal_if_full_cross={rep['l2_nominal']} (plan listed tuples instead)")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
