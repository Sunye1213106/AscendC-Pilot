# -*- coding: utf-8 -*-
"""Resolving a guard must change the expression, not just the paperwork.

An over-approximation lives in two places: a free variable inside `value_expr`,
and an `UndecidedGuard` recording what it stands for. Striking the record while
leaving the variable produces the worst possible state — the solver still
treats the condition as "either way", but the counters report it closed and
nothing remains to say what needs closing.
"""
from __future__ import annotations

from uo_init.derive_key_fields import EX_EXACT, EX_OVERAPPROX, substitute_vars
from uo_init.gap_patch import apply_bindings_to_derivation, binding_condition
from uo_init.host_derivation import (
    FieldDerivation,
    HostDerivation,
    UndecidedGuard,
    _to_field,
)

SOFTENED = {"op": "eq", "var": "VAR_UNDECIDED_ABC", "value": True}
REAL_CONDITION = {"op": "eq", "var": "VAR_ATTR_LAYOUT", "value": "TND"}


def _field(**over: object) -> FieldDerivation:
    base = dict(
        name="IsTnd",
        index=3,
        status="partial",
        exactness=EX_OVERAPPROX,
        free_vars=["VAR_UNDECIDED_ABC"],
        value_expr={"op": "if_then_else", "condition": SOFTENED, "then": 1, "else": 0},
        variables=["VAR_UNDECIDED_ABC"],
        undecided_guards=[
            UndecidedGuard(
                id="UG_ABC",
                var_id="VAR_UNDECIDED_ABC",
                reason="UNMAPPED_SYMBOL",
                text="layoutType == kTND",
                presort="unmapped",
                escalate=True,
            )
        ],
    )
    base.update(over)
    return FieldDerivation(**base)  # type: ignore[arg-type]


def _doc(field: FieldDerivation) -> HostDerivation:
    return HostDerivation(op_name="fag", fields=[field])


def _binding(**over: object) -> dict:
    base = {
        "guard_ids": ["UG_ABC"],
        "classification": "input_derived",
        "binding": {"var_id": "VAR_ATTR_LAYOUT", "op": "eq", "value": "TND"},
    }
    base.update(over)
    return base


# -- substitution ----------------------------------------------------------
def test_substitute_replaces_the_softened_probe():
    out = substitute_vars(
        {"op": "if_then_else", "condition": SOFTENED, "then": 1, "else": 0},
        {"VAR_UNDECIDED_ABC": REAL_CONDITION},
    )
    assert out["condition"] == REAL_CONDITION


def test_substitute_leaves_other_variables_alone():
    other = {"op": "eq", "var": "VAR_UNDECIDED_XYZ", "value": True}
    out = substitute_vars({"op": "not", "arg": other}, {"VAR_UNDECIDED_ABC": REAL_CONDITION})
    assert out == {"op": "not", "arg": other}


def test_substitute_reaches_inside_negation_and_conjunction():
    expr = {
        "op": "and",
        "args": [{"op": "not", "arg": SOFTENED}, {"op": "eq", "var": "VAR_SHAPE_B", "value": 1}],
    }
    out = substitute_vars(expr, {"VAR_UNDECIDED_ABC": REAL_CONDITION})
    assert out["args"][0] == {"op": "not", "arg": REAL_CONDITION}


def test_substitute_keeps_shared_subtrees_shared():
    """The expression is a DAG; rebuilding it as a tree explodes its size."""
    shared = {"op": "eq", "var": "VAR_SHAPE_B", "value": 1}
    expr = {"op": "and", "args": [shared, shared, {"op": "not", "arg": SOFTENED}]}
    out = substitute_vars(expr, {"VAR_UNDECIDED_ABC": REAL_CONDITION})
    assert out["args"][0] is out["args"][1]


def test_a_variable_only_matches_as_a_truth_probe():
    """`VAR == True` is how a softened guard appears; a comparison against some
    other value is a different statement and must not be overwritten."""
    expr = {"op": "eq", "var": "VAR_UNDECIDED_ABC", "value": False}
    assert substitute_vars(expr, {"VAR_UNDECIDED_ABC": REAL_CONDITION}) == expr


# -- binding conditions ----------------------------------------------------
def test_binding_condition_reads_a_complete_binding():
    assert binding_condition({"var_id": "V", "op": "eq", "value": 3}) == {"op": "eq", "var": "V", "value": 3}


def test_binding_condition_expands_membership_to_a_value_list():
    assert binding_condition({"var_id": "V", "op": "in", "value": [1, 2]}) == {
        "op": "in",
        "var": "V",
        "values": [1, 2],
    }


def test_binding_condition_rejects_an_incomplete_binding():
    assert binding_condition({"var_id": "V", "op": "eq"}) is None
    assert binding_condition({"op": "eq", "value": 3}) is None
    assert binding_condition({"var_id": "V", "op": "matches", "value": 3}) is None


# -- applying verdicts -----------------------------------------------------
def test_input_derived_rewrites_the_expression_and_regrades_the_field():
    field = _field()
    counters = apply_bindings_to_derivation(_doc(field), [_binding()])

    assert counters["resolved"] == 1
    assert field.value_expr["condition"] == REAL_CONDITION
    assert field.variables == ["VAR_ATTR_LAYOUT"]
    assert field.free_vars == []
    assert field.exactness == EX_EXACT
    assert field.status == "derived"
    assert field.undecided_guards == []


def test_input_derived_without_a_usable_binding_keeps_the_guard():
    """"It comes from the input" with no statement of what it tests resolves
    nothing, so the field must stay over-approximated."""
    field = _field()
    counters = apply_bindings_to_derivation(_doc(field), [_binding(binding={"var_id": "VAR_ATTR_LAYOUT"})])

    assert counters["resolved"] == 0
    assert counters["unusable"] == 1
    assert field.value_expr["condition"] == SOFTENED
    assert field.exactness == EX_OVERAPPROX
    assert [g.var_id for g in field.undecided_guards] == ["VAR_UNDECIDED_ABC"]


def test_a_scheduling_verdict_stops_escalating_but_stays_on_the_books():
    field = _field()
    apply_bindings_to_derivation(_doc(field), [_binding(classification="scheduling", binding={})])

    assert field.value_expr["condition"] == SOFTENED, "expression must be untouched"
    assert len(field.undecided_guards) == 1
    assert field.undecided_guards[0].escalate is False
    assert field.free_vars == ["VAR_UNDECIDED_ABC"]


def test_genuinely_unknown_changes_nothing():
    field = _field()
    apply_bindings_to_derivation(_doc(field), [_binding(classification="genuinely_unknown", binding={})])
    assert field.undecided_guards[0].escalate is True
    assert field.exactness == EX_OVERAPPROX


# -- the invariant ---------------------------------------------------------
def test_every_over_approximation_keeps_a_guard_record():
    field = _field()
    assert field.unrecorded_free_vars() == []


def test_an_unexplained_free_variable_is_reported():
    field = _field(free_vars=["VAR_UNDECIDED_ABC", "VAR_SCHED_COREIDX"])
    assert field.unrecorded_free_vars() == ["VAR_SCHED_COREIDX"]


def test_resolving_a_guard_cannot_orphan_its_variable():
    """The regression this file exists for: dropping the record while the
    variable stays in the expression."""
    field = _field()
    apply_bindings_to_derivation(_doc(field), [_binding()])
    assert field.unrecorded_free_vars() == []


# -- assumed zero defaults -------------------------------------------------
ASSUMED_ZERO = {
    "function": "GetShapeAttrsInfo",
    "file": "tiling.cpp",
    "line": 103,
    "guard": 'strcmp(inputLayout, "SBH") == 0',
}


def test_assumed_defaults_survive_into_the_field():
    """Closing an if/else-if chain with `Const(0)` asserts a default nobody
    read. It is not a free variable, so only this record makes it auditable."""
    field = _to_field({"name": "SplitAxis", "index": 1, "implicit_defaults": [ASSUMED_ZERO]}, None)
    assert field.implicit_defaults == [ASSUMED_ZERO]
    assert field.to_dict()["implicit_defaults"] == [ASSUMED_ZERO]


def test_assumed_defaults_are_counted_across_fields():
    doc = HostDerivation(
        fields=[
            FieldDerivation(name="A", index=0, status="derived", implicit_defaults=[ASSUMED_ZERO] * 2),
            FieldDerivation(name="B", index=1, status="derived", implicit_defaults=[ASSUMED_ZERO]),
        ]
    )
    assert doc.totals()["implicit_defaults"] == 3


def test_an_older_artifact_without_the_field_still_loads():
    assert _to_field({"name": "A", "index": 0}, None).implicit_defaults == []
