# -*- coding: utf-8 -*-
"""Which bare strings in `value_expr` cost us a TilingKey dimension, and why.

K6 reads a bare string as a constant to fold; when it cannot fold it, the name
is a variable nobody modelled and the whole dimension is dropped
(`_Rewrite._loose`). The IR gives those two cases the same shape, so this walks
every dimension's `value_expr`, collects the bare strings, and says for each
whether the variable model already knows it -- the difference between "nothing
knows this name" and "the information exists but never reached the solver".

Read-only. Reads what `_probe_derive.py` cached.

    python scripts/_probe_bare.py             # only the dropped dimensions
    python scripts/_probe_bare.py --all       # every dimension
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_reach import load  # noqa: E402

#: Keys whose string value names something (a field, a function) rather than
#: standing in for a value. A bare string there is not a symbol to fold.
NAME_KEYS = {
    "var",
    "field",
    "name",
    "fn",
    "function",
    "op",
    "kind",
    "reason",
    # Says how to read a sibling value; not a value itself.
    "value_kind",
}


def walk(node: Any, path: str, seen: set[int], out: list[tuple[str, str, str]]) -> None:
    """Collect (name, parent context, path) for every bare string K6 must fold.

    A string paired with a `var` in the same node is that variable's value --
    `{"var": layout, "value": "SBH"}` -- and `_Rewrite._dict` folds it against
    the other values the same variable is compared with. Those never reach
    `_loose`, so counting them here would bury the handful of strings that do.

    Memoised on identity: `value_expr` is a DAG and walking it as a tree is
    exponential on the wide dimensions.
    """
    if isinstance(node, dict):
        if id(node) in seen:
            return
        seen.add(id(node))
        op = str(node.get("op") or node.get("kind") or "?")
        paired = isinstance(node.get("var"), str)
        for key, value in node.items():
            if key in NAME_KEYS:
                continue
            if key == "value" and paired:
                continue
            if isinstance(value, str):
                out.append((value, f"{op}.{key}", f"{path}.{key}"))
            else:
                walk(value, f"{path}.{key}", seen, out)
    elif isinstance(node, list):
        if id(node) in seen:
            return
        seen.add(id(node))
        for i, value in enumerate(node):
            if isinstance(value, str):
                out.append((value, f"[{i}]", f"{path}[{i}]"))
            else:
                walk(value, f"{path}[{i}]", seen, out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="not just dropped dimensions")
    ap.add_argument("--timeout", type=int, default=5000)
    args = ap.parse_args()

    doc, var_model, _schema, _binding = load()

    from uo_init.key_reachability import KeyReachability

    reach = KeyReachability.from_derivation(doc, var_model, timeout_ms=args.timeout)
    omitted = reach.summary()["omitted"]

    print(f"dimensions omitted: {len(omitted)}")
    for name, why in sorted(omitted.items()):
        print(f"  - {name}: {why}")

    # A name the variable model already carries is one the solver could have
    # constrained; a name it does not is a genuine gap in the derivation.
    known: dict[str, Any] = {}
    try:
        known = dict(var_model.domains())
    except Exception as exc:  # pragma: no cover - diagnostic only
        print(f"(could not read domains: {exc})")

    per_name: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for field in doc.fields:
        if not args.all and field.name not in omitted:
            continue
        if field.value_expr is None:
            print(f"\n{field.name}: value_expr is None")
            continue
        found: list[tuple[str, str, str]] = []
        walk(field.value_expr, "$", set(), found)
        if not found:
            print(f"\n{field.name}: no bare strings")
            continue
        counts: dict[str, int] = defaultdict(int)
        sample: dict[str, tuple[str, str]] = {}
        for name, context, path in found:
            counts[name] += 1
            sample.setdefault(name, (context, path))
            per_name[name].append((field.name, context, path))
        print(f"\n{field.name}: {len(found)} bare strings, {len(counts)} distinct")
        for name in sorted(counts, key=lambda n: (-counts[n], n)):
            context, path = sample[name]
            mark = "in var_model" if name in known or var_model.get(name) else "UNKNOWN"
            tail = path if len(path) <= 56 else "..." + path[-53:]
            print(f"    {name:28} x{counts[name]:<4} {mark:12} {context:16} {tail}")

    if per_name:
        print("\nnames shared across dimensions:")
        for name in sorted(per_name):
            dims = sorted({d for d, _, _ in per_name[name]})
            if len(dims) > 1:
                print(f"  {name:32} {', '.join(dims)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
