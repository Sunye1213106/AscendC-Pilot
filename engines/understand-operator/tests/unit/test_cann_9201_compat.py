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


def test_overlay_prepends_patched_tpipe(tmp_path: Path) -> None:
    basic = (
        tmp_path
        / "cann"
        / "cann-asc-devkit"
        / "x86_64-linux"
        / "asc"
        / "include"
        / "basic_api"
    )
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
    includes = [p.replace("\\", "/") for p in ctx.kernel_includes()]
    overlay = str(overlay_dir(op, "arch-920r1")).replace("\\", "/")
    assert includes[0].rstrip("/") == overlay.rstrip("/")
    patched = (overlay_dir(op, "arch-920r1") / "kernel_tpipe.h").read_text(encoding="utf-8")
    assert "(__NPU_ARCH__ == 9201)" in patched
    utils = (
        overlay_dir(op, "arch-920r1") / "kernel_reg_compute_utils.h"
    ).read_text(encoding="utf-8")
    assert "(__NPU_ARCH__ == 9201)" in utils
    assert ctx.cann_9201.get("headers") == "overlay"


def test_native_9201_header_skips_overlay(tmp_path: Path) -> None:
    basic = (
        tmp_path
        / "cann"
        / "cann-asc-devkit"
        / "x86_64-linux"
        / "asc"
        / "include"
        / "basic_api"
    )
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
