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


def test_param_bindings_fibonacci_callers_finish_quickly():
    """Same-named formals through a DAG of callers must not re-expand exponentially."""
    import time

    from uo_init.host_ir import FuncSummary, HostIR

    summaries = {
        "f0": FuncSummary(name="f0", params=["x"], locals={"y": "1"}),
        "f1": FuncSummary(name="f1", params=["x"], locals={"y": "1"}),
    }
    for i in range(2, 36):
        summaries[f"f{i}"] = FuncSummary(
            name=f"f{i}",
            params=["x"],
            calls=[(f"f{i - 1}", ("x",)), (f"f{i - 2}", ("x",))],
        )
    ir = HostIR(summaries=summaries)
    t0 = time.perf_counter()
    got = ir.param_bindings()
    assert time.perf_counter() - t0 < 1.0
    assert "f0" in got
    assert "f1" in got
