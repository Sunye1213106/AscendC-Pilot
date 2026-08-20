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
    start_workflow(tmp_path, "tg-init", phase="scan", force_phase=True, architecture="arch35")
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


def test_interpret_user_turn_adopts_path_inside_chinese(tmp_path: Path) -> None:
    from ascendc_pilot.paths import ensure_agent_layout

    ensure_agent_layout(tmp_path, arch="arch35")
    repo = tmp_path / "fag_debug_tools"
    repo.mkdir()
    start_workflow(tmp_path, "tg-init", architecture="arch35")
    text = f"{repo} 这个才是真正的测试脚本仓"
    out = interpret_user_turn(tmp_path, text=text)
    assert out.get("ok") is True, out
    state = load_state(tmp_path) or {}
    assert Path(str(state.get("test_script_root") or "")).resolve() == repo.resolve()


def _ask_harness() -> dict:
    return {
        "header": "选择测试仓",
        "question": "尚未确认 test_script_root",
        "options": [
            {"label": "没有测试仓，由 Agent 按算子约束生成", "value": "no_repo_uo_query"},
            {"label": "有外部测试仓，或其他想法：在下面输入", "value": "custom"},
        ],
        "allow_free_text": True,
        "field": "test_script_root",
    }


def test_interpret_pending_harness_adopts_git_url(tmp_path: Path, monkeypatch) -> None:
    import sys

    from ascendc_pilot.paths import ensure_agent_layout

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw

    ensure_agent_layout(tmp_path, arch="arch35")
    dest = tmp_path / "cloned_harness"
    dest.mkdir()
    start_workflow(tmp_path, "tg-init", architecture="arch35")
    issue_interaction_request(
        tmp_path,
        kind="human_required",
        ask_question=_ask_harness(),
        decision_kind="test_script_root",
        allowed_values=["no_repo_uo_query", "custom"],
        action_id="repo_scan",
    )
    monkeypatch.setattr(
        gw,
        "clone_harness_repo",
        lambda url, *, project_root: {"ok": True, "path": str(dest.resolve()), "cloned": True},
    )
    out = interpret_user_turn(
        tmp_path, text="用这个仓 https://gitcode.com/foo/bar 吧"
    )
    assert out.get("ok") is True, out
    assert out.get("disposition") == "answered"
    state = load_state(tmp_path) or {}
    assert Path(str(state.get("test_script_root") or "")).resolve() == dest.resolve()


def test_interpret_pending_harness_interrupt_nl_supersedes(tmp_path: Path) -> None:
    from ascendc_pilot.paths import ensure_agent_layout

    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "tg-init", architecture="arch35")
    issue_interaction_request(
        tmp_path,
        kind="human_required",
        ask_question=_ask_harness(),
        decision_kind="test_script_root",
        allowed_values=["no_repo_uo_query", "custom"],
        action_id="repo_scan",
    )
    out = interpret_user_turn(tmp_path, text="先别测了，这个算子 s1Inner 怎么切")
    assert out.get("ok") is True, out
    assert out.get("error") != "NOT_A_DIRECTORY"
    assert out.get("disposition") == "superseded"
    assert pending_is_open(load_pending(tmp_path)) is False


def test_parse_git_repo_url_rejects_pr() -> None:
    import sys

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw

    ok = gw.parse_git_repo_url("https://gitcode.com/cann/ops-transformer")
    assert ok.get("ok") is True
    pr = gw.parse_git_repo_url(
        "https://gitcode.com/cann/ops-transformer/pulls/9851"
    )
    assert pr.get("ok") is False
    assert pr.get("error") == "GIT_URL_IS_PR"
