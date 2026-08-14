# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import yaml

from uo_init.kernel_tiling_view import _default_tiling_type, render_stub
from uo_init.source_layout import (
    GLOBAL_KERNEL_RE,
    KERNEL_ENTRY_NAME_RE,
    entry_include_architecture,
    selected_host_files,
    selected_kernel_files,
    selected_tiling_headers,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_scope(op: Path, architecture: str, rels: list[str]) -> None:
    scope = op / ".ascendc-pilot" / architecture / "uo" / "summary"
    scope.mkdir(parents=True, exist_ok=True)
    (scope / "scope_set.yaml").write_text(
        yaml.safe_dump({"confirmed_source_files": rels}),
        encoding="utf-8",
    )


def test_heuristic_skips_other_arch_root_entry(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _write(
        op / "op_kernel" / "toy.cpp",
        '#include "arch22/tiling.h"\n__global__ __aicore__ void toy() {}\n',
    )
    _write(
        op / "op_kernel" / "toy_apt.cpp",
        '#include "arch35/tiling.h"\nREGISTER_TILING_DEFAULT(CurrentTiling);\n',
    )
    _write(op / "op_kernel" / "arch35" / "extra.h", "struct Extra {};\n")
    names = {p.name for p in selected_kernel_files(op, "arch35")}
    assert "toy_apt.cpp" in names
    assert "toy.cpp" not in names
    assert "extra.h" in names


def test_confirmed_set_is_the_scan_universe(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    extra = op / "op_kernel" / "arch35" / "extra.h"
    apt = op / "op_kernel" / "toy_apt.cpp"
    foreign = op / "op_kernel" / "arch22" / "old_tiling.h"
    host = op / "op_host" / "arch35" / "tiling.cpp"
    unused_host = op / "op_host" / "arch35" / "unused.cpp"
    _write(extra, "struct Extra {};\n")
    _write(apt, '#include "arch35/tiling.h"\nREGISTER_TILING_DEFAULT(CurrentTiling);\n')
    _write(foreign, "struct OldTiling {};\n")
    _write(host, "void DoTiling() {}\n")
    _write(unused_host, "void Unused() {}\n")
    stub = op / ".ascendc-pilot" / "arch35" / "uo" / "cache" / "kernel_tiling_view" / "toy_tiling_stub.h"
    _write(
        stub,
        "#define GET_TILING_DATA(tiling_data, tiling_arg) "
        "GET_TILING_DATA_WITH_STRUCT(CurrentTiling, tiling_data, tiling_arg)\n",
    )
    _seed_scope(
        op,
        "arch35",
        [
            "op_kernel/toy_apt.cpp",
            "op_kernel/arch22/old_tiling.h",
            "op_host/arch35/tiling.cpp",
            ".ascendc-pilot/arch35/uo/cache/kernel_tiling_view/toy_tiling_stub.h",
        ],
    )

    kernel = {p.resolve() for p in selected_kernel_files(op, "arch35")}
    assert apt.resolve() in kernel
    assert extra.resolve() not in kernel
    assert foreign.resolve() not in kernel
    assert stub.resolve() not in kernel

    host_files = {p.resolve() for p in selected_host_files(op, "arch35")}
    assert host.resolve() in host_files
    assert unused_host.resolve() not in host_files

    tiling = {p.resolve() for p in selected_tiling_headers(op, "arch35")}
    assert foreign.resolve() not in tiling
    assert stub.resolve() not in tiling


def test_default_tiling_type_uses_current_arch_entry(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _write(
        op / "op_kernel" / "toy.cpp",
        '#include "arch22/tiling.h"\nREGISTER_TILING_DEFAULT(OldTiling);\n',
    )
    _write(
        op / "op_kernel" / "toy_apt.cpp",
        '#include "arch35/tiling.h"\nREGISTER_TILING_DEFAULT(CurrentTiling);\n',
    )
    assert _default_tiling_type(op, "arch35") == "CurrentTiling"
    stub = render_stub(op, "arch35")
    assert "CurrentTiling" in stub
    assert "OldTiling" not in stub
    assert "kernel_tiling/kernel_tiling.h" not in stub
    assert "#ifndef GET_TILING_DATA" in stub


def test_stub_emits_nested_macro_struct_referenced_by_parent(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _write(
        op / "op_host" / "op_tiling" / "tiling.h",
        "BEGIN_TILING_DATA_DEF(InnerArray)\n"
        "TILING_DATA_FIELD_DEF_ARR(int32_t, 8, vals)\n"
        "END_TILING_DATA_DEF\n"
        "BEGIN_TILING_DATA_DEF(OuterTiling)\n"
        "TILING_DATA_FIELD_DEF_STRUCT(InnerArray, inner)\n"
        "TILING_DATA_FIELD_DEF_STRUCT(TCubeTiling, mmTiling)\n"
        "END_TILING_DATA_DEF\n",
    )
    _write(
        op / "op_kernel" / "arch35" / "inner.h",
        "namespace Ns { struct InnerArray { int32_t vals[8]; }; }\n",
    )
    stub = render_stub(op, "arch35")
    assert "kernel_tiling/kernel_tiling.h" not in stub
    assert "struct InnerArray" in stub
    assert "struct OuterTiling" in stub
    assert "InnerArray inner" in stub
    assert "mmTiling_opaque" in stub
    assert "struct TCubeTiling" not in stub


def test_kernel_entry_regex_accepts_qualifier_orders() -> None:
    text = (
        "extern \"C\" __global__ void plain(int x) { }\n"
        "__aicore__ __global__ void reversed(int y) { }\n"
        "template <bool Flag>\n"
        "__global__ __aicore__ void classic(int z) { }\n"
    )
    names = {m.group("name") for m in GLOBAL_KERNEL_RE.finditer(text)}
    assert names == {"plain", "reversed", "classic"}
    assert KERNEL_ENTRY_NAME_RE.findall(text) == ["plain", "reversed", "classic"]


def test_mixed_arch_includes_do_not_pin_a_foreign_entry() -> None:
    text = (
        '#if (__NPU_ARCH__ == 5102)\n'
        '#include "../prompt_flash_attention/arch38/prompt_flash_attention_entry_regbase.h"\n'
        '#else\n'
        '#include "incre_flash_attention_arch22.h"\n'
        '#endif\n'
        'extern "C" __global__ __aicore__ void incre_flash_attention() {}\n'
    )
    assert entry_include_architecture(text) == ""
    assert entry_include_architecture('#include "arch35/tiling.h"\n') == "arch35"
