# -*- coding: utf-8 -*-
"""Say which precondition is blocking a dimension that never flipped.

A dimension that stays at one value is either unreachable or under-sampled, and
guessing between those wastes time. The tiling logs its intermediates, so each
conjunct of the condition can be counted separately: the one that is never
satisfied is the one to attack.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import runner as R


def load() -> tuple[list[dict], list[str]]:
    rows = (R.CACHE / "fag_key_cases.csv").read_text(encoding="utf-8").splitlines()
    head = rows[0].split(",")
    out = []
    for line in rows[1:]:
        f = line.split(",")
        if len(f) == len(head):
            out.append(dict(zip(head, f)))
    return out, head


def _i(row: dict, key: str, default: int = -1) -> int:
    v = row.get(key, "")
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def main() -> int:
    rows, _ = load()
    ok = [r for r in rows if r["ok"] == "1" and r.get("log_splitAxis", "")]
    print(f"{len(rows)} cases, {len(ok)} with logs\n")

    # IsTndSwizzle = enableSwizzle && TND && templateSupportCond
    #                && b < 129 && !seq has zero && no EOD tail
    print("=== IsTndSwizzle preconditions ===")
    tnd = [r for r in ok if _i(r, "log_isTnd") == 1]
    print(f"  TND cases with logs: {len(tnd)}")
    conds = {
        "enableSwizzle=1": lambda r: _i(r, "enableSwizzle") == 1,
        "splitAxis=BN2S2(5)": lambda r: _i(r, "log_splitAxis") == 5,
        "not deterministic": lambda r: _i(r, "log_isDeterministic") == 0,
        "sparseType!=3": lambda r: _i(r, "sparseType") != 3,
        "s1>=2048 or (s2>128 and s1>=1024)": lambda r: (
            _i(r, "s1") >= 2048 or (_i(r, "s2") > 128 and _i(r, "s1") >= 1024)),
        "b<129": lambda r: 0 <= _i(r, "b") < 129,
        "no zero-length seq": lambda r: r.get("seq_has_zero") == "0",
    }
    for name, fn in conds.items():
        hit = [r for r in tnd if fn(r)]
        print(f"  {name:<34} {len(hit):>5}/{len(tnd)}")

    survivors = tnd
    print("\n  cases surviving each conjunct, cumulatively:")
    for name, fn in conds.items():
        survivors = [r for r in survivors if fn(r)]
        print(f"    after {name:<34} {len(survivors):>5}")
    if survivors:
        print("\n  survivors that still did not set IsTndSwizzle:")
        for r in survivors[:5]:
            print(f"    {r['case_id']} b={r['b']} s1={r['s1']} s2={r['s2']} "
                  f"d={r['d']} n2={r['n2']} sparse={r['sparse_mode']} "
                  f"IsTndSwizzle={r['dim_IsTndSwizzle']}")

    # The two conjuncts that never hold together are the interesting ones.
    print("\n=== where TND cases lose enableSwizzle ===")
    print("  isExceedL2Cache by count:",
          dict(Counter(r.get("isExceedL2Cache", "") for r in tnd)))
    exceeded = [r for r in tnd if _i(r, "isExceedL2Cache") == 1]
    print(f"  TND with isExceedL2Cache=1: {len(exceeded)}, of those "
          f"enableSwizzle=1: {sum(1 for r in exceeded if _i(r, 'enableSwizzle') == 1)}")
    if exceeded:
        print("  examples (exceed L2 but no swizzle):")
        for r in exceeded[:5]:
            if _i(r, "enableSwizzle") == 0:
                print(f"    {r['case_id']} b={r['b']} s1={r['s1']} s2={r['s2']} "
                      f"n2={r['n2']} g={r['g']} d={r['d']} split={r['log_splitAxis']}")

    print("\n=== splitAxis distribution among TND ===")
    print(" ", dict(Counter(r.get("log_splitAxis", "") for r in tnd)))

    print("\n=== DeterType=1 (DETER_OLD) preconditions ===")
    det = [r for r in ok if _i(r, "log_isDeterministic") > 0]
    print(f"  deterministic cases: {len(det)}")
    print("  DeterType seen:", dict(Counter(r["dim_DeterType"] for r in det)))
    print("  sparse_mode among deterministic:",
          dict(Counter(r["sparse_mode"] for r in det)))

    print("\n=== SplitAxis=5 overall ===")
    five = [r for r in ok if _i(r, "log_splitAxis") == 5]
    print(f"  {len(five)} cases; layouts: "
          f"{dict(Counter(r['layout'] for r in five))}")
    if five:
        r = five[0]
        print(f"  example: {r['case_id']} layout={r['layout']} b={r['b']} "
              f"s1={r['s1']} s2={r['s2']} n2={r['n2']} d={r['d']} "
              f"enableSwizzle={r.get('enableSwizzle')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
