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
    assert "struct RegTensor" not in text
    assert "struct SoftMaxTiling" not in text


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


def test_kernel_erases_no_simd_vf_fusion_qualifier():
    import yaml

    doc = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "spec" / "build_context.yaml").read_text(
            encoding="utf-8"
        )
    )
    quals = (doc.get("kernel") or {}).get("erase_qualifiers") or []
    assert "__no_simd_vf_fusion__" in quals
