# -*- coding: utf-8 -*-
"""What values a shape variable is allowed to take.

A shape accessor reads one of two things, and the variable layer already tells
them apart: with an axis index it names one axis length (`VAR_SHAPE_QUERY_D2`),
without one it names the shape as a whole (`VAR_SHAPE_PSE_SHIFT`) — its rank,
or its element count. Their ranges differ at exactly one value, and it is the
value an operator looks for when it asks whether it was given an optional
input at all.
"""
from __future__ import annotations

from uo_init.concrete_eval import samples
from uo_init.variable_model import VariableModel


def test_a_shape_read_without_an_axis_may_be_zero():
    """`GetStorageShape().GetDimNum() == 0` is how the source spells "this
    optional input was not passed". Bounding the variable below by one makes
    that test false whatever the input, and the branch it selects — the one
    where the tensor is absent — stops existing."""
    spec = VariableModel().declare_on_demand("VAR_SHAPE_PSE_SHIFT", "INPUT_SHAPE")
    assert spec.domain.lo == 0


def test_an_axis_of_a_tensor_that_is_there_is_still_at_least_one():
    spec = VariableModel().declare_on_demand("VAR_SHAPE_PSE_SHIFT_D0", "INPUT_SHAPE", 0)
    assert spec.domain.lo == 1


def test_the_bound_follows_the_axis_the_accessor_named():
    """Decided by what the atom read, not by how the id happens to be spelled."""
    model = VariableModel()
    assert model.declare_on_demand("VAR_SHAPE_A", "INPUT_SHAPE", 2).domain.lo == 1
    assert model.declare_on_demand("VAR_SHAPE_B", "INPUT_SHAPE").domain.lo == 0


def test_only_shape_variables_carry_a_lower_bound_at_all():
    spec = VariableModel().declare_on_demand("VAR_ATTR_HEAD_NUM", "ATTRIBUTE")
    assert spec.domain.lo is None


def test_the_absent_tensor_value_survives_into_what_gets_sampled():
    """The bound is not decoration: representative values are intersected with
    it, so a rank pinned above zero is never tried at zero and the guard that
    reads it can only ever come out one way."""
    model = VariableModel()
    rank = model.declare_on_demand("VAR_SHAPE_PSE_SHIFT", "INPUT_SHAPE")
    axis = model.declare_on_demand("VAR_SHAPE_PSE_SHIFT_D0", "INPUT_SHAPE", 0)
    assert 0 in samples({0}, rank.domain)
    assert 0 not in samples({0}, axis.domain)


def test_the_rank_and_an_axis_of_one_tensor_stay_different_variables():
    """Both are named off the tensor, which is what keeps the convention
    readable: no separate spelling for "the rank of", only the absence of an
    axis."""
    model = VariableModel()
    assert model.var_id_for("INPUT_SHAPE", "pse_shift") == "VAR_SHAPE_PSE_SHIFT"
    assert model.var_id_for("INPUT_SHAPE", "pse_shift", 0) == "VAR_SHAPE_PSE_SHIFT_D0"
