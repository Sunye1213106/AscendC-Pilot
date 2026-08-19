"""HumanDecisionReceipt broker: issue → answer → require/consume."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.actions.tg_primary import materialize_primary_decision
from ascendc_pilot.human_interaction import (
    issue_interaction_request,
    record_answer,
    require_decision_receipt,
)
from ascendc_pilot.paths import runs_root
from ascendc_pilot.state import load_state, start_workflow


def _ask(value: str = "confirm") -> dict:
    return {
        "header": "test",
        "question": "continue?",
        "options": [
            {"label": value, "value": value},
            {"label": "stop", "value": "stop"},
        ],
    }


def test_issue_answer_require_consumes_receipt(tmp_path: Path) -> None:
    start_workflow(tmp_path, "tg-init", phase="confirm", force_phase=True, architecture="arch35")
    env = issue_interaction_request(
        tmp_path,
        kind="primary_confirm",
        ask_question=_ask("confirm"),
        action_id="human_confirm",
        decision_kind="primary_confirm",
        allowed_values=["confirm", "stop"],
    )
    answered = record_answer(tmp_path, request_id=env["request_id"], value="confirm")
    assert answered.get("ok") is True
    assert answered.get("value") == "confirm"

    required = require_decision_receipt(
        tmp_path,
        expected_values=["confirm"],
        expected_action_id="human_confirm",
        expected_kind="primary_confirm",
        consume=True,
    )
    assert required.get("ok") is True
    assert required.get("value") == "confirm"

    # Consumed: second require fails closed.
    again = require_decision_receipt(
        tmp_path,
        expected_values=["confirm"],
        expected_action_id="human_confirm",
        expected_kind="primary_confirm",
        consume=True,
    )
    assert again.get("ok") is False
    assert again.get("error") in {
        "HUMAN_DECISION_RECEIPT_REQUIRED",
        "HUMAN_DECISION_RECEIPT_CONSUMED",
    }


def test_require_without_receipt_and_materialize(tmp_path: Path) -> None:
    start_workflow(
        tmp_path, "tg-init", phase="confirm", force_phase=True, architecture="arch35"
    )
    missing = require_decision_receipt(tmp_path, expected_values=["confirm"])
    assert missing.get("ok") is False
    assert missing.get("error") == "HUMAN_DECISION_RECEIPT_REQUIRED"

    # Prepared session present, but no receipt → materialize fails with receipt error.
    state = load_state(tmp_path) or {}
    run_id = str(state.get("run_id") or "")
    assert run_id
    sdir = runs_root(tmp_path) / run_id / "actions" / "human_confirm"
    sdir.mkdir(parents=True)
    (sdir / "session.yaml").write_text(
        yaml.safe_dump(
            {
                "action_id": "human_confirm",
                "run_id": run_id,
                "workflow_id": "tg-init",
                "phase": "confirm",
                "actor_id": "ascendc-pilot",
                "role_id": "primary_interactive",
                "action_session_id": f"{run_id}:human_confirm",
                "lease_id": "lease-test",
                "prepare_nonce": "nonce-test",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    out = materialize_primary_decision(tmp_path, "human_confirm")
    assert out.get("ok") is False
    # Expert /tg-init skips AskQuestion, so finalize goes to the domain gate.
    # Without init.yaml the confirm still fails closed.
    assert out.get("error") in {
        "HUMAN_DECISION_RECEIPT_REQUIRED",
        "INIT_CONFIRM_DOMAIN_GATE_FAILED",
        "INIT_YAML_MISSING",
    }


def test_require_expected_values_retry_mismatch(tmp_path: Path) -> None:
    """Retry path: wrong affirmative value is rejected (must re-AskQuestion)."""
    start_workflow(tmp_path, "tg-plan", phase="approve", force_phase=True, architecture="arch35")
    env = issue_interaction_request(
        tmp_path,
        kind="primary_approve",
        ask_question=_ask("rework"),
        action_id="plan_approve",
        decision_kind="primary_approve",
        allowed_values=["approve", "rework", "stop"],
    )
    answered = record_answer(tmp_path, request_id=env["request_id"], value="rework")
    assert answered.get("ok") is True

    # Affirmative finalize expects approve — rework must not pass.
    bad = require_decision_receipt(
        tmp_path,
        expected_values=["approve"],
        expected_action_id="plan_approve",
        expected_kind="primary_approve",
        consume=True,
    )
    assert bad.get("ok") is False
    assert bad.get("error") == "HUMAN_DECISION_RECEIPT_VALUE_MISMATCH"


def test_record_answer_without_pending_includes_path(tmp_path: Path) -> None:
    missed = record_answer(tmp_path, request_id="nope", value="confirm")
    assert missed.get("ok") is False
    assert missed.get("error") == "NO_PENDING_INTERACTION"
    assert "pending_interaction_path" in missed
    assert "pending_interaction.yaml" in str(missed.get("pending_interaction_path") or "")
