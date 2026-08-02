# -*- coding: utf-8 -*-
"""Why the sampling harness cannot tell any two inputs apart.

The control run found no variable at all — not one of 45 — that changes
`IsBn2MultiBlk`, and only 21 of 250 draws were usable. Either the operator
really does ignore its input here, or the harness is blind, and every
"this variable is dead" claim rests on which one it is.

Splits the two failure modes apart: how many draws each premise rejects,
what the evaluator gives up on, and how much variety the surviving points
actually have.
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--dim", default="IsBn2MultiBlk")
    args = ap.parse_args()

    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        domains, constants = domains_of(pickle.load(fh)["var_model"])
    blobs = (doc.get("host_derivation") or {}).get("premises") or []
    premises = Premises(blobs)
    print(f"premises: {len(premises.trees)} usable, {len(premises.dropped)} dropped")

    field = next(f for f in doc["fields"] if f["name"] == args.dim)
    tree = ValueTree(field.get("value_expr"))
    cuts, allvars = tree.cuts()
    for v in allvars & premises.vars:
        cuts.setdefault(v, set()).update(premises.cuts.get(v, set()))

    divisors = tree.divisors()
    axes = {}
    for v in sorted(allvars):
        vals = samples(cuts.get(v, set()), domain_for(v, domains), constants)
        if v in divisors:
            vals = [x for x in vals if x != 0] or vals
        axes[v] = premises.keeps(v, vals)
    print(f"{len(divisors)} variables sit under a division")
    thin = [v for v, vals in axes.items() if len(vals) < 2]
    print(f"\n{len(axes)} variables; {len(thin)} of them offer a single value")
    for v in thin[:15]:
        print(f"    frozen  {v} = {axes[v]}")
    for v in sorted(axes)[:8]:
        print(f"    {len(axes[v]):3} values  {v}  {str(axes[v])[:90]}")

    # Which premise does the rejecting, and what does evaluation trip over?
    rng = random.Random(args.seed)
    blame: Counter = Counter()
    verdicts: Counter = Counter()
    reasons: Counter = Counter()
    values: Counter = Counter()
    for _ in range(args.n):
        env = {v: rng.choice(vals) for v, vals in axes.items()}
        killed = None
        for i, t in enumerate(premises.trees):
            try:
                if not t.value(env):
                    killed = i
                    break
            except Unknown:
                continue
        if killed is not None:
            verdicts["rejected by a premise"] += 1
            blame[killed] += 1
            continue
        try:
            got = tree.value(env)
        except Unknown as exc:
            verdicts["evaluation gave up"] += 1
            reasons[str(exc)[:70]] += 1
            continue
        if not isinstance(got, (int, str, bool)):
            verdicts[f"non-scalar {type(got).__name__}"] += 1
            continue
        verdicts["usable"] += 1
        values[got] += 1

    print(f"\nof {args.n} draws:")
    for k, c in verdicts.most_common():
        print(f"  {c:5}  {k}")
    if values:
        print(f"\n{args.dim} took {len(values)} distinct values: {dict(values)}")
    if reasons:
        print("\nwhat evaluation tripped over:")
        for k, c in reasons.most_common(8):
            print(f"  {c:5}  {k}")
    if blame:
        print("\nwhich premise rejected (first one to fire):")
        for i, c in blame.most_common(8):
            src = blobs[[j for j, b in enumerate(blobs) if b.get("usable") and b.get("expr")][i]]
            where = f"{str(src.get('function',''))}:{src.get('line','')}"
            print(f"  {c:5}  #{i} {where}  {str(src.get('text',''))[:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
