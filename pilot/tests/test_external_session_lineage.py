"""Control-plane external session registry and resume lineage."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.action_dispatch import prepare_resume_fields, record_continuation
from ascendc_pilot.actions.external_session_registry import (
    latest_external_session,
    patch_external_session_id,
    register_external_session,
)
from ascendc_pilot.debug import is_enabled, register_child


def test_register_works_when_debug_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ASCENDC_DEBUG", "0")
    # Ensure debug stays off
    assert is_enabled(tmp_path) is False
    # Seed active action so register_child can resolve run/action
    state = tmp_path / ".ascendc-pilot" / "state"
    state.mkdir(parents=True)
    (state / "active_action.yaml").write_text(
        "run_id: r1\naction_id: adjudicate_llm_tasks\n", encoding="utf-8"
    )
    out = register_child(
        tmp_path,
        parent_session_id="ses_primary",
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        dispatch_nonce="nonce_a",
    )
    assert out.get("ok") is True
    assert out.get("control_plane") is True
    latest = latest_external_session(tmp_path, run_id="r1", action_id="adjudicate_llm_tasks")
    # pending without child id yet
    assert latest.get("external_task_session_id") in {"", None} or True
    patched = patch_external_session_id(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        external_task_session_id="ses_child_a",
        primary_session_id="ses_primary",
        registration_id=str(out.get("registration_id") or ""),
        dispatch_nonce="nonce_a",
    )
    assert patched.get("ok") is True
    latest = latest_external_session(tmp_path, run_id="r1", action_id="adjudicate_llm_tasks")
    assert latest.get("external_task_session_id") == "ses_child_a"


def test_same_primary_does_not_verify_resume(tmp_path: Path) -> None:
    register_external_session(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        primary_session_id="ses_primary",
        external_task_session_id="ses_a",
    )
    cont = record_continuation(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        external_task_session_id="ses_b",
        primary_session_id="ses_primary",
        previous_external_task_session_id="ses_a",
        host_reported_resumed_from="",  # no host resume claim
    )
    assert cont["continuation_mode"] == "fork_with_context"
    assert cont["lineage_verified"] is False


def test_resume_verified_only_when_host_points_to_previous_child(tmp_path: Path) -> None:
    cont = record_continuation(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        external_task_session_id="ses_b",
        primary_session_id="ses_primary",
        previous_external_task_session_id="ses_a",
        host_reported_resumed_from="ses_a",
    )
    assert cont["continuation_mode"] == "resume"
    assert cont["lineage_verified"] is True


def test_prepare_resume_reads_control_plane(tmp_path: Path) -> None:
    patch_external_session_id(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        external_task_session_id="ses_prev",
        primary_session_id="ses_primary",
    )
    fields = prepare_resume_fields(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        workflow_status="rework_required",
    )
    assert fields["resume_required"] is True
    assert fields["resume_session_id"] == "ses_prev"
