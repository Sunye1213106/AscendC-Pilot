# -*- coding: utf-8 -*-
from pathlib import Path

from uo_init.build_context import BuildContext, SPEC_DIR


def test_package_import():
    import uo_init

    assert uo_init.__version__


def test_compat_files_exist(spec_dir: Path):
    assert (spec_dir / "compat" / "bisheng_prelude.h").is_file()
    assert (
        spec_dir / "compat" / "ascendc" / "host_api" / "tiling" / "template_argument.h"
    ).is_file()


def test_build_context_placeholders(tmp_path: Path, spec_dir: Path):
    ctx = BuildContext.load(
        cann_root="D:/cann",
        ops_root="D:/ops",
        op_dir="D:/ops/attention/fag",
        arch_dir="arch35",
        repo_root=str(spec_dir.parents[2]),
    )
    assert ctx.cann_root == "D:/cann"
    assert "arch35" in ctx.resolve_path("{op_dir}/op_host/{arch_dir}")
    assert ctx.resolve_path("{op_dir}/op_host/{arch_dir}") == "D:/ops/attention/fag/op_host/arch35"
    assert "{compat_root}" not in ctx.compat_root
    assert "compat" in ctx.compat_root.replace("\\", "/")
