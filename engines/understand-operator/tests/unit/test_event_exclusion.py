# -*- coding: utf-8 -*-
"""Can two guarded events happen on the same iteration?

Asked as one satisfiability query rather than a stack of syntactic cases. An
`if/else` and `x == A` versus `x == B` are both just conjunctions that turn out
to be unsatisfiable, and keeping separate rules for them means each has to be
extended on its own every time a new shape shows up.

Only `unsat` counts. Everything else — satisfiable, unknown, timeout, a guard
we could not compile — means we did not establish exclusion, because claiming
it wrongly is what would let two real appends be counted as one.
"""
from __future__ import annotations

from uo_init.clang_walk import PathCond
from uo_init.loop_summary import guards_exclusive


def _c(text: str, negated: bool = False, line: int = 1, kind: str = "if") -> PathCond:
    return PathCond(text, negated, "f.cpp", line, kind=kind)


def test_the_two_sides_of_one_if_cannot_both_run():
    """The shape the syncRounds bound rests on."""
    g = _c("startSyncRound > endSyncRound", line=439)
    assert guards_exclusive([g], [_c(g.text, True, 439)], function_a="F", function_b="F")


def test_the_same_guard_twice_is_not_exclusive():
    g = _c("startSyncRound > endSyncRound", line=439)
    v = guards_exclusive([g], [g], function_a="F", function_b="F")
    assert not v
    assert v.reason == "not_proven:sat"


def test_one_variable_cannot_equal_two_different_values():
    """No enum table needed: the contradiction is arithmetic."""
    assert guards_exclusive(
        [_c("fBaseParams.deterSparseType == 2", line=84)],
        [_c("fBaseParams.deterSparseType == 4", line=90)],
        function_a="Dense",
        function_b="Band",
        members={"fBaseParams"},
    )


def test_the_same_value_twice_is_not_exclusive():
    assert not guards_exclusive(
        [_c("fBaseParams.deterSparseType == 2", line=84)],
        [_c("fBaseParams.deterSparseType == 2", line=90)],
        function_a="Dense",
        function_b="Band",
        members={"fBaseParams"},
    )


def test_a_member_read_in_two_functions_is_one_variable():
    """Without the member hint the two reads cannot be assumed to be one object."""
    args = (
        [_c("fBaseParams.deterSparseType == 2")],
        [_c("fBaseParams.deterSparseType == 4")],
    )
    assert guards_exclusive(*args, function_a="A", function_b="B", members={"fBaseParams"})
    assert not guards_exclusive(*args, function_a="A", function_b="B")


def test_two_functions_with_a_same_named_local_are_two_variables():
    """`i` in one function contradicting `i` in another proves nothing."""
    g = _c("i > 0")
    assert not guards_exclusive([g], [_c("i > 0", True)], function_a="A", function_b="B")


def test_a_local_contradicting_itself_in_one_function_is_exclusive():
    g = _c("i > 0")
    assert guards_exclusive([g], [_c("i > 0", True)], function_a="A", function_b="A")


def test_a_guard_we_cannot_parse_still_contradicts_its_own_negation():
    """Opaque atoms are kept, not dropped: dropping weakens the conjunction."""
    g = _c("SOME_MACRO(x, y) && ??")
    assert guards_exclusive([g], [_c(g.text, True)], function_a="F", function_b="F")


def test_unrelated_guards_alongside_a_contradiction_do_not_hide_it():
    a = [_c("coreId != 0", line=436), _c("startSyncRound > endSyncRound", line=439)]
    b = [_c("coreId != 0", line=436), _c("startSyncRound > endSyncRound", True, 439)]
    v = guards_exclusive(a, b, function_a="F", function_b="F")
    assert v
    assert v.checked == 4


def test_unrelated_guards_alone_are_not_exclusive():
    assert not guards_exclusive(
        [_c("coreId != 0", line=436)],
        [_c("batchId > 3", line=440)],
        function_a="F",
        function_b="F",
    )


def test_an_empty_guard_set_proves_nothing():
    v = guards_exclusive([], [], function_a="F", function_b="F")
    assert not v
    assert v.reason == "no_readable_guards"


def test_a_macro_that_did_not_expand_is_not_an_atom():
    """Empty text is not a condition; two of them are not the same condition."""
    v = guards_exclusive([_c("")], [_c("")], function_a="F", function_b="F")
    assert not v
    assert v.reason == "no_readable_guards"


def test_a_conjunction_inside_one_guard_is_understood():
    assert guards_exclusive(
        [_c("a > 0 && b == 1")],
        [_c("b == 2")],
        function_a="F",
        function_b="F",
    )


def test_a_disjunction_is_not_over_read():
    """`a == 1 || a == 2` and `a == 2` can both hold."""
    assert not guards_exclusive(
        [_c("a == 1 || a == 2")], [_c("a == 2")], function_a="F", function_b="F"
    )


def test_comparisons_across_the_range_are_exclusive():
    assert guards_exclusive(
        [_c("n < 4")], [_c("n > 9")], function_a="F", function_b="F"
    )


def test_overlapping_ranges_are_not_exclusive():
    assert not guards_exclusive(
        [_c("n < 9")], [_c("n > 4")], function_a="F", function_b="F"
    )
