# -*- coding: utf-8 -*-
"""BuildContext kernel -I must follow ops-transformer asc/ layout (not ascendc basic_api)."""
from __future__ import annotations

from pathlib import Path

from uo_init.build_context import BuildContext


def test_host_includes_cover_cann_alog_and_math_util():
    ctx = BuildContext.load(
        cann_root="/cann",
        ops_root="/ops",
        op_dir="/ops/gmm/grouped_matmul",
        arch_dir="arch35",
    )
    includes = [p.replace("\\", "/") for p in ctx.host_includes()]
    joined = "\n".join(includes)
    assert any(p.endswith("cann-npu-runtime/x86_64-linux/include/base") for p in includes)
    assert any(p.endswith("include/op_common/op_host") for p in includes)
    assert any("hccl/internal/hcomm/pkg_inc" in p for p in includes)
    assert any(p.endswith("hccl/internal/hcomm") for p in includes)
    assert "/ops" in includes
    assert "/ops/gmm/common" in includes
    assert "/ops/gmm/common/utils" in includes
    assert "/ops/gmm/3rd" in includes
    assert "alog_pub" not in joined  # directory, not the file


def test_mc2_family_includes_cover_3rd_weight_quant():
    ctx = BuildContext.load(
        cann_root="/cann",
        ops_root="/ops",
        op_dir="/ops/mc2/matmul_all_reduce",
        arch_dir="arch22",
    )
    includes = [p.replace("\\", "/") for p in ctx.host_includes()]
    assert "/ops/mc2/common" in includes
    assert "/ops/mc2/common/utils" in includes
    assert "/ops/mc2/3rd" in includes


def test_kernel_includes_still_prefer_asc_over_ascendc_basic_api():
    ctx = BuildContext.load(
        cann_root="/cann",
        ops_root="/ops",
        op_dir="/ops/attention/flash_attention_score_grad",
        arch_dir="arch35",
    )
    includes = ctx.kernel_includes()
    joined = "\n".join(includes)

    assert "asc/include/basic_api" in joined
    assert "asc/impl/basic_api" in joined
    assert "asc/include/utils/std" in joined
    assert "asc/impl/utils/std/tuple" in joined
    assert "ascendc/include/highlevel_api" in joined
    assert any(p.replace("\\", "/").endswith("include/op_common") for p in includes)
    # The ses_00c0 probe trap: -I …/ascendc/include/basic_api makes
    # ../../../../include/utils/std/tuple.h resolve under impl/include (missing).
    assert "ascendc/include/basic_api" not in joined


def test_kernel_args_do_not_pass_ascendc_basic_api():
    ctx = BuildContext.load(cann_root="/cann", ops_root="/ops", op_dir="/op", arch_dir="arch35")
    args = ctx.kernel_args(dtype_variant="DT_FLOAT16")
    bad = [
        a
        for i, a in enumerate(args)
        if a == "-I" and i + 1 < len(args) and "ascendc/include/basic_api" in args[i + 1]
    ]
    assert bad == []


def test_kernel_yaml_does_not_globally_force_include_kernel_tiling():
    import yaml

    doc = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "spec" / "build_context.yaml").read_text(
            encoding="utf-8"
        )
    )
    force = (doc.get("kernel") or {}).get("force_include") or []
    joined = "\n".join(str(x) for x in force)
    assert "bisheng_prelude.h" in joined
    assert "struct SoftMaxTiling" not in joined
    # Real CANN header is attached by include_heal on unknown-type, not globally.
    assert "kernel_tiling/kernel_tiling.h" not in joined


def test_kernel_force_include_skips_missing_cann_tiling(tmp_path: Path):
    ctx = BuildContext.load(
        cann_root=str(tmp_path / "cann"),
        ops_root=str(tmp_path / "ops"),
        op_dir=str(tmp_path / "op"),
        arch_dir="arch35",
        apply_saved_extras=False,
    )
    force = [p.replace("\\", "/") for p in ctx.kernel_force_includes()]
    assert any(p.endswith("bisheng_prelude.h") for p in force)
    assert not any("kernel_tiling.h" in p for p in force)


def test_kernel_defines_not_dynamic_compile_like_ut():
    ctx = BuildContext.load(cann_root="/cann", ops_root="/ops", op_dir="/op", arch_dir="arch35")
    defs = ctx.kernel_defines()
    assert "NOT_DYNAMIC_COMPILE" in defs


def test_cann_layout_issues_reports_missing(tmp_path: Path):
    from uo_init import paths

    issues = paths.cann_layout_issues(tmp_path)
    assert issues
    assert any("does not look like" in x or "missing" in x for x in issues)
