"""human_required / auto must surface AskQuestion for every workflow."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.drive import drive_until_interaction
from ascendc_pilot.state import describe_next, load_state, save_state, start_workflow


def test_describe_next_header_uses_workflow_id(tmp_path: Path) -> None:
    start_workflow(tmp_path, "tg-init", phase="bind", force_phase=True, architecture="arch35")
    state = load_state(tmp_path) or {}
    state["status"] = "human_required"
    state["last_failure"] = {
        "error_code": "ORACLE_SUSPECT",
        "message_zh": "需要人工介入",
    }
    save_state(tmp_path, state)
    nxt = describe_next(tmp_path)
    ask = nxt.get("ask_question") or {}
    assert nxt.get("needs_human_decision") is True
    assert "tg-init" in str(ask.get("header") or "")
    assert "uo-init" not in str(ask.get("header") or "")
    values = {o.get("value") for o in (ask.get("options") or []) if isinstance(o, dict)}
    assert "retry_after_environment_fix" in values
    msg = str(nxt.get("human_required", {}).get("message_zh") or nxt.get("message_zh") or "")
    assert "推荐" in msg
    assert "换话题" in msg
    assert "ORACLE_SUSPECT" in msg or "需要人工介入" in msg


def test_auto_drive_surfaces_ask_question_on_human_required(tmp_path: Path) -> None:
    start_workflow(tmp_path, "tg-solve", phase="analyze", force_phase=True, architecture="arch35")
    state = load_state(tmp_path) or {}
    state["status"] = "human_required"
    state["last_failure"] = {
        "error_code": "PROOF_BLOCKED",
        "message_zh": "引理受阻",
    }
    save_state(tmp_path, state)

    def _prepare(_root: Path, _action_id: str) -> dict:
        raise AssertionError("auto must not prepare when status != running")

    out = drive_until_interaction(tmp_path, prepare=_prepare, max_steps=2)
    assert out.get("stopped") is True
    assert out.get("ask_question"), out
    assert out.get("needs_human_decision") is True
    assert "tg-solve" in str((out.get("ask_question") or {}).get("header") or "")
