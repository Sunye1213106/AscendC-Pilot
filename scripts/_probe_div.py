# -*- coding: utf-8 -*-
"""Which denominator actually goes to zero, and what it is made of."""
from __future__ import annotations

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
    Premises,
    Unknown,
    ValueTree,
    domain_for,
    domains_of,
    samples,
)


def sketch(tree: ValueTree, node, depth: int = 3) -> str:
    node = tree.deref(node)
    if not isinstance(node, dict):
        return repr(node)
    if "lit" in node:
        return repr(node["lit"])
    op = node.get("op")
    if op is None:
        return str(node.get("var") or node.get("call") or sorted(node)[:3])
    if depth <= 0:
        return f"{op}(...)"
    if op == "if_then_else":
        return (
            f"({sketch(tree, node.get('condition'), depth - 1)}"
            f" ? {sketch(tree, node.get('then'), depth - 1)}"
            f" : {sketch(tree, node.get('else'), depth - 1)})"
        )
    if "lhs" in node or "rhs" in node:
        return f"{sketch(tree, node.get('lhs'), depth - 1)} {op} {sketch(tree, node.get('rhs'), depth - 1)}"
    if "var" in node:
        return f"{node['var']} {op} {node.get('value')!r}"
    args = [sketch(tree, a, depth - 1) for a in (node.get("args") or ())]
    return f"{op}({', '.join(args)})"


def main() -> int:
    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        domains, constants = domains_of(pickle.load(fh)["var_model"])
    premises = Premises((doc.get("host_derivation") or {}).get("premises") or [])

    field = next(f for f in doc["fields"] if f["name"] == "IsDNoEqual")
    tree = ValueTree(field["value_expr"])
    cuts, allvars = tree.cuts()
    divisors = tree.divisors()
    axes = {}
    for v in sorted(allvars):
        vals = samples(cuts.get(v, set()), domain_for(v, domains), constants)
        if v in divisors:
            vals = [x for x in vals if x != 0] or vals
        axes[v] = premises.keeps(v, vals)

    # Find the div nodes and evaluate each denominator on its own.
    dens = []
    seen = set()

    def walk(node):
        node = tree.deref(node)
        if isinstance(node, list):
            for x in node:
                walk(x)
            return
        if not isinstance(node, dict) or id(node) in seen:
            return
        seen.add(id(node))
        if node.get("op") in ("div", "mod"):
            for arg in (node.get("args") or ())[1:]:
                dens.append((node.get("op"), arg))
        for v in node.values():
            walk(v)

    walk(tree.root)
    print(f"{len(dens)} denominators, {len(divisors)} bare-variable divisors\n")

    rng = random.Random(3)
    blame: Counter = Counter()
    for _ in range(400):
        env = {v: rng.choice(vals) for v, vals in axes.items()}
        if premises.rejects(env):
            continue
        try:
            tree.value(env)
            continue
        except Unknown as exc:
            if "zero" not in str(exc):
                continue
        for op, arg in dens:
            try:
                if tree._eval(arg, env) == 0:
                    blame[sketch(tree, arg)] += 1
            except Unknown:
                pass

    for text, n in blame.most_common(8):
        print(f"{n:5}  {text[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
