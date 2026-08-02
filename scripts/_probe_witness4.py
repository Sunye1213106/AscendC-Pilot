# -*- coding: utf-8 -*-
"""Hunt for a single input where one of the 4 variables changes a dimension.

`_probe_pin4.py` swept all combinations on ~2000 inputs and found none. This
one trades combination coverage for input coverage: one flip per variable per
input, many more inputs, and it stops on the first witness it finds so the
input can be printed and re-run.

A witness proves the variable is load-bearing. Its absence over a large sample
is not a proof of the opposite, but it does bound how much precision a summary
of that variable could buy.
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.concrete_eval import (  # noqa: E402
    Premises,
    Unknown,
    ValueTree,
    domain_for,
    domains_of,
    samples,
)

TARGETS = [
    "VAR_LOOPELEM_INVALIDS1ARRAY_344A1EAA60F0",
    "VAR_LOOPELEM_INVALIDS1ARRAY_A62F1BECD415",
    "VAR_LOOPELEM_PARSEINFO_7555587D750D",
    "VAR_SCHED_COREIDX",
]
DIMS = ["SplitAxis", "DeterType", "IsBn2MultiBlk", "IsNzOut", "IsTndSwizzle"]
FLIPS = {
    "VAR_LOOPELEM_INVALIDS1ARRAY_344A1EAA60F0": [0, 1],
    "VAR_LOOPELEM_INVALIDS1ARRAY_A62F1BECD415": [0, 1],
    "VAR_LOOPELEM_PARSEINFO_7555587D750D": [0, 1, 2, 7, 64, 1024],
    "VAR_SCHED_COREIDX": [0, 1, 2, 8, 35, 48],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--dims", nargs="*", default=DIMS)
    ap.add_argument("--no-premises", action="store_true")
    args = ap.parse_args()

    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        domains, constants = domains_of(pickle.load(fh)["var_model"])
    premises = None
    if not args.no_premises:
        premises = Premises((doc.get("host_derivation") or {}).get("premises") or [])

    rng = random.Random(args.seed)
    for f in doc["fields"]:
        if f["name"] not in args.dims:
            continue
        tree = ValueTree(f.get("value_expr"))
        cuts, allvars = tree.cuts()
        if premises is not None:
            for v in allvars & premises.vars:
                cuts.setdefault(v, set()).update(premises.cuts.get(v, set()))
        axes = {}
        for v in sorted(allvars):
            if v in TARGETS:
                axes[v] = FLIPS[v]
            else:
                axes[v] = samples(cuts.get(v, set()), domain_for(v, domains), constants)
        present = [t for t in TARGETS if t in allvars]

        usable = 0
        found = Counter()
        witness: dict[str, tuple] = {}
        seen_values = set()
        for _ in range(args.n):
            env = {v: rng.choice(vals) for v, vals in axes.items()}
            if premises is not None and premises.rejects(env):
                continue
            try:
                base = tree.value(env)
            except Unknown:
                continue
            if not isinstance(base, (int, str, bool)):
                continue
            usable += 1
            seen_values.add(base)
            for t in present:
                keep = env[t]
                for alt in FLIPS[t]:
                    if alt == keep:
                        continue
                    env[t] = alt
                    try:
                        got = tree.value(env)
                    except Unknown:
                        continue
                    if got != base:
                        found[t] += 1
                        seen_values.add(got)
                        witness.setdefault(t, (keep, alt, base, got, dict(env)))
                        break
                env[t] = keep

        print(f"=== {f['name']} ===  usable {usable}/{args.n}, values seen"
              f" {sorted(seen_values, key=str)}")
        for t in present:
            print(f"  {t:45} flips the answer on {found[t]}/{usable}")
            if t in witness:
                a, b, va, vb, env = witness[t]
                interesting = {k: v for k, v in env.items()
                               if k in TARGETS or v not in (0, 1, False)}
                print(f"      {a} -> {b} turns {va!r} into {vb!r}")
                print(f"      at {interesting}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
