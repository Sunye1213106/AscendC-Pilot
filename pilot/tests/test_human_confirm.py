"""Host-owned human confirm: workflow-derived AskQuestion and receipts."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ascendc_pilot.human_confirm import (
    build_ask,
    grill_should_ask,
    hosted_confirm_should_ask,
    is_hosted_confirm,
    materialize_primary_decision,
)
from ascendc_pilot.human_interaction import issue_interaction_request, record_answer
from ascendc_pilot.human_voice import build_human_confirm_ask
from ascendc_pilot.paths import ce_root, runs_root, tg_root
from ascendc_pilot.state import load_state, start_workflow
from ascendc_pilot.user_goal import create_user_goal


@pytest.fixture(autouse=True)
def _isolate_uo_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UO_ARCH", raising=False)


def _ask(value: str = "confirm") -> dict:
    return {
        "header": "test",
        "question": "continue?",
        "options": [
            {"label": value, "value": value},
            {"label": "stop", "value": "stop"},
        ],
    }


def _write_session(tmp_path: Path, action_id: str, workflow_id: str) -> None:
    state = load_state(tmp_path) or {}
    run_id = str(state.get("run_id") or "")
    assert run_id
    sdir = runs_root(tmp_path) / run_id / "actions" / action_id
    sdir.mkdir(parents=True)
    (sdir / "session.yaml").write_text(
        yaml.safe_dump(
            {
                "action_id": action_id,
                "run_id": run_id,
                "workflow_id": workflow_id,
                "phase": "confirm",
                "actor_id": "ascendc-pilot",
                "role_id": "primary_interactive",
                "action_session_id": f"{run_id}:{action_id}",
                "lease_id": "lease-test",
                "prepare_nonce": "nonce-test",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_ce_plan_ask_is_not_tg_planning(tmp_path: Path) -> None:
    start_workflow(tmp_path, "ce-plan", phase="confirm", force_phase=True, architecture="arch35")
    ask = build_ask(
        tmp_path,
        {"workflow_id": "ce-plan", "op_name": "DemoOp", "architecture": "arch35"},
        action_id="human_confirm",
    )
    header = str(ask.get("header") or "")
    question = str(ask.get("question") or "")
    labels = [str(o.get("label") or "") for o in ask.get("options") or []]
    assert "覆盖合同" not in header
    assert "进入规划" not in header
    assert "计划" in header or "计划" in question
    assert any("ce-apply" in lb for lb in labels)
    assert not any("确认进入规划" in lb for lb in labels)


def test_legacy_human_confirm_ask_without_workflow_is_tg(tmp_path: Path) -> None:
    ask = build_human_confirm_ask(tmp_path, {"op_name": "DemoOp", "architecture": "arch35"})
    labels = [str(o.get("label") or "") for o in ask.get("options") or []]
    assert any("规划" in lb for lb in labels)


def test_ce_human_confirm_materialize_does_not_write_yaml(tmp_path: Path) -> None:
    start_workflow(tmp_path, "ce-plan", phase="confirm", force_phase=True, architecture="arch35")
    _write_session(tmp_path, "human_confirm", "ce-plan")
    env = issue_interaction_request(
        tmp_path,
        kind="primary_confirm",
        ask_question=_ask("confirm"),
        action_id="human_confirm",
        decision_kind="primary_confirm",
        allowed_values=["confirm", "rework", "stop"],
    )
    assert record_answer(tmp_path, request_id=env["request_id"], value="confirm").get("ok")

    out = materialize_primary_decision(tmp_path, "human_confirm")
    assert out.get("ok") is True
    ce_confirm = ce_root(tmp_path, arch="arch35") / "intent" / "confirmation.yaml"
    tg_confirm = tg_root(tmp_path, arch="arch35") / "init" / "confirmation.yaml"
    assert not ce_confirm.is_file()
    assert not tg_confirm.is_file()
    yaml_hits = list(ce_root(tmp_path, arch="arch35").rglob("*.yaml")) if ce_root(tmp_path, arch="arch35").exists() else []
    assert yaml_hits == []


def test_ce_apply_report_is_hosted(tmp_path: Path) -> None:
    start_workflow(tmp_path, "ce-apply", phase="report", force_phase=True, architecture="arch35")
    assert is_hosted_confirm(tmp_path, "apply_report")
    ask = build_ask(tmp_path, action_id="apply_report")
    header = str(ask.get("header") or "")
    values = [str(o.get("value") or "") for o in ask.get("options") or []]
    assert "改码" in header or "下一步" in header
    assert "review" in values
    assert "覆盖合同" not in header


def test_plan_approve_unique_without_workflow(tmp_path: Path) -> None:
    ask = build_ask(tmp_path, action_id="plan_approve")
    header = str(ask.get("header") or "")
    assert "规划" in header or "求解" in header
    values = [str(o.get("value") or "") for o in ask.get("options") or []]
    assert "approve" in values


def _write_grill_staging(tmp_path: Path, body: str) -> None:
    state = load_state(tmp_path) or {}
    run_id = str(state.get("run_id") or "")
    assert run_id
    sdir = runs_root(tmp_path) / run_id / "actions" / "intent_grill"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "staging.md").write_text(body, encoding="utf-8")


def test_grill_should_ask_skips_when_authorized_and_no_forks(tmp_path: Path) -> None:
    start_workflow(
        tmp_path,
        "ce-plan",
        phase="confirm",
        force_phase=True,
        architecture="arch35",
        intent="按这个写，直接出计划",
    )
    _write_grill_staging(
        tmp_path,
        "# 范围\n- kernel\n\n## 未决决策\n- 无\n",
    )
    state = load_state(tmp_path) or {}
    assert grill_should_ask(tmp_path, state, action_id="grill_confirm") is False
    assert hosted_confirm_should_ask(tmp_path, state, action_id="human_confirm") is False


def test_grill_should_ask_when_open_forks(tmp_path: Path) -> None:
    start_workflow(
        tmp_path,
        "ce-plan",
        phase="confirm",
        force_phase=True,
        architecture="arch35",
        intent="按这个写",
    )
    _write_grill_staging(
        tmp_path,
        "## 未决决策\n- 改 kernel 还是 tiling？推荐 kernel\n",
    )
    state = load_state(tmp_path) or {}
    assert grill_should_ask(tmp_path, state, action_id="grill_confirm") is True


def test_grill_should_ask_default_still_asks(tmp_path: Path) -> None:
    start_workflow(
        tmp_path,
        "ce-plan",
        phase="confirm",
        force_phase=True,
        architecture="arch35",
        intent="帮我整理一下需求",
    )
    state = load_state(tmp_path) or {}
    assert grill_should_ask(tmp_path, state, action_id="grill_confirm") is True


def test_hosted_confirm_skips_tg_on_full_coverage_goal(tmp_path: Path) -> None:
    start_workflow(
        tmp_path,
        "tg-init",
        phase="bind",
        force_phase=True,
        architecture="arch35",
        intent="补全量 TilingKey 覆盖测试",
    )
    create_user_goal(
        tmp_path,
        intent_text="补全量 TilingKey 覆盖测试",
        llm_intent={
            "objective_zh": "全量覆盖测试",
            "needed_capabilities": ["knowledge", "test_generation"],
            "source": {"kind": "local"},
        },
        architecture="arch35",
    )
    state = load_state(tmp_path) or {}
    assert hosted_confirm_should_ask(tmp_path, state, action_id="human_confirm") is False
    state["workflow_id"] = "tg-plan"
    assert hosted_confirm_should_ask(tmp_path, state, action_id="plan_approve") is False


def test_review_report_skips_when_goal_wants_tests(tmp_path: Path) -> None:
    start_workflow(
        tmp_path,
        "ce-review",
        phase="summary",
        force_phase=True,
        architecture="arch35",
        intent="审这个 PR 并生成针对性测例",
    )
    create_user_goal(
        tmp_path,
        intent_text="审这个 PR 并生成针对性测例",
        llm_intent={
            "objective_zh": "审查后生成测例",
            "needed_capabilities": ["knowledge", "change_analysis", "test_generation"],
            "source": {"kind": "pull_request"},
        },
        architecture="arch35",
    )
    state = load_state(tmp_path) or {}
    state["workflow_id"] = "ce-review"
    assert hosted_confirm_should_ask(tmp_path, state, action_id="review_report") is False


def test_review_report_asks_without_test_goal(tmp_path: Path) -> None:
    start_workflow(
        tmp_path,
        "ce-review",
        phase="summary",
        force_phase=True,
        architecture="arch35",
        intent="只做代码审查",
    )
    state = load_state(tmp_path) or {}
    assert hosted_confirm_should_ask(tmp_path, state, action_id="review_report") is True


def test_hosted_confirm_asks_tg_without_goal(tmp_path: Path) -> None:
    start_workflow(
        tmp_path,
        "tg-init",
        phase="bind",
        force_phase=True,
        architecture="arch35",
        intent="只绑定测试脚本",
    )
    state = load_state(tmp_path) or {}
    assert hosted_confirm_should_ask(tmp_path, state, action_id="human_confirm") is False
