"""Human-voice contract + user-goal + tg-init-audit METHOD materialization."""

from __future__ import annotations

from pathlib import Path

import pytest

from ascendc_pilot.actions.runtime import _load_method_and_prompt
from ascendc_pilot.human_voice import (
    build_human_confirm_ask,
    build_plan_approve_ask,
    contains_banned_jargon,
    progress_zh,
)
from ascendc_pilot.user_goal import (
    create_user_goal,
    mark_workflow_passed,
    progress_line_zh,
)


ROOT = Path(__file__).resolve().parents[2]


def test_banned_jargon_detects_internal_fields() -> None:
    assert "conditional_pass" in contains_banned_jargon("status conditional_pass ok")
    assert "exactness" in contains_banned_jargon("check exactness empty")
    assert "reads" in contains_banned_jargon("empty reads list")
    assert "status=None" in contains_banned_jargon("finalize status=None")
    assert contains_banned_jargon("覆盖合同已建立，约 8705 个合法 Key") == []


def test_ask_question_has_intent_and_consequences(tmp_path: Path) -> None:
    create_user_goal(
        tmp_path,
        intent_text="为这个 PR 生成针对性测试用例",
        llm_intent={
            "objective_zh": "生成针对性测试用例",
            "needed_capabilities": ["knowledge", "change_analysis", "test_generation"],
            "source": {"kind": "local"},
        },
        architecture="arch35",
        op_name="FlashAttentionScoreGrad",
    )
    ask = build_human_confirm_ask(
        tmp_path,
        {"op_name": "FlashAttentionScoreGrad", "architecture": "arch35"},
    )
    q = str(ask.get("question") or "")
    assert "目标" in q
    assert "请你决定" in q
    assert "选「" in q
    assert contains_banned_jargon(q) == []
    assert contains_banned_jargon(str(ask.get("header") or "")) == []
    labels = [str(o.get("label") or "") for o in ask.get("options") or []]
    assert any("规划" in lb for lb in labels)
    for lb in labels:
        assert contains_banned_jargon(lb) == []

    ask2 = build_plan_approve_ask(
        tmp_path,
        {"op_name": "FlashAttentionScoreGrad", "architecture": "arch35"},
    )
    q2 = str(ask2.get("question") or "")
    assert "目标" in q2 and "请你决定" in q2
    assert contains_banned_jargon(q2) == []


def test_progress_template_structure() -> None:
    text = progress_zh(
        goal="全量 TilingKey 覆盖测试",
        just_done="覆盖合同已建立",
        next_step="规划测试义务",
    )
    assert "【目标】" in text
    assert "【刚完成】" in text
    assert "【下一步】" in text


def test_bind_init_is_staged_analyst_with_method() -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    action = next(a for a in WORKFLOWS["tg-init"]["actions"] if a["id"] == "bind_init")
    assert action["execution_mode"] == "subagent"
    assert action["agent_id"] == "tg-analyst"
    assert action.get("action_method_id") == "testcase-generation/bind-init"
    method, prompt = _load_method_and_prompt(ROOT, action)
    assert method.strip(), "METHOD.md must be non-empty"
    assert "init.yaml" in method
    assert prompt.strip()


def test_bind_init_method_file_exists() -> None:
    path = (
        ROOT
        / "skills"
        / "testcase-generation"
        / "capabilities"
        / "bind-init"
        / "METHOD.md"
    )
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "mapping" in text.lower() or "列" in text


def test_ce_capability_methods_load_from_action_method_id() -> None:
    plan, prompt = _load_method_and_prompt(
        ROOT,
        {
            "task_prompt_id": "ce/plan-draft",
            "action_method_id": "code-engineering/ce-plan-draft",
            "id": "plan_draft",
        },
    )
    assert "plan.md" in plan or "{slug}" in plan
    assert prompt.strip()
    assert "Open = O - V - X" not in plan

    apply_m, apply_prompt = _load_method_and_prompt(
        ROOT,
        {
            "task_prompt_id": "ce/apply",
            "action_method_id": "code-engineering/ce-apply",
            "id": "patch",
        },
    )
    assert apply_m.strip()
    assert apply_prompt.strip()

    missing, missing_prompt = _load_method_and_prompt(
        ROOT,
        {
            "task_prompt_id": "ce/impact-audit",
            "action_method_id": "code-engineering/ce-impact-audit",
            "id": "impact_audit",
        },
    )
    assert missing == ""
    assert missing_prompt == ""


def test_deterministic_plan_precheck_loads_no_prompt() -> None:
    method, prompt = _load_method_and_prompt(
        ROOT,
        {
            "task_prompt_id": None,
            "action_method_id": None,
            "id": "plan_precheck",
        },
    )
    assert prompt == ""
    assert method == ""


def test_user_goal_match_and_advance(tmp_path: Path) -> None:
    from ascendc_pilot.planning.task_plan import plan_for, write_task_plan

    llm_intent = {
        "objective_zh": "生成针对性测试用例",
        "needed_capabilities": ["knowledge", "test_generation"],
        "source": {"kind": "local"},
    }
    goal = create_user_goal(
        tmp_path,
        intent_text="帮我生成对应 case",
        llm_intent=llm_intent,
        architecture="arch35",
        op_name="DemoOp",
    )
    assert goal is not None
    assert goal["schema"] == "pilot-user-goal/v2"
    assert "test_generation" in goal["intent"]["needed_capabilities"]
    plan = plan_for(llm_intent, {"has_uo": True, "uo_stale": False})
    write_task_plan(tmp_path, plan)
    line = progress_line_zh(goal)
    assert line

    adv = mark_workflow_passed(tmp_path, "tg-init")
    assert adv is not None
    assert adv["next_workflow_id"] == "tg-plan"
    assert contains_banned_jargon(str(adv.get("message_zh") or "")) == []

    adv2 = mark_workflow_passed(tmp_path, "tg-plan")
    assert adv2 is not None
    assert adv2["next_workflow_id"] == "tg-solve"

    adv3 = mark_workflow_passed(tmp_path, "tg-solve")
    assert adv3 is not None
    assert adv3.get("completed") is True


def test_tg_init_phase_labels_honest() -> None:
    from ascendc_pilot.workflows import get_workflow

    tg = get_workflow("tg-init")
    states = {s["id"]: s["label_zh"] for s in tg["states"]}
    assert "意图确认" not in states.values()
    assert states["kb_ready"] == "校验知识库"
    assert states["confirm"] == "确认进入规划"
    acts = {a["id"]: a["label_zh"] for a in tg["actions"]}
    assert acts["repo_scan"] == "扫描测试脚本仓（含 xls/xlsx）"
    assert acts["human_confirm"] == "确认进入规划"


def test_human_voice_invariants_doc_exists() -> None:
    path = ROOT / "pilot" / "policies" / "invariants" / "human-voice-invariants.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "意图" in text and "决策后果" in text
    assert "conditional_pass" in text
