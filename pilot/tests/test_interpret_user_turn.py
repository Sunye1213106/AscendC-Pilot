"""User turn vs pending AskQuestion: map options or supersede (never deadlock)."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.human_interaction import (
    interpret_user_turn,
    issue_interaction_request,
    load_pending,
    match_pending_option,
    pending_is_open,
    supersede_pending,
)
from ascendc_pilot.state import describe_next, load_state, save_state, start_workflow


def _ask_arch() -> dict:
    return {
        "header": "选择 architecture",
        "question": "用哪个 arch？",
        "options": [
            {"label": "arch35", "value": "arch35"},
            {"label": "arch22", "value": "arch22"},
        ],
    }


def _ask_resume() -> dict:
    return {
        "header": "继续上次还是删除重开？",
        "question": "已有未完成 run",
        "options": [
            {"label": "继续上次", "value": "continue"},
            {"label": "删除重开", "value": "reinit"},
            {"label": "去查询", "value": "query"},
        ],
    }


def test_match_arch_token_and_reject_long_offtopic(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    env = issue_interaction_request(
        tmp_path,
        kind="intake",
        ask_question=_ask_arch(),
        decision_kind="architecture",
        allowed_values=["arch35", "arch22"],
    )
    pending = {
        "status": "pending",
        "request_id": env["request_id"],
        "allowed_values": ["arch35", "arch22"],
        "ask_question": _ask_arch(),
    }
    assert match_pending_option(pending, "用 arch35") == "arch35"
    assert match_pending_option(pending, "arch22") == "arch22"
    assert match_pending_option(pending, "s1Inner 这条路径怎么切，先别建库") is None


def test_interpret_answers_then_supersedes_new_intent(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    issue_interaction_request(
        tmp_path,
        kind="intake",
        ask_question=_ask_arch(),
        decision_kind="architecture",
        allowed_values=["arch35", "arch22"],
    )
    answered = interpret_user_turn(tmp_path, text="用 arch35 吧")
    assert answered.get("ok") is True
    assert answered.get("disposition") == "answered"
    assert answered.get("value") == "arch35"
    assert answered.get("needs_human_decision") is False

    issue_interaction_request(
        tmp_path,
        kind="resume",
        ask_question=_ask_resume(),
        decision_kind="resume",
        allowed_values=["continue", "reinit", "query"],
    )
    moved = interpret_user_turn(
        tmp_path, text="先别确认了，这个算子 s1Inner 是怎么算的？"
    )
    assert moved.get("ok") is True
    assert moved.get("disposition") == "superseded"
    assert moved.get("needs_human_decision") is False
    assert pending_is_open(load_pending(tmp_path)) is False

    st = load_state(tmp_path) or {}
    assert st.get("human_decision_superseded") is True
    nxt = describe_next(tmp_path)
    assert not nxt.get("ask_question")
    assert nxt.get("needs_human_decision") is not True


def test_interpret_does_not_treat_offtopic_as_reinit(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    issue_interaction_request(
        tmp_path,
        kind="resume",
        ask_question=_ask_resume(),
        decision_kind="resume",
        allowed_values=["continue", "reinit", "query"],
    )
    out = interpret_user_turn(tmp_path, text="这个算子的 tiling 怎么切，先回答问题")
    assert out.get("disposition") == "superseded"
    assert out.get("value") not in {"reinit", "continue"}


def test_interpret_maps_continue_alias(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    issue_interaction_request(
        tmp_path,
        kind="resume",
        ask_question=_ask_resume(),
        decision_kind="resume",
        allowed_values=["continue", "reinit", "query"],
    )
    out = interpret_user_turn(tmp_path, text="继续上次")
    assert out.get("ok") is True
    assert out.get("disposition") == "answered"
    assert out.get("value") == "continue"


def test_supersede_then_describe_next_human_required_does_not_reask(
    tmp_path: Path,
) -> None:
    start_workflow(tmp_path, "tg-init", phase="confirm", force_phase=True, architecture="arch35")
    state = load_state(tmp_path) or {}
    state["status"] = "human_required"
    state["last_failure"] = {"error_code": "ORACLE_SUSPECT", "message_zh": "需要人工介入"}
    save_state(tmp_path, state)
    issue_interaction_request(
        tmp_path,
        kind="human_required",
        ask_question={
            "header": "tg-init 需要人工介入",
            "question": "请选择",
            "options": [
                {"label": "终止本次运行", "value": "abort_run"},
                {"label": "查看失败", "value": "inspect_failure"},
            ],
        },
        allowed_values=["abort_run", "inspect_failure"],
    )
    before = describe_next(tmp_path)
    assert before.get("ask_question")
    supersede_pending(tmp_path, reason="user_interrupted", user_text="换个问题")
    after = describe_next(tmp_path)
    assert not after.get("ask_question")
    assert after.get("needs_human_decision") is not True
    assert "打断" in str(after.get("message_zh") or after.get("primary_instruction_zh") or "")
