# -*- coding: utf-8 -*-
"""bisheng_prelude.h must declare kernel builtins that block generalize probes."""
from __future__ import annotations

from pathlib import Path

PRELUDE = (
    Path(__file__).resolve().parents[2] / "spec" / "compat" / "bisheng_prelude.h"
)


def test_prelude_declares_packed_s4_vector_and_round():
    text = PRELUDE.read_text(encoding="utf-8")
    assert "struct vector_s4x2" in text
    assert "struct vector_u4x2" in text
    assert "enum class ROUND" in text
    assert "{ R, A, F, C, Z, O, H }" in text or "R, A, F, C, Z, O, H" in text
    assert "namespace cce" in text
    assert "using Dim3 = cce::dim3" in text
    assert "struct half2" in text
    assert "#define __callee__" in text
    assert "#define __simt_vf__" in text
    assert "#define LAUNCH_BOUND(...)" in text
    assert "struct RegTensor" not in text
    assert "struct SoftMaxTiling" not in text
    assert "struct TCubeTiling" not in text
    assert "QF322F32_PRE" in text
    assert "REQ8" in text
    assert "VREQ8" in text


def test_prelude_parses_vector_s4x2_and_round_snippet(tmp_path: Path):
    from clang import cindex

    src = tmp_path / "probe.cpp"
    src.write_text(
        "vector_s4x2 lanes;\n"
        "ROUND mode = ROUND::R;\n",
        encoding="utf-8",
    )
    tu = cindex.Index.create().parse(
        str(src),
        args=["-std=c++17", "-fsyntax-only", "-include", str(PRELUDE)],
    )
    op_errs = [
        d
        for d in tu.diagnostics
        if int(d.severity) >= 3
        and d.location.file is not None
        and Path(d.location.file.name).name == "probe.cpp"
    ]
    assert not op_errs, [d.spelling for d in op_errs]


def test_prelude_parses_dim3_and_half2_snippet(tmp_path: Path):
    from clang import cindex

    src = tmp_path / "probe.cpp"
    src.write_text(
        "Dim3 grid;\n"
        "cce::dim3 block;\n"
        "half2 lanes;\n",
        encoding="utf-8",
    )
    tu = cindex.Index.create().parse(
        str(src),
        args=["-std=c++17", "-fsyntax-only", "-include", str(PRELUDE)],
    )
    op_errs = [
        d
        for d in tu.diagnostics
        if int(d.severity) >= 3
        and d.location.file is not None
        and Path(d.location.file.name).name == "probe.cpp"
    ]
    assert not op_errs, [d.spelling for d in op_errs]


def test_prelude_half_converts_from_float(tmp_path: Path):
    from clang import cindex

    src = tmp_path / "probe.cpp"
    src.write_text(
        "const half x = 0.0f;\n"
        "static constexpr half MIN_VALUE = -65504.0f;\n",
        encoding="utf-8",
    )
    tu = cindex.Index.create().parse(
        str(src),
        args=["-std=c++17", "-fsyntax-only", "-include", str(PRELUDE)],
    )
    op_errs = [
        d
        for d in tu.diagnostics
        if int(d.severity) >= 3
        and d.location.file is not None
        and Path(d.location.file.name).name == "probe.cpp"
    ]
    assert not op_errs, [d.spelling for d in op_errs]


def test_prelude_parses_quant_mode_l0c_members(tmp_path: Path):
    from clang import cindex

    src = tmp_path / "probe.cpp"
    src.write_text(
        "static constexpr auto a = QuantMode_t::QF322F32_PRE;\n"
        "static constexpr auto b = QuantMode_t::REQ8;\n"
        "static constexpr auto c = QuantMode_t::VREQ8;\n",
        encoding="utf-8",
    )
    tu = cindex.Index.create().parse(
        str(src),
        args=["-std=c++17", "-fsyntax-only", "-include", str(PRELUDE)],
    )
    op_errs = [
        d
        for d in tu.diagnostics
        if int(d.severity) >= 3
        and d.location.file is not None
        and Path(d.location.file.name).name == "probe.cpp"
    ]
    assert not op_errs, [d.spelling for d in op_errs]


def test_rewritten_host_device_template_parses(tmp_path: Path):
    from clang import cindex

    from uo_init.bisheng_attrs import strip_bisheng_bracket_attrs

    raw = (
        "#define HOST_DEVICE __forceinline__ [host, aicore]\n"
        "template <class T, class U>\n"
        "HOST_DEVICE constexpr T add(T a, U b) { return a; }\n"
        "int use(int x) { return add(x, 1); }\n"
    )
    src = tmp_path / "probe.cpp"
    src.write_text(strip_bisheng_bracket_attrs(raw), encoding="utf-8")
    tu = cindex.Index.create().parse(
        str(src),
        args=["-std=c++17", "-fsyntax-only", "-include", str(PRELUDE)],
    )
    op_errs = [
        d
        for d in tu.diagnostics
        if int(d.severity) >= 3
        and d.location.file is not None
        and Path(d.location.file.name).name == "probe.cpp"
    ]
    assert not op_errs, [d.spelling for d in op_errs]


def test_kernel_erases_no_simd_vf_fusion_qualifier():
    import yaml

    doc = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "spec" / "build_context.yaml").read_text(
            encoding="utf-8"
        )
    )
    quals = (doc.get("kernel") or {}).get("erase_qualifiers") or []
    assert "__no_simd_vf_fusion__" in quals
    assert "__simt_vf__" in quals
    assert "LAUNCH_BOUND" in quals


def test_prelude_erases_callee_qualifier(tmp_path: Path):
    from clang import cindex

    src = tmp_path / "probe.cpp"
    src.write_text("static __callee__ int max_i(int a, int b);\n", encoding="utf-8")
    tu = cindex.Index.create().parse(
        str(src),
        args=["-std=c++17", "-fsyntax-only", "-include", str(PRELUDE)],
    )
    op_errs = [
        d
        for d in tu.diagnostics
        if int(d.severity) >= 3
        and d.location.file is not None
        and Path(d.location.file.name).name == "probe.cpp"
    ]
    assert not op_errs, [d.spelling for d in op_errs]


def test_prelude_parses_simt_vf_launch_bound_snippet(tmp_path: Path):
    from clang import cindex

    src = tmp_path / "probe.cpp"
    src.write_text(
        "template<typename T>\n"
        "__simt_vf__ inline void SinkhornKnoppSimt(T *ptr);\n"
        "__simt_vf__ LAUNCH_BOUND(1024) inline void ComputeSimt();\n",
        encoding="utf-8",
    )
    tu = cindex.Index.create().parse(
        str(src),
        args=["-std=c++17", "-fsyntax-only", "-include", str(PRELUDE)],
    )
    op_errs = [
        d
        for d in tu.diagnostics
        if int(d.severity) >= 3
        and d.location.file is not None
        and Path(d.location.file.name).name == "probe.cpp"
    ]
    assert not op_errs, [d.spelling for d in op_errs]
