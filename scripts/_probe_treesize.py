# -*- coding: utf-8 -*-
"""How big is each dimension's expression, as a DAG and expanded as a tree.

`value_expr` is a DAG: sub-expressions are shared, and the rewrite in K6 is
memoised on node identity so it stays one. Anything downstream that walks it
without sharing pays the expanded size instead, which is the difference
between thousands of nodes and numbers with hundreds of digits.

This says which dimensions are safe to hand to the solver and which are not.

Read-only. Reads what `_probe_derive.py` cached.

    python scripts/_probe_treesize.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _probe_reach import load  # noqa: E402


def dag_nodes(root: Any) -> int:
    seen: set[int] = set()
    stack = [root]
    count = 0
    while stack:
        node = stack.pop()
        if isinstance(node, (dict, list)):
            if id(node) in seen:
                continue
            seen.add(id(node))
            count += 1
            stack.extend(node.values() if isinstance(node, dict) else node)
        else:
            count += 1
    return count


def tree_nodes(root: Any) -> int:
    """Size once sharing is lost. Memoised, so the count is cheap even when
    the number itself is astronomically large."""
    memo: dict[int, int] = {}

    def walk(node: Any) -> int:
        if not isinstance(node, (dict, list)):
            return 1
        hit = memo.get(id(node))
        if hit is not None:
            return hit
        kids = node.values() if isinstance(node, dict) else node
        total = 1 + sum(walk(k) for k in kids)
        memo[id(node)] = total
        return total

    sys.setrecursionlimit(100000)
    return walk(root)


def depth(root: Any) -> int:
    """Longest path from the root. Sets the recursion any compiler needs."""
    memo: dict[int, int] = {}

    def walk(node: Any) -> int:
        if not isinstance(node, (dict, list)):
            return 1
        hit = memo.get(id(node))
        if hit is not None:
            return hit
        kids = list(node.values() if isinstance(node, dict) else node)
        memo[id(node)] = 1 + max((walk(k) for k in kids), default=0)
        return memo[id(node)]

    sys.setrecursionlimit(200000)
    return walk(root)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()

    doc, _var_model, _schema, _binding = load()

    rows = []
    for field in doc.fields:
        if field.value_expr is None:
            rows.append((field.name, 0, 0, 0))
            continue
        rows.append(
            (
                field.name,
                dag_nodes(field.value_expr),
                tree_nodes(field.value_expr),
                depth(field.value_expr),
            )
        )

    print(f"{'dimension':22} {'dag':>8} {'depth':>7}  expanded")
    for name, dag, tree, deep in sorted(rows, key=lambda r: -r[1]):
        digits = len(str(tree))
        shown = str(tree) if digits <= 12 else f"~1e{digits - 1}"
        print(f"{name:22} {dag:>8} {deep:>7}  {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
