# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import yaml

from uo_init.kernel_tiling_view import _default_tiling_type, render_stub
from uo_init.source_layout import (
    ARCH_DIR_RE,
    GLOBAL_KERNEL_RE,
    KERNEL_ENTRY_NAME_RE,
    arch_number,
    architecture_in_scope,
    canonicalize_architecture,
    entry_include_architecture,
    include_root_owned_architecture,
    is_foreign_arch_entry_tu,
    is_other_arch_path,
    keep_lexical_kernel_path,
    match_on_disk_architecture,
    path_owned_architecture,
    pick_kernel_entry,
    selected_host_files,
    selected_kernel_files,
    selected_tiling_headers,
    tpl_decl_files,
    tpl_sel_files,
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
    assert foreign.resolve() in kernel
    assert stub.resolve() not in kernel

    host_files = {p.resolve() for p in selected_host_files(op, "arch35")}
    assert host.resolve() in host_files
    assert unused_host.resolve() not in host_files

    tiling = {p.resolve() for p in selected_tiling_headers(op, "arch35")}
    assert foreign.resolve() in tiling
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


def test_stub_skips_kernel_using_alias_for_host_macro_struct(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _write(
        op / "op_host" / "tiling.h",
        "BEGIN_TILING_DATA_DEF(ToyTilingData)\n"
        "TILING_DATA_FIELD_DEF(uint32_t, n)\n"
        "END_TILING_DATA_DEF\n",
    )
    _write(
        op / "op_kernel" / "toy_apt.cpp",
        "struct ToyArch35TilingData { uint32_t n; };\n"
        "using ToyTilingData = ToyArch35TilingData;\n",
    )
    stub = render_stub(op, "arch35")
    assert "struct ToyTilingData" not in stub
    assert "GET_TILING_DATA_WITH_STRUCT" in stub



def test_install_force_includes_real_cann_kernel_tiling(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from uo_init.kernel_tiling_view import install_kernel_tiling_view

    op = tmp_path / "toy"
    _write(
        op / "op_host" / "tiling.h",
        "BEGIN_TILING_DATA_DEF(OuterTiling)\n"
        "TILING_DATA_FIELD_DEF(uint32_t, n)\n"
        "END_TILING_DATA_DEF\n",
    )
    _write(op / "op_kernel" / "entry.cpp", "REGISTER_TILING_DEFAULT(OuterTiling);\n")
    cann_h = (
        tmp_path
        / "cann"
        / "cann-asc-devkit"
        / "x86_64-linux"
        / "ascendc"
        / "include"
        / "highlevel_api"
        / "kernel_tiling"
        / "kernel_tiling.h"
    )
    _write(cann_h, "struct TCubeTiling { uint32_t M; };\n")
    ctx = SimpleNamespace(
        op_dir=str(op),
        arch_dir="arch35",
        cann_root=str(tmp_path / "cann"),
        extra_kernel_force_includes=[],
        kernel_includes=lambda: [str(cann_h.parent.parent)],
        add_force_include=None,
    )
    spec = SimpleNamespace(op_dir=op, arch_dir="arch35", op_snake="toy")
    path = install_kernel_tiling_view(spec, ctx)
    assert path is not None
    force = [p.replace("\\", "/") for p in ctx.extra_kernel_force_includes]
    assert any(p.endswith("toy_tiling_stub.h") for p in force)
    assert not any(p.endswith("kernel_tiling/kernel_tiling.h") for p in force)


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


def test_kernel_entry_regex_accepts_long_commented_abi_list() -> None:
    params = ",\n".join(
        f"                            GM_ADDR arg{i},  // input {i}: {'x' * 80}"
        for i in range(16)
    )
    text = (
        "extern \"C\" __global__ __aicore__ void\n"
        f"inplace_fused_causal_conv1d({params},\n"
        "                            GM_ADDR tiling)  // tiling\n"
        "{\n"
        "  if (TILING_KEY_IS(TILING_KEY_BH_BF16)) { return; }\n"
        "}\n"
    )
    names = {m.group("name") for m in GLOBAL_KERNEL_RE.finditer(text)}
    assert names == {"inplace_fused_causal_conv1d"}


def test_tpl_sel_files_follow_entry_include_to_split_header(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _write(
        op / "op_kernel" / "toy_tiling_key_decl.h",
        "ASCENDC_TPL_ARGS_DECL(Toy, ASCENDC_TPL_BOOL_DECL(Flag, 0, 1));\n",
    )
    _write(
        op / "op_kernel" / "arch35" / "toy_apt_tiling_key.h",
        '#include "../toy_tiling_key_decl.h"\n'
        "ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_BOOL_SEL(Flag, 0, 1));\n",
    )
    _write(
        op / "op_kernel" / "toy_apt.cpp",
        '#include "arch35/toy_apt_tiling_key.h"\n'
        "__global__ __aicore__ void toy() {}\n",
    )
    decls = tpl_decl_files(op, "arch35")
    sels = tpl_sel_files(op, "arch35")
    assert [p.name for p in decls] == ["toy_tiling_key_decl.h"]
    assert [p.name for p in sels] == ["toy_apt_tiling_key.h"]


def test_tpl_decl_ignores_sibling_operator_include(tmp_path: Path) -> None:
    """Fusion wrappers include another op's TPL header; that is not this schema."""
    sib = tmp_path / "other_op"
    _write(
        sib / "op_kernel" / "other_tiling_key_decl.h",
        "ASCENDC_TPL_ARGS_DECL(Other, ASCENDC_TPL_BOOL_DECL(Flag, 0, 1));\n",
    )
    op = tmp_path / "fusion_op"
    _write(
        op / "op_kernel" / "fusion_apt.cpp",
        '#include "../../other_op/op_kernel/other_tiling_key_decl.h"\n'
        "__global__ __aicore__ void fusion_op() {}\n",
    )
    assert tpl_decl_files(op, "arch35") == []
    assert tpl_sel_files(op, "arch35") == []


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


def test_path_owned_architecture_wins_over_shared_arch35_include(tmp_path: Path) -> None:
    cpp = tmp_path / "op_kernel" / "arch22" / "widget.cpp"
    _write(
        cpp,
        '#include "../widget_arch35.h"\n'
        '__global__ __aicore__ void widget() {}\n',
    )
    assert path_owned_architecture(cpp) == "arch22"
    assert entry_include_architecture(cpp.read_text(encoding="utf-8")) == "arch35"


def test_hyphenated_arch_920r1_is_a_distinct_owned_path(tmp_path: Path) -> None:
    own = tmp_path / "op_kernel" / "arch-920r1" / "widget.cpp"
    foreign = tmp_path / "op_kernel" / "arch35" / "old.cpp"
    _write(own, '#include "tiling.h"\n__global__ __aicore__ void widget() {}\n')
    _write(foreign, "struct Old {};\n")
    assert path_owned_architecture(own) == "arch-920r1"
    assert is_other_arch_path(foreign, "arch-920r1") is False
    assert is_other_arch_path(own, "arch-920r1") is False
    assert arch_number("arch-920r1") == 920
    assert arch_number("arch920r1") == 920
    assert arch_number("arch35") == 35
    assert entry_include_architecture('#include "arch-920r1/tiling.h"\n') == "arch-920r1"
    assert include_root_owned_architecture(own.parent) == "arch-920r1"
    assert include_root_owned_architecture(own.parent.parent) == ""
    assert is_foreign_arch_entry_tu(foreign, "arch-920r1") is True
    assert is_foreign_arch_entry_tu(tmp_path / "op_kernel" / "arch35" / "old.h", "arch-920r1") is False


def test_confirmed_keeps_clang_included_other_arch_header(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    header = op / "op_kernel" / "arch35" / "foo.h"
    entry = op / "op_kernel" / "arch-920r1" / "k.cpp"
    foreign_entry = op / "op_kernel" / "arch35" / "old.cpp"
    _write(header, "struct Foo {};\n")
    _write(entry, '#include "arch35/foo.h"\n__global__ __aicore__ void k() {}\n')
    _write(foreign_entry, "__global__ __aicore__ void old() {}\n")
    _seed_scope(
        op,
        "arch-920r1",
        [
            "op_kernel/arch-920r1/k.cpp",
            "op_kernel/arch35/foo.h",
        ],
    )
    kernel = {p.resolve() for p in selected_kernel_files(op, "arch-920r1")}
    assert header.resolve() in kernel
    assert entry.resolve() in kernel
    assert foreign_entry.resolve() not in kernel


def test_canonicalize_and_cousin_scope() -> None:
    assert canonicalize_architecture("arch920r1") == "arch-920r1"
    assert canonicalize_architecture("DAV_9201") == "arch-920r1"
    assert canonicalize_architecture("9201") == "arch-920r1"
    assert canonicalize_architecture("arch35") == "arch35"
    assert ARCH_DIR_RE.match("arch920r1")
    assert ARCH_DIR_RE.match("arch-920r1")
    assert match_on_disk_architecture("arch920r1", ["arch-920r1", "arch35"]) == "arch-920r1"
    assert architecture_in_scope("arch35", "arch-920r1") is True
    assert architecture_in_scope("arch-920r1", "arch35") is False
    assert architecture_in_scope("arch22", "arch-920r1") is False
    assert is_other_arch_path(Path("op_kernel/arch22/x.h"), "arch-920r1") is True


def test_920r1_heuristic_keeps_arch35_apt_and_host_tiling(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _write(
        op / "op_kernel" / "toy_apt.cpp",
        '#include "arch35/tiling.h"\n__global__ __aicore__ void toy() {}\n',
    )
    _write(op / "op_kernel" / "arch35" / "tiling.h", "struct T {};\n")
    _write(op / "op_kernel" / "arch22" / "old.h", "struct Old {};\n")
    _write(op / "op_host" / "arch35" / "toy_tiling.cpp", "void DoTiling() {}\n")
    kernel = [p.as_posix().replace("\\", "/") for p in selected_kernel_files(op, "arch-920r1")]
    assert any(p.endswith("toy_apt.cpp") for p in kernel)
    assert any(p.endswith("arch35/tiling.h") for p in kernel)
    assert not any("arch22" in p for p in kernel)
    host = [p.as_posix().replace("\\", "/") for p in selected_host_files(op, "arch-920r1")]
    assert any(p.endswith("toy_tiling.cpp") for p in host)
    picked = pick_kernel_entry(
        [op / "op_kernel" / "toy_apt.cpp", op / "op_kernel" / "arch35" / "old.cpp"],
        "arch-920r1",
    )
    assert picked is not None
    assert picked.name == "toy_apt.cpp"


def test_keep_lexical_kernel_path_drops_foreign_arch_bodies() -> None:
    assert keep_lexical_kernel_path(Path("op_kernel/arch35/k.h"), "arch35") is True
    assert keep_lexical_kernel_path(Path("op_kernel/arch22/old_tiling.h"), "arch35") is False
    assert keep_lexical_kernel_path(Path("op_kernel/entry.cpp"), "arch35") is True
    assert keep_lexical_kernel_path(Path("common/op_kernel/arch35/util.h"), "arch35") is True


