# -*- coding: utf-8 -*-
"""The mechanical checks that stand between a model's answer and belief."""

from __future__ import annotations

from dataclasses import dataclass, field

from uo_init.concrete_eval import Premises
from uo_init.patch_gates import (
    check_condition_decides_something,
    check_patch_condition,
    check_reads_what_the_code_reads,
    check_values_stay_declared,
)


@dataclass
class _Domain:
    values: list = field(default_factory=list)
    lo: int | None = None
    hi: int | None = None


def _cmp(var, op, value):
    return {"op": op, "var": var, "value": value}


def _ite(cond, then, other):
    return {"op": "if_then_else", "condition": cond, "then": then, "else": other}


def _codes(findings):
    return {f.code for f in findings}


# -- it reads what the code reads -------------------------------------------


def test_a_condition_about_variables_the_code_touches_passes():
    got = check_reads_what_the_code_reads(
        _cmp("VAR_S1", "ge", 2048), ["VAR_S1", "VAR_D"]
    )
    assert got == []


def test_a_condition_about_something_that_stretch_of_code_never_reads_is_caught():
    """Inventing a symbol with a spelling the model already knows is still
    invention, and `validate_patch` cannot see it — the variable is real."""
    got = check_reads_what_the_code_reads(
        {"op": "and", "args": [_cmp("VAR_S1", "ge", 1), _cmp("VAR_LAYOUT", "eq", 3)]},
        ["VAR_S1", "VAR_D"],
    )
    assert _codes(got) == {"reads_what_the_code_cannot"}
    assert "VAR_LAYOUT" in got[0].message


def test_no_record_of_what_the_code_reads_means_no_opinion():
    """Silence where there is no information; "touches nothing" would reject
    every answer."""
    assert check_reads_what_the_code_reads(_cmp("VAR_S1", "ge", 1), []) == []
    assert check_reads_what_the_code_reads(_cmp("VAR_S1", "ge", 1), None) == []


# -- it decides something ---------------------------------------------------


def test_a_condition_that_can_go_either_way_passes():
    got = check_condition_decides_something(
        _cmp("VAR_S1", "ge", 2048), domains={"VAR_S1": _Domain(lo=1, hi=8192)}
    )
    assert got == []


def test_a_condition_true_at_every_legal_input_is_caught():
    """It stands in for a branch, and a branch that is always taken is not a
    branch. The witness is an input where it holds."""
    got = check_condition_decides_something(
        _cmp("VAR_S1", "ge", 0), domains={"VAR_S1": _Domain(lo=1, hi=8192)}
    )
    assert _codes(got) == {"condition_never_false"}
    assert got[0].witness


def test_a_condition_false_at_every_legal_input_is_caught():
    got = check_condition_decides_something(
        _cmp("VAR_S1", "lt", 0), domains={"VAR_S1": _Domain(lo=1, hi=8192)}
    )
    assert _codes(got) == {"condition_never_true"}
    assert got[0].witness


def test_the_premises_decide_what_counts_as_a_legal_input():
    """`layout == TND` is not a constant in general, but it is once the
    operator has rejected every other layout."""
    p = Premises([{"usable": True, "expr": _cmp("VAR_LAYOUT", "eq", "TND")}])
    plain = check_condition_decides_something(_cmp("VAR_LAYOUT", "eq", "TND"))
    assert plain == []
    guarded = check_condition_decides_something(
        _cmp("VAR_LAYOUT", "eq", "TND"), premises=p
    )
    assert _codes(guarded) == {"condition_never_false"}


def test_a_space_too_large_to_walk_yields_no_opinion():
    """Running out of budget must not read as a failure it never established."""
    wide = {
        "op": "and",
        "args": [_cmp(f"V{i}", "ge", i) for i in range(10)],
    }
    assert check_condition_decides_something(wide, cap=8) == []


# -- it leaves the field inside its declared values -------------------------

#: `IsX` is 1 when the unreadable guard holds and 0 otherwise.
_FIELD = _ite({"op": "eq", "var": "VAR_LOOPELEM_1", "value": True}, {"lit": 1}, {"lit": 0})


def test_a_condition_that_keeps_the_field_inside_the_template_passes():
    got = check_values_stay_declared(
        _FIELD,
        "VAR_LOOPELEM_1",
        _cmp("VAR_S1", "ge", 2048),
        declared=[0, 1],
        domains={"VAR_S1": _Domain(lo=1, hi=8192)},
    )
    assert got == []


def test_a_condition_that_lets_the_field_leave_the_template_is_caught():
    """The template declares 0 and 1. A condition that puts 7 in the field is
    wrong about the source whatever it says about it, and the witness is the
    input that gets there."""
    field_expr = _ite(
        {"op": "eq", "var": "VAR_LOOPELEM_1", "value": True}, {"lit": 7}, {"lit": 0}
    )
    got = check_values_stay_declared(
        field_expr,
        "VAR_LOOPELEM_1",
        _cmp("VAR_S1", "ge", 2048),
        declared=[0, 1],
        domains={"VAR_S1": _Domain(lo=1, hi=8192)},
    )
    assert _codes(got) == {"value_outside_template"}
    assert got[0].witness["VAR_S1"] >= 2048


def test_a_condition_that_leaves_the_field_with_nothing_is_caught():
    """Every legal input is refused once the condition is in, so it contradicts
    the rest of the derivation."""
    p = Premises([{"usable": True, "expr": _cmp("VAR_S1", "le", 16)}])
    got = check_values_stay_declared(
        _FIELD,
        "VAR_LOOPELEM_1",
        _cmp("VAR_S1", "ge", 2048),
        declared=[0, 1],
        domains={"VAR_S1": _Domain(lo=2048, hi=8192)},
        premises=p,
    )
    assert _codes(got) == {"no_values_left"}


def test_a_template_that_declares_nothing_yields_no_opinion():
    got = check_values_stay_declared(
        _FIELD,
        "VAR_LOOPELEM_1",
        _cmp("VAR_S1", "ge", 2048),
        declared=None,
        domains={"VAR_S1": _Domain(lo=1, hi=8192)},
    )
    assert got == []


# -- all three together -----------------------------------------------------


def test_a_sound_answer_survives_every_check():
    got = check_patch_condition(
        _cmp("VAR_S1", "ge", 2048),
        var_id="VAR_LOOPELEM_1",
        value_expr=_FIELD,
        readable=["VAR_S1", "VAR_D"],
        declared=[0, 1],
        domains={"VAR_S1": _Domain(lo=1, hi=8192)},
    )
    assert got == []


def test_a_wrong_answer_comes_back_with_what_shows_it_wrong():
    got = check_patch_condition(
        _cmp("VAR_ELSEWHERE", "ge", 0),
        var_id="VAR_LOOPELEM_1",
        value_expr=_FIELD,
        readable=["VAR_S1", "VAR_D"],
        declared=[0, 1],
        domains={"VAR_ELSEWHERE": _Domain(lo=1, hi=64)},
    )
    assert "reads_what_the_code_cannot" in _codes(got)
    assert "condition_never_false" in _codes(got)
    assert any(f.witness for f in got)
