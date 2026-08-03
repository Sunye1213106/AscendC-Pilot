# -*- coding: utf-8 -*-
"""One-shot attribution of the remaining U-R gap. Read-only."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"),
                str(ROOT / "engines" / "understand-operator" / "src")]

from replay import rule_engine as RE  # noqa: E402
from replay import runner as R  # noqa: E402
from replay_runtime_counterexample_gate import (  # noqa: E402
    load_declared, load_runtime, partition,
)


def main() -> int:
    book = RE.default_book()
    seen = load_runtime()
    dec = load_declared()
    _ex, in_r, gap = partition(seen, dec, book)
    dims = list(R.DIM_NAMES)

    print("DECLARED_BUT_NEVER_IN_R")
    for d in dims:
        allv = sorted({str(dec[k][d]) for k in dec})
        got = sorted({str(dec[k][d]) for k in in_r})
        miss = [v for v in allv if v not in got]
        if miss:
            print(f"  {d}: miss={miss}  declared={allv}  seen={got}")

    codes: dict[tuple[str, str], int] = {}

    def row(inst):
        out = []
        for d in dims:
            key = (d, str(inst[d]))
            c = codes.get(key)
            if c is None:
                c = codes[key] = len(codes)
            out.append(c)
        return out

    gap_items = list(gap.items())
    wit_items = list(in_r.items())
    W = [row(inst) for _, inst in wit_items]
    G = [row(inst) for _, inst in gap_items]
    dist: Counter = Counter()
    which: Counter = Counter()
    by_dim: Counter = Counter()
    for (_k, _inst), g in zip(gap_items, G):
        best = 99
        bestdiff: tuple = ()
        for w in W:
            n = 0
            diff = []
            for i, (a, b) in enumerate(zip(g, w)):
                if a != b:
                    n += 1
                    diff.append(dims[i])
                    if n >= best:
                        break
            else:
                if n < best:
                    best = n
                    bestdiff = tuple(diff)
                    if best == 1:
                        break
        dist[best] += 1
        which[bestdiff] += 1
        for d in bestdiff:
            by_dim[d] += 1

    print("DIST", dict(sorted(dist.items())))
    print("TOP_DIFF_COMBOS")
    for c, n in which.most_common(15):
        label = ", ".join(c) if c else "none"
        print(f"  {n:5d}  {label}")
    print("DIMS_INVOLVED_IN_GAP_DIFF")
    for d, n in by_dim.most_common():
        print(f"  {n:5d}  {d}")
    print("GAP_VALUE_HISTO")
    for d in ["SplitAxis", "DeterType", "IsBn2MultiBlk", "IsNzOut",
              "IsTndSwizzle", "IsEmptyTensor", "DTemplateNum", "IsPse",
              "IsTnd", "IsRope", "IsNEqual"]:
        print(f"  {d}:",
              dict(Counter(str(inst[d]) for inst in gap.values()).most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
