# -*- coding: utf-8 -*-
import pytest

from uo_init.anchors import (
    ValidationError,
    Anchor,
    Evidence,
    arch_bucket,
    build_anchors_yaml,
    extract_kernel_entry,
    extract_opdef,
    extract_registry,
)


def test_opdef_unique_counts(fag_dir):
    r = extract_opdef(fag_dir / "op_host" / "flash_attention_score_grad_def.cpp")
    assert len(r["inputs_unique"]) == 27
    assert len(r["outputs_unique"]) == 7
    assert len(r["attrs_unique"]) == 13


def test_opdef_per_soc_kept(fag_dir):
    r = extract_opdef(fag_dir / "op_host" / "flash_attention_score_grad_def.cpp")
    assert r["inputs_raw_count"] == 54
    assert r["outputs_raw_count"] == 14


def test_anchor_requires_evidence():
    with pytest.raises(ValidationError):
        Anchor(role="x", symbol="y", evidence=Evidence(file="", line=0, snippet="")).validate()


OP_NAME = "FlashAttentionScoreGrad"


def test_registry_priority_order(fag_dir):
    regs = extract_registry(fag_dir / "op_host", OP_NAME)
    a35 = sorted(
        [r for r in regs if arch_bucket(r["arch_expr"]) == "DAV_3510"],
        key=lambda r: r["priority"],
    )
    assert len(a35) == 2
    assert "Varlen" in a35[0]["class"] and a35[0]["priority"] == 900
    assert "Normal" in a35[1]["class"] and a35[1]["priority"] == 950


def test_kernel_entry_nttp_arity(fag_dir):
    e = extract_kernel_entry(fag_dir / "op_kernel" / "flash_attention_score_grad_apt.cpp")
    assert e["nttp_arity"] == 19


def test_build_anchors_yaml(fag_dir):
    y = build_anchors_yaml(
        fag_dir / "op_host" / "flash_attention_score_grad_def.cpp",
        fag_dir / "op_host",
        fag_dir / "op_kernel" / "flash_attention_score_grad_apt.cpp",
        op_name=OP_NAME,
    )
    assert len(y["opdef"]["inputs"]) == 27
