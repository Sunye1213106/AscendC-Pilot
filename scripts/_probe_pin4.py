# -*- coding: utf-8 -*-
"""Do the 4 blocking free vars actually change any of the 5 open dimensions?

The 5 dimensions carry 42-45 variables, so `enumerate_cells` cannot walk them.
This probe samples input points at random from the same per-variable region
grid `_probe_eval.py` uses, then at each point sweeps the 4 target variables
over their values and records whether the dimension moved.

Three numbers come out per dimension:

  values(free)   what the dimension can be when the 4 vars roam
  values(pinned) what it can be when all 4 are held at one assignment
  sensitive      fraction of sampled inputs where flipping the 4 changed it

`sensitive == 0` would mean the over-approximation label is spurious: the
variables are in the tree but never reach the result. Anything above 0 means
they are load-bearing and have to be summarised before the dimension closes.
"""
from __future__ import annotations

import argparse
import itertools
import json
import pickle
import random
import sys
from collections import defaultdict
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000, help="input points per dim")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        domains, constants = domains_of(pickle.load(fh)["var_model"])
    premises = Premises((doc.get("host_derivation") or {}).get("premises") or [])

    rng = random.Random(args.seed)
    for f in doc["fields"]:
        if f["name"] not in DIMS:
            continue
        tree = ValueTree(f.get("value_expr"))
        cuts, allvars = tree.cuts()
        for v in allvars & premises.vars:
            cuts.setdefault(v, set()).update(premises.cuts.get(v, set()))
        present = [t for t in TARGETS if t in allvars]
        others = sorted(allvars - set(present))
        axes = {v: samples(cuts.get(v, set()), domain_for(v, domains), constants)
                for v in others}
        # the 4 are unconstrained by the model; sweep the values the tree can
        # tell apart, plus 0/1 for the bare-boolean uses
        tgt_axes = []
        for t in present:
            vals = sorted({0, 1} | {c for c in cuts.get(t, set())
                                    if isinstance(c, int)}, key=str)
            tgt_axes.append(vals)

        free_vals: dict = {}
        pinned_vals: dict[tuple, set] = defaultdict(set)
        sensitive = 0
        usable = 0
        per_var_sensitive = defaultdict(int)
        for _ in range(args.n):
            env = {v: rng.choice(vals) for v, vals in axes.items()}
            if premises.rejects(env):
                continue
            got = set()
            by_combo = {}
            for combo in itertools.product(*tgt_axes):
                env.update(dict(zip(present, combo)))
                try:
                    val = tree.value(env)
                except Unknown:
                    continue
                if not isinstance(val, (int, str, bool)):
                    continue
                got.add(val)
                by_combo[combo] = val
                pinned_vals[combo].add(val)
                free_vals.setdefault(val, dict(env))
            if not by_combo:
                continue
            usable += 1
            if len(got) > 1:
                sensitive += 1
                base = next(iter(by_combo))
                for k, t in enumerate(present):
                    for alt in tgt_axes[k]:
                        c2 = list(base)
                        c2[k] = alt
                        if by_combo.get(tuple(c2)) != by_combo[base]:
                            per_var_sensitive[t] += 1
                            break

        print(f"=== {f['name']}  ({f['exactness']}) ===")
        print(f"  usable input points   {usable}/{args.n}")
        print(f"  values when 4 roam    {sorted(free_vals, key=str)}")
        for combo in sorted(pinned_vals, key=str):
            print(f"  values pinned {combo}  {sorted(pinned_vals[combo], key=str)}")
        pct = 100.0 * sensitive / usable if usable else 0.0
        print(f"  inputs where the 4 change the answer: {sensitive} ({pct:.2f}%)")
        for t in present:
            n = per_var_sensitive[t]
            print(f"      {t:45} {n:6}  ({100.0*n/usable if usable else 0:.2f}%)")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
