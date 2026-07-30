# -*- coding: utf-8 -*-
"""IsCapable must be decided by interpreting the parsed body, not by class name."""
import pytest

from uo_init.registry_capable import (
    CapablePred,
    EnumVal,
    build_arch35_competition,
    parse_body,
    parse_enums,
)

VARLEN = "FlashAttentionScoreGradTilingVarlenRegbase"
NORMAL = "FlashAttentionScoreGradTilingNormalRegbase"


@pytest.fixture
def comp(fag_dir):
    return build_arch35_competition(
        fag_dir / "op_host", op_name="FlashAttentionScoreGrad"
    )


def test_enum_ordinals_are_parsed():
    enums = parse_enums("enum class E : uint32_t { A = 0, B, C = 7, D };")
    assert enums["E"] == {"A": 0, "B": 1, "C": 7, "D": 8}


def test_enum_value_compares_as_name_and_as_ordinal():
    v = EnumVal("AttrIndex", "TND_SOFTMAX_IN", 12)
    assert v == "TND_SOFTMAX_IN"
    assert 13 > v
    assert v == 12


def test_declarator_name_is_not_truncated():
    stmts = parse_body("auto actualSeqQLenTensor = ctx->Get();")
    assert stmts[0].kind == "decl"
    assert stmts[0].name == "actualSeqQLenTensor"


def test_plain_assignment_is_not_a_declaration():
    stmts = parse_body("x = 1;")
    assert stmts[0].kind == "expr"


def test_roots_come_from_the_body(comp):
    assert set(comp.preds[VARLEN].roots) == {
        "PLATFORM_ARCH",
        "OPTIONAL_INPUT_PRESENCE",
        "INPUT_SHAPE",
    }
    assert set(comp.preds[NORMAL].roots) == {"ATTRIBUTE", "PLATFORM_ARCH"}
    assert not comp.preds[VARLEN].unresolved


def test_varlen_wins_when_actual_seq_present(comp):
    env = {
        "npu_arch": "DAV_3510",
        "actual_seq_qlen_present": True,
        "actual_seq_qlen_size": 3,
        "tnd_softmax_in": "",
    }
    assert comp.choose(env) == VARLEN


def test_normal_wins_without_actual_seq(comp):
    env = {
        "npu_arch": "DAV_3510",
        "actual_seq_qlen_present": False,
        "actual_seq_qlen_size": 0,
        "tnd_softmax_in": "",
    }
    assert comp.choose(env) == NORMAL


def test_empty_actual_seq_tensor_does_not_select_varlen(comp):
    """Presence alone is not enough: the body also requires GetShapeSize() != 0."""
    env = {
        "npu_arch": "DAV_3510",
        "actual_seq_qlen_present": True,
        "actual_seq_qlen_size": 0,
        "tnd_softmax_in": "",
    }
    assert comp.choose(env) == NORMAL


def test_tnd_softmax_attribute_disables_normal(comp):
    env = {
        "npu_arch": "DAV_3510",
        "actual_seq_qlen_present": False,
        "actual_seq_qlen_size": 0,
        "tnd_softmax_in": "TND",
    }
    assert comp.choose(env) is None


def test_wrong_arch_selects_nothing(comp):
    env = {
        "npu_arch": "DAV_2201",
        "actual_seq_qlen_present": True,
        "actual_seq_qlen_size": 5,
        "tnd_softmax_in": "",
    }
    assert comp.choose(env) is None


def test_missing_environment_yields_unknown_not_false(comp):
    """An unbound accessor must be reported, never silently treated as false."""
    verdict = comp.preds[VARLEN].evaluate_env({"npu_arch": "DAV_3510"})
    assert verdict is None
    trace = comp.choose_with_reason({"npu_arch": "DAV_3510"})
    assert trace["chosen"] is None
    assert any(t["reason"] == "UNKNOWN_SYMBOL" for t in trace["trace"])


def test_selection_lineage_negates_higher_priority(comp):
    lineage = comp.selection_lineage(NORMAL)
    assert lineage == f"not capable({VARLEN}) and capable({NORMAL})"


def test_evaluation_is_not_keyed_on_class_name(comp):
    """Renaming the class must not change the verdict."""
    pred = comp.preds[NORMAL]
    clone = CapablePred(
        class_name="SomethingCompletelyDifferent",
        file=pred.file,
        line=pred.line,
        body=pred.body,
        statements=parse_body(pred.body),
        enums=pred.enums,
    )
    env = {"npu_arch": "DAV_3510", "tnd_softmax_in": ""}
    assert clone.evaluate_env(env) == pred.evaluate_env(env) is True
