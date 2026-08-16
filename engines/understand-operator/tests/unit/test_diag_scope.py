# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.diag_scope import (
    is_benign_kernel_probe_residual,
    is_libclang_cann_residual,
    score_tu_diagnostics,
)


class _File:
    def __init__(self, name: str) -> None:
        self.name = name


class _Loc:
    def __init__(self, name: str | None) -> None:
        self.file = _File(name) if name else None


class _Diag:
    def __init__(self, severity: int, spelling: str, file: str | None) -> None:
        self.severity = severity
        self.spelling = spelling
        self.location = _Loc(file)


def test_asc_dump_redefinition_is_cann_residual():
    assert is_libclang_cann_residual("redefinition of 'asc_dump'")
    assert is_libclang_cann_residual("redefinition of 'asc_atomic_add'")
    assert is_libclang_cann_residual("redefinition of 'normf'")
    assert is_libclang_cann_residual("redefinition of 'rnormf'")


def test_simt_math_redefinition_is_cann_residual():
    for name in ("modff", "remquof", "sincosf", "sincospif", "frexpf"):
        assert is_libclang_cann_residual(f"redefinition of '{name}'")
    assert not is_libclang_cann_residual("redefinition of 'FooTilingData'")


def test_cann_header_fatal_is_not_probe_relevant(tmp_path: Path):
    op = tmp_path / "toy"
    tu = op / "op_kernel" / "entry.cpp"
    tu.parent.mkdir(parents=True)
    tu.write_text("int x;\n", encoding="utf-8")
    cann = tmp_path / "cann" / "kernel_tiling.h"
    cann.parent.mkdir(parents=True)
    scored = score_tu_diagnostics(
        [
            _Diag(4, "'hccl/hcom.h' file not found", str(cann)),
            _Diag(3, "no viable conversion from 'float' to 'const half'", str(cann)),
        ],
        str(tu),
        str(op),
    )
    assert scored["fatal_count"] == 1
    assert scored["operator_error_count"] == 0
    assert scored["probe_relevant_errors"] == 0


def test_operator_missing_header_is_probe_relevant(tmp_path: Path):
    op = tmp_path / "toy"
    tu = op / "op_host" / "tiling.cpp"
    tu.parent.mkdir(parents=True)
    tu.write_text('#include "missing.h"\n', encoding="utf-8")
    scored = score_tu_diagnostics(
        [_Diag(4, "'missing.h' file not found", str(tu))],
        str(tu),
        str(op),
    )
    assert scored["operator_error_count"] == 1
    assert scored["operator_fatal_count"] == 1
    assert scored["probe_relevant_errors"] == 1
    assert "'missing.h' file not found" in scored["heal_hints"]


def test_heal_hints_keep_missing_header_past_sample_cap(tmp_path: Path):
    op = tmp_path / "toy"
    tu = op / "op_kernel" / "entry.cpp"
    tu.parent.mkdir(parents=True)
    tu.write_text("int x;\n", encoding="utf-8")
    scored = score_tu_diagnostics(
        [_Diag(3, "unknown type name 'T'", str(tu))] * 8
        + [_Diag(4, "'op_kernel/platform_util.h' file not found", str(tu))],
        str(tu),
        str(op),
    )
    assert all("unknown type name 'T'" == s for s in scored["samples"])
    assert "'op_kernel/platform_util.h' file not found" not in scored["samples"]
    assert "'op_kernel/platform_util.h' file not found" in scored["heal_hints"]


def test_tcube_tiling_decl_residual_is_benign():
    probes = [
        {
            "side": "kernel",
            "errors": 1,
            "fatal": 0,
            "samples": ["unknown type name 'TCubeTiling'"],
        }
    ]
    assert is_benign_kernel_probe_residual(probes) is True


def test_softmax_tiling_decl_residual_is_benign():
    probes = [
        {
            "side": "kernel",
            "errors": 1,
            "fatal": 0,
            "samples": ["unknown type name 'SoftMaxTiling'"],
        }
    ]
    assert is_benign_kernel_probe_residual(probes) is True


def test_kernel_syntax_error_is_not_benign():
    probes = [
        {
            "side": "kernel",
            "errors": 1,
            "fatal": 0,
            "samples": ["expected ';' after expression"],
        }
    ]
    assert is_benign_kernel_probe_residual(probes) is False


def test_kernel_probe_exception_is_not_benign():
    probes = [
        {
            "side": "kernel",
            "error": "libclang crashed",
            "errors": -1,
        }
    ]
    assert is_benign_kernel_probe_residual(probes) is False
