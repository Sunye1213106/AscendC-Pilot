"""ses_062d: Task authorize must recover operator root when cwd is workspace."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.runtime import _write_active_action
from ascendc_pilot.authorize import authorize
from ascendc_pilot.state import start_workflow


def test_task_authorize_recovers_via_last_project_cache(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    op = tmp_path / "ops" / "flash_attention_score_grad"
    workspace.mkdir()
    op.mkdir(parents=True)
    # Leftover empty marker under workspace (no workflow) — must not win.
    (workspace / ".ascendc-pilot" / "state").mkdir(parents=True)

    start_workflow(op, "uo-init", phase="extract", force_phase=True, architecture="arch35")
    _write_active_action(
        op,
        {
            "action_id": "extract_plan",
            "actor_id": "uo-semantic-resolve",
            "role_id": "producer",
            "execution_mode": "subagent",
            "status": "prepared",
            "phase": "extract",
            "workflow_id": "uo-init",
        },
    )

    home = tmp_path / "home"
    cache = home / ".config" / "opencode" / "ascendc-last-project"
    cache.parent.mkdir(parents=True)
    cache.write_text(str(op.resolve()), encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    denied = authorize(
        workspace,
        tool="task",
        path="uo-semantic-resolve",
        command="uo-semantic-resolve",
        agent="ascendc-pilot",
        action="extract_plan",
    )
    assert denied.get("decision") == "allow", denied
    assert denied.get("reason_code") == "TASK_OK", denied


def test_task_authorize_still_denies_without_cache_or_workflow(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".ascendc-pilot" / "state").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    verdict = authorize(
        workspace,
        tool="task",
        path="uo-semantic-resolve",
        command="uo-semantic-resolve",
        agent="ascendc-pilot",
        action="extract_plan",
    )
    assert verdict.get("decision") == "deny", verdict
    assert verdict.get("reason_code") == "TASK_AGENT_UNKNOWN", verdict
