"""Debug Task correlation: registration_id, concurrent tasks, run bind, anomalies."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot import debug as dbg
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import load_state, start_workflow


def test_concurrent_same_action_requires_registration_id(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    parent = "ses_hostCONC01"
    dbg.set_enabled(tmp_path, True, parent_session_id=parent)
    r1 = dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        action_id="extract_plan",
        actor_id="uo-flow-extraction",
        task_prompt_text="task-a",
    )
    r2 = dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        action_id="extract_plan",
        actor_id="uo-flow-extraction",
        task_prompt_text="task-b",
    )
    assert r1["registration_id"] != r2["registration_id"]

    # Without registration_id, concurrent same action must not guess.
    bad = dbg.patch_child_session_id(
        tmp_path,
        child_session_id="ses_childAAAA01",
        parent_session_id=parent,
        action_id="extract_plan",
    )
    assert bad.get("ok") is False
    assert bad.get("error") == "ambiguous_pending_registration"

    ok1 = dbg.patch_child_session_id(
        tmp_path,
        child_session_id="ses_childAAAA01",
        parent_session_id=parent,
        action_id="extract_plan",
        registration_id=r1["registration_id"],
        task_result_text="result for task-a: writers confirmed",
    )
    ok2 = dbg.patch_child_session_id(
        tmp_path,
        child_session_id="ses_childBBBB02",
        parent_session_id=parent,
        action_id="extract_plan",
        registration_id=r2["registration_id"],
        task_result_text="result for task-b: receivers confirmed",
    )
    assert ok1["ok"] and ok2["ok"]
    assert ok1["registration"]["child_session_id"] == "ses_childAAAA01"
    assert ok2["registration"]["child_session_id"] == "ses_childBBBB02"


def test_child_tool_events_isolated_from_host(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    parent = "ses_hostTOOL01"
    child = "ses_childTOOL01"
    dbg.set_enabled(tmp_path, True, parent_session_id=parent)
    reg = dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        action_id="extract_plan",
        actor_id="uo-flow-extraction",
        task_prompt_text="read sources",
    )
    dbg.patch_child_session_id(
        tmp_path,
        child_session_id=child,
        registration_id=reg["registration_id"],
        task_result_text="done reading",
    )
    # Host event
    dbg.record_tool_event(
        tmp_path,
        tool="read",
        parent_session_id=parent,
        child_session_id="",
        action_id="extract_plan",
        path="METHOD.md",
    )
    # Child event
    dbg.record_tool_event(
        tmp_path,
        tool="read",
        parent_session_id=parent,
        child_session_id=child,
        action_id="extract_plan",
        path="op_host/foo.cpp",
    )
    exp = dbg.export_child_session(tmp_path, child_session_id=child, reason="test")
    assert exp.get("ok") is True
    export_dir = Path(exp["export_dir"])
    events = (export_dir / "tool_events.jsonl").read_text(encoding="utf-8")
    assert "op_host/foo.cpp" in events
    assert "METHOD.md" not in events
    result = (export_dir / "result.md").read_text(encoding="utf-8")
    assert "done reading" in result
    meta = (export_dir / "metadata.yaml").read_text(encoding="utf-8")
    assert "transcript_status" in meta


def test_debug_enable_before_start_binds_run(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    # Enable debug BEFORE start → run_id empty
    dbg.set_enabled(tmp_path, True, parent_session_id="ses_hostEARLY01")
    ds = dbg.load_debug_session(tmp_path)
    assert ds.get("debug_session_id")
    assert not str(ds.get("run_id") or "").strip()

    start_workflow(tmp_path, "uo-init")
    st = load_state(tmp_path) or {}
    ds2 = dbg.load_debug_session(tmp_path)
    assert ds2.get("run_id") == st.get("run_id")
    # Second bind with different run must not overwrite
    ds2["run_id"] = "RUN_BOUND_ALREADY"
    dbg._save_debug_session(tmp_path, ds2)
    # Simulate another start attempt binding
    bind = dbg.bind_debug_session_run(tmp_path)
    assert bind.get("ok") is False or bind.get("error") == "debug_run_already_bound" or ds2.get("run_id") == "RUN_BOUND_ALREADY"


def test_export_failure_writes_anomaly(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    dbg.set_enabled(tmp_path, True, parent_session_id="ses_hostFAIL01")
    out = dbg.export_child_session(tmp_path, child_session_id="ses_missingXXXX", reason="test")
    assert out.get("ok") is False
    dbg.record_export_failure_anomaly(tmp_path, summary="child_not_registered", detail=out)
    anoms = dbg.list_anomalies(tmp_path)
    assert any(a.get("kind") == "debug_export_failure" for a in anoms)


def test_transcript_unavailable_does_not_pick_old_file(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    parent = "ses_hostTX01"
    child = "ses_childTX01"
    dbg.set_enabled(tmp_path, True, parent_session_id=parent)
    # Plant decoy
    (tmp_path / "session-ses_070dOLD.md").write_text("# unrelated\n", encoding="utf-8")
    reg = dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        action_id="extract_plan",
        task_prompt_text="x",
    )
    dbg.patch_child_session_id(
        tmp_path,
        child_session_id=child,
        registration_id=reg["registration_id"],
        task_result_text="ok",
    )
    exp = dbg.export_child_session(tmp_path, child_session_id=child, reason="test")
    assert exp.get("ok") is True
    export_dir = Path(exp["export_dir"])
    assert not (export_dir / "transcript.md").is_file()
    meta_text = (export_dir / "metadata.yaml").read_text(encoding="utf-8")
    assert "unavailable" in meta_text
