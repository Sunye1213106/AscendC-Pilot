# -*- coding: utf-8 -*-
"""Pick the unresolved key that costs the least to reason about.

Closing a key is an experiment, and the first experiment should isolate one
variable. Among the keys that differ from a real witness in exactly the asked
dimension, this prefers the one whose surrounding context brings in the fewest
other mechanisms: no TND, no rope, no sparse, no deterministic path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import runner as R  # noqa: E402
from replay_closure_gate import load_declared, load_runtime, partition  # noqa: E402

#: Dimensions whose non-default value drags in machinery we would rather not
#: have in a first experiment, and what "quiet" looks like for each.
QUIET = {
    "IsTnd": "0", "IsRope": "0", "IsDrop": "0", "IsAttenMask": "0",
    "IsDNoEqual": "0", "DeterType": "0", "IsTndSwizzle": "0",
    "IsNzOut": "0", "IsBn2MultiBlk": "0", "IsEmptyTensor": "0",
    "SplitAxis": "0", "IsNEqual": "0", "OutDType": "0",
}


def complexity(dims: dict) -> int:
    return sum(1 for d, quiet in QUIET.items() if str(dims.get(d)) != quiet)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dimension", default="IsPse")
    ap.add_argument("--target-value", default="1")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    seen = load_runtime()
    dec = load_declared()
    _, _, gap = partition(seen, dec)

    wit = {k: R.SCHEMA.decode_tiling_key(k) for k in seen if k in dec}

    found = []
    for key, inst in gap.items():
        if str(inst.get(args.dimension)) != args.target_value:
            continue
        for wk, wd in wit.items():
            diff = [d for d in R.DIM_NAMES
                    if str(inst.get(d)) != str(wd.get(d))]
            if diff == [args.dimension]:
                found.append((complexity(inst), key, wk, inst))
                break

    found.sort(key=lambda x: x[0])
    print(f"{len(found)} keys differ from a witness in {args.dimension} alone")
    if not found:
        return 1

    for score, key, wk, inst in found[:args.top]:
        loud = [f"{d}={inst[d]}" for d, q in QUIET.items()
                if str(inst.get(d)) != q]
        print(f"  score {score}  key {key}  witness {seen[wk]['case_id']}"
              + (f"  non-quiet: {', '.join(loud)}" if loud else "  fully quiet"))

    score, key, wk, inst = found[0]
    out = R.CACHE / "obligation.yaml"
    with out.open("w", encoding="utf-8") as f:
        f.write("obligation_id: OBL-%s-001\n" % args.dimension.upper())
        f.write(f"target_key: {key}\n")
        f.write("target_dims:\n")
        for d in R.DIM_NAMES:
            f.write(f"  {d}: {inst[d]}\n")
        f.write("nearest_witness:\n")
        f.write(f"  case_id: {seen[wk]['case_id']}\n")
        f.write(f"  key: {wk}\n")
        f.write("  differing_dims:\n")
        f.write(f"    {args.dimension}: [{R.SCHEMA.decode_tiling_key(wk)[args.dimension]}, "
                f"{inst[args.dimension]}]\n")
        f.write(f"complexity_score: {score}\n")
    print(f"\nchosen -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
