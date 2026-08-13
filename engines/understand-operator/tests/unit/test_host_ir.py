# -*- coding: utf-8 -*-
from uo_init.host_ir import assert_no_flatten, build_host_ir, extract_writes_text


def test_write_path_isNzOut(fag_dir):
    p = (
        fag_dir
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_normal_regbase.cpp"
    )
    writes = extract_writes_text(p, template_precondition="Normal")
    paths = [w.path for w in writes]
    assert any("isNzOut" in p for p in paths)


def test_no_field_flatten(fag_dir):
    p = (
        fag_dir
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_normal_regbase.cpp"
    )
    writes = extract_writes_text(p)
    assert_no_flatten(writes)
    assert any("." in w.path for w in writes if "isNzOut" in w.path)


def test_summary_process_optional_input(fag_dir):
    ir = build_host_ir(
        [
            fag_dir
            / "op_host"
            / "arch35"
            / "flash_attention_score_grad_tiling_common_regbase.cpp"
        ]
    )
    assert "ProcessOptionalInput" in ir.summaries
    assert any(w.startswith("fBaseParams") for w in ir.summaries["ProcessOptionalInput"].writes)
    rec = ir.summaries["ProcessOptionalInput"]
    assert rec.file
    assert int(rec.line or 0) > 0


def test_selection_precondition_threaded(fag_dir):
    p = (
        fag_dir
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_normal_regbase.cpp"
    )
    writes = extract_writes_text(p, template_precondition="Normal")
    assert all(w.template_precondition == "Normal" for w in writes)
