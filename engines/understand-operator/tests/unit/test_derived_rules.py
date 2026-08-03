"""Rules must be provable, not merely unrefuted.

The hazard here is the opposite of a missing rule: a rule the solver did not
actually prove, written out with a grade that says it did. Anything the solver
answered `unknown` for -- a timeout, an over-approximated dimension, a symbol it
had to invent a value for -- has to land in `undecided`, because a coverage run
reads these as permission to stop looking for a key.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from uo_init.derived_rules import (
    GRADE_SOLVER,
    KIND_IMPLICATION,
    KIND_PAIR,
    KIND_VALUE,
    DerivedRule,
    derive_rules,
    refute,
    source_hash,
)
from uo_init.key_reachability import (
    R_REACHABLE,
    R_UNKNOWN,
    R_UNREACHABLE,
    KeyReachability,
)

pytest.importorskip("z3", reason="rule derivation needs the z3 backend")


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


def _never():
    """A dimension whose condition cannot hold, so it is always 0.

    This is the shape a collapsed variable identity takes: one variable carrying
    two incompatible comparisons.
    """
    return {
        "op": "if_then_else",
        "condition": {
            "op": "and",
            "args": [
                {"op": "eq", "var": "VAR_ONE", "value": 1},
                {"op": "eq", "var": "VAR_ONE", "value": 2},
            ],
        },
        "then": 1,
        "else": 0,
    }


def _context(fields, specs, constants=None):
    return KeyReachability.from_derivation(
        SimpleNamespace(fields=fields), _model(specs, constants)
    )


def _shared_pair():
    """Two dimensions reading one host value, so they can genuinely clash."""
    return _context(
        [_field("A", _is("VAR_LAYOUT", 1)), _field("B", _is("VAR_LAYOUT", 2))],
        {"VAR_LAYOUT": _spec()},
    )


BOOL = ["0", "1"]


# -- joint_verdict ---------------------------------------------------------
def test_asking_about_a_subset_does_not_count_the_others_as_gaps():
    """`verdict` wants a whole key; a two-dimension question is not missing 17."""
    ctx = _shared_pair()
    assert ctx.joint_verdict({"A": 1, "B": 1}).status == R_UNREACHABLE
    assert ctx.joint_verdict({"A": 1}).status == R_REACHABLE


def test_a_whole_key_verdict_still_reports_dimensions_it_cannot_see():
    ctx = _shared_pair()
    # `verdict` is handed a key naming a dimension that never compiled, so its
    # SAT stays `unknown` where `joint_verdict`'s would not.
    assert ctx.verdict({"A": 1, "MISSING": 1}).status == R_UNKNOWN


def test_an_over_approximated_dimension_is_never_called_reachable():
    ctx = _context(
        [_field("A", _is("VAR_LAYOUT", 1), derivable=False)], {"VAR_LAYOUT": _spec()}
    )
    assert ctx.joint_verdict({"A": 1}).status == R_UNKNOWN


# -- single values ---------------------------------------------------------
def test_a_value_the_expression_cannot_produce_becomes_a_rule():
    ctx = _context([_field("C", _never())], {"VAR_ONE": _spec()})
    out = derive_rules(ctx, {"C": BOOL})
    dead = out.of_kind(KIND_VALUE)
    assert [(r.excludes, r.evidence_grade) for r in dead] == [
        ((("C", 1),), GRADE_SOLVER)
    ]
    assert out.dead_values() == {("C", 1)}
    assert dead[0].evidence, "an exclusion must carry the core that proved it"


def test_a_dead_value_is_not_paired_with_anything():
    """Every pair containing it is vacuous, so asking would only add noise."""
    ctx = _context(
        [_field("A", _is("VAR_LAYOUT", 1)), _field("C", _never())],
        {"VAR_LAYOUT": _spec(), "VAR_ONE": _spec()},
    )
    out = derive_rules(ctx, {"A": BOOL, "C": BOOL})
    assert out.dead_values() == {("C", 1)}
    for rule in out.of_kind(KIND_PAIR):
        assert ("C", 1) not in rule.excludes


# -- pairs -----------------------------------------------------------------
def test_two_dimensions_that_cannot_hold_together_become_a_pair_rule():
    out = derive_rules(_shared_pair(), {"A": BOOL, "B": BOOL})
    pairs = {r.excludes for r in out.of_kind(KIND_PAIR)}
    assert (("A", 1), ("B", 1)) in pairs
    # The compatible corners must not be claimed as exclusions.
    assert (("A", 1), ("B", 0)) not in pairs
    assert (("A", 0), ("B", 0)) not in pairs


def test_pairs_can_be_switched_off():
    out = derive_rules(_shared_pair(), {"A": BOOL, "B": BOOL}, pairs=False)
    assert out.of_kind(KIND_PAIR) == []


# -- implications ----------------------------------------------------------
def test_a_row_with_one_option_left_folds_into_an_implication():
    """`A=1` excludes `B=1`, and `B` has only `0` left, so `A=1` forces it."""
    out = derive_rules(_shared_pair(), {"A": BOOL, "B": BOOL})
    forced = {
        (r.excludes[0], r.forces) for r in out.of_kind(KIND_IMPLICATION)
    }
    assert (("A", 1), ("B", 0)) in forced
    assert (("B", 1), ("A", 0)) in forced


def test_an_implication_keeps_the_pairs_it_came_from():
    out = derive_rules(_shared_pair(), {"A": BOOL, "B": BOOL})
    rule = next(
        r for r in out.of_kind(KIND_IMPLICATION) if r.excludes[0] == ("A", 1)
    )
    assert rule.folded_from == ((("A", 1), ("B", 1)),)
    assert "forces B=0" in rule.describe()


def test_nothing_is_forced_when_the_row_leaves_two_options():
    ctx = _context(
        [_field("A", _is("VAR_LAYOUT", 1)), _field("B", _is("VAR_OTHER", 2))],
        {"VAR_LAYOUT": _spec(), "VAR_OTHER": _spec()},
    )
    out = derive_rules(ctx, {"A": BOOL, "B": BOOL})
    # Independent dimensions exclude nothing, so there is nothing to fold.
    assert out.of_kind(KIND_PAIR) == []
    assert out.of_kind(KIND_IMPLICATION) == []


def test_implications_can_be_switched_off():
    out = derive_rules(_shared_pair(), {"A": BOOL, "B": BOOL}, implications=False)
    assert out.of_kind(KIND_IMPLICATION) == []


# -- what must not become a rule ------------------------------------------
def test_an_undecidable_value_is_recorded_as_a_gap_not_a_rule():
    ctx = _context(
        [_field("A", _is("VAR_LAYOUT", 1), derivable=False)], {"VAR_LAYOUT": _spec()}
    )
    out = derive_rules(ctx, {"A": BOOL})
    assert out.rules == []
    assert [u["status"] for u in out.undecided] == [R_UNKNOWN, R_UNKNOWN]
    assert out.undecided[0]["excludes"] == [{"dim": "A", "value": 0}]


def test_a_dimension_without_an_expression_is_reported_not_assumed():
    ctx = _context([_field("A", _is("VAR_LAYOUT", 1))], {"VAR_LAYOUT": _spec()})
    out = derive_rules(ctx, {"A": BOOL, "GHOST": BOOL})
    assert out.skipped == {"GHOST": "no compiled expression"}
    assert all("GHOST" not in r.dims for r in out.rules)


def test_no_derivation_yields_no_rules_at_all():
    out = derive_rules(KeyReachability.unavailable("nothing to go on"), {"A": BOOL})
    assert out.rules == []


# -- the document ----------------------------------------------------------
def test_the_document_carries_counts_and_provenance():
    out = derive_rules(_shared_pair(), {"A": BOOL, "B": BOOL})
    doc = out.to_dict(provenance={"source_hash": "abc", "operator": "demo"})
    assert doc["version"] == 1
    assert doc["source_hash"] == "abc"
    assert doc["counts"]["rules"] == len(out.rules)
    assert doc["counts"]["queries"] == out.queries
    assert all(r["evidence_grade"] == GRADE_SOLVER for r in doc["rules"])
    assert all("statement" in r for r in doc["rules"])


def test_the_source_hash_tracks_what_was_derived_from():
    assert source_hash("a", "b") == source_hash("a", "b")
    assert source_hash("a", "b") != source_hash("a", "c")
    assert source_hash(b"a") == source_hash("a")


# -- the runtime counterexample gate --------------------------------------
def test_a_value_rule_is_refuted_by_a_run_that_produced_it():
    rule = DerivedRule(kind=KIND_VALUE, excludes=(("SplitAxis", 5),))
    hits = refute([rule], [{"SplitAxis": "0"}, {"SplitAxis": "5"}])
    assert [(r.kind, e) for r, e in hits] == [(KIND_VALUE, {"SplitAxis": 5})]


def test_a_rule_no_run_contradicts_survives():
    rule = DerivedRule(kind=KIND_VALUE, excludes=(("SplitAxis", 5),))
    assert refute([rule], [{"SplitAxis": "0"}, {"SplitAxis": "1"}]) == []


def test_a_pair_rule_needs_both_values_in_the_same_run():
    rule = DerivedRule(kind=KIND_PAIR, excludes=(("A", 1), ("B", 1)))
    apart = [{"A": "1", "B": "0"}, {"A": "0", "B": "1"}]
    assert refute([rule], apart) == []
    assert len(refute([rule], apart + [{"A": "1", "B": "1"}])) == 1


def test_an_implication_is_refuted_by_the_premise_holding_without_it():
    rule = DerivedRule(
        kind=KIND_IMPLICATION, excludes=(("IsNzOut", 1),), forces=("SplitAxis", 0)
    )
    obeys = [{"IsNzOut": "1", "SplitAxis": "0"}, {"IsNzOut": "0", "SplitAxis": "5"}]
    assert refute([rule], obeys) == []
    breaks = obeys + [{"IsNzOut": "1", "SplitAxis": "5"}]
    assert len(refute([rule], breaks)) == 1


def test_a_run_that_says_nothing_about_a_rule_cannot_refute_it():
    """A dimension missing from the row is unknown, not a mismatch."""
    rule = DerivedRule(kind=KIND_PAIR, excludes=(("A", 1), ("B", 1)))
    assert refute([rule], [{"A": "1"}, {"B": "1"}, {"A": "1", "C": "9"}]) == []


def test_each_refuted_rule_is_reported_once():
    rule = DerivedRule(kind=KIND_VALUE, excludes=(("A", 1),))
    assert len(refute([rule], [{"A": "1"}] * 20)) == 1


def test_progress_is_reported_per_phase():
    seen: list[tuple[str, int, int]] = []
    derive_rules(
        _shared_pair(), {"A": BOOL, "B": BOOL}, on_progress=lambda *a: seen.append(a)
    )
    kinds = {k for k, _, _ in seen}
    assert kinds == {KIND_VALUE, KIND_PAIR}
    assert all(total > 0 and index < total for _, index, total in seen)
