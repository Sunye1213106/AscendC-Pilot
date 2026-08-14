# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.op_spec import _tiling_key_header
from uo_init.pilot_engines import _hard_scope_blockers


def test_tiling_key_header_accepts_underscore_tiling_key_h(tmp_path: Path):
    kernel = tmp_path / "op_kernel"
    arch = kernel / "arch35"
    arch.mkdir(parents=True)
    hit = arch / "grouped_matmul_add_tiling_key.h"
    hit.write_text("// keys\n", encoding="utf-8")
    found, notes = _tiling_key_header(kernel, "arch35", "GroupedMatmulAdd")
    assert found == hit
    assert notes == []


def test_tiling_key_header_entry_include_wins_over_root_glob(tmp_path: Path):
    op = tmp_path / "toy"
    kernel = op / "op_kernel"
    variant = kernel / "arch35" / "variant"
    variant.mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    entry_hdr = variant / "variant_tiling_key.h"
    entry_hdr.write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy,\n"
        "  ASCENDC_TPL_UINT_DECL(K0, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1));\n",
        encoding="utf-8",
    )
    (kernel / "toy_tiling_key.h").write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy,\n"
        "  ASCENDC_TPL_DTYPE_DECL(DimA, DT_FLOAT, DT_FLOAT16),\n"
        "  ASCENDC_TPL_BOOL_DECL(Flag, 0, 1));\n",
        encoding="utf-8",
    )
    (kernel / "toy_apt.cpp").write_text(
        '#include "arch35/variant/variant_tiling_key.h"\n'
        "__global__ __aicore__ void toy(__gm__ uint8_t *x) {}\n",
        encoding="utf-8",
    )
    found, notes = _tiling_key_header(kernel, "arch35", "Toy", op_dir=op)
    assert found == entry_hdr
    assert notes == []


def test_tiling_key_header_prefers_template_dsl(tmp_path: Path):
    kernel = tmp_path / "op_kernel"
    arch = kernel / "arch35"
    arch.mkdir(parents=True)
    (arch / "foo_tiling_key.h").write_text("// alt\n", encoding="utf-8")
    dsl = arch / "foo_template_tiling_key.h"
    dsl.write_text("ASCENDC_TPL_ARGS_DECL(Foo,\n", encoding="utf-8")
    found, notes = _tiling_key_header(kernel, "arch35", "Foo")
    assert found == dsl
    assert notes == []


def test_tiling_key_header_missing_is_soft_ambiguity():
    blockers = _hard_scope_blockers(
        ["tiling_key_header_not_found: no *template_tiling_key.h"],
        arch_user_specified=True,
        probe_clean=True,
        clang_scope_status="complete",
        hosts=["a.cpp"],
        kernel_entry="k.cpp",
    )
    assert blockers == []


def test_tiling_key_header_missing_still_notes_when_probe_dirty():
    blockers = _hard_scope_blockers(
        ["tiling_key_header_not_found: no *template_tiling_key.h"],
        arch_user_specified=True,
        probe_clean=False,
        clang_scope_status="complete",
        hosts=["a.cpp"],
        kernel_entry="k.cpp",
    )
    assert "clang_probe_unclean" in blockers
    assert not any(b.startswith("tiling_key_header_not_found") for b in blockers)
