# -*- coding: utf-8 -*-
"""What a gap patch is allowed to say, and what happens when it says more."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from uo_init.gap_patch import (
    MAX_CONDITION_NODES,
    PatchVerdict,
    binding_condition,
    merge_accepted,
    patch_condition,
    validate_patch,
)


@dataclass
class _Domain:
    values: list = field(default_factory=list)
    lo: int | None = None
    hi: int | None = None


@dataclass
class _Spec:
    domain: _Domain | None = None
    value_type: str = "int"


class _Model:
    """Two declared variables and nothing else, so inventing one shows up."""

    def __init__(self):
        self._vars = {
            "VAR_SHAPE_Q_D2": _Spec(_Domain(lo=1, hi=4096)),
            "VAR_ATTR_LAYOUT": _Spec(_Domain(values=["BSH", "TND"]), "enum"),
        }

    def get(self, var_id):
        return self._vars.get(var_id)


BLOCKERS = {"BLK_1": {"id": "BLK_1", "text": "unreadable guard"}}


@pytest.fixture
def evidence(tmp_path):
    src = tmp_path / "tiling.cpp"
    src.write_text("int a = 0;\nif (s1 >= 2048) {\n  use();\n}\n", encoding="utf-8")
    return src, [{"file": "tiling.cpp", "line": 2, "snippet": "if (s1 >= 2048) {"}]


def _verdict(patch, tmp_path):
    return validate_patch(
        patch, blockers=BLOCKERS, var_model=_Model(), ops_root=tmp_path
    )


def _codes(v: PatchVerdict) -> set[str]:
    return {i.code for i in v.issues}


# -- the checks that were already there, now covered ------------------------


def test_a_single_comparison_on_a_declared_variable_is_admitted(tmp_path, evidence):
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "binding": {"var_id": "VAR_SHAPE_Q_D2", "op": "ge", "value": 2048},
            "evidence": rows,
        },
        tmp_path,
    )
    assert v.ok, _codes(v)


def test_a_variable_the_model_never_declared_is_refused(tmp_path, evidence):
    """Inventing a symbol is how a patch says something nothing can check."""
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "binding": {"var_id": "VAR_MADE_UP", "op": "ge", "value": 1},
            "evidence": rows,
        },
        tmp_path,
    )
    assert "invented_var" in _codes(v)


def test_a_value_outside_the_declared_domain_is_refused(tmp_path, evidence):
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "binding": {"var_id": "VAR_ATTR_LAYOUT", "op": "eq", "value": "SBH"},
            "evidence": rows,
        },
        tmp_path,
    )
    assert "value_out_of_domain" in _codes(v)


def test_an_unknown_blocker_is_refused(tmp_path, evidence):
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_NOPE",
            "classification": "input_derived",
            "binding": {"var_id": "VAR_SHAPE_Q_D2", "op": "ge", "value": 1},
            "evidence": rows,
        },
        tmp_path,
    )
    assert "unknown_blocker" in _codes(v)


def test_evidence_that_does_not_match_the_source_is_refused(tmp_path, evidence):
    """Evidence is the only tie between an answer and the code it claims to
    read; a quote that is not there unties it."""
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "binding": {"var_id": "VAR_SHAPE_Q_D2", "op": "ge", "value": 1},
            "evidence": [
                {"file": "tiling.cpp", "line": 2, "snippet": "if (s1 >= 9999) {"}
            ],
        },
        tmp_path,
    )
    assert "evidence_mismatch" in _codes(v)


def test_a_quote_from_elsewhere_in_the_same_function_is_accepted(tmp_path):
    """The batch hands over the whole function, so the line worth quoting is
    routinely not the blocker's own — the loop header, the early return that
    explains why a branch is dead. Held to a three-line window those answers
    were rejected for quoting the code they had just been given."""
    src = tmp_path / "tiling.cpp"
    src.write_text(
        "void f()\n{\n  int n = 0;\n  for (int i = 0; i < k; i++) {\n"
        "    if (mask[i]) {\n      n += 1;\n    }\n  }\n}\n",
        encoding="utf-8",
    )
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "binding": {"var_id": "VAR_SHAPE_Q_D2", "op": "ge", "value": 1},
            "evidence": [
                {"file": "tiling.cpp", "line": 6, "snippet": "for (int i = 0; i < k; i++)"}
            ],
        },
        tmp_path,
    )
    assert v.ok, _codes(v)


def test_reindenting_a_quote_does_not_break_it(tmp_path):
    src = tmp_path / "tiling.cpp"
    src.write_text("void f()\n{\n    if (a  &&   b) {\n    }\n}\n", encoding="utf-8")
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "binding": {"var_id": "VAR_SHAPE_Q_D2", "op": "ge", "value": 1},
            "evidence": [{"file": "tiling.cpp", "line": 3, "snippet": "if (a && b) {"}],
        },
        tmp_path,
    )
    assert v.ok, _codes(v)


def test_a_quote_from_a_different_function_is_still_refused(tmp_path):
    """Widening the window must not turn into "anywhere in the file"."""
    src = tmp_path / "tiling.cpp"
    src.write_text(
        "void f()\n{\n  int n = 0;\n}\n\nvoid g()\n{\n  int marker = 7;\n}\n",
        encoding="utf-8",
    )
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "binding": {"var_id": "VAR_SHAPE_Q_D2", "op": "ge", "value": 1},
            "evidence": [{"file": "tiling.cpp", "line": 3, "snippet": "int marker = 7;"}],
        },
        tmp_path,
    )
    assert "evidence_mismatch" in _codes(v)


def test_a_patch_with_no_evidence_at_all_is_refused(tmp_path):
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "binding": {"var_id": "VAR_SHAPE_Q_D2", "op": "ge", "value": 1},
        },
        tmp_path,
    )
    assert "missing_evidence" in _codes(v)


def test_a_binding_under_a_non_input_classification_is_refused(tmp_path, evidence):
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "scheduling",
            "binding": {"var_id": "VAR_SHAPE_Q_D2", "op": "ge", "value": 1},
            "evidence": rows,
        },
        tmp_path,
    )
    assert "unexpected_binding" in _codes(v)


# -- the tree ---------------------------------------------------------------


def test_two_tests_joined_by_and_are_admitted(tmp_path, evidence):
    """The answers that matter are shaped like "s1 >= 2048 and d <= 128", and a
    single comparison cannot say that."""
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "condition": {
                "op": "and",
                "args": [
                    {"op": "ge", "var": "VAR_SHAPE_Q_D2", "value": 2048},
                    {"op": "eq", "var": "VAR_ATTR_LAYOUT", "value": "TND"},
                ],
            },
            "evidence": rows,
        },
        tmp_path,
    )
    assert v.ok, _codes(v)


def test_a_leaf_of_a_tree_is_held_to_the_same_rules_as_a_binding(tmp_path, evidence):
    """A tree is a way to say more, not a way to say things a single test could
    not: inventing a symbol inside `or` is still inventing a symbol."""
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "condition": {
                "op": "or",
                "args": [
                    {"op": "ge", "var": "VAR_SHAPE_Q_D2", "value": 1},
                    {"op": "not", "arg": {"op": "eq", "var": "VAR_INVENTED", "value": 0}},
                ],
            },
            "evidence": rows,
        },
        tmp_path,
    )
    assert "invented_var" in _codes(v)
    assert any("args[1].arg.var" in i.path for i in v.issues), v.issues


def test_a_value_out_of_domain_inside_a_tree_is_refused(tmp_path, evidence):
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "condition": {
                "op": "and",
                "args": [{"op": "in", "var": "VAR_ATTR_LAYOUT", "values": ["TND", "SBH"]}],
            },
            "evidence": rows,
        },
        tmp_path,
    )
    assert "value_out_of_domain" in _codes(v)


def test_an_operator_outside_the_grammar_is_refused(tmp_path, evidence):
    """`div` in a guard is a program, not a test on a declared variable."""
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "condition": {"op": "div", "args": [{"var": "VAR_SHAPE_Q_D2"}, {"lit": 2}]},
            "evidence": rows,
        },
        tmp_path,
    )
    assert "bad_op" in _codes(v)


def test_a_value_that_is_itself_an_expression_is_refused(tmp_path, evidence):
    """Comparing against a computed value smuggles arithmetic back in through
    the one place the grammar still takes free text."""
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "condition": {
                "op": "eq",
                "var": "VAR_SHAPE_Q_D2",
                "value": {"op": "mul", "args": [{"lit": 2}, {"lit": 4}]},
            },
            "evidence": rows,
        },
        tmp_path,
    )
    assert "bad_condition" in _codes(v)


def test_a_tree_beyond_the_size_limit_is_refused_whole(tmp_path, evidence):
    """A guard is a guard, not a program."""
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "condition": {
                "op": "and",
                "args": [
                    {"op": "ge", "var": "VAR_SHAPE_Q_D2", "value": 1}
                    for _ in range(MAX_CONDITION_NODES + 2)
                ],
            },
            "evidence": rows,
        },
        tmp_path,
    )
    assert "condition_too_large" in _codes(v)


def test_a_tree_nested_past_the_depth_limit_is_refused(tmp_path, evidence):
    _, rows = evidence
    node = {"op": "ge", "var": "VAR_SHAPE_Q_D2", "value": 1}
    for _ in range(8):
        node = {"op": "not", "arg": node}
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "condition": node,
            "evidence": rows,
        },
        tmp_path,
    )
    assert "condition_too_large" in _codes(v)


def test_saying_it_both_ways_at_once_is_refused(tmp_path, evidence):
    """Two answers to one question leave no way to tell which was meant."""
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "input_derived",
            "binding": {"var_id": "VAR_SHAPE_Q_D2", "op": "ge", "value": 1},
            "condition": {"op": "ge", "var": "VAR_SHAPE_Q_D2", "value": 2},
            "evidence": rows,
        },
        tmp_path,
    )
    assert "bad_condition" in _codes(v)


def test_a_condition_under_a_non_input_classification_is_refused(tmp_path, evidence):
    _, rows = evidence
    v = _verdict(
        {
            "blocker_id": "BLK_1",
            "classification": "genuinely_unknown",
            "condition": {"op": "ge", "var": "VAR_SHAPE_Q_D2", "value": 1},
            "evidence": rows,
        },
        tmp_path,
    )
    assert "unexpected_binding" in _codes(v)


# -- what reaches the deriver -----------------------------------------------


def test_a_tree_reaches_the_deriver_in_the_shape_it_was_written():
    row = {
        "classification": "input_derived",
        "condition": {
            "op": "and",
            "args": [{"op": "ge", "var": "VAR_SHAPE_Q_D2", "value": 2048}],
        },
    }
    assert patch_condition(row) == row["condition"]


def test_a_single_comparison_still_reaches_it_the_old_way():
    row = {"binding": {"var_id": "VAR_SHAPE_Q_D2", "op": "ge", "value": 2048}}
    assert patch_condition(row) == {"op": "ge", "var": "VAR_SHAPE_Q_D2", "value": 2048}


def test_a_row_that_names_no_test_substitutes_into_nothing():
    """"It comes from the input" without saying what it tests teaches the
    deriver nothing, and must not read as an answer."""
    assert patch_condition({"classification": "input_derived"}) is None
    assert binding_condition({"var_id": "V", "op": "ge"}) is None


def test_an_in_binding_becomes_a_membership_test():
    got = binding_condition({"var_id": "V", "op": "in", "value": [1, 2]})
    assert got == {"op": "in", "var": "V", "values": [1, 2]}


def test_the_ledger_carries_the_tree_through_to_the_next_pass(tmp_path, evidence):
    """A condition dropped on the way into the ledger would be validated and
    then quietly not applied."""
    _, rows = evidence
    patch = {
        "blocker_id": "BLK_1",
        "classification": "input_derived",
        "condition": {
            "op": "and",
            "args": [{"op": "ge", "var": "VAR_SHAPE_Q_D2", "value": 2048}],
        },
        "evidence": rows,
    }
    v = _verdict(patch, tmp_path)
    assert v.ok, _codes(v)
    bindings, accepted, rejected = merge_accepted([], [v], blockers=BLOCKERS)
    assert not rejected and len(accepted) == 1
    assert patch_condition(bindings[0]) == patch["condition"]
