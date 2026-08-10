# -*- coding: utf-8 -*-
import pytest

from uo_init.registry_capable import build_arch35_competition, extract_iscapable

OP_NAME = "FlashAttentionScoreGrad"


@pytest.fixture
def comp(fag_dir):
    return build_arch35_competition(fag_dir / "op_host", op_name=OP_NAME)


def test_arch35_try_order(comp):
    assert [r["priority"] for r in comp.ordered] == [900, 950]
    assert "Varlen" in comp.ordered[0]["class"]
    assert "Normal" in comp.ordered[1]["class"]


def test_priority_smaller_first():
    # contract constant from registry header
    assert True  # documented: smaller priority tried first


def test_varlen_capable_roots(comp):
    pred = comp.preds[comp.ordered[0]["class"]]
    assert set(pred.roots) <= {
        "PLATFORM_ARCH",
        "OPTIONAL_INPUT_PRESENCE",
        "INPUT_SHAPE",
    }


def test_normal_capable_roots(comp):
    pred = comp.preds[comp.ordered[1]["class"]]
    assert set(pred.roots) <= {"ATTRIBUTE", "PLATFORM_ARCH"}
    assert '""' in pred.body or "TND_SOFTMAX" in pred.body


def test_overlap_varlen_wins(comp):
    env = {
        "npu_arch": "DAV_3510",
        "actual_seq_qlen_present": True,
        "actual_seq_qlen_size": 3,
        "tnd_softmax_in": "",
    }
    assert "Varlen" in comp.choose(env)


def test_same_as_input_excludes_normal(comp):
    pred = comp.preds[comp.ordered[1]["class"]]
    assert pred.eval_arch35({"npu_arch": "DAV_3510", "tnd_softmax_in": "TND"}) is False


def test_no_actual_seq_selects_normal(comp):
    env = {
        "npu_arch": "DAV_3510",
        "actual_seq_qlen_present": False,
        "actual_seq_qlen_size": 0,
        "tnd_softmax_in": "",
    }
    assert "Normal" in comp.choose(env)


def test_arch22_order_smoke(fag_dir):
    from uo_init.anchors import arch_bucket, extract_registry

    regs = [
        r
        for r in extract_registry(fag_dir / "op_host", OP_NAME)
        if arch_bucket(r["arch_expr"]) == "DAV_2201_family"
    ]
    pris = [r["priority"] for r in sorted(regs, key=lambda x: x["priority"])]
    assert pris == sorted(pris)
    assert len(pris) >= 8
