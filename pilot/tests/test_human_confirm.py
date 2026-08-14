"""Host-owned human confirm: workflow-derived AskQuestion and receipts."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ascendc_pilot.human_confirm import (
    build_ask,
    is_hosted_confirm,
    materialize_primary_decision,
)
from ascendc_pilot.human_interaction import issue_interaction_request, record_answer
from ascendc_pilot.human_voice import build_human_confirm_ask
from ascendc_pilot.paths import ce_root, runs_root, tg_root
from ascendc_pilot.state import load_state, start_workflow


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


def test_ce_intent_ask_is_not_tg_planning(tmp_path: Path) -> None:
    start_workflow(tmp_path, "ce-intent", phase="confirm", force_phase=True, architecture="arch35")
    ask = build_ask(
        tmp_path,
        {"workflow_id": "ce-intent", "op_name": "DemoOp", "architecture": "arch35"},
        action_id="human_confirm",
    )
    header = str(ask.get("header") or "")
    question = str(ask.get("question") or "")
    labels = [str(o.get("label") or "") for o in ask.get("options") or []]
    assert "覆盖合同" not in header
    assert "进入规划" not in header
    assert "变更计划" in header or "变更计划" in question
    assert any("确认变更计划" in lb for lb in labels)
    assert not any("确认进入规划" in lb for lb in labels)


def test_legacy_human_confirm_ask_without_workflow_is_tg(tmp_path: Path) -> None:
    ask = build_human_confirm_ask(tmp_path, {"op_name": "DemoOp", "architecture": "arch35"})
    labels = [str(o.get("label") or "") for o in ask.get("options") or []]
    assert any("规划" in lb for lb in labels)


def test_ce_human_confirm_materialize_writes_ce_not_tg(tmp_path: Path) -> None:
    start_workflow(tmp_path, "ce-intent", phase="confirm", force_phase=True, architecture="arch35")
    _write_session(tmp_path, "human_confirm", "ce-intent")
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
    assert ce_confirm.is_file()
    assert not tg_confirm.is_file()
    doc = yaml.safe_load(ce_confirm.read_text(encoding="utf-8"))
    assert doc.get("schema") == "ce-intent-confirmation/v1"
    assert doc.get("status") == "confirmed"


def test_scenario_confirm_is_hosted(tmp_path: Path) -> None:
    start_workflow(tmp_path, "ce-impact", phase="scenarios", force_phase=True, architecture="arch35")
    assert is_hosted_confirm(tmp_path, "scenario_confirm")
    ask = build_ask(tmp_path, action_id="scenario_confirm")
    header = str(ask.get("header") or "")
    assert "场景" in header
    assert "覆盖合同" not in header


def test_scenario_plan_unique_without_workflow(tmp_path: Path) -> None:
    ask = build_ask(tmp_path, action_id="scenario_plan")
    header = str(ask.get("header") or "")
    assert "场景" in header
    values = [str(o.get("value") or "") for o in ask.get("options") or []]
    assert "confirm" in values
