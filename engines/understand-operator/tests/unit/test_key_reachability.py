"""Soundness of per-key reachability.

The one thing this must never do is call a key unreachable when a host run can
produce it. Every test here is aimed at a way that could happen: sharing a
variable that stands for two different values, compiling a symbol we could not
read, or answering at all when there is no derivation to answer from.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from uo_init.key_reachability import (
    R_REACHABLE,
    R_UNDERIVABLE,
    R_UNKNOWN,
    R_UNREACHABLE,
    DIM_PREFIX,
    KeyReachability,
)

pytest.importorskip("z3", reason="reachability needs the z3 backend")


def _spec(value_type="int", origin="opdef_attr", merged=False):
    return SimpleNamespace(
        value_type=value_type, origin=origin, identity_merged=merged
    )


def _model(specs, constants=None):
    return SimpleNamespace(
        get=lambda var_id: specs.get(var_id),
        named_constants=dict(constants or {}),
    )


def _field(name, expr, *, derivable=True):
    return SimpleNamespace(name=name, value_expr=expr, input_derivable=derivable)


def _is(var, value):
    """`1` when `var == value`, else `0` — the shape a key dimension has."""
    return {
        "op": "if_then_else",
        "condition": {"op": "eq", "var": var, "value": value},
        "then": 1,
        "else": 0,
    }


def _context(fields, specs, constants=None):
    return KeyReachability.from_derivation(
        SimpleNamespace(fields=fields), _model(specs, constants)
    )


# -- no derivation ---------------------------------------------------------
def test_without_a_derivation_nothing_is_ever_called_reachable():
    ctx = KeyReachability.unavailable("no host derivation")
    verdict = ctx.verdict({"A": "1", "B": "0"})
    assert verdict.status == R_UNDERIVABLE
    assert "no host derivation" in verdict.reason


def test_a_key_whose_dimensions_were_all_omitted_is_underivable():
    # A float bound cannot be expressed in an integer IR, so nothing compiles.
    ctx = _context([_field("A", _is("VAR_X", 1.5))], {"VAR_X": _spec()})
    assert ctx.summary()["dimensions_compiled"] == 0
    assert ctx.verdict({"A": "1"}).status == R_UNDERIVABLE


# -- identity --------------------------------------------------------------
def test_two_dimensions_reading_one_value_can_contradict_each_other():
    ctx = _context(
        [_field("A", _is("VAR_LAYOUT", 1)), _field("B", _is("VAR_LAYOUT", 2))],
        {"VAR_LAYOUT": _spec()},
    )
    assert "VAR_LAYOUT" in ctx.summary()["identity_shared"]
    # The layout cannot be 1 and 2 at once, so no host run produces both.
    assert ctx.verdict({"A": "1", "B": "1"}).status == R_UNREACHABLE
    assert ctx.verdict({"A": "1", "B": "0"}).status == R_REACHABLE


def test_a_merged_identity_never_makes_two_dimensions_contradict():
    # Same expressions, but now the variable stands for "some shape dimension",
    # so the two dimensions need not be talking about the same one.
    ctx = _context(
        [_field("A", _is("VAR_DIM", 1)), _field("B", _is("VAR_DIM", 2))],
        {"VAR_DIM": _spec(merged=True)},
    )
    assert "VAR_DIM" in ctx.summary()["identity_isolated"]
    assert ctx.verdict({"A": "1", "B": "1"}).status == R_REACHABLE


def test_an_accessor_shaped_name_is_isolated_even_if_nobody_flagged_it():
    ctx = _context(
        [
            _field("A", _is("VAR_SHAPE_GETSTORAGESHAPE", 1)),
            _field("B", _is("VAR_SHAPE_GETSTORAGESHAPE", 2)),
        ],
        {"VAR_SHAPE_GETSTORAGESHAPE": _spec()},
    )
    assert ctx.verdict({"A": "1", "B": "1"}).status == R_REACHABLE


def test_a_variable_the_model_never_declared_is_isolated():
    ctx = _context(
        [_field("A", _is("VAR_UNKNOWN", 1)), _field("B", _is("VAR_UNKNOWN", 2))],
        {},
    )
    assert ctx.verdict({"A": "1", "B": "1"}).status == R_REACHABLE


# -- symbols ---------------------------------------------------------------
def test_a_symbol_we_can_read_is_folded_and_the_dimension_compiles():
    ctx = _context(
        [_field("A", _is("VAR_MODE", "ModeEnum::FAST"))],
        {"VAR_MODE": _spec()},
        {"ModeEnum::FAST": 3},
    )
    assert ctx.summary()["dimensions_compiled"] == 1
    assert ctx.verdict({"A": "1"}).status == R_REACHABLE


def test_a_symbol_we_cannot_read_is_recorded_as_an_assumption():
    ctx = _context(
        [_field("A", _is("VAR_MODE", "ge::DT_FLOAT"))], {"VAR_MODE": _spec()}
    )
    # The dimension still compiles, so it can constrain the key...
    assert ctx.summary()["dimensions_compiled"] == 1
    # ...but we had to invent a value for the symbol, and we say so.
    assert ctx.summary()["assumed_distinct"] == ["ge::DT_FLOAT"]


def _any_of(var, values):
    """`1` when `var` equals one of `values`, else `0`."""
    return {
        "op": "if_then_else",
        "condition": {
            "op": "or",
            "args": [{"op": "eq", "var": var, "value": v} for v in values],
        },
        "then": 1,
        "else": 0,
    }


def test_one_group_never_mixes_a_value_we_read_with_one_we_invented():
    """An attribute compared against the layout strings `"BNSD"` and `"SBH"`.

    `BNSD` is also the name of an enum member the operator uses for something
    unrelated, so it can be read while `SBH` cannot. Reading one of the group
    and inventing the other puts the two strings in different encodings, and
    lands the first on whatever integer that unrelated enum happens to use —
    deciding comparisons the source never made. Either the whole group is read
    or none of it is.
    """
    ctx = _context(
        [_field("A", _any_of("VAR_ATTR", ["BNSD", "SBH"]))],
        {"VAR_ATTR": _spec()},
        {"BNSD": 2},
    )
    assert ctx.summary()["dimensions_compiled"] == 1
    assert ctx.summary()["assumed_distinct"] == ["BNSD", "SBH"]


def test_two_spellings_of_one_value_are_kept_together_when_we_read_both():
    """Reading the group is what makes aliases work.

    `REAL` and `ALIAS` are one value under two names, so a key asking both
    dimensions to match is reachable. Inventing distinct numbers would call it
    a contradiction.
    """
    ctx = _context(
        [
            _field("A", _is("VAR_MODE", "E::REAL")),
            _field("B", _is("VAR_MODE", "E::ALIAS")),
        ],
        {"VAR_MODE": _spec()},
        {"E::REAL": 1, "E::ALIAS": 1},
    )
    assert ctx.summary()["assumed_distinct"] == []
    assert ctx.verdict({"A": "1", "B": "1"}).status == R_REACHABLE


def test_a_merged_variable_compared_with_both_a_number_and_a_symbol_is_split():
    """`VAR_ATTR_GETATTRS` stands for every `GetAttrs()` call in the operator.

    So the comparison against a layout string and the one against a number are
    almost certainly different attributes. Left in one variable, the numeric
    bound rules out the string's invented encoding and the key looks impossible.
    """
    both = {
        "op": "if_then_else",
        "condition": {
            "op": "and",
            "args": [
                {"op": "eq", "var": "VAR_ATTR_GETATTRS", "value": "SBH"},
                {"op": "gt", "var": "VAR_ATTR_GETATTRS", "value": 0},
            ],
        },
        "then": 1,
        "else": 0,
    }
    ctx = _context([_field("A", both)], {"VAR_ATTR_GETATTRS": _spec(merged=True)})
    assert ctx.summary()["dimensions_compiled"] == 1
    assert ctx.verdict({"A": "1"}).status == R_REACHABLE


def test_a_conflict_between_symbols_we_could_not_read_is_only_unknown():
    """Two spellings we never read could be aliases for the same value.

    Treating them as distinct is what lets the dimension be solved at all, but
    it is also the assumption that could invent this contradiction, so the
    verdict has to stop short of `unreachable`.
    """
    ctx = _context(
        [
            _field("A", _is("VAR_MODE", "ge::DT_FLOAT")),
            _field("B", _is("VAR_MODE", "ge::DT_FLOAT32")),
        ],
        {"VAR_MODE": _spec()},
    )
    verdict = ctx.verdict({"A": "1", "B": "1"})
    assert verdict.status == R_UNKNOWN
    assert "could not read" in verdict.reason


def test_a_conflict_between_symbols_we_did_read_is_still_unreachable():
    ctx = _context(
        [
            _field("A", _is("VAR_MODE", "ModeEnum::FAST")),
            _field("B", _is("VAR_MODE", "ModeEnum::SLOW")),
        ],
        {"VAR_MODE": _spec()},
        {"ModeEnum::FAST": 1, "ModeEnum::SLOW": 2},
    )
    assert ctx.summary()["assumed_distinct"] == []
    assert ctx.verdict({"A": "1", "B": "1"}).status == R_UNREACHABLE


# -- what a SAT is allowed to mean -----------------------------------------
def test_a_dimension_left_out_of_the_conjunction_downgrades_the_answer():
    ctx = _context(
        [_field("A", _is("VAR_X", 1)), _field("B", _is("VAR_Y", 1.5))],
        {"VAR_X": _spec(), "VAR_Y": _spec()},
    )
    verdict = ctx.verdict({"A": "1", "B": "0"})
    assert verdict.participating == ("A",)
    assert verdict.status == R_UNKNOWN


def test_an_over_approximated_dimension_downgrades_the_answer():
    ctx = _context(
        [_field("A", _is("VAR_X", 1), derivable=False)], {"VAR_X": _spec()}
    )
    verdict = ctx.verdict({"A": "1"})
    assert verdict.status == R_UNKNOWN
    assert "over-approximated" in verdict.reason


def test_a_witness_reproduces_the_key_it_explains():
    ctx = _context(
        [_field("A", _is("VAR_X", 7)), _field("B", _is("VAR_Y", 9))],
        {"VAR_X": _spec(), "VAR_Y": _spec()},
    )
    verdict = ctx.verdict({"A": "1", "B": "0"})
    assert verdict.status == R_REACHABLE
    assert verdict.witness[DIM_PREFIX + "A"] == 1
    assert verdict.witness[DIM_PREFIX + "B"] == 0


# -- targets ---------------------------------------------------------------
def test_a_boolean_dimension_asked_for_a_third_value_is_unreachable():
    ctx = _context(
        [_field("A", {"op": "eq", "var": "VAR_FLAG", "value": True})],
        {"VAR_FLAG": _spec(value_type="bool")},
    )
    assert ctx.verdict({"A": "2"}).status == R_UNREACHABLE


def test_a_constant_dimension_rules_out_every_other_value():
    ctx = _context([_field("A", {"op": "lit", "value": 5})], {})
    assert ctx.verdict({"A": "5"}).status == R_REACHABLE
    assert ctx.verdict({"A": "4"}).status == R_UNREACHABLE


def test_an_unreachable_key_says_which_dimensions_disagreed():
    ctx = _context(
        [_field("A", _is("VAR_LAYOUT", 1)), _field("B", _is("VAR_LAYOUT", 2))],
        {"VAR_LAYOUT": _spec()},
    )
    core = ctx.verdict({"A": "1", "B": "1"}).unsat_core
    assert any("VAR_KEYDIM_A" in item for item in core)
    assert any("VAR_KEYDIM_B" in item for item in core)
