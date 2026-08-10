# -*- coding: utf-8 -*-
"""A dimension with no input knob has to be distinguishable from a stale cache.

`reads_host_state` answers "which of this dimension's variables can no case
set", which is what tells a search that a dimension is not worth nudging inputs
at. The failure that mattered was not a wrong answer: it was an empty one. A
derivation written before the `var_roots` field existed made every dimension
look input-driven, so nothing ever reported that a dimension had no knob, and
the search used hand-written ones instead without saying so.
"""

from __future__ import annotations

import pytest

from replay import bridge


def _field(**kw):
    return {"name": "IsNzOut", **kw}


def test_variables_rooted_in_tiling_state_are_the_ones_reported():
    field = _field(
        var_roots={
            "VAR_TDF_SPLITAXIS": "TILING_DATA",
            "VAR_TDF_DETERSPARSETYPE": "TILING_DATA",
            "VAR_SHAPE_QUERY_D2": "INPUT_SHAPE",
            "VAR_ATTR_SPARSE_MODE": "ATTRIBUTE",
        }
    )
    assert bridge.reads_host_state(field) == [
        "VAR_TDF_DETERSPARSETYPE",
        "VAR_TDF_SPLITAXIS",
    ]


def test_a_dimension_driven_entirely_by_inputs_reports_nothing():
    field = _field(var_roots={"VAR_SHAPE_QUERY_D2": "INPUT_SHAPE"})
    assert bridge.reads_host_state(field) == []


def test_a_derivation_without_the_field_is_refused_not_read_as_empty():
    """The distinction the old code lost: no host state vs. nothing recorded."""
    with pytest.raises(KeyError) as caught:
        bridge.reads_host_state(_field())
    message = str(caught.value)
    assert "IsNzOut" in message
    assert "derive_key_fields" in message, "the error has to say how to fix it"


def test_the_set_of_roots_is_not_accepted_in_place_of_the_mapping():
    """`root_vars` is a list of roots, so it cannot say which variable is which."""
    with pytest.raises(KeyError):
        bridge.reads_host_state(_field(root_vars=["TILING_DATA", "INPUT_SHAPE"]))
