# -*- coding: utf-8 -*-
"""What the derivation promises a test generator, and what it must not.

`exactness` grades the *expression*; these tests cover the two questions it
cannot answer — whether anything a case can set reaches the field, and whether
the values the field can take are the ones the template declared.
"""
from __future__ import annotations

from uo_init.derive_key_fields import (
    EX_CONSTANT,
    EX_EXACT,
    EX_OVERAPPROX,
    STATUS_DERIVED,
    STATUS_PARTIAL,
    substitute_vars,
)
from uo_init.gap_patch import apply_bindings_to_derivation
from uo_init.gaps import (
    cluster,
    collect_derivation_gap_items,
    collect_free_var_gap_items,
)
from uo_init.host_derivation import (
    PRESORT_LOOP_ELEMENT,
    PRESORT_UNMAPPED,
    FieldDerivation,
    HostDerivation,
    UndecidedGuard,
    _guards_of,
    _to_field,
)
from uo_init.kb_model import (
    IC_CONTROLLABLE,
    IC_HOST_STATE,
    IC_NONE,
    IC_PLATFORM_LOCKED,
    classify_input_closure,
)


def _field(exactness: str, roots: list[str], **kw) -> FieldDerivation:
    status = STATUS_DERIVED if exactness in (EX_EXACT, EX_CONSTANT) else STATUS_PARTIAL
    return FieldDerivation(
        name=kw.pop("name", "Dim"),
        index=0,
        status=status,
        exactness=exactness,
        root_vars=roots,
        **kw,
    )


# -- can a test case actually drive this dimension? -------------------------
def test_a_field_closing_onto_host_state_is_not_input_derivable():
    """`IsTnd` is the case this exists for: its SMT form is the single
    comparison `layoutType == 4` with no free variables, so it grades `exact`,
    but `layoutType` is tiling state the resolver stopped on rather than the
    layout attribute behind it. Nothing a generator sets reaches it.

    The old rule was `status == "derived" and bool(root_vars)`, which passed any
    non-empty root set and so reported four dimensions as controllable.
    """
    fld = _field(EX_EXACT, ["TILING_DATA"], name="IsTnd")
    assert fld.input_closure == IC_HOST_STATE
    assert fld.input_derivable is False


def test_a_field_on_shapes_and_attributes_is_input_derivable():
    fld = _field(EX_EXACT, ["INPUT_SHAPE", "ATTRIBUTE"])
    assert fld.input_closure == IC_CONTROLLABLE
    assert fld.input_derivable is True


def test_platform_facts_do_not_make_a_field_undrivable():
    """Platform quantities are not knobs but are fixed by the CANN profile, so a
    case can still be built against them. Treating them like host state would
    throw away dimensions that are perfectly reachable on a given target."""
    fld = _field(EX_EXACT, ["INPUT_SHAPE", "PLATFORM_CORE_COUNT", "COMPILE_INFO"])
    assert fld.input_closure == IC_PLATFORM_LOCKED
    assert fld.input_derivable is True


def test_a_constant_field_needs_nothing_set_and_counts_as_derivable():
    """`IsRegbase` is constant on this arch, so its value is reachable without
    setting anything. The old rule failed it for having no roots at all."""
    fld = _field(EX_CONSTANT, [], name="IsRegbase")
    assert fld.input_closure == IC_NONE
    assert fld.input_derivable is True


def test_an_over_approximated_field_is_never_input_derivable():
    """Drivable roots are not enough: a free variable means the condition was
    widened, so the value the generator computes may not be the value the host
    encodes."""
    fld = _field(EX_OVERAPPROX, ["INPUT_SHAPE"], free_vars=["VAR_LOOPELEM_X_1"])
    assert fld.input_closure == IC_CONTROLLABLE
    assert fld.input_derivable is False


def test_a_document_round_trip_keeps_what_grades_a_dimension():
    """`to_dict` and `_to_field` are two halves of one format, and both ways of
    disagreeing on a name fail quietly.

    Losing the roots turns the `IsTnd` case above into the `IsRegbase` case
    below it: an empty root set grades `IC_NONE`, which reads as "constant,
    nothing needs setting" and counts as drivable. Losing the guards leaves
    nothing for `_reregister_soft_vars` to re-declare, and the solver then meets
    those variables as unknown symbols.
    """
    fld = _field(
        EX_EXACT,
        ["TILING_DATA"],
        name="IsTnd",
        undecided_guards=[
            UndecidedGuard(
                id="G1",
                var_id="VAR_UNDECIDED_X",
                reason="unmapped",
                text="layoutType",
                presort=PRESORT_UNMAPPED,
                escalate=True,
            )
        ],
    )
    back = _to_field(fld.to_dict(), None)
    assert back.root_vars == ["TILING_DATA"]
    assert back.input_closure == IC_HOST_STATE
    assert back.input_derivable is False
    assert [g.var_id for g in back.undecided_guards] == ["VAR_UNDECIDED_X"]


def _reregistered(row: dict) -> dict[str, str]:
    """var_id -> declared type, after the parent re-declares a worker's row."""
    from uo_init.host_derivation import _reregister_soft_vars
    from uo_init.variable_model import VariableModel

    doc = HostDerivation(op_name="Op", fields=[_field(EX_OVERAPPROX, [], undecided_guards=_guards_of(row, None))])
    model = VariableModel()
    _reregister_soft_vars(model, doc)
    return {v: model.get(v).value_type for v in (row.get("undecided") or {})}


def test_a_worker_declaring_a_type_is_believed_over_the_name():
    """`VAR_SCHED_` covers two unrelated things: a softened guard, which is a
    bool, and a traversal position like `coreIdx`, which is an int compared
    against the core count. The bucket can only see the prefix, so the type has
    to travel with the record. Guessing bool for `coreIdx` makes `coreIdx == 36`
    fail to compile, and that took every dimension down with it.
    """
    row = {
        "undecided": {
            "VAR_SCHED_COREIDX": "LOOP_INDUCTION: coreIdx",
            "VAR_SCHED_abcdef012345": "SCHED_SOFT: some guard",
        },
        "var_types": {"VAR_SCHED_COREIDX": "int"},
    }
    types = _reregistered(row)
    assert types["VAR_SCHED_COREIDX"] == "int"
    # The one the worker said nothing about still follows its bucket.
    assert types["VAR_SCHED_abcdef012345"] == "bool"


def test_the_declared_type_survives_a_document_round_trip():
    """The record goes to disk between the worker and the solver, so a type
    that is not serialised is a type that is lost."""
    row = {
        "undecided": {"VAR_SCHED_COREIDX": "LOOP_INDUCTION: coreIdx"},
        "var_types": {"VAR_SCHED_COREIDX": "int"},
    }
    fld = _field(EX_OVERAPPROX, [], undecided_guards=_guards_of(row, None))
    [back] = _to_field(fld.to_dict(), None).undecided_guards
    assert back.var_type == "int"


def test_an_unclassified_root_counts_as_host_state():
    """Guessing the other way would report a dimension as drivable on the
    strength of a root nobody classified."""
    assert classify_input_closure(["SOMETHING_NEW"]) == IC_HOST_STATE
    assert classify_input_closure(["INPUT_SHAPE", "SOMETHING_NEW"]) == IC_HOST_STATE


def test_scheduling_roots_are_not_drivable():
    """A branch on traversal position is taken on some iteration regardless of
    the input, so it is not a knob."""
    assert classify_input_closure(["LOOP_INDUCTION"]) == IC_HOST_STATE
    assert classify_input_closure(["KERNEL_BUILTIN"]) == IC_HOST_STATE


# -- do the derived values fit the template's declaration? ------------------
def test_a_value_outside_the_declared_domain_is_reported():
    """`OutDType` in FAG: the template declares 0-3, but the FP8 and HiFloat8
    paths write 4/5/6 into the key. An operator-side contract conflict that only
    a derivation can see."""
    fld = _field(EX_EXACT, ["INPUT_DTYPE"], name="OutDType")
    fld.domain = ["0", "1", "2", "3"]
    fld.value_leaves = ["0", "1", "2", "3", "4", "5", "6"]
    assert fld.domain_violations == ["4", "5", "6"]


def test_the_same_values_under_a_wider_declaration_are_clean():
    """`InputDType` carries the identical leaves but declares 0-6. Without this
    the check could be passing for the wrong reason."""
    fld = _field(EX_EXACT, ["INPUT_DTYPE"], name="InputDType")
    fld.domain = ["0", "1", "2", "3", "4", "5", "6"]
    fld.value_leaves = ["0", "1", "2", "3", "4", "5", "6"]
    assert fld.domain_violations == []


def test_unfolded_enum_spellings_are_not_reported():
    """`value_leaves` keeps symbolic constants alongside folded ones. Judging
    those would flag every dimension and make the check useless noise."""
    fld = _field(EX_EXACT, ["INPUT_DTYPE"])
    fld.domain = ["0", "1"]
    fld.value_leaves = ["0", "1", "OptionEnum::ENABLE", "TILING_KEY_1"]
    assert fld.domain_violations == []


def test_a_boolean_leaf_is_read_as_a_number():
    """`IsBn2MultiBlk` renders a folded arm as `False`, which is 0 in the key,
    not an unrelated symbol."""
    fld = _field(EX_EXACT, ["INPUT_SHAPE"])
    fld.domain = ["0", "1"]
    fld.value_leaves = ["0", "1", "False"]
    assert fld.domain_violations == []


def test_nothing_is_reported_when_the_template_declares_no_domain():
    fld = _field(EX_EXACT, ["INPUT_SHAPE"])
    fld.domain = []
    fld.value_leaves = ["7"]
    assert fld.domain_violations == []


# -- which guards may become LLM questions? ---------------------------------
def _guard(presort: str, *, escalate: bool, reason: str = "UNMAPPED_SYMBOL"):
    return UndecidedGuard(
        id="G1",
        var_id="VAR_LOOPELEM_INVALIDS1ARRAY_1",
        reason=reason,
        text="invalidS1Array[j] != 0",
        presort=presort,
        escalate=escalate,
    )


def test_a_loop_element_guard_is_not_escalated():
    """All six surviving loop elements in FAG are computed from operator inputs
    — interval coverage, a prefix sum, a filtered count. Asking a model whether
    they are input-derived collects a yes that does not make the expression
    solvable, while dropping the guard from `kept` pretends it was closed."""
    fld = _field(EX_OVERAPPROX, ["INPUT_SHAPE"])
    fld.undecided_guards = [_guard(PRESORT_LOOP_ELEMENT, escalate=False)]
    assert fld.escalating == []


def test_gap_collection_filters_on_presort_not_on_the_reason_text():
    """Second line of defence, and the reason it must not read `reason`: a loop
    element whose normalization failed as UNMAPPED_SYMBOL carries an escalatable
    reason, so the old `SCHED_SOFT` check passed it straight through."""
    fld = _field(EX_OVERAPPROX, ["INPUT_SHAPE"])
    fld.undecided_guards = [_guard(PRESORT_LOOP_ELEMENT, escalate=True)]
    assert collect_derivation_gap_items(HostDerivation(fields=[fld])) == []


def test_an_unmapped_guard_is_still_escalated():
    """The filter has to stay narrow: an unresolved symbol is a real question,
    and softening everything would leave nothing to ask."""
    fld = _field(EX_OVERAPPROX, ["INPUT_SHAPE"])
    fld.undecided_guards = [_guard(PRESORT_UNMAPPED, escalate=True)]
    items = collect_derivation_gap_items(HostDerivation(fields=[fld]))
    # One question, tagged onto both the key field and the guard id so that
    # clustering can merge them.
    assert {i.node_id for i in items} == {"KEYFIELD_Dim", "G1"}


# -- do the over-approximations themselves become questions? ----------------
def _initial_value_field(**kw):
    """A field whose expression still carries the value a member held before
    any write — the shape `implicit_defaults` records."""
    fld = _field(EX_OVERAPPROX, ["INPUT_SHAPE"], **kw)
    fld.free_vars = ["VAR_INIT_ABC123"]
    fld.implicit_defaults = [
        {
            "variable": "VAR_INIT_ABC123",
            "field": "fBaseParams.someFlag",
            "file": "f.cpp",
            "line": 42,
            "function": "Prepare",
            "guard": "layout == TND",
        }
    ]
    return fld


def test_an_initial_value_assumption_becomes_a_question():
    """It was never a guard, so `collect_derivation_gap_items` cannot see it —
    and it is exactly what keeps the dimension from closing."""
    items = collect_free_var_gap_items(HostDerivation(fields=[_initial_value_field()]))
    assert [i.reason for i in items] == ["UNWRITTEN_INITIAL_VALUE"]
    assert items[0].text == "fBaseParams.someFlag"
    assert (items[0].file, items[0].line) == ("f.cpp", 42)


def test_the_question_carries_the_variable_an_answer_would_remove():
    """An initial-value variable has no guard record to hang a binding off, so
    without naming it the substitution would have nothing to aim at."""
    items = collect_free_var_gap_items(HostDerivation(fields=[_initial_value_field()]))
    assert items[0].var_id == "VAR_INIT_ABC123"
    blocker = cluster(items)[0]
    assert "VAR_INIT_ABC123" in blocker.affected_nodes


def test_two_dimensions_blocked_by_one_member_ask_once():
    doc = HostDerivation(
        fields=[
            _initial_value_field(name="DimA"),
            _initial_value_field(name="DimB"),
        ]
    )
    assert len(cluster(collect_free_var_gap_items(doc))) == 1


def test_a_loop_element_cut_becomes_a_question_even_though_it_never_escalates():
    """Filtered out of the escalating queue on purpose — asking whether it is
    input-derived collects a yes that changes nothing. Asking what the loop
    computes is a different question, and it is the one worth asking."""
    fld = _field(EX_OVERAPPROX, ["INPUT_SHAPE"])
    fld.free_vars = ["VAR_LOOPELEM_INVALIDS1ARRAY_1"]
    fld.undecided_guards = [_guard(PRESORT_LOOP_ELEMENT, escalate=False)]
    items = collect_free_var_gap_items(HostDerivation(fields=[fld]))
    assert [i.reason for i in items] == ["LOOP_SUMMARY_NEEDED"]
    assert items[0].var_id == "VAR_LOOPELEM_INVALIDS1ARRAY_1"


def test_a_scheduling_position_is_still_not_asked_about():
    """Which core ran a block is not a property of the input, so any answer
    would be invention."""
    fld = _field(EX_OVERAPPROX, ["INPUT_SHAPE"])
    fld.free_vars = ["VAR_SCHED_COREIDX", "VAR_REACHED_Helper"]
    assert collect_free_var_gap_items(HostDerivation(fields=[fld])) == []


def test_a_free_variable_with_nothing_behind_it_is_not_turned_into_a_question():
    """`unrecorded_free_vars` gates on this, and it means the derivation has a
    bug. Inventing a question would paper over it with a model's guess."""
    fld = _field(EX_OVERAPPROX, ["INPUT_SHAPE"])
    fld.free_vars = ["VAR_INIT_NOTHING_KNOWN"]
    assert collect_free_var_gap_items(HostDerivation(fields=[fld])) == []


def test_an_assumption_already_substituted_away_is_not_asked_about():
    """`free_vars` is what survives in the expression; a record left over from
    an answered question would spend a model's attention on nothing."""
    fld = _initial_value_field()
    fld.free_vars = []
    assert collect_free_var_gap_items(HostDerivation(fields=[fld])) == []


# -- does an accepted verdict actually change the expression? ---------------
_COND = {"op": "gt", "var": "VAR_INPUT_SHAPE_B", "value": 1}


def test_an_int_variable_probe_is_substitutable():
    """`_truthy` renders an int variable as `var != 0`, not `var == True`. Only
    matching the bool spelling skipped every loop-element cut in silence."""
    expr = {"op": "ne", "var": "VAR_LOOPELEM_X_1", "value": 0}
    assert substitute_vars(expr, {"VAR_LOOPELEM_X_1": _COND}) == _COND


def test_a_bool_variable_probe_is_still_substitutable():
    expr = {"op": "eq", "var": "VAR_UNDECIDED_X_1", "value": True}
    assert substitute_vars(expr, {"VAR_UNDECIDED_X_1": _COND}) == _COND


def test_a_real_comparison_on_the_variable_is_left_alone():
    """Only the truthiness probe stands for "the guard held". `x == 5` is a test
    the source wrote, and a binding about the guard says nothing about it."""
    expr = {"op": "eq", "var": "VAR_LOOPELEM_X_1", "value": 5}
    assert substitute_vars(expr, {"VAR_LOOPELEM_X_1": _COND}) == expr


def _patched_field(expr: dict) -> tuple[FieldDerivation, dict]:
    fld = _field(EX_OVERAPPROX, ["INPUT_SHAPE"])
    fld.value_expr = expr
    fld.undecided_guards = [
        UndecidedGuard(
            id="G1",
            var_id="VAR_LOOPELEM_X_1",
            reason="OPAQUE",
            text="invalidS1Array[j] != 0",
            presort=PRESORT_UNMAPPED,
            escalate=True,
        )
    ]
    metrics = apply_bindings_to_derivation(
        HostDerivation(fields=[fld]),
        [
            {
                "guard_ids": ["G1"],
                "classification": "input_derived",
                "binding": {"var_id": "VAR_INPUT_SHAPE_B", "op": "gt", "value": 1},
            }
        ],
    )
    return fld, metrics


def test_a_verdict_that_lands_resolves_the_guard():
    fld, metrics = _patched_field({"op": "ne", "var": "VAR_LOOPELEM_X_1", "value": 0})
    assert (metrics["resolved"], metrics["reverted"]) == (1, 0)
    assert fld.undecided_guards == []
    assert "VAR_LOOPELEM_X_1" not in fld.variables


def test_a_verdict_that_does_not_land_is_rolled_back():
    """The silent failure this exists to stop: the guard is struck off the
    record, `escalating_after` drops, the loop gate passes — and the variable is
    still in the expression a solver reads, now with nothing to explain it.

    Here the variable is also read in a value position, which no boolean
    condition can replace, so the rewrite cannot fully land.
    """
    fld, metrics = _patched_field(
        {
            "op": "if_then_else",
            "condition": {"op": "ne", "var": "VAR_LOOPELEM_X_1", "value": 0},
            "then": {"var": "VAR_LOOPELEM_X_1"},
            "else": {"lit": 0},
        }
    )
    assert (metrics["resolved"], metrics["reverted"]) == (0, 1)
    assert [g.id for g in fld.undecided_guards] == ["G1"]
    # The invariant the rollback protects: every free variable still has a
    # guard record naming it.
    assert fld.unrecorded_free_vars() == []
