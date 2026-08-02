# -*- coding: utf-8 -*-
"""Why an auxiliary does not come back, one draw at a time.

    python scripts/_probe_fix.py [--n 200]

`resolve` reports a name only when two different starting points agree on it,
so a missing name means one of two very different things: the sweeps never
produced a value at all, or they produced two and the start decided which.
The fix for each is different, and the coverage run cannot tell them apart --
both arrive as `unbound`. This does.
"""
from __future__ import annotations

import argparse
import json
import pickle
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.concrete_eval import (  # noqa: E402
    AUX_SEEDS,
    Auxiliaries,
    Premises,
    ValueTree,
    domain_for,
    domains_of,
    samples,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        domains, constants = domains_of(pickle.load(fh)["var_model"])
    saved = doc.get("host_derivation") or {}
    premises = Premises(saved.get("premises") or [])
    aux = Auxiliaries.from_rows(saved.get("auxiliaries") or {})

    fields = [f for f in doc["fields"] if f.get("value_expr") is not None]
    trees = [ValueTree(f["value_expr"]) for f in fields]

    cuts: dict[str, set] = defaultdict(set)
    allvars: set[str] = set()
    divisors: set[str] = set()
    for t in trees + list(aux.trees.values()):
        c, v = t.cuts()
        allvars |= v
        divisors |= t.divisors()
        for k, s in c.items():
            cuts[k] |= s
    allvars -= aux.names
    # Without the values the premises compare against, every draw lands where
    # the operator refuses it and nothing is measured.
    for v in allvars & premises.vars:
        cuts[v] |= premises.cuts.get(v, set())
    axes = {}
    for v in sorted(allvars):
        vals = samples(cuts.get(v, set()), domain_for(v, domains), constants)
        if v in divisors:
            vals = [x for x in vals if x != 0] or vals
        axes[v] = premises.keeps(v, vals)

    rng = random.Random(args.seed)
    verdict: dict[str, Counter] = {n: Counter() for n in sorted(aux.names)}
    disagreed: dict[str, Counter] = defaultdict(Counter)
    why: dict[str, Counter] = defaultdict(Counter)
    drawn_ok = 0
    for _ in range(args.n):
        drawn = {v: rng.choice(vals) for v, vals in axes.items()}
        if premises.rejects(drawn):
            continue
        drawn_ok += 1
        runs = [aux._iterate(drawn, s) for s in AUX_SEEDS]
        for name in verdict:
            here = [r.get(name, "<none>") for r in runs]
            if any(v == "<none>" for v in here):
                verdict[name]["never evaluated"] += 1
                # Replay the last sweep's scope to recover the reason
                # `_iterate` swallowed.
                scope = {**drawn, **{n: AUX_SEEDS[0] for n in aux.names}}
                scope.update(runs[0])
                try:
                    aux.trees[name].value(scope)
                    why[name]["evaluable outside the sweep"] += 1
                except Exception as exc:  # noqa: BLE001
                    why[name][f"{type(exc).__name__}: {exc}"[:70]] += 1
            elif len(set(map(repr, here))) == 1:
                verdict[name]["settled"] += 1
            else:
                verdict[name]["start decided it"] += 1
                disagreed[name][tuple(map(repr, here))] += 1

    print(f"{drawn_ok} draws past the premises, {len(aux.names)} auxiliaries\n")
    for name, c in verdict.items():
        total = sum(c.values()) or 1
        got = c["settled"]
        print(f"{name}")
        print(f"  settled {got}/{total} ({100 * got // total}%)  "
              f"never evaluated {c['never evaluated']}  "
              f"start decided {c['start decided it']}")
        for values, n in disagreed[name].most_common(3):
            print(f"    {n:5}x  seeds {AUX_SEEDS} -> {list(values)}")
        for reason, n in why[name].most_common(3):
            print(f"    {n:5}x  {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
