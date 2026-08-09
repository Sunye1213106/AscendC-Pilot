# -*- coding: utf-8 -*-
"""Obligations: dimension targets become Case mutations via search_hints."""

from __future__ import annotations

import pytest

from replay import inputs as I
from replay import obligations as O
from replay.package_data import active_package_dir, repo_root


def _require_search_hints():
    pkg = active_package_dir(repo_root())
    path = pkg / "search_hints.yaml"
    if not path.is_file():
        pytest.skip("search_hints.yaml missing (run export_adapter_pack)")
    return O.load_hints(refresh=True)


def test_every_hinted_dim_has_a_generator():
    hints = _require_search_hints()
    for dim, spec in (hints.get("special_generators") or {}).items():
        name = spec.get("generator") if isinstance(spec, dict) else spec
        assert name in O.GENERATORS, f"{dim} -> {name}"


def test_pse_on_and_off_match_the_old_ladder():
    hints = _require_search_hints()
    if "IsPse" not in (hints.get("special_generators") or {}):
        pytest.skip("IsPse generator not in search_hints")
    base = I.Case()
    on = O.variants(base, "IsPse", "1")
    off = O.variants(base, "IsPse", "0")
    assert {c.pse_shape for c in on} == set(I.PSE_SHAPES)
    assert all(c.pse for c in on)
    assert off == [I.Case(pse=False)] or (len(off) == 1 and not off[0].pse)


def test_host_state_dims_come_from_hints_not_a_set_in_code():
    hints = _require_search_hints()
    if not hints.get("host_state_dims"):
        pytest.skip("host_state_dims not in search_hints")
    assert O.is_host_state("SplitAxis")
    assert O.is_host_state("IsNzOut")
    assert not O.is_host_state("IsPse")
    assert not O.needs_compensation("S1TemplateNum")
    assert O.needs_compensation("IsPse")


def test_a_dim_with_no_knob_returns_empty():
    # Host-state / unbound dims return empty even without search_hints.
    assert O.variants(I.Case(), "SplitAxis", "5") == []
