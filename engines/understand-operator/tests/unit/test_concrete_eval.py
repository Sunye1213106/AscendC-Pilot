# -*- coding: utf-8 -*-
"""Walking a derived value forwards on concrete inputs."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from uo_init.concrete_eval import (
    CANDIDATE,
    CONFIRMED,
    OTHER,
    Auxiliaries,
    Premises,
    Unknown,
    ValueTree,
    axes_for,
    domain_for,
    domains_of,
    drivable_root,
    enumerate_cells,
    grade_witness,
    invented_range,
    possible_values,
    root_of_var,
    samples,
)


def _cmp(var, op, value):
    return {"op": op, "var": var, "value": value}


def _ite(cond, then, other):
    return {"op": "if_then_else", "condition": cond, "then": then, "else": other}


# -- the tree ---------------------------------------------------------------


def test_a_branch_is_taken_by_evaluating_its_condition():
    tree = ValueTree(_ite(_cmp("D", "ge", 128), {"lit": 1}, {"lit": 0}))
    assert tree.value({"D": 256}) == 1
    assert tree.value({"D": 64}) == 0


def test_shared_subtrees_are_followed_through_their_reference():
    """`value_expr` comes out as a DAG: the layout ternary is reached from
    dozens of places and is stored once."""
    tree = ValueTree(
        {
            "$dag": True,
            "defs": {"n1": _cmp("D", "ge", 128)},
            "root": _ite({"$ref": "n1"}, {"lit": 7}, {"lit": 8}),
        }
    )
    assert tree.value({"D": 128}) == 7


def test_a_variable_standing_alone_under_a_division_is_found():
    tree = ValueTree(
        {"op": "div", "args": [{"var": "TOTAL"}, {"var": "CORES"}]}
    )
    assert tree.divisors() == {"CORES"}


def test_a_variable_inside_a_compound_divisor_is_not_claimed():
    """Under `a / (b - c)` no single value of `b` divides by zero, and ruling
    one out would exclude an input on no evidence."""
    tree = ValueTree(
        {
            "op": "div",
            "args": [
                {"var": "TOTAL"},
                {"op": "sub", "args": [{"var": "B"}, {"var": "C"}]},
            ],
        }
    )
    assert tree.divisors() == set()


def test_a_dividing_variable_is_never_drawn_as_zero():
    """Zero there throws the whole point away, and it was throwing away most
    of them — leaving too few to tell any two inputs apart."""
    tree = {
        "op": "if_then_else",
        "condition": _cmp("MODE", "eq", 1),
        "then": {"op": "div", "args": [{"lit": 4096}, {"var": "BLK"}]},
        "else": {"lit": 0},
    }
    out = enumerate_cells(tree)
    assert out["unknown"] == 0, "no cell should divide by zero"


def test_a_variable_nothing_compares_against_spans_magnitudes():
    """It still reaches the key through arithmetic, and {0, 1} cannot
    separate a ceil-division from a degenerate one."""
    got = samples(set())
    assert 0 in got and max(got) > 64


def test_a_reference_that_loops_is_not_followed_forever():
    tree = ValueTree({"$dag": True, "defs": {"a": {"$ref": "a"}}, "root": {"$ref": "a"}})
    with pytest.raises(Unknown):
        tree.value({})


def test_arithmetic_the_solver_stalls_on_is_just_arithmetic_here():
    """Integer division and modulo are what make the symbolic form
    undecidable. Forwards they are two operations."""
    tree = ValueTree(
        {
            "op": "mod",
            "args": [{"op": "div", "args": [{"var": "S"}, {"lit": 3}]}, {"lit": 16}],
        }
    )
    assert tree.value({"S": 1000}) == 333 % 16


def test_a_conjunct_that_guards_a_division_actually_guards_it():
    """`n != 0 && total / n > 1` is what the source wrote. Evaluating the
    second half anyway turns a legal input into a division by zero."""
    tree = ValueTree(
        {
            "op": "and",
            "args": [
                _cmp("N", "ne", 0),
                {
                    "op": "gt",
                    "lhs": {"op": "div", "args": [{"var": "TOTAL"}, {"var": "N"}]},
                    "rhs": {"lit": 1},
                },
            ],
        }
    )
    assert tree.value({"TOTAL": 8, "N": 0}) is False


def test_a_disjunct_already_settled_is_not_read():
    tree = ValueTree({"op": "or", "args": [_cmp("A", "eq", 1), {"var": "B"}]})
    read: set[str] = set()
    assert tree.value({"A": 1}, read=read) is True
    assert read == {"A"}


def test_dividing_by_zero_is_unknown_rather_than_a_crash():
    tree = ValueTree({"op": "div", "args": [{"var": "S"}, {"var": "N"}]})
    with pytest.raises(Unknown):
        tree.value({"S": 8, "N": 0})


def test_an_unbound_variable_is_unknown_not_zero():
    """Reading a missing binding as 0 answers a question nobody asked, and the
    answer would look like a fact."""
    with pytest.raises(Unknown):
        ValueTree({"var": "D"}).value({})


def test_ordering_two_labels_is_refused():
    """`layout < "TND"` is not a question about the operator."""
    tree = ValueTree(_cmp("L", "lt", "TND"))
    with pytest.raises(Unknown):
        tree.value({"L": "BSH"})


def test_a_label_equality_still_answers():
    tree = ValueTree(_cmp("L", "eq", "TND"))
    assert tree.value({"L": "TND"}) is True
    assert tree.value({"L": "BSH"}) is False


def test_the_variables_a_tree_reads_come_back_with_their_thresholds():
    tree = ValueTree(
        _ite(_cmp("D", "ge", 128), _cmp("S", "eq", 2048), {"lit": 0})
    )
    cuts, names = tree.cuts()
    assert names == {"D", "S"}
    assert cuts == {"D": {128}, "S": {2048}}


# -- representative values --------------------------------------------------


@dataclass
class _Domain:
    values: list = field(default_factory=list)
    lo: int | None = None
    hi: int | None = None


def test_a_threshold_gets_a_point_on_each_side_and_on_it():
    """Below, on, and above is every distinction a comparison can draw."""
    assert set(samples({128})) >= {127, 128, 129}


def test_representatives_stay_inside_the_declared_range():
    """A point the operator could never be given makes an unreachable key look
    reachable, which is the direction that lies."""
    got = samples({128}, _Domain(lo=1, hi=200))
    assert min(got) >= 1 and max(got) <= 200
    assert 1 in got and 200 in got


def test_a_closed_enum_is_already_the_list_of_regions():
    assert samples({1, 2}, _Domain(values=["A", "B"])) == ["A", "B"]


def test_an_enum_is_put_in_the_form_the_code_compares_against():
    """The model spells a dtype `DT_BF16`; the tiling code compares against 27.
    Left in the model's spelling every comparison is silently false, which
    collapses the dimension onto one branch."""
    got = samples({27}, _Domain(values=["DT_BF16", "DT_FLOAT"]), {"DT_BF16": 27, "DT_FLOAT": 0})
    assert got == [0, 27]


def test_a_variable_only_compared_to_labels_keeps_a_none_of_the_above():
    assert samples({"TND"}) == ["TND", OTHER]


def test_an_axis_inherits_the_tensors_domain():
    domains = {"VAR_SHAPE_QUERY": _Domain(lo=1, hi=99)}
    assert domain_for("VAR_SHAPE_QUERY_D2", domains) is domains["VAR_SHAPE_QUERY"]
    assert domain_for("VAR_SHAPE_KEY_D0", domains) is None


def test_domains_are_read_off_the_variable_model():
    class _Var:
        def __init__(self, domain):
            self.domain = domain

    class _Model:
        variables = {"A": _Var(_Domain(lo=0)), "B": _Var(None)}
        named_constants = {"K": 4, "FLAG": True, "NAME": "x"}

    domains, constants = domains_of(_Model())
    assert set(domains) == {"A"}
    assert constants == {"K": 4}


# -- enumeration ------------------------------------------------------------


def test_every_value_comes_back_with_an_input_that_produces_it():
    """A witness is what makes a reachable verdict need no trust."""
    out = enumerate_cells(_ite(_cmp("D", "ge", 128), {"lit": 1}, {"lit": 0}))
    assert set(out["values"]) == {0, 1}
    for value, env in out["values"].items():
        assert ValueTree(_ite(_cmp("D", "ge", 128), {"lit": 1}, {"lit": 0})).value(
            env
        ) == value


def test_a_table_too_large_to_walk_says_so_rather_than_walking_it():
    tree = {
        "op": "add",
        "args": [_cmp(f"V{i}", "ge", i) for i in range(12)],
    }
    out = enumerate_cells(tree, cap=100)
    assert out["skipped"] and out["cells"] > 100


def test_a_premise_removes_the_inputs_the_operator_refuses():
    """The operator rejects `DT == 6`, so no run reaches the key with it, and
    the value that branch produces was never reachable."""
    tree = _ite(_cmp("DT", "eq", 6), {"lit": 6}, {"lit": 1})
    plain = enumerate_cells(tree)
    assert set(plain["values"]) == {1, 6}

    guarded = enumerate_cells(
        tree, premises=Premises([{"usable": True, "expr": _cmp("DT", "ne", 6)}])
    )
    assert set(guarded["values"]) == {1}
    # Settled while the values are chosen, so the input it refuses is never
    # built rather than built and then turned away.
    assert guarded["refused"] == 0


def test_a_premise_relating_two_variables_is_still_applied_per_cell():
    """Only one naming a single variable can be settled up front."""
    tree = _ite(
        _cmp("A", "eq", 1), _ite(_cmp("B", "eq", 1), {"lit": 9}, {"lit": 2}), {"lit": 1}
    )
    guarded = enumerate_cells(
        tree,
        premises=Premises(
            [{"usable": True, "expr": {"op": "ne", "lhs": {"var": "A"}, "rhs": {"var": "B"}}}]
        ),
    )
    assert guarded["refused"] > 0
    assert 9 not in set(guarded["values"])


def test_a_premise_splits_the_input_space_of_the_dimensions_it_touches():
    """The dimension never compares `DT` against 6 itself; without taking the
    premise's own thresholds no sample would land on the value it rejects."""
    p = Premises([{"usable": True, "expr": _cmp("DT", "ne", 6)}])
    assert p.cuts["DT"] == {6}
    assert p.vars == {"DT"}


def test_a_premise_nobody_could_read_is_skipped_not_believed():
    """Refusing an input on a premise that cannot be evaluated excludes it on
    no evidence, and excluding is the direction that loses reachable keys."""
    p = Premises([{"usable": True, "expr": {"op": "div", "args": [{"lit": 1}, {"lit": 0}]}}])
    assert p.rejects({}) is False


def test_a_premise_marked_unusable_never_enters():
    p = Premises([{"usable": False, "expr": _cmp("DT", "ne", 6), "why": "no inputs"}])
    assert p.trees == [] and len(p.dropped) == 1


# -- what a witness is worth ------------------------------------------------


def test_a_shape_is_something_a_case_can_set():
    assert root_of_var("VAR_SHAPE_QUERY_D2") == "INPUT_SHAPE"
    assert drivable_root("VAR_SHAPE_QUERY_D2") is True


def test_tiling_state_is_not_an_input_however_the_expression_reads_it():
    """`SplitAxis == 5` witnessed by `VAR_TDF_SPLITAXIS = 5` restates the
    question. Counting it as coverage is how 5.2% came to mean nothing."""
    assert root_of_var("VAR_TDF_SPLITAXIS") == "TILING_DATA"
    assert drivable_root("VAR_TDF_SPLITAXIS") is False


def test_what_the_analysis_minted_when_it_gave_up_is_never_an_input():
    for vid in (
        "VAR_UNDECIDED_ABC",
        "VAR_SCHED_COREIDX",
        "VAR_INIT_1234",
        "VAR_LOOPELEM_INVALIDS1_1",
        "VAR_AUX_BLOCKOUTER",
    ):
        assert drivable_root(vid) is False, vid


def test_a_recorded_root_beats_the_prefix():
    """`VAR_ELEM_*` is an element of a container, and only the derivation knows
    whether that container came from an input."""
    assert drivable_root("VAR_ELEM_ELEM_SEQLEN") is False
    assert drivable_root("VAR_ELEM_ELEM_SEQLEN", {"VAR_ELEM_ELEM_SEQLEN": "INPUT_VALUE"})


def test_a_recorded_root_cannot_rescue_a_variable_the_analysis_invented():
    """The resolver puts a root behind `coreIdx` too. It is still not something
    a case sets."""
    assert drivable_root("VAR_SCHED_COREIDX", {"VAR_SCHED_COREIDX": "INPUT_SHAPE"}) is False


def test_a_platform_value_counts_because_choosing_the_profile_fixes_it():
    assert drivable_root("VAR_PLATFORM_CORE_COUNT") is True


def test_a_witness_naming_only_inputs_is_confirmed():
    assert grade_witness({"VAR_SHAPE_QUERY_D0": 8, "VAR_ATTR_SPARSEMODE": 3}) == (
        CONFIRMED,
        [],
    )


def test_a_witness_naming_host_state_is_a_candidate_and_says_which():
    grade, blame = grade_witness({"VAR_SHAPE_QUERY_D0": 8, "VAR_TDF_LAYOUTTYPE": 4})
    assert (grade, blame) == (CANDIDATE, ["VAR_TDF_LAYOUTTYPE"])


def test_a_variable_nobody_bounded_or_compared_is_marked_made_up():
    """`samples` still answers -- over-approximating is the safe direction --
    but a verdict resting on `{0, 1, 2, 8, 64, 512}` rests on nothing read."""
    assert invented_range(set()) is True
    assert invented_range({128}) is False
    assert invented_range(set(), _Domain(values=[0, 1])) is False


def test_a_bound_alone_does_not_make_the_magnitudes_evidence():
    assert invented_range(set(), _Domain(lo=1, hi=1024)) is True


def test_an_axis_carries_both_gradings():
    tree = ValueTree(
        _ite(_cmp("VAR_TDF_SPLITAXIS", "eq", 5), {"var": "VAR_SHAPE_Q_D0"}, {"lit": 0})
    )
    got = {a.var: a for a in axes_for(tree)}
    assert got["VAR_TDF_SPLITAXIS"].drivable is False
    assert got["VAR_SHAPE_Q_D0"].drivable is True
    # Compared against 5, so its points come from the source; the other is
    # read for its value alone and nothing says what that value can be.
    assert got["VAR_TDF_SPLITAXIS"].invented is False
    assert got["VAR_SHAPE_Q_D0"].invented is True


def test_the_walk_reports_what_it_could_not_model():
    out = enumerate_cells(_ite(_cmp("VAR_TDF_LAYOUTTYPE", "eq", 4), {"lit": 1}, {"lit": 0}))
    assert out["undrivable_vars"] == ["VAR_TDF_LAYOUTTYPE"]


def test_a_value_is_graded_by_the_path_that_produced_it():
    """The draw sets every variable; only the ones the taken branch read had
    anything to do with the value."""
    tree = _ite(_cmp("VAR_ATTR_MODE", "eq", 1), {"lit": 7}, {"var": "VAR_TDF_X"})
    out = enumerate_cells(tree)
    assert out["grades"][7] == CONFIRMED
    assert set(out["grades"].values()) == {CONFIRMED, CANDIDATE}


def test_the_input_that_needs_nothing_invented_is_the_one_kept():
    """Both draws reach 1; only one of them is a test case."""
    tree = {
        "op": "if_then_else",
        "condition": {
            "op": "or",
            "args": [
                _cmp("VAR_ATTR_MODE", "eq", 1),
                _cmp("VAR_TDF_LAYOUTTYPE", "eq", 4),
            ],
        },
        "then": {"lit": 1},
        "else": {"lit": 0},
    }
    out = enumerate_cells(tree)
    assert out["grades"][1] == CONFIRMED


def test_which_variables_a_run_consulted_is_not_which_ones_it_could_have():
    tree = ValueTree(_ite(_cmp("A", "ge", 128), {"var": "B"}, {"var": "C"}))
    read: set[str] = set()
    tree.value({"A": 256, "B": 1, "C": 2}, read=read)
    assert read == {"A", "B"}


# -- values the operator computes for itself --------------------------------


def test_an_auxiliary_is_computed_from_the_input_not_drawn_alongside_it():
    aux = Auxiliaries({"VAR_AUX_BLOCKOUTER": {"op": "mul", "args": [{"var": "B"}, {"lit": 4}]}})
    assert aux.resolve({"B": 8}) == {"VAR_AUX_BLOCKOUTER": 32}


def test_one_auxiliary_reading_another_is_ordered_behind_it():
    aux = Auxiliaries(
        {
            "VAR_AUX_OUTER": {"op": "add", "args": [{"var": "VAR_AUX_INNER"}, {"lit": 1}]},
            "VAR_AUX_INNER": {"var": "B"},
        }
    )
    assert aux.order == ["VAR_AUX_INNER", "VAR_AUX_OUTER"]
    assert aux.resolve({"B": 7}) == {"VAR_AUX_INNER": 7, "VAR_AUX_OUTER": 8}


def test_a_name_that_reads_itself_back_still_settles_when_it_converges():
    """`blockOuter` is written from the shapes, then read by a guard deciding
    which of its writes ran. Statically that is a cycle; at one input it is a
    number, and iterating finds it."""
    tree = _ite(_cmp("VAR_AUX_X", "eq", 5), {"lit": 5}, {"var": "N"})
    assert Auxiliaries({"VAR_AUX_X": tree}).resolve({"N": 5}) == {"VAR_AUX_X": 5}


def test_a_value_that_depends_on_where_the_iteration_started_is_not_reported():
    """Both 0 and 1 are fixpoints of `x -> x`, so the source says nothing here,
    and reporting either would be reporting the seed."""
    assert Auxiliaries({"VAR_AUX_X": {"var": "VAR_AUX_X"}}).resolve({}) == {}


def test_an_auxiliary_that_oscillates_is_left_out_rather_than_cut_off():
    tree = _ite(_cmp("VAR_AUX_X", "eq", 0), {"lit": 1}, {"lit": 0})
    assert Auxiliaries({"VAR_AUX_X": tree}).resolve({}) == {}


def test_a_reader_of_an_unsettled_auxiliary_gets_no_value_either():
    aux = Auxiliaries(
        {
            "VAR_AUX_BAD": _ite(_cmp("VAR_AUX_BAD", "eq", 0), {"lit": 1}, {"lit": 0}),
            "VAR_AUX_READER": {"op": "add", "args": [{"var": "VAR_AUX_BAD"}, {"lit": 1}]},
        }
    )
    assert aux.resolve({}) == {}


def test_an_auxiliary_is_not_an_axis_and_not_a_charge_against_the_witness():
    """Drawing it would assert host state; computing it asserts nothing the
    input did not already."""
    tree = _ite(_cmp("VAR_AUX_X", "ge", 8), {"lit": 1}, {"lit": 0})
    aux = Auxiliaries({"VAR_AUX_X": {"op": "mul", "args": [{"var": "VAR_ATTR_N"}, {"lit": 4}]}})
    out = enumerate_cells(tree, auxiliaries=aux)
    assert "VAR_AUX_X" not in out["undrivable_vars"]
    assert set(out["values"]) == {0, 1}
    assert set(out["grades"].values()) == {CONFIRMED}
    for env in out["values"].values():
        assert "VAR_AUX_X" not in env


def test_an_auxiliary_document_is_read_under_either_expression_key():
    rows = {"VAR_AUX_A": {"value_expr": {"lit": 3}}, "VAR_AUX_B": {"expr": {"lit": 4}}}
    assert Auxiliaries.from_rows(rows).resolve({}) == {"VAR_AUX_A": 3, "VAR_AUX_B": 4}


def test_an_auxiliary_that_never_came_back_is_simply_absent():
    assert Auxiliaries.from_rows({"VAR_AUX_A": {"value_expr": None}}).names == set()


# -- what a free variable leaves open ---------------------------------------


def test_a_free_variable_leaves_a_set_of_possible_values():
    """The expression has no single value where a variable was never pinned
    down, but it has a set of them, and that set is a fact about the source."""
    tree = _ite({"var": "F"}, {"lit": 10}, {"lit": 20})
    got = possible_values(tree, {}, free=["F"])
    assert got == {10, 20}


def test_the_set_narrows_once_the_input_is_fixed():
    tree = _ite(_cmp("D", "ge", 128), _ite({"var": "F"}, {"lit": 10}, {"lit": 20}), {"lit": 0})
    assert possible_values(tree, {"D": 64}, free=["F"]) == {0}
    assert possible_values(tree, {"D": 256}, free=["F"]) == {10, 20}


def test_too_many_combinations_is_no_opinion_rather_than_an_empty_set():
    """None has to mean "could not say". An empty set would read as "nothing
    is possible", which would reject every answer."""
    tree = {"op": "add", "args": [{"var": f"F{i}"} for i in range(8)]}
    assert possible_values(tree, {}, free=[f"F{i}" for i in range(8)], cap=4) is None


def test_a_point_where_nothing_evaluates_is_also_no_opinion():
    """Every assignment divides by zero, so the source says nothing here —
    and saying nothing must not read as "no value is possible"."""
    tree = {"op": "div", "args": [{"lit": 1}, {"var": "F"}]}
    domains = {"F": _Domain(values=[0])}
    assert possible_values(tree, {}, free=["F"], domains=domains) is None
