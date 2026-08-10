# -*- coding: utf-8 -*-
"""One expansion, four exits.

The point of these is not that the exits agree -- they read the same tuple,
so they cannot do otherwise. It is that the expansion says the right thing in
the first place, and that the two readings which genuinely differ (a dtype on
an absent tensor, a scale factor's decimals) differ deliberately.
"""

from __future__ import annotations

import pytest

from replay import inputs as I
from replay import materialized as M
from replay.adapter import ADAPTER
from replay.materialized import default_spec
from replay.package_data import active_package_dir, repo_root


def expand(case: I.Case, cid: str = "c0") -> M.MaterializedCase:
    return ADAPTER.materialize(case, cid)


@pytest.fixture
def bridge_spec_required():
    """Env binding tests need exported bridge_spec (adapter pack)."""
    if not (active_package_dir(repo_root()) / "bridge_spec.yaml").is_file():
        pytest.skip(
            "bridge_spec.yaml missing (FAG priors purged; run export_adapter_pack)"
        )


def tensor_of(m: M.MaterializedCase, name: str) -> M.MaterializedTensor:
    for t in (*m.inputs, *m.outputs):
        if t.name == name:
            return t
    raise AssertionError(f"{name} is not in the expansion")


# --- the pieces ---------------------------------------------------------


def test_an_absent_tensor_has_no_element_count():
    """Zero and absent are different: guards test the pointer first."""
    absent = M.MaterializedTensor(name="t", present=False)

    assert absent.elements is None


def test_an_empty_tensor_that_is_there_counts_zero():
    there = M.MaterializedTensor(name="t", present=True, dims=(0, 4))

    assert there.elements == 0


def test_a_value_tensor_writes_its_contents_not_its_extent():
    t = M.MaterializedTensor(name="t", present=True, dims=(3,),
                             values=(10, 20, 30))

    assert t.csv_field() == "3@10/20/30"


def test_a_plain_tensor_writes_its_extent():
    t = M.MaterializedTensor(name="t", present=True, dims=(2, 3))

    assert t.csv_field() == "2|3"


# --- the two readings of a dtype ----------------------------------------


def test_the_line_is_told_a_dtype_even_for_an_absent_tensor():
    """A slot's type belongs to the signature, not to this case."""
    m = expand(I.Case(atten_mask="none"))

    assert not tensor_of(m, "atten_mask").present
    assert tensor_of(m, "atten_mask").dtype == I.DT["UINT8"]
    assert ";" in m.serialize_for_host()


def test_the_derivation_is_not_told_the_shape_of_a_tensor_that_is_absent(
        bridge_spec_required):
    """Measuring an optional nobody passed is measuring nothing.

    None rather than zero: the host tests the pointer before the extent, so
    an absent tensor reported as rank 0 would take the branch meant for a
    tensor that is there and empty.
    """
    env = expand(I.Case(atten_mask="none")).build_static_env()

    assert env["VAR_OPT_ATTEN_MASK"] is False
    assert env["VAR_RANK_ATTEN_MASK"] is None


def test_a_present_tensor_reaches_the_derivation_with_its_shape(
        bridge_spec_required):
    env = expand(I.Case(atten_mask="bnss")).build_static_env()

    assert env["VAR_OPT_ATTEN_MASK"] is True
    assert env["VAR_RANK_ATTEN_MASK"] == 4


def test_only_the_dtype_the_derivation_reads_is_supplied(bridge_spec_required):
    """The spec supplies what is read, which is one dtype and not twenty-two.

    Every tensor used to get one whether anything consulted it or not. The
    surplus was harmless to the solver and misleading to a reader: it looked
    like the derivation cared about all of them.
    """
    case = I.Case(atten_mask="bnss")
    env = expand(case).build_static_env()

    assert env["VAR_DTYPE_QUERY"] == I.DT[case.dtype]
    assert not [k for k in env if k.startswith("VAR_DTYPE_") and k != "VAR_DTYPE_QUERY"]


# --- the two readings of a number ---------------------------------------


def test_the_scale_factor_is_rounded_for_the_line_and_kept_exact_beside_it():
    """Two readings of one number, stored once.

    Nothing consults the exact one today -- the derivation does not read this
    attr -- and the rounding still cannot be allowed to become the value.
    Storing the rendering separately is what keeps that true for whichever
    operator does read it.
    """
    m = expand(I.Case(d=128))
    scale = next(a for a in m.attrs if a.name == "scale_value")

    assert scale.rendered == f"{1.0 / 128 ** 0.5:.8f}"
    assert scale.value == 1.0 / 128 ** 0.5
    assert scale.rendered != str(scale.value)


def test_an_attribute_with_no_rendering_is_spelled_with_str():
    attr = M.MaterializedAttr(name="a", kind="i", value=7)

    assert attr.rendered == "7"


# --- values the host reads rather than measures --------------------------


def test_a_sequence_tensor_carries_its_contents_into_the_environment(
        bridge_spec_required):
    env = expand(I.Case(layout="TND", seq_q=[128, 256], seq_kv=[128, 256])) \
        .build_static_env()

    assert env["VAR_VALUE_ACTUAL_SEQ_Q_LEN"] == [128, 256]
    # The last entry of a prefix sum is the total, which tiling reads as T.
    assert env["VAR_ELEM_ELEM_ACTUAL_SEQ_Q_LEN"] == 256
    assert env["VAR_REDUCE_MAX_ACTUAL_SEQ_Q_LEN"] == 256
    # Its extent is how many batches there are, not how long they are.
    assert env["VAR_SHAPE_ACTUAL_SEQ_Q_LEN"] == 2


def test_a_sequence_tensor_nobody_passed_is_absent_everywhere(
        bridge_spec_required):
    """Absent, but still asked about: the variable is there, bound to None."""
    env = expand(I.Case(layout="BSND")).build_static_env()

    assert env["VAR_VALUE_ACTUAL_SEQ_Q_LEN"] is None
    assert env["VAR_SHAPE_ACTUAL_SEQ_Q_LEN"] is None
    assert env["VAR_ELEM_ELEM_ACTUAL_SEQ_Q_LEN"] is None
    assert "VAR_VALUE_ACTUAL_SEQ_Q_LEN" in env


def test_the_environment_asks_about_the_same_variables_for_every_case(
        bridge_spec_required):
    """A key that appears only for some cases is a key the evaluator cannot
    tell from one that was never modelled. Which variables exist is a
    property of the operator; only their values vary."""
    from replay import search as S

    cases = [I.Case(), I.Case(layout="TND", seq_q=[128], seq_kv=[128]),
             I.Case(rope=True), I.Case(pse=True, pse_shape="slope"),
             I.Case(sparse_mode=5, prefix_n=[7], b=1),
             *list(S.tnd_seeds().values())[:5]]
    keys = {frozenset(expand(c).build_static_env()) for c in cases}

    assert len(keys) == 1, "the variable set moves with the case"


def test_the_context_reaches_the_environment(bridge_spec_required):
    """The session's flag comes from the case; the architecture does not.

    There is one spec per architecture, so the spec carries it and the
    expansion no longer asserts it a second time.
    """
    env = expand(I.Case(deterministic=1)).build_static_env()

    assert env["VAR_SESSION_DETERMINISTIC"] is True
    assert env["VAR_PLATFORM_ARCH"] == 35


# --- what the audit can still find ---------------------------------------


def test_a_well_formed_case_contradicts_nothing():
    assert expand(I.Case()).validate_contract() == []


def test_a_tensor_present_with_no_shape_is_reported():
    m = M.MaterializedCase(
        case_id="c",
        inputs=(M.MaterializedTensor(name="q", present=True),))

    assert "present with no shape" in m.validate_contract()[0]


def test_an_absent_tensor_carrying_a_shape_is_reported():
    m = M.MaterializedCase(
        case_id="c",
        inputs=(M.MaterializedTensor(name="q", present=False, dims=(2, 2)),))

    assert "absent but carries a shape" in m.validate_contract()[0]


def test_a_negative_extent_is_reported():
    """A negative batch length reached six tensors before this existed."""
    m = M.MaterializedCase(
        case_id="c",
        inputs=(M.MaterializedTensor(name="q", present=True, dims=(-192, 2)),))

    assert "negative extent" in m.validate_contract()[0]


def test_a_value_tensor_whose_extent_disagrees_with_its_contents():
    m = M.MaterializedCase(
        case_id="c",
        inputs=(M.MaterializedTensor(name="s", present=True, dims=(9,),
                                     values=(1, 2)),))

    assert "extent should be (2,)" in m.validate_contract()[0]


def test_an_attribute_kind_the_driver_cannot_read_is_reported():
    m = M.MaterializedCase(
        case_id="c",
        attrs=(M.MaterializedAttr(name="a", kind="q", value=1),))

    assert "is not one the driver reads" in m.validate_contract()[0]


def test_a_duplicated_attribute_is_reported():
    m = M.MaterializedCase(
        case_id="c",
        attrs=(M.MaterializedAttr(name="a", kind="i", value=1),
               M.MaterializedAttr(name="a", kind="i", value=2)))

    assert "given more than once" in m.validate_contract()[0]


def test_a_value_outside_a_closed_set_is_reported():
    m = expand(I.Case())
    problems = m.validate_contract(enums={"layout": ("TND",)}, case=I.Case())

    assert "is not one of ('TND',)" in problems[0]


# --- the adapter ---------------------------------------------------------


def test_the_adapter_satisfies_the_protocol():
    assert isinstance(ADAPTER, M.OperatorInputAdapter)


def test_every_declared_input_appears_in_the_expansion():
    m = expand(I.Case())

    assert [t.name for t in m.inputs] == list(I.IN_ORDER)
    assert [t.name for t in m.outputs] == list(I.OUT_ORDER)


def test_a_tensor_no_variable_models_reaches_the_line_but_not_the_environment(
        bridge_spec_required):
    """The host is handed it and the derivation never asks about it.

    That is now a finding rather than an omission: the spec was exported from
    what the derivation reads, so a tensor missing from it is one nothing
    consults. It still has to reach the line, because the host counts slots.
    """
    m = expand(I.Case())
    env = m.build_static_env()

    assert tensor_of(m, "q_start_idx") is not None
    assert not any(k.endswith("Q_START_IDX") for k in env)
    assert "q_start_idx" not in default_spec().tensors()


def test_the_report_survives_the_expansion():
    case = I.Case(inner_precise=1, prefix_n=[7], sparse_mode=5, b=1)

    assert expand(case).report_inputs() == I.describe(case.normalised())


@pytest.mark.parametrize("layout", list(I.LAYOUTS))
def test_every_layout_expands_to_something_self_consistent(layout: str):
    case = I.Case(layout=layout,
                  seq_q=[128, 256] if layout == "TND" else None,
                  seq_kv=[128, 256] if layout == "TND" else None)

    assert expand(case).validate_contract() == []


def test_the_generators_produce_nothing_the_host_would_refuse_on_shape():
    """The ragged-length helper used to take short cases below zero."""
    from replay import search as S

    for pool in (S.seeds(), S.targeted_seeds(), S.tnd_seeds()):
        for cid, case in pool.items():
            assert expand(case, cid).validate_contract() == [], cid
