# -*- coding: utf-8 -*-
"""An unguarded read is a question worth asking, not a reason to give up.

`guards_cover` decides whether reaching a read implies one of the writes has
run. It used to refuse the query outright when the read carried no path
condition, which reads as caution and is the opposite of it: an empty premise
is `True`, the weakest premise available, so proving coverage under it proves
coverage under every read condition there could be.

The shape below is `GetDeterSparseTilingKey`'s: five writes forming an
if / else-if chain that between them cover every run. Refusing to ask left the
VAR_INIT minted for the chain's fall-through standing on three dimensions.
"""

from __future__ import annotations

from uo_init.clang_walk import PathCond
from uo_init.loop_summary import guards_cover

A = "isDeterministic_is_false"
B = "not_sparse_or_all_mask"
C = "left_up_causal"
D = "band_mode"

FN = "GetDeterSparseTilingKey"


def _c(text: str, negated: bool = False) -> PathCond:
    return PathCond(text=text, negated=negated, file="f.cpp", line=1, kind="if")


#: The chain's five arms. The last one repeats the second test as a
#: guard_clause, which is what closes `not A and not B`.
CHAIN = [
    ([_c(A)], FN),
    ([_c(A, True), _c(B)], FN),
    ([_c(A, True), _c(B, True), _c(C)], FN),
    ([_c(A, True), _c(B, True), _c(C, True), _c(D)], FN),
    ([_c(A, True), _c(B, True)], FN),
]


def test_an_unguarded_read_is_covered_by_an_exhaustive_chain():
    """No read condition at all is the strongest thing the writes can cover."""
    assert guards_cover((), CHAIN, read_function="DoSparse").holds


def test_the_tautological_premise_agrees_with_the_empty_one():
    """Spelling `True` out loud must not change the answer."""
    explicit = guards_cover((_c("1 == 1"),), CHAIN, read_function="DoSparse")
    assert explicit.holds
    assert explicit.checked == len(CHAIN)


def test_a_chain_with_a_hole_is_not_covered():
    """Without this the result above would be a tautology, not a proof.

    Dropping the arm that closes `not A and not B` leaves a run that reaches
    the read having written nothing, and the query has to find it.
    """
    partial = guards_cover((), CHAIN[:-1], read_function="DoSparse")
    assert not partial.holds
    assert partial.reason.startswith("not_proven")


def test_an_unguarded_write_covers_everything_on_its_own():
    """A write with no guards always runs, so nothing is ever assumed."""
    assert guards_cover((), [([], FN)], read_function="DoSparse").holds


def test_no_writes_at_all_proves_nothing():
    assert not guards_cover((_c(A),), [], read_function="DoSparse").holds
