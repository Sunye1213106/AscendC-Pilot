"""UO update resolve boundary after retiring per-KEY model agents."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import start_workflow
from ascendc_pilot.workflows import actions_for_phase, phase_pipeline
from ascendc_pilot.workflows.pipeline import recommend_next_action


def test_uo_update_resolve_actions_are_deterministic() -> None:
    actions = actions_for_phase("uo-update", "resolve")
    assert actions
    for action in actions:
        assert action.get("execution_mode") == "deterministic"
        assert not action.get("agent_id")
        assert not action.get("task_prompt_id")
        assert action.get("actors") == []


def test_uo_init_has_no_resolve_phase() -> None:
    assert phase_pipeline("uo-init", "resolve") == []
    assert actions_for_phase("uo-init", "resolve") == []
    pipe = phase_pipeline("uo-init", "verify")
    assert pipe == ["verify"]
    actions = {action["id"]: action for action in actions_for_phase("uo-init", "verify")}
    assert actions["verify"]["execution_mode"] == "deterministic"
    assert not actions["verify"].get("agent_id")


def test_uo_investigate_has_readonly_gap_investigator() -> None:
    pipe = phase_pipeline("uo-investigate", "investigate")
    assert pipe == ["investigate"]
    actions = {action["id"]: action for action in actions_for_phase("uo-investigate", "investigate")}
    assert actions["investigate"]["agent_id"] == "uo-gap-investigator"
    assert actions["investigate"]["execution_mode"] == "subagent"
    assert actions["investigate"]["task_prompt_id"] == "uo/investigate-gaps"


def test_recommend_uo_update_resolve_starts_at_first_engine_action(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-update", phase="resolve", force_phase=True)
    allowed = actions_for_phase("uo-update", "resolve")
    rec = recommend_next_action(
        tmp_path,
        workflow_id="uo-update",
        phase="resolve",
        allowed_actions=allowed,
    )
    assert rec and rec["id"] == phase_pipeline("uo-update", "resolve")[0]
