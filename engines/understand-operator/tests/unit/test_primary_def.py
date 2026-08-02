# -*- coding: utf-8 -*-
"""Which of a local's definitions stands for the local.

A local written more than once has no single defining expression, and the one
picked here is inlined wherever the local is read. Picking the wrong one does
not lose precision, it states something false about the operator.
"""
from uo_init.host_ir import _pick_primary_def


def test_the_only_definition_is_the_definition():
    assert _pick_primary_def("p", ["CeilDiv(s1, 16)"]) == "CeilDiv(s1, 16)"


def test_a_literal_stands_when_nothing_updates_it():
    assert _pick_primary_def("blockSize", ["128"]) == "128"


def test_an_update_from_itself_does_not_hide_the_real_definition():
    """`p = CeilDiv(...); p = p + q` still chases the CeilDiv."""
    assert _pick_primary_def("p", ["CeilDiv(s1, 16)", "p + q"]) == "CeilDiv(s1, 16)"


def test_a_counter_is_not_the_value_it_starts_at():
    """`coreIdx = 0; ... coreIdx += 1` folded to 0 pins `blockOuter` to 1 and
    every key needing more than one core stops existing. Narrowing the
    feasible set invents unreachable keys, so no definition is better."""
    assert _pick_primary_def("coreIdx", ["0", "coreIdx + (1)"]) is None


def test_a_prefix_sum_is_not_its_empty_sum():
    assert _pick_primary_def("total", ["0", "total + (s1 * s2)"]) is None


def test_a_running_maximum_is_not_its_floor():
    assert _pick_primary_def("s1Max", ["0", "a>s1Max ? a : s1Max"]) is None


def test_a_flag_raised_in_a_loop_is_neither_of_its_two_values():
    """Declared `false`, set `true` where a branch fires. Taking the
    declaration says the branch never fires; taking the other says it always
    does. Nothing here decides between them."""
    assert _pick_primary_def("hit", ["false", "true"]) is None


def test_the_same_literal_written_twice_is_still_that_literal():
    assert _pick_primary_def("n", ["16", "16"]) == "16"


def test_nothing_to_pick_from():
    assert _pick_primary_def("x", []) is None
    assert _pick_primary_def("x", ["", "  "]) is None
