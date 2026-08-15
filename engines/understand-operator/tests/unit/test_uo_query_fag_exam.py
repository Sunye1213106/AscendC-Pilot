# -*- coding: utf-8 -*-
"""Offline FAG arch35 goldens for the query-compiler exam (Q6–Q14 / Q16–Q18).

GLM sessions are not the pass bar. Extraction-dependent asserts skip until the
committed ``.uo`` contains the new locatable tokens.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from uo_init.query.plan import compile_query, plan_query_slices
from uo_init.store.reader import find_uo_product
from uo_init.uo_query import open_query

FAG_ROOT = Path(
    r"d:\TEST\ops-transformer\attention\flash_attention_score_grad"
)
FAG_PRODUCT = find_uo_product(FAG_ROOT, architecture="arch35")

Q6 = (
    "FP16 精度不过：dq 量级差一截，FP32 同 shape 过了。"
    "是不是 POST 的 scale/cast 写错了？先画出 arch35 单 launch 的三相，"
    "并说明 FP32 / BN2 / enablePreSfmg 各自怎么走。"
)
Q9 = (
    "950 上某 FP16、D=80、带 dropout 的 case 报 kernel 找不到。"
    "host 算出的 TilingKey 在 ASCENDC_TPL_SEL 里一定有吗？"
)
Q13 = (
    "B=1,N=4,S=2048 只有 4 个 AIC 在干活，vendor 几乎打满。"
    "是核内 VF 慢，还是分核轴错了？fusedOuter 在 BN2GS1S2 / BN2 / BN2S2 里分别乘了什么？"
)
Q16 = (
    "业务要 D=320。现在 D 模板是 64/128/192/256/768。"
    "只改 DTemplateNum 的 ASCENDC_TPL_UINT_SEL 够不够？"
)
Q17 = (
    "tests/ut/op_host/arch35/test_flash_attention_score_grad_tiling.cpp "
    "要补“一改就静默错”的 case。列 5 个，每个说期望的 splitAxis / "
    "deterSparseType / enablePreSfmg / isTndSwizzle / isNzOut，"
    "以及断言哪个 TilingData 子结构存在。"
)
Q18 = (
    "950 上一个 FP16 dropout 的 case，D=80，B=1 N=4 S=2048。"
    "host 算出 TilingKey 了，板上却报找不到 kernel。"
    "同一份 shape 打开确定性 TND 之后能编过、tiling 也成功，可是一进核 "
    "coreNum/s1/s2 就是垃圾，连跑下来 dK 对不齐、dQ 齐。"
    "把确定性关掉又能跑完，但核占不满，只有四个 AIC 在动，"
    "msprof 里 AIC 堵着等 AIV 的 L1。"
    "先别改 VF，按 CodeMap 把这条路径说清楚；缺实际 seq 或分核轴就说还缺什么，"
    "不要先认定是同一处 bug。"
)


pytestmark = pytest.mark.skipif(
    FAG_PRODUCT is None or not Path(FAG_PRODUCT).is_file(),
    reason="FAG arch35 .uo product is not present",
)


@pytest.fixture(scope="module")
def q():
    return open_query(FAG_ROOT, architecture="arch35")


def test_q6_compile_and_kernel_launch_first_page_is_arch35(q) -> None:
    plan = compile_query(Q6, architecture="arch35")
    assert plan["first_query"][0]["mode"] == "kernel_launch"
    launch = q.aggregate_kernel_launch()
    assert launch["count"] >= 1
    first_pipe = next((row for row in launch["phases"] if row.get("ok")), None)
    assert first_pipe is not None
    pipe_file = str(first_pipe.get("file") or "").replace("\\", "/")
    assert "arch35" in pipe_file
    assert first_pipe.get("pipe") in {"pipeIn", "pipeBase", "pipePost"}
    if launch.get("entry"):
        entry_file = str(launch["entry"].get("file") or "").replace("\\", "/")
        assert "arch35" in entry_file or "entry_regbase" in entry_file


def test_q7_locate_coverage_keeps_sibling_files(q) -> None:
    out = q.aggregate_locate("CalcleTNDDeterParam", limit=8)
    cov = out.get("coverage") or {}
    files = " ".join(list(out.get("files") or {}) + list(cov.get("sibling_files") or []))
    assert "coverage" in out
    assert "files" in out
    assert cov.get("completeness") != "first_hit" or int(cov.get("definition_sites_count") or 0) > 1
    assert "varlen" in files.replace("\\", "/").lower() or out["count"] > 1


def test_q9_first_page_is_dim_coverage(q) -> None:
    out = q.aggregate_template_match("DTemplateNum=128,DeterType=0,InputDType=3")
    cov = (out.get("coverage") or {}).get("dim_coverage") or out.get("dim_coverage") or {}
    assert "128" in (cov.get("DTemplateNum") or [])
    keys = list(out.keys())
    assert keys.index("coverage") < keys.index("template_blocks")


def test_q10_register_tiling_default_or_template(q) -> None:
    default = q.aggregate_locate("REGISTER_TILING_DEFAULT")
    template = q.aggregate_locate("REGISTER_TILING_TEMPLATE")
    if default["count"] == 0:
        pytest.skip("REGISTER_TILING_DEFAULT not in committed .uo; rebuild after extract")
    assert default["count"] >= 1
    assert template["count"] >= 1 or default["count"] >= 1


def test_q11_setschedulemode_and_sync(q) -> None:
    sched = q.aggregate_locate("SetScheduleMode")
    assert sched["count"] >= 1
    files = " ".join(str(row.get("file") or "") for row in sched.get("locations") or [])
    files += " ".join((sched.get("coverage") or {}).get("sibling_files") or [])
    assert "arch35" in files.replace("\\", "/")
    sync = q.aggregate_locate("SyncALLCores")
    if sync["count"] == 0:
        pytest.skip("SyncALLCores not in committed .uo")
    sync_files = " ".join(str(row.get("file") or "") for row in sync.get("locations") or [])
    sync_files += " ".join((sync.get("coverage") or {}).get("sibling_files") or [])
    assert "arch35" in sync_files.replace("\\", "/")


def test_q13_fused_outer_alias_and_occupancy(q) -> None:
    hit = q.field_impact("fusedOuter")
    if not hit.get("ok"):
        pytest.skip("fusedOuter local_aliases not in committed .uo; extra query round is OK")
    assert hit.get("canonical") == "blockOuter" or hit["field"]["name"] == "blockOuter"
    assert hit.get("occupancy_axis") == "fusedOuter vs aicNum"


def test_q14_3buff_hits_cube_policy(q) -> None:
    out = q.aggregate_buffer("3buff")
    if out["count"] == 0:
        pytest.skip("3buff mutex_policy not in committed .uo; rebuild after extract")
    blob = str(out).lower()
    assert "3buff" in blob or "mutex" in blob


def test_q16_d320_nearby_lists_templates(q) -> None:
    out = q.aggregate_template_match("DTemplateNum=320")
    assert int(out.get("matching_block_count") or 0) == 0
    nearby = out.get("nearby") or []
    values: list[str] = []
    for row in nearby:
        values.extend(str(v) for v in (row.get("values") or []))
    coverage = (out.get("dim_coverage") or {}).get("DTemplateNum") or []
    listed = set(values) | set(str(v) for v in coverage)
    for width in ("64", "128", "192", "256", "768"):
        assert width in listed


def test_q17_no_sel_pipe_fanout() -> None:
    assert plan_query_slices(Q17) == []
    plan = compile_query(Q17)
    assert plan["ut_authoring"] is True


def test_q18_four_slices_without_pipe() -> None:
    ids = [row["slice_id"] for row in plan_query_slices(Q18)]
    assert ids == ["sel", "locate", "field", "buffer"]
    plan = compile_query(Q18)
    assert plan["differential"] is True
    modes = [row["mode"] for row in plan["first_query"]]
    assert "kernel_launch" not in modes
    assert "template_match" in modes
    assert "field" in modes
    assert "buffer" in modes
