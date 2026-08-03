# -*- coding: utf-8 -*-
"""Obligations: dimension targets become Case mutations via search_hints."""

from __future__ import annotations

from replay import inputs as I
from replay import obligations as O


def test_every_hinted_dim_has_a_generator():
    hints = O.load_hints()
    for dim, spec in (hints.get("special_generators") or {}).items():
        name = spec.get("generator") if isinstance(spec, dict) else spec
        assert name in O.GENERATORS, f"{dim} -> {name}"


def test_pse_on_and_off_match_the_old_ladder():
    base = I.Case()
    on = O.variants(base, "IsPse", "1")
    off = O.variants(base, "IsPse", "0")
    assert {c.pse_shape for c in on} == set(I.PSE_SHAPES)
    assert all(c.pse for c in on)
    assert off == [I.Case(pse=False)] or (len(off) == 1 and not off[0].pse)


def test_host_state_dims_come_from_hints_not_a_set_in_code():
    assert O.is_host_state("SplitAxis")
    assert O.is_host_state("IsNzOut")
    assert not O.is_host_state("IsPse")
    assert not O.needs_compensation("S1TemplateNum")
    assert O.needs_compensation("IsPse")


def test_a_dim_with_no_knob_returns_empty():
    assert O.variants(I.Case(), "SplitAxis", "5") == []
