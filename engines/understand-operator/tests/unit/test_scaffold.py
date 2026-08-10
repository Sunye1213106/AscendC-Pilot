# -*- coding: utf-8 -*-
from pathlib import Path

from uo_init.build_context import BuildContext


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
