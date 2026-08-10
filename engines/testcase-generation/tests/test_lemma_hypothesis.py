# -*- coding: utf-8 -*-
"""Engine-proposed antecedents: minimisation, folding, and what they may claim.

The dimension names here are deliberately nothing like any real operator's. The
hypothesis engine reads its dimensions from the key schema and its values from
decoded keys, so a test that passes with invented names is evidence the logic
carries no operator knowledge — which is the property that lets the next
operator use it without a rewrite.
"""

from __future__ import annotations

import pytest

from testcase_agent.closure import hypothesis as HYP


def _wit(*rows):
    return [dict(r) for r in rows]


def test_minimise_drops_dimensions_that_do_not_carry_the_exclusion():
    """Only the part R actually never witnessed should survive."""
    # R witnessed every mode/flavour, but never mode=c together with flavour=hot.
    wit = _wit(
        {"mode": "a", "flavour": "hot", "size": "8"},
        {"mode": "b", "flavour": "hot", "size": "8"},
        {"mode": "c", "flavour": "cold", "size": "8"},
        {"mode": "c", "flavour": "cold", "size": "16"},
    )
    opn = _wit({"mode": "c", "flavour": "hot", "size": "8"})

    got = HYP.minimise_when(
        {"mode": "c", "flavour": "hot", "size": "8"}, wit, opn
    )
    # size is irrelevant: dropping it keeps R empty. mode+flavour must stay.
    assert got == {"mode": "c", "flavour": "hot"}


def test_minimise_refuses_a_combination_a_witness_satisfies():
    """A hypothesis R already contradicts is not a hypothesis."""
    wit = _wit({"mode": "a", "flavour": "hot"})
    assert HYP.minimise_when({"mode": "a", "flavour": "hot"}, wit, []) == {}


def test_minimise_keeps_a_single_dimension_when_that_is_the_whole_story():
    wit = _wit({"mode": "a", "size": "8"}, {"mode": "b", "size": "16"})
    got = HYP.minimise_when({"mode": "z", "size": "8"}, wit, [])
    assert got in ({"mode": "z"}, {"mode": "z", "size": "8"})
    assert "mode" in got


def test_siblings_differing_in_one_dimension_fold_into_one_membership_term():
    """Four rules over one dimension are one proposition, not four."""
    wit = _wit({"mode": "a", "size": "1"})
    opn = _wit(
        {"mode": "z", "size": "8"},
        {"mode": "z", "size": "16"},
        {"mode": "z", "size": "32"},
    )
    cands = [
        {"when": {"mode": "z", "size": s}, "closes": 1}
        for s in ("8", "16", "32")
    ]
    folded = HYP.fold_set_terms(cands, wit, opn)

    assert len(folded) == 1
    term = folded[0]["when"]["size"]
    assert term == {"in": ["16", "32", "8"]}
    assert folded[0]["folded_from"] == 3
    assert folded[0]["closes"] == 3


def test_folding_is_refused_when_the_merged_term_admits_a_witness():
    """Merging must not widen an antecedent into something R contradicts."""
    wit = _wit({"mode": "z", "size": "16"})
    cands = [
        {"when": {"mode": "z", "size": "8"}, "closes": 1},
        {"when": {"mode": "z", "size": "32"}, "closes": 1},
    ]
    folded = HYP.fold_set_terms(cands, wit, [])
    # The union {8,32} does not contain 16, so this fold is legitimate...
    assert len(folded) == 1
    # ...but one whose union covers the witness must be rejected.
    cands2 = [
        {"when": {"mode": "z", "size": "8"}, "closes": 1},
        {"when": {"mode": "z", "size": "16"}, "closes": 1},
    ]
    folded2 = HYP.fold_set_terms(cands2, wit, [])
    assert all(
        not isinstance(c["when"].get("size"), dict) for c in folded2
    ), "a fold that admits a witness must not be produced"


def test_hypothesis_grade_can_never_shrink_the_bound():
    """The grade must sit outside the set that promotion accepts."""
    from replay.rule_engine import SOUND_GRADES

    assert HYP.HYPOTHESIS_GRADE not in SOUND_GRADES


def test_module_names_no_dimension_of_any_operator():
    """The logic must be schema-driven, never keyed on a dimension name."""
    import inspect

    src = inspect.getsource(HYP)
    body = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )
    for token in ("DTemplateNum", "SparseMode", "IsRope", "LayoutType", "TND"):
        assert token not in body, f"{token} hardcoded in hypothesis engine"
