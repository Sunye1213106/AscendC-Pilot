from __future__ import annotations

from operators.flash_attention_score_grad.arch35 import input_semantics as fag


def _target(**overrides: str) -> dict[str, str]:
    base = {
        "IsEmptyTensor": "0",
        "SplitAxis": "0",
        "InputDType": "3",
        "IsTnd": "0",
        "IsDrop": "0",
        "IsPse": "0",
        "IsAttenMask": "0",
        "S1TemplateNum": "128",
        "S2TemplateNum": "128",
        "DTemplateNum": "128",
        "DeterType": "0",
        "IsNEqual": "0",
        "IsBn2MultiBlk": "0",
        "IsDNoEqual": "0",
        "IsRope": "0",
        "OutDType": "3",
        "IsNzOut": "0",
        "IsTndSwizzle": "0",
        "IsRegbase": "1",
    }
    base.update({k: str(v) for k, v in overrides.items()})
    return base


def test_bn2_multiblock_uses_source_bounded_sequence() -> None:
    cases = fag.construct_case(
        _target(SplitAxis="1", IsBn2MultiBlk="1", DTemplateNum="768")
    )

    assert len(cases) == 1
    assert cases[0].layout == "BSND"
    assert cases[0].s1 == 640
    assert cases[0].s2 == 640
    assert cases[0].d == 512


def test_is_nz_out_preserves_deterministic_sparse_route() -> None:
    cases = fag.construct_case(
        _target(
            IsAttenMask="1",
            IsNzOut="1",
            DeterType="2",
            IsNEqual="1",
        )
    )

    assert len(cases) == 1
    assert cases[0].deterministic == 1
    assert cases[0].sparse_mode == 0
    assert cases[0].atten_mask == "bnss"
    assert cases[0].d == 72
    assert cases[0].g == 1


def test_split_axis_five_only_constructs_no_deter_source_route() -> None:
    assert fag.construct_case(_target(SplitAxis="5", DeterType="2")) == []
    assert fag.construct_case(_target(SplitAxis="5", IsNEqual="1")) == []
    assert fag.construct_case(_target(SplitAxis="5", IsBn2MultiBlk="1")) == []
    assert fag.construct_case(_target(SplitAxis="5", DTemplateNum="192")) == []

    cases = fag.construct_case(_target(SplitAxis="5", DTemplateNum="128"))
    assert len(cases) == 1
    assert cases[0].s1 == 128
    assert cases[0].s2 == 512


def test_float_dtemplate_768_requires_s1_template_64() -> None:
    assert fag.construct_case(
        _target(InputDType="1", OutDType="1", DTemplateNum="768", S1TemplateNum="128")
    ) == []

    cases = fag.construct_case(
        _target(InputDType="1", OutDType="1", DTemplateNum="768", S1TemplateNum="64")
    )

    assert len(cases) == 1
    assert cases[0].dtype == "FLOAT"
    assert cases[0].d == 512


def test_tnd_constructor_avoids_all_same_rewrite_at_s1_128() -> None:
    cases = fag.construct_case(_target(IsTnd="1", SplitAxis="1", DTemplateNum="128"))

    assert len(cases) == 1
    record = fag.describe(cases[0])
    assert record["layout"] == "TND"
    assert record["s1"] == 128
    assert record["seq_q"] == "128/192"
    assert record["all_same"] == 0


def test_deterministic_n_equal_false_keeps_gqa() -> None:
    cases = fag.construct_case(_target(DeterType="2", IsNEqual="0"))

    assert len(cases) == 1
    assert cases[0].deterministic == 1
    assert cases[0].g == 2


def test_rope_always_sets_d_no_equal_in_tiling_key() -> None:
    assert fag.construct_case(
        _target(IsRope="1", IsDNoEqual="0", DTemplateNum="192")
    ) == []


def test_empty_tensor_key_has_a_direct_witness() -> None:
    cases = fag.construct_case(
        _target(
            IsEmptyTensor="1",
            InputDType="0",
            S1TemplateNum="0",
            S2TemplateNum="0",
            DTemplateNum="0",
            OutDType="0",
        )
    )

    assert len(cases) == 1
    assert cases[0].s1 == 0
    assert cases[0].tag == "construct_case_empty"


def test_nz_out_source_route_guards() -> None:
    assert fag.construct_case(_target(IsNzOut="1", IsTnd="1")) == []
    assert fag.construct_case(_target(IsNzOut="1", SplitAxis="5")) == []
    assert fag.construct_case(_target(IsNzOut="1", DTemplateNum="64")) == []
    assert fag.construct_case(_target(IsNzOut="1", DeterType="4", IsAttenMask="1")) == []


def test_normalise_repairs_blank_pse_shape_after_mutation() -> None:
    dense = fag.Case(layout="BSND", pse=True, pse_shape="").normalised()
    assert dense.pse_shape == "bnss"
    fag.shapes(dense)

    tnd = fag.Case(
        layout="TND",
        pse=True,
        pse_shape="",
        seq_q=[1024, 1152],
        seq_kv=[1024, 1152],
    ).normalised()
    assert tnd.pse_shape == "slope"
    assert tnd.pse_type == 2
    fag.shapes(tnd)
