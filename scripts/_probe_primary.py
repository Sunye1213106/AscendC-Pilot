# -*- coding: utf-8 -*-
"""How many locals are folded to a value they only hold before their updates.

`_pick_primary_def` drops every definition that mentions the variable, to get
past `p = CeilDiv(...); p = p + q` and reach the CeilDiv. For an accumulator
that leaves only the initialiser, so `coreIdx = 0; ... coreIdx += 1` folds to
0 and `blockOuter = coreIdx + 1` is pinned to 1 — keys needing more than one
core vanish. Narrowing the feasible set like that invents unreachable keys.

Sizes the fix before making it: how many locals are updated from themselves,
and of those, how many have nothing left but a literal.
"""
from __future__ import annotations

import pickle
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))


def main() -> int:
    from uo_init.host_ir import _IS_LITERAL, _pick_primary_def, _rhs_mentions

    with (ROOT / ".probe_cache" / "fag_bundle.pkl").open("rb") as fh:
        ir = pickle.load(fh)["host_ir"]

    tally: Counter = Counter()
    literal_only: list[tuple[str, str, list[str]]] = []
    keeps_info: list[tuple[str, str, str]] = []
    for fn, defs in ir.defs_by_function().items():
        for var, candidates in defs.items():
            cleaned = [(c or "").strip() for c in candidates if (c or "").strip()]
            if not cleaned:
                continue
            independent = [c for c in cleaned if not _rhs_mentions(var, c)]
            if len(independent) == len(cleaned):
                tally["never updated from itself"] += 1
                continue
            tally["updated from itself"] += 1
            pool = independent or cleaned
            nonlit = [c for c in pool if not _IS_LITERAL.match(c)]
            if nonlit:
                tally["  ... and keeps a non-literal definition"] += 1
                keeps_info.append((fn, var, nonlit[0]))
            else:
                tally["  ... and folds to a bare literal"] += 1
                literal_only.append((fn, var, cleaned))

    for k, c in tally.most_common():
        print(f"{c:6}  {k}")

    print("\nfolded to a literal despite being updated:")
    for fn, var, cands in literal_only[:25]:
        got = _pick_primary_def(var, cands)
        print(f"    {fn}::{var} -> {got!r}   from {cands[:4]}")
    print(f"    ({len(literal_only)} in all)")

    print("\nupdated but keeping a real definition (unchanged by the fix):")
    for fn, var, got in keeps_info[:8]:
        print(f"    {fn}::{var} -> {got[:60]!r}")
    print(f"    ({len(keeps_info)} in all)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
