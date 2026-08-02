# -*- coding: utf-8 -*-
"""Reading the kernel's compile-time branching.

The classification is what these cover: which name in a condition is a key
dimension, which is merely built from one, and which is neither. Getting that
wrong attaches a branch to a dimension that does not decide it, which is worse
than reporting nothing -- a test aimed at the dimension would then be aimed at
the wrong code.
"""
from __future__ import annotations

import pytest

from uo_init.kernel_ir import KernelBranch, KernelIR, _classify, _Dimensions

DIMS = ["SplitAxis", "IsRope", "OutDType", "IsTnd", "DeterType"]


@pytest.fixture
def dims() -> _Dimensions:
    return _Dimensions(DIMS)


def _names(condition: str, d: _Dimensions):
    exact, derived, others = _classify(condition, d)
    return exact, derived, others


def test_the_two_sides_spell_a_dimension_differently(dims):
    """`IS_ROPE` in the kernel is `IsRope` in the key. Separators and case are
    a convention, not a difference."""
    exact, _, _ = _names("if constexpr (IS_ROPE)", dims)
    assert exact == ["IsRope"]


def test_the_same_name_matches_whatever_the_case(dims):
    for spelling in ("SplitAxis", "SPLIT_AXIS", "splitAxis", "split_axis"):
        exact, _, _ = _names(spelling, dims)
        assert exact == ["SplitAxis"], spelling


def test_a_name_built_from_a_dimension_is_not_the_dimension(dims):
    """A `constexpr bool OUTDTYPE_IS_B16` is evidence about `OutDType` without
    being it, so it lands separately."""
    exact, derived, _ = _names("if constexpr (OUTDTYPE_IS_B16)", dims)
    assert exact == []
    assert derived == ["OutDType"]


def test_a_derived_name_prefers_the_longer_dimension():
    """`OUTDTYPE_IS_B16` starts with both `Out` and `OutDType`; the specific
    one is the one that produced it."""
    d = _Dimensions(["Out", "OutDType"])
    _, derived, _ = _names("OUTDTYPE_IS_B16", d)
    assert derived == ["OutDType"]


def test_a_short_coincidence_does_not_count_as_derived():
    """Three letters in common is a coincidence, not a derivation."""
    d = _Dimensions(["Isd"])
    _, derived, others = _names("isdifferent", d)
    assert derived == []
    assert others == ["isdifferent"]


def test_a_condition_naming_several_dimensions_reports_all(dims):
    exact, _, _ = _names("IS_TND && !IS_ROPE && SPLIT_AXIS == 2", dims)
    assert exact == ["IsTnd", "IsRope", "SplitAxis"]


def test_a_dimension_named_twice_is_reported_once(dims):
    exact, _, _ = _names("SPLIT_AXIS == 1 || SPLIT_AXIS == 3", dims)
    assert exact == ["SplitAxis"]


def test_the_call_is_not_a_value(dims):
    """`IsSameType<T1, float>::value` names a trait, not an input."""
    _, _, others = _names("IsSameType<T1, float>::value", dims)
    assert "IsSameType" not in others


def test_the_scope_a_name_sits_in_is_not_a_value(dims):
    _, _, others = _names("op::DataType::DT_BF16 == x", dims)
    assert "op" not in others
    assert "DataType" not in others


def test_a_name_that_is_neither_is_kept_for_inspection(dims):
    """Where a renamed dimension shows up, so it must not be discarded."""
    _, _, others = _names("DETER_SPARSE_TYPE != 0", dims)
    assert others == ["DETER_SPARSE_TYPE"]


def _branch(condition: str, *, dimensions=(), derived=(), variants=("a",), line=1):
    return KernelBranch(
        condition=condition,
        file="k.h",
        line=line,
        dimensions=list(dimensions),
        derived=list(derived),
        variants=list(variants),
    )


def test_branches_are_counted_against_the_dimension_that_decides_them():
    ir = KernelIR(
        branches=[
            _branch("a", dimensions=["IsRope"], line=1),
            _branch("b", dimensions=["IsRope", "IsTnd"], line=2),
            _branch("c", derived=["OutDType"], line=3),
        ]
    )
    assert ir.by_dimension() == {"IsRope": 2, "IsTnd": 1, "OutDType": 1}
    assert len(ir.touching("IsRope")) == 2
    # A branch turning on a name built from the dimension still belongs to it.
    assert len(ir.touching("OutDType")) == 1


def test_a_dimension_no_branch_mentions_is_named():
    """Silence is a finding: either the dimension decides nothing at compile
    time, or the kernel renamed it."""
    ir = KernelIR(branches=[_branch("a", dimensions=["IsRope"])])
    assert ir.silent_dimensions(["IsRope", "DeterType", "IsRegbase"]) == [
        "DeterType",
        "IsRegbase",
    ]


def test_unmapped_names_come_back_commonest_first():
    ir = KernelIR(
        branches=[
            KernelBranch("a", "k.h", 1, symbols=["RARE", "COMMON"]),
            KernelBranch("b", "k.h", 2, symbols=["COMMON"]),
            KernelBranch("c", "k.h", 3, symbols=["COMMON"]),
        ]
    )
    assert ir.unmapped_symbols() == [("COMMON", 3), ("RARE", 1)]
    assert ir.unmapped_symbols(limit=1) == [("COMMON", 3)]


def test_a_branch_only_some_variants_compile_is_flagged():
    """The dtype macro is a preprocessor value, so a single parse sees only
    part of the kernel. These branches are what makes the extra parses worth
    their cost."""
    ir = KernelIR(
        variants=["DT_FLOAT16", "DT_BF16", "DT_FLOAT"],
        branches=[
            _branch("everywhere", variants=["DT_FLOAT16", "DT_BF16", "DT_FLOAT"]),
            _branch("fp32 only", variants=["DT_FLOAT"], line=2),
        ],
    )
    assert [b.condition for b in ir.variant_only()] == ["fp32 only"]


def test_no_dimensions_given_means_nothing_is_claimed():
    """Callers that do not know the key schema still get the branches, with
    every name unclassified rather than force-fitted."""
    exact, derived, others = _names("IS_ROPE && SPLIT_AXIS", _Dimensions([]))
    assert exact == []
    assert derived == []
    assert others == ["IS_ROPE", "SPLIT_AXIS"]
