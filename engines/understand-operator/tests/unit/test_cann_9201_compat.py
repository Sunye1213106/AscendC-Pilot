# -*- coding: utf-8 -*-
"""arch-920r1 compiles as 9201; overlay widens 3510 header gates when needed."""
from __future__ import annotations

from pathlib import Path

from uo_init.build_context import BuildContext
from uo_init.cann_9201_compat import expand_3510_gates, overlay_dir


def test_expand_3510_gates_is_idempotent() -> None:
    src = "#if __NPU_ARCH__ == 3510\nint x;\n#endif\n"
    once = expand_3510_gates(src)
    assert "(__NPU_ARCH__ == 9201)" in once
    twice = expand_3510_gates(once)
    assert twice.count("9201") == once.count("9201")


def test_expand_3510_ne_keeps_9201_on_3510_side() -> None:
    src = "#if __NPU_ARCH__ != 3510\nint other;\n#endif\n"
    once = expand_3510_gates(src)
    assert "(__NPU_ARCH__ != 9201)" in once
    twice = expand_3510_gates(once)
    assert twice.count("9201") == once.count("9201")


def _mock_cann_basic(tmp_path: Path) -> Path:
    return (
        tmp_path
        / "cann"
        / "cann-asc-devkit"
        / "x86_64-linux"
        / "asc"
        / "include"
        / "basic_api"
    )


def test_overlay_prepends_patched_tpipe(tmp_path: Path) -> None:
    basic = _mock_cann_basic(tmp_path)
    basic.mkdir(parents=True)
    (basic / "kernel_tpipe.h").write_text(
        "#if __NPU_ARCH__ == 3510\nint tpipe;\n#endif\n",
        encoding="utf-8",
    )
    (basic / "kernel_reg_compute_utils.h").write_text(
        "#if __NPU_ARCH__ == 3510 || __NPU_ARCH__ == 5102\nint utils;\n#endif\n",
        encoding="utf-8",
    )
    (basic / "kernel_reg_compute_intf.h").write_text(
        "// no arch gate\n",
        encoding="utf-8",
    )
    op = tmp_path / "op"
    op.mkdir()
    (op / "op_host").mkdir()
    (op / "op_kernel").mkdir()
    ctx = BuildContext.load(
        cann_root=str(tmp_path / "cann"),
        ops_root=str(tmp_path),
        op_dir=str(op),
        arch_dir="arch-920r1",
        apply_saved_extras=False,
    )
    assert ctx.kernel_defines()["__NPU_ARCH__"] == "9201"
    overlay = str(overlay_dir(op, "arch-920r1")).replace("\\", "/")
    includes = [p.replace("\\", "/").rstrip("/") for p in ctx.kernel_includes()]
    overlay_incs = [p for p in includes if p.startswith(overlay)]
    assert overlay_incs
    assert includes[0] == overlay_incs[0]
    patched = (
        overlay_dir(op, "arch-920r1") / "asc" / "include" / "basic_api" / "kernel_tpipe.h"
    ).read_text(encoding="utf-8")
    assert "(__NPU_ARCH__ == 9201)" in patched
    utils = (
        overlay_dir(op, "arch-920r1")
        / "asc"
        / "include"
        / "basic_api"
        / "kernel_reg_compute_utils.h"
    ).read_text(encoding="utf-8")
    assert "(__NPU_ARCH__ == 9201)" in utils
    assert ctx.cann_9201.get("headers") == "overlay"
    assert int(ctx.cann_9201.get("overlay_file_count") or 0) >= 2


def test_overlay_mirrors_impl_next_to_interface(tmp_path: Path) -> None:
    cann_asc = tmp_path / "cann" / "cann-asc-devkit" / "x86_64-linux" / "asc"
    basic = cann_asc / "include" / "basic_api"
    impl = cann_asc / "impl" / "basic_api"
    basic.mkdir(parents=True)
    impl.mkdir(parents=True)
    (basic / "kernel_tpipe.h").write_text(
        "#if __NPU_ARCH__ == 3510\n"
        "static constexpr int k = GlobalManageQueConfig<0>::maxBufferBlock;\n"
        "#endif\n"
        '#include "../../impl/basic_api/kernel_tpipe_impl.h"\n',
        encoding="utf-8",
    )
    (impl / "kernel_tpipe_impl.h").write_text(
        "#if (__NPU_ARCH__ == 3510) || (__NPU_ARCH__ == 5102)\n"
        "template <int x> struct GlobalManageQueConfig { static constexpr int maxBufferBlock = 1; };\n"
        "#endif\n"
        "#if __NPU_ARCH__ != 3510\n"
        "int not_c310;\n"
        "#endif\n",
        encoding="utf-8",
    )
    op = tmp_path / "op"
    op.mkdir()
    ctx = BuildContext.load(
        cann_root=str(tmp_path / "cann"),
        ops_root=str(tmp_path),
        op_dir=str(op),
        arch_dir="arch-920r1",
        apply_saved_extras=False,
    )
    overlay = overlay_dir(op, "arch-920r1")
    iface = overlay / "asc" / "include" / "basic_api" / "kernel_tpipe.h"
    impl_out = overlay / "asc" / "impl" / "basic_api" / "kernel_tpipe_impl.h"
    assert iface.is_file()
    assert impl_out.is_file()
    text = impl_out.read_text(encoding="utf-8")
    assert "(__NPU_ARCH__ == 9201)" in text
    assert "(__NPU_ARCH__ != 9201)" in text
    assert '#include "../../impl/basic_api/kernel_tpipe_impl.h"' in iface.read_text(
        encoding="utf-8"
    )
    includes = [p.replace("\\", "/").rstrip("/") for p in ctx.kernel_includes()]
    assert any(p.endswith("asc/impl/basic_api") for p in includes)


def test_native_9201_header_skips_overlay(tmp_path: Path) -> None:
    basic = _mock_cann_basic(tmp_path)
    basic.mkdir(parents=True)
    (basic / "kernel_tpipe.h").write_text(
        "#if __NPU_ARCH__ == 9201\nint tpipe;\n#endif\n",
        encoding="utf-8",
    )
    op = tmp_path / "op"
    op.mkdir()
    ctx = BuildContext.load(
        cann_root=str(tmp_path / "cann"),
        ops_root=str(tmp_path),
        op_dir=str(op),
        arch_dir="arch-920r1",
        apply_saved_extras=False,
    )
    assert ctx.overlay_includes == []
    assert ctx.cann_9201.get("headers") == "native"
    assert not (overlay_dir(op, "arch-920r1") / "kernel_tpipe.h").is_file()
    assert not (
        overlay_dir(op, "arch-920r1") / "asc" / "include" / "basic_api" / "kernel_tpipe.h"
    ).is_file()


def test_overlay_keeps_nested_path_not_basename(tmp_path: Path) -> None:
    cann_asc = tmp_path / "cann" / "cann-asc-devkit" / "x86_64-linux" / "asc"
    utils = cann_asc / "impl" / "utils"
    basic_impl = cann_asc / "impl" / "basic_api"
    utils.mkdir(parents=True)
    basic_impl.mkdir(parents=True)
    (utils / "common_types.h").write_text(
        "#if __NPU_ARCH__ == 3510\nusing fp8_e5m2_t = uint8_t;\n#endif\n",
        encoding="utf-8",
    )
    (basic_impl / "common_types.h").write_text(
        "enum class TPosition : unsigned char { GM };\n",
        encoding="utf-8",
    )
    op = tmp_path / "op"
    op.mkdir()
    BuildContext.load(
        cann_root=str(tmp_path / "cann"),
        ops_root=str(tmp_path),
        op_dir=str(op),
        arch_dir="arch-920r1",
        apply_saved_extras=False,
    )
    overlay = overlay_dir(op, "arch-920r1")
    assert (overlay / "asc" / "impl" / "utils" / "common_types.h").is_file()
    assert not (overlay / "asc" / "common_types.h").is_file()
    assert not (overlay / "tikcfw" / "common_types.h").is_file()


def test_overlay_copies_ungated_siblings(tmp_path: Path) -> None:
    reg = (
        tmp_path
        / "cann"
        / "cann-asc-devkit"
        / "x86_64-linux"
        / "asc"
        / "include"
        / "basic_api"
        / "reg_compute"
    )
    reg.mkdir(parents=True)
    (reg / "kernel_reg_compute_intf.h").write_text(
        "#if __NPU_ARCH__ == 3510\n"
        '#include "kernel_reg_compute_maskreg_intf.h"\n'
        "#endif\n",
        encoding="utf-8",
    )
    (reg / "kernel_reg_compute_maskreg_intf.h").write_text(
        "struct MaskReg {};\n",
        encoding="utf-8",
    )
    op = tmp_path / "op"
    op.mkdir()
    BuildContext.load(
        cann_root=str(tmp_path / "cann"),
        ops_root=str(tmp_path),
        op_dir=str(op),
        arch_dir="arch-920r1",
        apply_saved_extras=False,
    )
    overlay = overlay_dir(op, "arch-920r1") / "asc" / "include" / "basic_api" / "reg_compute"
    assert (overlay / "kernel_reg_compute_intf.h").is_file()
    assert (overlay / "kernel_reg_compute_maskreg_intf.h").is_file()


def test_overlay_follows_relative_dav_include(tmp_path: Path) -> None:
    cann_asc = tmp_path / "cann" / "cann-asc-devkit" / "x86_64-linux" / "asc"
    reg = cann_asc / "impl" / "basic_api" / "reg_compute"
    dav = reg / "dav_3510"
    dav.mkdir(parents=True)
    (reg / "kernel_reg_compute_maskreg_intf_impl.h").write_text(
        "#if __NPU_ARCH__ == 3510\n"
        '#include "../../basic_api/reg_compute/dav_3510/kernel_reg_compute_maskreg_impl.h"\n'
        "#endif\n",
        encoding="utf-8",
    )
    (dav / "kernel_reg_compute_maskreg_impl.h").write_text(
        "inline void MaskRegImpl() {}\n",
        encoding="utf-8",
    )
    op = tmp_path / "op"
    op.mkdir()
    BuildContext.load(
        cann_root=str(tmp_path / "cann"),
        ops_root=str(tmp_path),
        op_dir=str(op),
        arch_dir="arch-920r1",
        apply_saved_extras=False,
    )
    overlay = overlay_dir(op, "arch-920r1") / "asc" / "impl" / "basic_api" / "reg_compute"
    assert (overlay / "kernel_reg_compute_maskreg_intf_impl.h").is_file()
    assert (overlay / "dav_3510" / "kernel_reg_compute_maskreg_impl.h").is_file()
