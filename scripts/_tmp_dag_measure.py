# -*- coding: utf-8 -*-
"""Temporary read-only measurement for rewrite DAG vs tree analysis."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import _probe_reach as probe
from uo_init import key_reachability as kr
from uo_init.derive_key_fields import _dag_postorder, _dag_sizes, expr_tree_size


def dag_distinct(root):
    order, _ = _dag_postorder(root)
    return len(order)


def shared_nodes(root):
    _, refs = _dag_postorder(root)
    return sum(1 for c in refs.values() if c > 1)


def shape_stats(node, depth=0, stats=None):
    if stats is None:
        stats = {"max_depth": 0, "leaves": 0, "ite_count": 0, "top_op": None}
    if isinstance(node, dict):
        op = node.get("op")
        if depth == 0 and op:
            stats["top_op"] = op
        if op == "if_then_else":
            stats["ite_count"] += 1
        stats["max_depth"] = max(stats["max_depth"], depth)
        if op == "lit" or ("var" in node and "op" not in node):
            stats["leaves"] += 1
        for v in node.values():
            shape_stats(v, depth + 1, stats)
    elif isinstance(node, list):
        for v in node:
            shape_stats(v, depth, stats)
    elif isinstance(node, (bool, int, str)) or node is None:
        stats["leaves"] += 1
    return stats


def main() -> int:
    doc_raw = json.loads((ROOT / ".probe_cache" / "fag_derive.json").read_text(encoding="utf-8"))
    fields_meta = {f["name"]: f for f in doc_raw.get("fields", [])}
    print("=== fag_derive.json expanded_chars (input value_expr) ===", flush=True)
    for name in ["SplitAxis", "IsNzOut", "IsTndSwizzle"]:
        f = fields_meta.get(name, {})
        print(
            f"  {name}: expanded_chars={f.get('expanded_chars')}, "
            f"dag_nodes={f.get('nodes')}, tree_nodes={f.get('tree_nodes')}",
            flush=True,
        )

    doc, var_model, _schema, _binding = probe.load()
    symbols = kr._Symbols(kr._named_constants(var_model))
    domains = kr._Domains()
    trees = []
    for fld in doc.fields:
        tree = getattr(fld, "value_expr", None)
        if tree is None:
            continue
        rename = kr._Isolator(fld.name, var_model, {})
        domains.read(tree, rename)
        trees.append((fld.name, fld, tree, rename))
    domains.resolve(symbols)

    print("\n=== per-dimension rewrite (safe DAG metrics) ===", flush=True)
    print(
        f"{'dim':<20} {'in_dag':>8} {'in_tree':>10} {'out_dag':>8} {'out_tree':>10} {'shared':>7} {'ratio':>6}",
        flush=True,
    )
    for name, _fld, tree, rename in trees:
        inp_dag = dag_distinct(tree)
        inp_tree = expr_tree_size(tree)
        rewrite = kr._Rewrite(symbols, rename, domains)
        try:
            adapted = rewrite.run(tree)
        except kr._Unadaptable as exc:
            print(f"{name:<20} OMITTED {exc}", flush=True)
            continue
        out_dag = dag_distinct(adapted)
        out_tree = expr_tree_size(adapted)
        sh = shared_nodes(adapted)
        ratio = out_tree / out_dag if out_dag else 0
        print(
            f"{name:<20} {inp_dag:>8} {inp_tree:>10} {out_dag:>8} {out_tree:>10} {sh:>7} {ratio:>5.1f}x",
            flush=True,
        )
        if name == "SplitAxis":
            s = shape_stats(adapted)
            print("\n=== SplitAxis rewritten shape ===", flush=True)
            print(f"  top_op={s['top_op']}", flush=True)
            print(f"  max_depth={s['max_depth']}", flush=True)
            print(f"  leaves={s['leaves']}", flush=True)
            print(f"  if_then_else_count={s['ite_count']}", flush=True)
            print(f"  distinct_nodes={out_dag}", flush=True)
            print(f"  tree_nodes (json.dumps expansion)={out_tree}", flush=True)
            print(f"  shared_nodes (in-degree>1)={sh}", flush=True)
            print(f"  rewrite._memo size={len(rewrite._memo)}", flush=True)
            print(f"  rewrite._prop_memo size={len(rewrite._prop_memo)}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
