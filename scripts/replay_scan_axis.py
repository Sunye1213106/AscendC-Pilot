# -*- coding: utf-8 -*-
"""Scan one input axis one value at a time and find where the key changes.

The question behind this: is the key a step function of each input, with a
handful of breakpoints, or does it keep moving? If it steps, the input space
factors into finitely many equivalence classes and enumerating them is a proof
of coverage. If it keeps moving, no amount of sampling ever certifies anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import inputs as I  # noqa: E402
from replay import runner as R  # noqa: E402


def scan(axis: str, values, base: dict, tag: str):
    cases = {f"{tag}{v}": I.Case(**{**base, axis: v}) for v in values}
    res = R.run(cases, tag=f"scan_{tag}")

    seq = []
    for v in values:
        r = res.get(f"{tag}{v}")
        if r is None:
            seq.append((v, None, "missing"))
        elif not r.ok:
            seq.append((v, None, r.reject[:40]))
        else:
            seq.append((v, r.key, ""))

    breaks = []
    prev = seq[0][1]
    for v, key, _ in seq[1:]:
        if key != prev:
            breaks.append((v, prev, key))
            prev = key

    accepted = sum(1 for _, k, _ in seq if k is not None)
    distinct = len({k for _, k, _ in seq if k is not None})
    print(f"\n=== {axis} over {len(values)} values "
          f"({values[0]}..{values[-1]}) ===")
    print(f"  accepted {accepted}, distinct keys {distinct}, "
          f"breakpoints {len(breaks)}")
    if len(breaks) <= 40:
        for v, a, b in breaks:
            print(f"    at {axis}={v}: {a} -> {b}")
    else:
        print(f"    first 20: {[v for v, _, _ in breaks[:20]]}")
        print(f"    last 20:  {[v for v, _, _ in breaks[-20:]]}")
    return breaks


def main() -> int:
    base = dict(layout="BSND", dtype="FLOAT16", b=2, s1=512, s2=512,
                n2=2, g=1, d=128)

    if "--couple" not in sys.argv:
        scan("s1", list(range(1, 1025)), {**base, "s1": 0}, "s1_")
        scan("b", list(range(1, 257)), {**base, "b": 0}, "b_")
        scan("d", list(range(1, 257)), {**base, "d": 0}, "d_")
        return 0

    # Do the breakpoints of one axis stay put when another axis moves? If they
    # do, each axis buckets independently and the equivalence classes are a
    # product of small sets. If they slide, the classes are defined by joint
    # expressions and per-axis bucketing is unsound.
    print("### does s1's breakpoint set depend on the other axes?")
    s1_vals = [1, 2, 4, 8, 16, 32, 64, 96, 128, 160, 192, 256, 320, 384, 512,
               640, 768, 1024, 1536, 2048, 3072, 4096, 6144, 8192]
    for ctx in ({}, {"b": 1}, {"b": 64}, {"b": 128}, {"s2": 128},
                {"s2": 4096}, {"n2": 8}, {"g": 4}, {"d": 64},
                {"dtype": "BFLOAT16"}, {"layout": "BNSD"}, {"layout": "TND"}):
        name = ",".join(f"{k}={v}" for k, v in ctx.items()) or "base"
        bp = scan("s1", s1_vals, {**base, **ctx, "s1": 0},
                  f"c{abs(hash(name)) % 100000}_")
        print(f"  >>> context [{name}] breakpoints at s1 = "
              f"{[v for v, _, _ in bp]}")

    print("\n### and b's, as the product grows?")
    b_vals = [1, 2, 4, 8, 16, 24, 32, 48, 64, 96, 128, 160, 192, 256]
    for ctx in ({}, {"s1": 128}, {"s1": 2048}, {"s2": 2048}, {"n2": 8},
                {"d": 256}):
        name = ",".join(f"{k}={v}" for k, v in ctx.items()) or "base"
        bp = scan("b", b_vals, {**base, **ctx, "b": 0},
                  f"cb{abs(hash(name)) % 100000}_")
        print(f"  >>> context [{name}] breakpoints at b = "
              f"{[v for v, _, _ in bp]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
