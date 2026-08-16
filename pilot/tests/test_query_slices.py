# -*- coding: utf-8 -*-
from __future__ import annotations

from ascendc_pilot.query_slices import focused_user_question, plan_query_slices


Q9 = "950 上某 FP16、D=80、带 dropout 的 case 报 kernel 找不到。host 算出的 TilingKey 在 ASCENDC_TPL_SEL 里一定有吗？"

Q7 = "确定性开了，连跑 7 次 dK 对不齐，dQ 齐。先别改 VF。是 DETER_DENSE 的坐标分核没生效，还是 POST 多核写回顺序，还是 TND prefix 没带上？"

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


def test_single_sel_question_does_not_fanout() -> None:
    assert plan_query_slices(Q9) == []


def test_single_tnd_question_does_not_fanout() -> None:
    assert plan_query_slices(Q7) == []


def test_q13_occupancy_alone_does_not_fanout() -> None:
    q13 = (
        "B=1,N=4,S=2048 只有 4 个 AIC 在干活，vendor 几乎打满。"
        "是核内 VF 慢，还是分核轴错了？fusedOuter 在 BN2GS1S2 / BN2 / BN2S2 里分别乘了什么？"
    )
    assert plan_query_slices(q13) == []


def test_q18_fans_out_independent_slices() -> None:
    slices = plan_query_slices(Q18)
    ids = [row["slice_id"] for row in slices]
    assert len(ids) >= 2
    assert "sel" in ids
    assert "locate" in ids
    assert "field" in ids
    assert "buffer" in ids
    assert "pipe" not in ids
    assert len(ids) >= 2
    assert len(ids) <= 5
    modes = [row["first_mode"] for row in slices]
    assert len(modes) == len(set(modes))


def test_focused_question_gates_child() -> None:
    row = {"slice_id": "sel", "focus": "SEL", "first_mode": "template_match"}
    text = focused_user_question(Q18, row)
    assert "SLICE_ID=sel" in text
    assert "FOCUS (this child only): SEL" in text
    assert "First mode: template_match" in text
    assert "Answer ONLY this slice" in text
    assert "FIRST_QUERY:" in text
    assert "Do not inherit" in text


Q6 = (
    "FP16 精度不过：dq 量级差一截，FP32 同 shape 过了。"
    "是不是 POST 的 scale/cast 写错了？先画出 arch35 单 launch 的三相，"
    "并说明 FP32 / BN2 / enablePreSfmg 各自怎么走。"
)

Q17 = (
    "tests/ut/op_host/arch35/test_flash_attention_score_grad_tiling.cpp "
    "要补“一改就静默错”的 case。列 5 个，每个说期望的 splitAxis / "
    "deterSparseType / enablePreSfmg / isTndSwizzle / isNzOut，"
    "以及断言哪个 TilingData 子结构存在。"
)


def test_q6_compiles_to_kernel_launch() -> None:
    from ascendc_pilot.query_slices import compile_query

    plan = compile_query(Q6, architecture="arch35")
    assert plan["first_query"]
    assert plan["first_query"][0]["mode"] == "kernel_launch"
    assert plan["differential"] is True
    assert "根因已定位" in (plan["answer_contract"].get("forbid") or [])
    assert plan_query_slices(Q6) == []


def test_q17_ut_authoring_does_not_fanout_sel_or_pipe() -> None:
    from ascendc_pilot.query_slices import compile_query, is_ut_authoring

    assert is_ut_authoring(Q17)
    assert plan_query_slices(Q17) == []
    plan = compile_query(Q17)
    modes = {row["mode"] for row in plan["first_query"]}
    assert "template_match" not in modes
    assert "kernel_launch" not in modes
    ids = [row.get("slice_id") for row in plan["slices"]]
    assert "sel" not in ids
    assert "pipe" not in ids


def test_q18_focused_stub_has_first_query_and_no_bleed() -> None:
    row = {
        "slice_id": "sel",
        "focus": "SEL",
        "first_mode": "template_match",
        "canonical": "dim_coverage",
    }
    text = focused_user_question(Q18, row)
    assert "FIRST_QUERY: acp uo-query --mode template_match" in text
    assert "Do not inherit hypotheses" in text
    assert "根因已定位" in text


def test_q18_first_query_tokens_come_from_question() -> None:
    from ascendc_pilot.query_slices import compile_query

    plan = compile_query(Q18)
    blob = str(plan["first_query"])
    assert "3buff" not in blob
    assert "blockOuter" not in blob
    assert "CalcleTNDDeterParam" not in blob
    assert "RegbaseFAG" not in blob
    assert "enablePreSfmg" not in blob
    by_mode = {row["mode"]: row for row in plan["first_query"]}
    assert by_mode["buffer"]["pattern"] != "3buff"
    assert by_mode["field"]["pattern"] != "blockOuter"


def test_q13_first_query_uses_mentioned_ident() -> None:
    from ascendc_pilot.query_slices import compile_query

    q13 = (
        "B=1,N=4,S=2048 只有 4 个 AIC 在干活，vendor 几乎打满。"
        "是核内 VF 慢，还是分核轴错了？fusedOuter 在 BN2GS1S2 / BN2 / BN2S2 里分别乘了什么？"
    )
    plan = compile_query(q13)
    assert plan["first_query"][0]["mode"] == "field"
    assert plan["first_query"][0]["pattern"] == "fusedOuter"


def test_rewritten_intent_would_add_pipe_so_prepare_must_keep_original() -> None:
    rewritten = Q18 + " 先画出三相 launch 和 SyncALLCores。"
    orig_ids = [row["slice_id"] for row in plan_query_slices(Q18)]
    rewrite_ids = [row["slice_id"] for row in plan_query_slices(rewritten)]
    assert orig_ids == ["sel", "locate", "field", "buffer"]
    assert "pipe" not in orig_ids
    assert "pipe" in rewrite_ids


def test_q11_hang_compiles_to_locate_setschedulemode() -> None:
    from ascendc_pilot.query_slices import compile_query

    q11 = (
        "偶发 hang，plog 停在 Pre 末尾 SyncALLCores。有人说 BufferID 没配对。"
        "arch35 为什么 PostTiling 要 SetScheduleMode(1)？哪条路径故意不设？"
        "AIC/AIV dummy 和 CrossCore flag 怎么配？"
    )
    ids = [row["slice_id"] for row in plan_query_slices(q11)]
    assert "pipe" not in ids
    assert "locate" in ids
    plan = compile_query(q11)
    assert plan["first_query"][0]["mode"] == "locate"
    assert plan["first_query"][0]["pattern"] == "SetScheduleMode"
