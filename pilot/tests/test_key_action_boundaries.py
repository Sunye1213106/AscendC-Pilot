"""UO update pipeline boundaries after retiring resolve stub chain."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import start_workflow
from ascendc_pilot.workflows import WORKFLOWS, actions_for_phase, phase_pipeline
from ascendc_pilot.workflows.pipeline import recommend_next_action


def test_uo_update_has_no_resolve_phase() -> None:
    assert "resolve" not in (WORKFLOWS["uo-update"].get("phases") or [])
    assert phase_pipeline("uo-update", "resolve") == []
    assert actions_for_phase("uo-update", "resolve") == []


def test_uo_update_pipeline_is_detect_plan_apply_export_diff() -> None:
    assert WORKFLOWS["uo-update"]["phases"] == [
        "detect",
        "plan",
        "apply",
        "export",
        "diff",
    ]
    assert phase_pipeline("uo-update", "detect") == ["detect_changes"]
    assert phase_pipeline("uo-update", "plan") == ["plan_update"]
    assert phase_pipeline("uo-update", "apply") == ["apply_update"]
    assert phase_pipeline("uo-update", "export") == ["export_integrity"]
    assert phase_pipeline("uo-update", "diff") == ["diff_summary"]
    for phase in ("detect", "plan", "apply", "export", "diff"):
        for action in actions_for_phase("uo-update", phase):
            assert action.get("execution_mode") == "deterministic"
            assert action.get("agent_id") in (None, "", "deterministic-uo-engine")
            assert not action.get("task_prompt_id")


def test_uo_init_has_no_resolve_phase() -> None:
    assert phase_pipeline("uo-init", "resolve") == []
    assert actions_for_phase("uo-init", "resolve") == []
    pipe = phase_pipeline("uo-init", "verify")
    assert pipe == ["verify"]
    actions = {action["id"]: action for action in actions_for_phase("uo-init", "verify")}
    assert actions["verify"]["execution_mode"] == "deterministic"
    assert actions["verify"].get("agent_id") in (None, "", "deterministic-uo-engine")


def test_uo_investigate_has_readonly_gap_investigator() -> None:
    pipe = phase_pipeline("uo-investigate", "investigate")
    assert pipe == ["investigate"]
    actions = {action["id"]: action for action in actions_for_phase("uo-investigate", "investigate")}
    assert actions["investigate"]["agent_id"] == "uo-gap-investigator"
    assert actions["investigate"]["execution_mode"] == "subagent"
    assert actions["investigate"]["task_prompt_id"] == "uo/investigate-gaps"


def test_recommend_uo_update_export_starts_at_integrity(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-update", phase="export", force_phase=True, architecture="arch35")
    allowed = actions_for_phase("uo-update", "export")
    rec = recommend_next_action(
        tmp_path,
        workflow_id="uo-update",
        phase="export",
        allowed_actions=allowed,
    )
    assert rec and rec["id"] == phase_pipeline("uo-update", "export")[0]
