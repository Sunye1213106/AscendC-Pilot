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


def test_cann_layout_issues_reports_missing(tmp_path: Path):
    from uo_init import paths

    issues = paths.cann_layout_issues(tmp_path)
    assert issues
    assert any("does not look like" in x or "missing" in x for x in issues)
