# -*- coding: utf-8 -*-
"""Which denominator is the one coming out zero, and what it is made of."""
from __future__ import annotations

import json
import pickle
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.concrete_eval import (  # noqa: E402
    Premises,
    Unknown,
    ValueTree,
    domain_for,
    domains_of,
    samples,
)

doc = json.loads((ROOT / ".probe_cache" / "fag_derive.json").read_text(encoding="utf-8"))
with (ROOT / ".probe_cache" / "fag_bundle.pkl").open("rb") as fh:
    domains, constants = domains_of(pickle.load(fh)["var_model"])
premises = Premises((doc.get("host_derivation") or {}).get("premises") or [])
t = [ValueTree(f["value_expr"]) for f in doc["fields"] if f["name"] == "IsNzOut"][0]

cuts, allvars = t.cuts()
divisors = t.divisors()
axes = {}
for v in sorted(allvars):
    vals = samples(cuts.get(v, set()), domain_for(v, domains), constants)
    if v in divisors:
        vals = [x for x in vals if x != 0] or vals
    axes[v] = premises.keeps(v, vals)


def sig(n, d=0):
    n = t.deref(n)
    if not isinstance(n, dict):
        return repr(n)[:24]
    if "lit" in n:
        return str(n["lit"])
    op = n.get("op")
    if op is None:
        return n.get("var", "?")
    if d > 3:
        return op + "(..)"
    return op + "(" + ",".join(sig(a, d + 1) for a in (n.get("args") or [])) + ")"


def guilty(node, env, seen):
    """The innermost denominator that evaluated to zero on this input."""
    node = t.deref(node)
    if isinstance(node, list):
        for x in node:
            got = guilty(x, env, seen)
            if got:
                return got
        return None
    if not isinstance(node, dict) or id(node) in seen:
        return None
    seen.add(id(node))
    for v in node.values():
        got = guilty(v, env, seen)
        if got:
            return got
    if node.get("op") in ("div", "mod"):
        for arg in (node.get("args") or [])[1:]:
            try:
                if t._eval(arg, env) == 0:
                    return arg
            except Unknown:
                pass
    return None


rng = random.Random(3)
blame = Counter()
zeroed = defaultdict(Counter)
shown = 0
for _ in range(400):
    env = {v: rng.choice(vals) for v, vals in axes.items()}
    if premises.rejects(env):
        continue
    try:
        t.value(env)
        continue
    except Unknown as exc:
        if "division" not in str(exc):
            continue
    bad = guilty(t.root, env, set())
    if bad is None:
        blame["<not found>"] += 1
        continue
    s = sig(bad)
    blame[s] += 1
    for v in sorted(ValueTree(bad).cuts()[1]):
        zeroed[s][f"{v}={env.get(v)}"] += 1
    if shown < 2:
        shown += 1
        print(f"--- denominator that came out zero ---\n{sig(bad, -3)}\n")

print(f"{sum(blame.values())} draws divided by zero\n")
for s, c in blame.most_common(6):
    print(f"{c:5}  {s}")
    for k, n in zeroed[s].most_common(6):
        print(f"          {n:5}  {k}")
