# -*- coding: utf-8 -*-
"""How many *distinct* queries do the legal keys really contain?

A key's verdict is a question about all 19 dimensions at once, and there are
8705 of them. But the dimensions do not vary independently: the legal set is
generated from selection rules, so a group of dimensions may take only a handful
of combinations across every key. Asking the solver once per distinct
combination rather than once per key is the difference between hours and
seconds, and it is exact -- the same question always has the same answer.

Reports, per group of dimensions, how many distinct value tuples the legal keys
project onto, and how many keys each tuple covers.

    python scripts/_probe_projection.py
    python scripts/_probe_projection.py --group SplitAxis,DeterType
"""

from __future__ import annotations

import argparse
from collections import Counter

from _probe_reach import load


def projection(rows: list[dict[str, str]], group: list[str]) -> Counter:
    return Counter(tuple(row[name] for name in group) for row in rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--group",
        action="append",
        default=[],
        help="comma-separated dimension names; repeatable",
    )
    ap.add_argument("--show", type=int, default=6, help="tuples to list per group")
    args = ap.parse_args()

    _doc, _var_model, schema, _binding = load()

    from uo_init.materialize_tiling import expand_legal_with_groups

    names = [d.name for d in schema.dims]
    rows = [
        {d.name: str(dims.get(d.name, d.value_domain[0])) for d in schema.dims}
        for _gi, dims in expand_legal_with_groups(schema)
    ]
    print(f"legal keys : {len(rows)}")
    print(f"dimensions : {len(names)}\n")

    print("per-dimension distinct values across the legal set:")
    for name in names:
        values = sorted({row[name] for row in rows})
        shown = ", ".join(values[:6]) + (" ..." if len(values) > 6 else "")
        print(f"  {name:16} {len(values):>3}  {shown}")

    groups = [g.split(",") for g in args.group] if args.group else []
    if not groups:
        return 0

    for group in groups:
        unknown = [n for n in group if n not in names]
        if unknown:
            print(f"\nunknown dimensions: {', '.join(unknown)}")
            continue
        counts = projection(rows, group)
        print(f"\ngroup {'+'.join(group)}")
        print(f"  distinct tuples : {len(counts)}   (keys {len(rows)})")
        for tup, count in counts.most_common(args.show):
            print(f"    {count:>6} keys  {', '.join(tup)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
