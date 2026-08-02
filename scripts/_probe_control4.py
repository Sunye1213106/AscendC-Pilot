# -*- coding: utf-8 -*-
"""Control for `_probe_witness4.py`: does *any* variable flip these dimensions?

The witness hunt found zero flips for the 4 blocking variables over 17k input
points. That number only means something if the same harness does find flips
for variables that are known to matter. This runs the identical procedure over
every variable each dimension reads and ranks them, so the 4 can be read
against the rest of the field rather than against nothing.
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

TARGETS = {
    "VAR_LOOPELEM_INVALIDS1ARRAY_344A1EAA60F0",
    "VAR_LOOPELEM_INVALIDS1ARRAY_A62F1BECD415",
    "VAR_LOOPELEM_PARSEINFO_7555587D750D",
    "VAR_SCHED_COREIDX",
}
DIMS = ["SplitAxis", "DeterType", "IsBn2MultiBlk", "IsNzOut", "IsTndSwizzle"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--dims", nargs="*", default=DIMS)
    args = ap.parse_args()

    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        domains, constants = domains_of(pickle.load(fh)["var_model"])
    premises = Premises((doc.get("host_derivation") or {}).get("premises") or [])

    rng = random.Random(args.seed)
    for f in doc["fields"]:
        if f["name"] not in args.dims:
            continue
        tree = ValueTree(f.get("value_expr"))
        cuts, allvars = tree.cuts()
        for v in allvars & premises.vars:
            cuts.setdefault(v, set()).update(premises.cuts.get(v, set()))
        axes = {}
        for v in sorted(allvars):
            if v in TARGETS:
                axes[v] = [0, 1, 2, 36]
            else:
                axes[v] = samples(cuts.get(v, set()), domain_for(v, domains), constants)

        usable = 0
        flips = Counter()
        for _ in range(args.n):
            env = {v: rng.choice(vals) for v, vals in axes.items()}
            if premises.rejects(env):
                continue
            try:
                base = tree.value(env)
            except Unknown:
                continue
            if not isinstance(base, (int, str, bool)):
                continue
            usable += 1
            for v, vals in axes.items():
                keep = env[v]
                for alt in vals:
                    if alt == keep:
                        continue
                    env[v] = alt
                    try:
                        got = tree.value(env)
                    except Unknown:
                        continue
                    if got != base:
                        flips[v] += 1
                        break
                env[v] = keep

        print(f"=== {f['name']} ===  usable {usable}/{args.n}, {len(axes)} variables")
        ranked = sorted(axes, key=lambda v: (-flips[v], v))
        movers = [v for v in ranked if flips[v]]
        print(f"  {len(movers)} of {len(axes)} variables move it at least once")
        for v in ranked[:12]:
            mark = "  <== target" if v in TARGETS else ""
            print(f"    {flips[v]:6}/{usable}  {v}{mark}")
        for v in sorted(TARGETS & set(axes)):
            print(f"    TARGET {flips[v]:6}/{usable}  {v}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
