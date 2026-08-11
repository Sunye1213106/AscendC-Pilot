"""Producer write remapping for the UO gap investigator."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.runtime import _write_active_action
from ascendc_pilot.authorize import _project_root_for_path, _remap_primary_actor, authorize
from ascendc_pilot.paths import agent_root, ensure_agent_layout
from ascendc_pilot.state import start_workflow


def _prepare_investigate_session(op: Path) -> str:
    ensure_agent_layout(op)
    state = start_workflow(op, "uo-investigate", phase="investigate", force_phase=True)
    run_id = str(state["run_id"])
    _write_active_action(
        op,
        {
            "action_id": "investigate",
            "actor_id": "uo-gap-investigator",
            "workflow_id": "uo-investigate",
            "phase": "investigate",
            "status": "prepared",
            "run_id": run_id,
        },
    )
    return run_id


def test_project_root_extracted_from_staging_write_path(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    write_path = op / ".ascendc-pilot" / "runs" / "r" / "actions" / "investigate" / "report.yaml"
    assert _project_root_for_path(tmp_path, str(write_path)) == op.resolve()


def test_remap_primary_to_prepared_gap_investigator(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    _prepare_investigate_session(op)
    agent, action = _remap_primary_actor(op, "ascendc-pilot", "investigate")
    assert agent == "uo-gap-investigator"
    assert action == "investigate"


def test_primary_mislabeled_report_write_allowed_via_active_investigator(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    run_id = _prepare_investigate_session(op)
    target = agent_root(op) / "runs" / run_id / "actions" / "investigate" / "report.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)

    verdict = authorize(
        tmp_path,
        tool="write",
        path=str(target),
        agent="ascendc-pilot",
        action="investigate",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("ok") is not False


def test_primary_task_dispatch_stays_primary(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    _prepare_investigate_session(op)
    verdict = authorize(
        op,
        tool="task",
        path="uo-gap-investigator",
        agent="ascendc-pilot",
        action="investigate",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") == "TASK_OK"


def test_task_agent_name_does_not_break_project_root_resolution(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    _prepare_investigate_session(op)
    verdict = authorize(
        op,
        tool="task",
        path="uo-gap-investigator",
        command="uo-gap-investigator",
        agent="ascendc-pilot",
        action="",
    )
    assert verdict.get("decision") == "allow", verdict
