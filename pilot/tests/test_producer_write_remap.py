"""Producer writes must succeed even when hooks mislabel agent as primary."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.authorize import authorize
from ascendc_pilot.authorize import _project_root_for_path, _remap_primary_actor
from ascendc_pilot.paths import agent_root, ensure_agent_layout
from ascendc_pilot.state import start_workflow
from ascendc_pilot.actions.runtime import _write_active_action


def test_project_root_extracted_from_write_path(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    write_path = op / ".ascendc-pilot" / "uo" / "ir" / "extract_plan.yaml"
    wrong_root = tmp_path  # workspace parent without active_action
    resolved = _project_root_for_path(wrong_root, str(write_path))
    assert resolved == op.resolve()


def test_remap_primary_to_prepared_producer(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "uo-init", phase="extract", force_phase=True)
    _write_active_action(
        op,
        {
            "action_id": "extract_plan",
            "actor_id": "uo-semantic-resolve",
            "workflow_id": "uo-init",
            "phase": "extract",
            "status": "prepared",
        },
    )
    agent, action = _remap_primary_actor(op, "ascendc-pilot", "extract_plan")
    assert agent == "uo-semantic-resolve"
    assert action == "extract_plan"


def test_primary_mislabeled_write_allowed_via_active_action(tmp_path: Path) -> None:
    """Simulates OpenCode hook reporting agent=ascendc-pilot on producer write."""
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "uo-init", phase="extract", force_phase=True)
    _write_active_action(
        op,
        {
            "action_id": "extract_plan",
            "actor_id": "uo-semantic-resolve",
            "workflow_id": "uo-init",
            "phase": "extract",
            "status": "prepared",
        },
    )
    target = agent_root(op) / "uo" / "ir" / "extract_plan.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)

    # Wrong project_root (parent) + primary agent label — previously PRIMARY_PROTECTED_WRITE
    verdict = authorize(
        tmp_path,
        tool="write",
        path=str(target),
        agent="ascendc-pilot",
        action="extract_plan",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("ok") is not False


def test_primary_still_blocked_without_active_producer(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "uo-init", phase="extract", force_phase=True)
    # No active_action / or primary is the declared actor for scope only
    target = agent_root(op) / "uo" / "ir" / "extract_plan.yaml"
    verdict = authorize(
        op,
        tool="write",
        path=str(target),
        agent="ascendc-pilot",
        action="extract_plan",
    )
    assert verdict.get("decision") == "deny"
    assert verdict.get("reason_code") == "PRIMARY_PROTECTED_WRITE"
