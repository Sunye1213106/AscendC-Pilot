# -*- coding: utf-8 -*-
"""The contract gate, and the drifts it was built to catch.

Each drift here is one that was actually there. Keeping them as tests is the
point: the gate passing today says nothing unless it would still fail on the
thing it once let through.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from replay import bridge as B
from replay import contract_audit as CA
from replay import inputs as I
from replay import surfaces as S
from replay.adapter import ADAPTER
from replay.materialized import default_spec


@pytest.fixture(scope="module")
def fag():
    return S.fag()


def line_of(case, fag, case_id="t"):
    return CA.parse_line(I.to_csv_line(case, case_id), fag)


# --- the line, read back -----------------------------------------------


def test_a_default_case_survives_being_parsed_back(fag):
    host = line_of(I.Case(), fag)

    assert host.case_id == "t"
    assert host.in_shapes["query"] == [1, 128, 1, 128]
    assert host.present("query")
    assert not host.present("atten_mask")
    assert host.attrs["input_layout"] == "BSND"


def test_a_value_tensor_parses_into_its_contents(fag):
    case = I.Case(layout="TND", seq_q=[128, 256], seq_kv=[128, 256])
    host = line_of(case, fag)

    assert host.in_values["actual_seq_qlen"] == [128, 256]
    # The extent is the number of entries, not their sum.
    assert host.in_shapes["actual_seq_qlen"] == [2]


def test_a_line_with_the_wrong_number_of_sections_is_refused(fag):
    with pytest.raises(ValueError, match="7 sections"):
        CA.parse_line("a;b;c", fag)


def test_a_line_with_the_wrong_number_of_tensors_is_refused(fag):
    good = I.to_csv_line(I.Case(), "t").split(";")
    good[1] = "1|2,3|4"
    with pytest.raises(ValueError, match="input shapes"):
        CA.parse_line(";".join(good), fag)


def test_a_value_field_whose_count_disagrees_is_refused(fag):
    good = I.to_csv_line(I.Case(layout="TND"), "t").split(";")
    good[1] = good[1].replace("1@128", "9@128")
    with pytest.raises(ValueError, match="count"):
        CA.parse_line(";".join(good), fag)


# --- the drifts that were there ----------------------------------------


def _tensor(case, name):
    for t in ADAPTER.materialize(case, "x").inputs:
        if t.name == name:
            return t
    raise AssertionError(f"{name} is not in the expansion")


def test_the_slope_pse_has_one_dtype_on_both_sides(fag):
    """The line forced FLOAT and the environment kept query's dtype.

    Both readings now come off one expansion, so there is only one dtype to
    have. Nothing consults this tensor's type statically -- the derivation
    reads query's and no other -- which is why the check is against the line.
    """
    case = I.Case(dtype="FLOAT16", pse=True, pse_shape="slope")

    host = line_of(case, fag)

    assert host.in_dtypes["pse_shift"] == I.DT["FLOAT"]
    assert _tensor(case, "pse_shift").dtype == I.DT["FLOAT"]
    assert CA.audit(case, "slope", fag) == []


def test_a_normal_pse_still_follows_the_main_dtype(fag):
    case = I.Case(dtype="BF16", pse=True, pse_shape="bnss")

    assert _tensor(case, "pse_shift").dtype == I.DT["BF16"]
    assert line_of(case, fag).in_dtypes["pse_shift"] == I.DT["BF16"]


def test_the_sequence_tensors_are_present_in_the_environment(fag):
    """`_shapes` skipped them, so every exit downstream called them absent."""
    case = I.Case(layout="TND", seq_q=[128, 256], seq_kv=[128, 256])
    env = B.env_of(case)

    # Its extent is how many batches there are, not how long they are.
    assert env["VAR_SHAPE_ACTUAL_SEQ_Q_LEN"] == 2
    assert env["VAR_VALUE_ACTUAL_SEQ_Q_LEN"] == [128, 256]
    # The last entry of a prefix sum is the total, which tiling reads directly.
    assert env["VAR_ELEM_ELEM_ACTUAL_SEQ_Q_LEN"] == 256
    assert env["VAR_REDUCE_MAX_ACTUAL_SEQ_Q_LEN"] == 256


def test_an_absent_sequence_tensor_reads_as_absent(fag):
    env = B.env_of(I.Case(layout="BSND"))

    assert env["VAR_SHAPE_ACTUAL_SEQ_Q_LEN"] is None
    assert env["VAR_VALUE_ACTUAL_SEQ_Q_LEN"] is None
    assert env["VAR_ELEM_ELEM_ACTUAL_SEQ_Q_LEN"] is None


def test_the_prefix_tensor_is_read_by_value_too(fag):
    """The line carries its contents, and no variable holds them.

    The tiling reads a prefix out of its own state rather than off the
    tensor, so the spec binds nothing here. The value still has to reach the
    host, which is what this checks.
    """
    case = I.Case(b=3, sparse_mode=5, prefix_n=[7, 11, 13])

    assert _tensor(case, "prefix").values == (7, 11, 13)
    assert line_of(case, fag).in_values["prefix"] == [7, 11, 13]
    assert "prefix" not in default_spec().tensors()


def test_inner_precise_survives_the_report(fag):
    """The row had no column for it, so a rebuilt case always ran with 0."""
    case = I.Case(inner_precise=1)
    back = S._rebuild(I.describe(case))

    assert back.inner_precise == 1
    assert CA.audit(case, "inner", fag) == []


def test_a_named_prefix_survives_the_report(fag):
    case = I.Case(b=3, sparse_mode=5, prefix_n=[7, 11, 13])
    back = S._rebuild(I.describe(case))

    assert back.normalised().prefix_n == [7, 11, 13]


def test_the_scale_factor_compares_as_a_number(fag):
    """The line rounds it to eight decimals; the environment does not."""
    case = I.Case(d=128)

    assert CA.audit_serialisation(case, "scale", fag) == []
    assert not CA._same_number(0.5, "0.6", 1e-7)


# --- the gate itself still bites ----------------------------------------


def test_a_dtype_that_disagrees_is_reported(fag):
    bad = replace(fag, static_env=lambda c: {
        **B.env_of(c), "VAR_DTYPE_QUERY": 99})

    kinds = {v.kind for v in CA.audit(I.Case(), "x", bad)}
    assert CA.DTYPE_MISMATCH in kinds


def test_a_presence_that_disagrees_is_reported(fag):
    bad = replace(fag, static_env=lambda c: {
        **B.env_of(c), "VAR_OPT_ATTEN_MASK": False})

    violations = CA.audit(I.Case(atten_mask="bnss"), "x", bad)
    assert any(v.kind == CA.PRESENCE_MISMATCH and v.where == "atten_mask"
               for v in violations)


def test_a_shape_that_disagrees_is_reported(fag):
    bad = replace(fag, static_env=lambda c: {
        **B.env_of(c), "VAR_SHAPE_QUERY_D0": 77})

    assert any(v.kind == CA.SHAPE_MISMATCH
               for v in CA.audit(I.Case(), "x", bad))


def test_an_attr_the_spec_binds_and_the_host_never_hears_is_reported(fag):
    """The spec claiming an attr the line does not carry is a real break.

    It is the direction that can actually go wrong now: the spec is exported
    from the derivation and the line comes from the generator, so the two can
    disagree about the operator's signature. The other direction -- an attr
    the host is told and nothing reads -- is what the export found, not a
    fault to report.
    """
    from replay import bridge_spec as BS

    spec = default_spec()
    invented = BS.Binding(var="VAR_ATTR_NOT_A_REAL_ATTR", root="ATTRIBUTE",
                          kind=BS.ATTR, operand="not_a_real_attr")
    bad = replace(
        fag,
        spec=replace(spec, bindings=spec.bindings + (invented,)),
        static_env=lambda c: {**B.env_of(c), "VAR_ATTR_NOT_A_REAL_ATTR": 1})

    violations = CA.audit(I.Case(), "x", bad)
    assert any(v.kind == CA.ATTR_MISMATCH and v.where == "not_a_real_attr"
               for v in violations)


def test_a_field_lost_in_the_round_trip_is_reported(fag):
    """Rebuild that drops a field the line carries, as `describe` once did."""
    def forgetful(row):
        return replace(S._rebuild(row), inner_precise=0)

    bad = replace(fag, rebuild=forgetful)
    violations = CA.audit_roundtrip(I.Case(inner_precise=1), "x", bad)

    assert any(v.kind == CA.REPORT_LOSSY and v.where == "inner_precise"
               for v in violations)


def test_a_value_outside_a_closed_set_is_reported(fag):
    case = I.Case(pse=True, pse_shape="slope_bn")

    violations = CA.audit_enums(case, "x", fag)
    assert [v.kind for v in violations] == [CA.ENUM_OUT_OF_RANGE]
    assert "slope_bn" in violations[0].detail


def test_a_closed_set_is_not_checked_when_its_guard_is_off(fag):
    """Without a pse there is no pse shape to be wrong about."""
    assert CA.audit_enums(I.Case(pse=False, pse_shape=""), "x", fag) == []


def test_a_mask_outside_the_closed_set_is_reported(fag):
    violations = CA.audit_enums(I.Case(atten_mask="bss"), "x", fag)

    assert [v.kind for v in violations] == [CA.ENUM_OUT_OF_RANGE]


def test_the_generator_refuses_a_mask_it_cannot_build():
    with pytest.raises(ValueError, match="not a mask shape"):
        I.to_csv_line(I.Case(atten_mask="bss"), "x")


def test_the_generator_refuses_a_pse_shape_it_cannot_build():
    with pytest.raises(ValueError, match="not a pse shape"):
        I.to_csv_line(I.Case(pse=True, pse_shape="slope_bn"), "x")


def test_a_refusal_is_reported_rather_than_raised(fag):
    """The gate surveys a batch, so one bad case must not end the survey."""
    bad = replace(fag, enums={})

    violations = CA.audit(I.Case(atten_mask="bss"), "x", bad)
    assert [v.kind for v in violations] == [CA.GENERATOR_REFUSED]


def test_the_search_only_asks_for_shapes_the_generator_has():
    """The probe lists once said "full", "slope_bn", "bss", "1sss"."""
    import replay_nudge

    for dim in ("IsPse", "IsAttenMask"):
        for want in ("0", "1"):
            for case in replay_nudge._variants(I.Case(), dim, want):
                assert case.atten_mask in I.ATTEN_MASKS
                assert not case.pse or case.pse_shape in I.PSE_SHAPES


# --- the closed sets are the ones the shape tables use ------------------


def test_the_declared_masks_are_the_ones_shapes_builds():
    """Two lists of names drift silently; a test is what couples them."""
    built = set()
    for name in I.ATTEN_MASKS:
        ins, _ = I._shapes(I.Case(atten_mask=name).normalised())
        if "atten_mask" in ins:
            built.add(name)

    assert built == set(I.ATTEN_MASKS) - {"none"}


def test_the_declared_pse_shapes_all_build_something_distinct():
    shapes = {}
    for name in I.PSE_SHAPES:
        # b > 1, or the batched and unbatched shapes coincide and the test
        # cannot tell a real name from one that fell through.
        case = I.Case(b=2, pse=True, pse_shape=name).normalised()
        shapes[name] = I._shapes(case)[0]["pse_shift"]

    # A name that reached the fallback would be indistinguishable from bnss.
    fallbacks = [n for n, s in shapes.items()
                 if n != "bnss" and s == shapes["bnss"]]
    assert fallbacks == []


# --- the whole surface, over cases that walk every field ----------------
# synthetic_cases lived in deleted scripts/_probe_contract_audit.py;
# contract_audit unit coverage above is the remaining surface.
