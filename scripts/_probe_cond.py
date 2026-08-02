# -*- coding: utf-8 -*-
"""What each dimension was derived to say, next to what the kernel declares.

The metrics say how much of the derivation closed; they do not say whether
what closed is right. This prints the condition itself, in a form that can be
read against the source, and marks every value the kernel declares that the
derived expression cannot produce -- each of those is either a branch the
analysis missed or a value this architecture never emits, and the two look
identical until someone reads them.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init import paths  # noqa: E402
from uo_init.concrete_eval import (  # noqa: E402
    Premises,
    Unknown,
    ValueTree,
    domain_for,
    domains_of,
    samples,
)
from uo_init.op_spec import discover  # noqa: E402
from uo_init.tpl_dsl import parse_file  # noqa: E402

_SHORT = {
    "VAR_ATTR_": "attr.",
    "VAR_SHAPE_": "shape.",
    "VAR_DTYPE_": "dtype.",
    "VAR_INIT_": "uninit#",
    "VAR_LOOPELEM_": "loop#",
    "VAR_SCHED_": "sched#",
    "VAR_UNDECIDED_": "undecided#",
    "VAR_OPTIONAL_": "opt.",
}


def short(name: str) -> str:
    for pre, rep in _SHORT.items():
        if name.startswith(pre):
            return rep + name[len(pre):].lower()
    return name


def render(tree: ValueTree, node, depth: int) -> str:
    node = tree.deref(node)
    if not isinstance(node, dict):
        return repr(node)
    if "lit" in node:
        return repr(node["lit"])
    op = node.get("op")
    if op is None:
        got = node.get("var")
        return short(got) if isinstance(got, str) else f"<{sorted(node)[:2]}>"
    if depth <= 0:
        return "..."
    r = lambda n: render(tree, n, depth - 1)  # noqa: E731
    if op == "if_then_else":
        return f"({r(node.get('condition'))} ? {r(node.get('then'))} : {r(node.get('else'))})"
    if op == "not":
        return f"!{r((node.get('args') or [None])[0])}"
    if op in ("and", "or"):
        sep = " && " if op == "and" else " || "
        return "(" + sep.join(r(a) for a in (node.get("args") or [])) + ")"
    if op in ("in", "not_in"):
        return f"{short(str(node.get('var')))} {'in' if op == 'in' else 'not in'} {node.get('values')}"
    sym = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">=",
           "add": "+", "sub": "-", "mul": "*", "div": "/", "mod": "%"}.get(op, op)
    if "var" in node and "value" in node:
        return f"{short(str(node['var']))} {sym} {node['value']!r}"
    if "lhs" in node or "rhs" in node:
        return f"({r(node.get('lhs'))} {sym} {r(node.get('rhs'))})"
    args = node.get("args") or []
    if len(args) > 1 and sym in "+-*/%":
        return "(" + f" {sym} ".join(r(a) for a in args) + ")"
    return f"{op}({', '.join(r(a) for a in args)})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dims", nargs="*")
    ap.add_argument("--depth", type=int, default=4)
    args = ap.parse_args()

    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        domains, constants = domains_of(pickle.load(fh)["var_model"])
    premises = Premises((doc.get("host_derivation") or {}).get("premises") or [])
    relative = os.environ.get("UO_OPERATOR", "attention/flash_attention_score_grad")
    declared = {d.name: list(d.value_domain) for d in parse_file(discover(paths.op_dir(relative=relative)).tiling_key_header).dims}

    for f in doc["fields"]:
        if args.dims and f["name"] not in args.dims:
            continue
        if f.get("value_expr") is None:
            continue
        tree = ValueTree(f["value_expr"])
        cuts, allvars = tree.cuts()
        divisors = tree.divisors()
        axes = {}
        for v in sorted(allvars):
            vals = samples(cuts.get(v, set()), domain_for(v, domains), constants)
            if v in divisors:
                vals = [x for x in vals if x != 0] or vals
            axes[v] = premises.keeps(v, vals)

        seen = set()
        import itertools
        import random
        rng = random.Random(5)
        space = 1
        for vals in axes.values():
            space *= len(vals)
        draws = (
            [dict(zip(axes, c)) for c in itertools.product(*axes.values())]
            if space <= 20000
            else [{v: rng.choice(vals) for v, vals in axes.items()} for _ in range(20000)]
        )
        for env in draws:
            if premises.rejects(env):
                continue
            try:
                got = tree.value(env)
            except Unknown:
                continue
            if isinstance(got, bool):
                got = int(got)
            if isinstance(got, (int, str)):
                seen.add(got)

        want = set()
        for raw in declared.get(f["name"], []):
            try:
                want.add(int(raw))
            except (TypeError, ValueError):
                want.add(raw)
        missing = want - seen

        print(f"\n{'=' * 78}\n{f['name']}   [{f.get('exactness')}]")
        print(f"  kernel declares {sorted(want, key=str)}")
        print(f"  derivation can produce {sorted(seen, key=str)}"
              + (f"   MISSING {sorted(missing, key=str)}" if missing else "   (all reachable)"))
        if f.get("free_variables"):
            print(f"  free: {[short(v) for v in f['free_variables']]}")
        print(f"  {len(allvars)} inputs, space {space:.3g}")
        print("  " + render(tree, tree.root, args.depth))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
