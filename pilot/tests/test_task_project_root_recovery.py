"""ses_062d: Task authorize must recover operator root when cwd is workspace."""

from __future__ import annotations

import json
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


def test_task_authorize_recovers_via_pending_dispatch(tmp_path: Path, monkeypatch) -> None:
    """pilot_run writes pending-dispatch; Task must not require last-project or stub path."""
    workspace = tmp_path / "workspace"
    op = tmp_path / "ops" / "flash_attention_score_grad"
    workspace.mkdir()
    op.mkdir(parents=True)
    (workspace / ".ascendc-pilot" / "state").mkdir(parents=True)

    start_workflow(op, "uo-query", phase="answer", force_phase=True, architecture="arch35")
    _write_active_action(
        op,
        {
            "action_id": "kb_lookup",
            "actor_id": "uo-query",
            "role_id": "readonly_analyst",
            "execution_mode": "subagent",
            "status": "prepared",
            "phase": "answer",
            "workflow_id": "uo-query",
        },
    )

    home = tmp_path / "home"
    cfg = home / ".config" / "opencode"
    cfg.mkdir(parents=True)
    # Polluted last-project (workspace) must not beat the live dispatch handoff.
    (cfg / "ascendc-last-project").write_text(str(workspace.resolve()), encoding="utf-8")
    (cfg / "ascendc-pending-dispatch.json").write_text(
        json.dumps(
            {
                "project": str(op.resolve()),
                "ticket": "dxt_test",
                "actor": "uo-query",
                "action": "kb_lookup",
                "ts": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    verdict = authorize(
        workspace,
        tool="task",
        path="uo-query",
        command="uo-query",
        agent="ascendc-pilot",
        action="kb_lookup",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") == "TASK_OK", verdict
    assert verdict.get("workflow_id") == "uo-query", verdict


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


def test_primary_may_task_uo_query_after_uo_init(tmp_path: Path) -> None:
    """ses_ff9e: leftover uo-init phase must not block delegated uo-query Task."""
    op = tmp_path / "ops" / "flash_attention_score_grad"
    op.mkdir(parents=True)
    start_workflow(op, "uo-init", phase="verify", force_phase=True, architecture="arch35")

    verdict = authorize(
        op,
        tool="task",
        path="uo-query",
        command="uo-query",
        agent="ascendc-pilot",
        action="",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") == "TASK_OK", verdict


def test_primary_may_task_uo_query_without_host_workflow(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".ascendc-pilot" / "state").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    verdict = authorize(
        workspace,
        tool="task",
        path="uo-query",
        command="uo-query",
        agent="ascendc-pilot",
        action="",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") == "TASK_OK", verdict


def test_primary_still_cannot_task_undeclared_producer_during_uo_init(tmp_path: Path) -> None:
    op = tmp_path / "ops" / "flash_attention_score_grad"
    op.mkdir(parents=True)
    start_workflow(op, "uo-init", phase="verify", force_phase=True, architecture="arch35")

    verdict = authorize(
        op,
        tool="task",
        path="uo-semantic-resolve",
        command="uo-semantic-resolve",
        agent="ascendc-pilot",
        action="",
    )
    assert verdict.get("decision") == "deny", verdict
    assert verdict.get("reason_code") == "TASK_AGENT_UNKNOWN", verdict


def test_primary_may_task_uo_query_during_failed_auto(tmp_path: Path) -> None:
    from ascendc_pilot.observation import record_pilot_result

    op = tmp_path / "ops" / "flash_attention_score_grad"
    op.mkdir(parents=True)
    (op / "op_host").mkdir()
    start_workflow(op, "auto", intent="获取 PR 代码", architecture="arch35")
    record_pilot_result(
        op,
        ok=False,
        action_id="intent_promote",
        step_id="intent_promote",
        messages=["ENGINE_FAILED"],
        source="finalize_action",
    )
    verdict = authorize(
        op,
        tool="task",
        path="uo-query",
        command="uo-query",
        agent="ascendc-pilot",
        action="",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") == "TASK_OK", verdict
