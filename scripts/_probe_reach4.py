# -*- coding: utf-8 -*-
"""Are the 4 blocking variables ever *read* while evaluating the 5 dimensions?

`_probe_pin4.py` found that sweeping the 4 variables never moved any of the 5
dimensions on 3000 random inputs. That has two very different explanations and
the fix depends on which:

  (a) the sampler never reaches the branch that reads them -- they are
      load-bearing but only on a rare region of the input space;
  (b) the branch is reached and the value is discarded -- the variables are
      dead in the result and the over-approximation label is spurious.

Distinguishing them needs to know whether the leaf was touched at all, so the
environment logs every read the evaluator performs.
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


class LoggingEnv(dict):
    """A plain env that remembers which names the evaluator asked for."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.reads: set[str] = set()

    def __getitem__(self, k):
        self.reads.add(k)
        return super().__getitem__(k)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=11)
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
        if f["name"] not in DIMS:
            continue
        tree = ValueTree(f.get("value_expr"))
        cuts, allvars = tree.cuts()
        if premises is not None:
            for v in allvars & premises.vars:
                cuts.setdefault(v, set()).update(premises.cuts.get(v, set()))
        axes = {}
        for v in sorted(allvars):
            if v in TARGETS:
                axes[v] = [0, 1]
            else:
                axes[v] = samples(cuts.get(v, set()), domain_for(v, domains), constants)

        hit = Counter()
        usable = 0
        refused = 0
        witness: dict[str, dict] = {}
        for _ in range(args.n):
            env = LoggingEnv({v: rng.choice(vals) for v, vals in axes.items()})
            if premises is not None and premises.rejects(dict(env)):
                refused += 1
                continue
            try:
                tree.value(env)
            except Unknown:
                continue
            usable += 1
            for t in TARGETS:
                if t in env.reads:
                    hit[t] += 1
                    witness.setdefault(t, {k: v for k, v in env.items()
                                           if k in env.reads})

        print(f"=== {f['name']} ===  usable {usable}, refused {refused}")
        for t in TARGETS:
            if t in allvars:
                print(f"  {t:45} read on {hit[t]:5}/{usable} inputs")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
