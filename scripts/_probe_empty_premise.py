# -*- coding: utf-8 -*-
"""Does an unguarded read really leave write coverage unprovable?

`_read_forces_a_write` returns False as soon as the read has no path
conditions, and `guards_cover` refuses an empty premise. Both read as caution,
but the direction is backwards: an empty premise is `True`, the *weakest* one
there is, so `True and not(or writes)` being unsat is a stronger result than
the same query under any real read condition -- and it is the query that
decides whether an if/else-if chain covers every run.

This reproduces the write-guard shape of GetDeterSparseTilingKey, whose
VAR_INIT currently blocks three dimensions, and asks the solver both ways.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common" / "src"))


@dataclass(frozen=True)
class Cond:
    text: str
    negated: bool = False


# GetDeterSparseTilingKey @ normal_regbase.cpp:793..813, as `mint_detertype.txt`
# records it. Guard texts are the branch conditions; the chain is an if /
# else-if with a trailing guard_clause on the same test as the second arm.
A = "isDeterministic_is_false"
B = "not_sparse_or_all_mask"
C = "left_up_causal"
D = "band_mode"

WRITES = [
    ([Cond(A)], "GetDeterSparseTilingKey"),                                   # 793
    ([Cond(A, True), Cond(B)], "GetDeterSparseTilingKey"),                    # 799
    ([Cond(A, True), Cond(B, True), Cond(C)], "GetDeterSparseTilingKey"),     # 806
    ([Cond(A, True), Cond(B, True), Cond(C, True), Cond(D)],
     "GetDeterSparseTilingKey"),                                              # 811
    ([Cond(A, True), Cond(B, True)], "GetDeterSparseTilingKey"),              # 813
]


def main() -> int:
    from uo_init.loop_summary import guards_cover

    print("write-guard chain (5 sites):")
    for conds, _ in WRITES:
        print("   " + " AND ".join(
            ("NOT " if c.negated else "") + c.text for c in conds))

    empty = guards_cover((), WRITES, read_function="DoSparse")
    print(f"\nread_conds = ()          -> holds={empty.holds!r:5} "
          f"reason={empty.reason!r}")

    # The same question with the premise spelled out as the tautology it is.
    true_premise = (Cond("1 == 1"),)
    explicit = guards_cover(true_premise, WRITES, read_function="DoSparse")
    print(f"read_conds = (True,)     -> holds={explicit.holds!r:5} "
          f"reason={explicit.reason!r}  checked={explicit.checked}")

    # Control: drop the arm that closes the chain. Coverage must fail, or the
    # query proves nothing and the result above is worthless.
    partial = guards_cover(true_premise, WRITES[:-1], read_function="DoSparse")
    print(f"without the closing arm  -> holds={partial.holds!r:5} "
          f"reason={partial.reason!r}")

    ok = (not empty.holds) and explicit.holds and (not partial.holds)
    print("\n" + ("CONFIRMED: the early return, not the solver, is what "
                  "leaves VAR_INIT standing" if ok else "INCONCLUSIVE"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
