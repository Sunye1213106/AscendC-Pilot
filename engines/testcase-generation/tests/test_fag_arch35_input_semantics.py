from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_fag():
    import sys

    repo = Path(__file__).resolve().parents[3]
    path = (
        repo
        / "tests"
        / "fixtures"
        / "flash_attention_score_grad"
        / "arch35"
        / "input_semantics.py"
    )
    name = "fixture_fag_input_semantics"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fag = _load_fag()


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


def test_split_axis_five_best_effort_even_when_risky() -> None:
    """Constructor must attempt historically reachable / rewrite-risk targets.

    Host oracle — not construct_reasons — decides hit / refuse / rewrite.
    """
    for overrides in (
        {"SplitAxis": "5", "DeterType": "2"},
        {"SplitAxis": "5", "IsNEqual": "1"},
        {"SplitAxis": "5", "IsBn2MultiBlk": "1"},
        {"SplitAxis": "5", "DTemplateNum": "192"},
        {"SplitAxis": "5", "IsDrop": "1"},
    ):
        cases = fag.construct_case(_target(**overrides))
        assert len(cases) >= 1, overrides

    cases = fag.construct_case(_target(SplitAxis="5", DTemplateNum="128"))
    assert len(cases) == 1
    assert cases[0].s1 == 128
    assert cases[0].s2 == 512


def test_float_dtemplate_768_still_attempts_mismatched_s1() -> None:
    # Mismatched S1 may rewrite on host; constructor still spells a case.
    risky = fag.construct_case(
        _target(InputDType="1", OutDType="1", DTemplateNum="768", S1TemplateNum="128")
    )
    assert len(risky) >= 1
    assert fag.construct_reasons(
        _target(InputDType="1", OutDType="1", DTemplateNum="768", S1TemplateNum="128")
    )

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


def test_rope_is_d_no_equal_zero_still_attempted() -> None:
    cases = fag.construct_case(
        _target(IsRope="1", IsDNoEqual="0", DTemplateNum="192")
    )
    assert len(cases) >= 1
    assert cases[0].rope is True
    assert fag.construct_reasons(
        _target(IsRope="1", IsDNoEqual="0", DTemplateNum="192")
    )


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


def test_nz_out_tnd_and_risky_routes_are_attempted() -> None:
    assert len(fag.construct_case(_target(IsNzOut="1", IsTnd="1"))) >= 1
    assert len(fag.construct_case(_target(IsNzOut="1", SplitAxis="5"))) >= 1
    assert len(fag.construct_case(_target(IsNzOut="1", DTemplateNum="64"))) >= 1
    assert len(
        fag.construct_case(_target(IsNzOut="1", DeterType="4", IsAttenMask="1"))
    ) >= 1
    # Drop + SplitAxis=1 was a major false-exclusion cluster vs hist R=4169.
    cases = fag.construct_case(_target(SplitAxis="1", IsDrop="1"))
    assert len(cases) >= 1
    assert cases[0].keep_prob < 1.0


def test_construct_reasons_are_diagnostic_not_gates() -> None:
    t = _target(SplitAxis="5", IsNEqual="1")
    assert fag.construct_reasons(t)
    assert all(r.startswith("hypothesis:") for r in fag.construct_reasons(t))
    assert fag.construct_case(t)


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
