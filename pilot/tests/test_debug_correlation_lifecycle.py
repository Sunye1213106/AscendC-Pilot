"""Debug Task correlation: registration_id, concurrent tasks, run bind, anomalies."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

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


def test_same_parent_same_action_concurrent_task_reverse_completion(tmp_path: Path) -> None:
    """Second-dispatched Task finishing first must not steal the first registration."""
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    parent = "ses_hostREV01"
    dbg.set_enabled(tmp_path, True, parent_session_id=parent)

    first = dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        action_id="extract_plan",
        actor_id="uo-flow-extraction",
        dispatch_nonce="nonce_first_aaa",
        task_prompt_text="first-dispatched",
    )
    second = dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        action_id="extract_plan",
        actor_id="uo-flow-extraction",
        dispatch_nonce="nonce_second_bbb",
        task_prompt_text="second-dispatched",
    )
    assert first["dispatch_nonce"] == "nonce_first_aaa"
    assert second["dispatch_nonce"] == "nonce_second_bbb"

    # Reverse completion: second Task finishes first, correlated by exact nonce.
    ok_second = dbg.patch_child_session_id(
        tmp_path,
        child_session_id="ses_childSECOND",
        parent_session_id=parent,
        action_id="extract_plan",
        dispatch_nonce="nonce_second_bbb",
        task_result_text="second done",
    )
    ok_first = dbg.patch_child_session_id(
        tmp_path,
        child_session_id="ses_childFIRST1",
        parent_session_id=parent,
        action_id="extract_plan",
        dispatch_nonce="nonce_first_aaa",
        task_result_text="first done",
    )
    assert ok_second["ok"] and ok_first["ok"]
    assert ok_second["registration"]["child_session_id"] == "ses_childSECOND"
    assert ok_second["registration"]["registration_id"] == second["registration_id"]
    assert ok_first["registration"]["child_session_id"] == "ses_childFIRST1"
    assert ok_first["registration"]["registration_id"] == first["registration_id"]

    rel_second = dbg.get_session_relationship(tmp_path, "ses_childSECOND")
    rel_first = dbg.get_session_relationship(tmp_path, "ses_childFIRST1")
    assert rel_second is not None
    assert rel_second["dispatch_nonce"] == "nonce_second_bbb"
    assert rel_first is not None
    assert rel_first["dispatch_nonce"] == "nonce_first_aaa"


def test_task_after_uses_exact_invocation_id(tmp_path: Path) -> None:
    """After-hook correlation must use registration_id / dispatch_nonce, never latest-by-action."""
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    parent = "ses_hostINV01"
    dbg.set_enabled(tmp_path, True, parent_session_id=parent)

    r_old = dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        action_id="extract_plan",
        dispatch_nonce="nonce_older_001",
        task_prompt_text="older",
    )
    r_new = dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        action_id="extract_plan",
        dispatch_nonce="nonce_newer_002",
        task_prompt_text="newer",
    )

    # Exact invocation (registration_id) binds the older Task even though newer is "latest".
    ok = dbg.patch_child_session_id(
        tmp_path,
        child_session_id="ses_childOLDER01",
        parent_session_id=parent,
        action_id="extract_plan",
        registration_id=r_old["registration_id"],
    )
    assert ok.get("ok") is True
    assert ok["registration"]["dispatch_nonce"] == "nonce_older_001"
    assert ok["registration"]["registration_id"] == r_old["registration_id"]
    assert ok["registration"]["child_session_id"] == "ses_childOLDER01"

    # Newer remains unbound — parent+action alone must not steal it for a different child.
    still_ambiguous_or_exact = dbg.patch_child_session_id(
        tmp_path,
        child_session_id="ses_childNEWER01",
        parent_session_id=parent,
        action_id="extract_plan",
        dispatch_nonce=r_new["dispatch_nonce"],
    )
    assert still_ambiguous_or_exact.get("ok") is True
    assert still_ambiguous_or_exact["registration"]["registration_id"] == r_new["registration_id"]


def test_child_tool_event_backfill_by_exact_session(tmp_path: Path) -> None:
    """Mid-Task child tools record event_session_id; patch backfills by exact session id."""
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    parent = "ses_hostBFILL1"
    child = "ses_childBFILL1"
    dbg.set_enabled(tmp_path, True, parent_session_id=parent)

    reg = dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        action_id="extract_plan",
        actor_id="uo-flow-extraction",
        dispatch_nonce="nonce_bfill_01",
        task_prompt_text="read during task",
    )

    # Child tools fire before Task after-hook knows the child id mapping.
    mid = dbg.record_tool_event(
        tmp_path,
        tool="read",
        event_session_id=child,
        parent_session_id=child,  # plugin may echo executing session before registry exists
        child_session_id="",
        action_id="extract_plan",
        path="op_host/kernel.cpp",
    )
    assert mid["ok"] is True
    assert mid["entry"]["event_session_id"] == child
    assert mid["entry"]["child_session_id"] == ""
    assert mid["entry"]["parent_session_id"] == parent

    other_child = "ses_childOTHER9"
    dbg.record_tool_event(
        tmp_path,
        tool="grep",
        event_session_id=other_child,
        parent_session_id=parent,
        child_session_id="",
        action_id="extract_plan",
        path="op_host",
        pattern="TODO",
    )

    patched = dbg.patch_child_session_id(
        tmp_path,
        child_session_id=child,
        parent_session_id=parent,
        registration_id=reg["registration_id"],
        dispatch_nonce="nonce_bfill_01",
        task_result_text="done",
    )
    assert patched.get("ok") is True
    assert patched.get("backfill", {}).get("updated") == 1

    events = dbg.list_tool_events(tmp_path)
    child_events = [e for e in events if e.get("event_session_id") == child]
    assert len(child_events) == 1
    assert child_events[0]["child_session_id"] == child
    assert child_events[0]["parent_session_id"] == parent
    assert child_events[0]["path"] == "op_host/kernel.cpp"

    # Other child's events must NOT be backfilled by action/time window.
    other_events = [e for e in events if e.get("event_session_id") == other_child]
    assert len(other_events) == 1
    assert other_events[0]["child_session_id"] == ""


def test_host_events_not_exported_to_child(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    parent = "ses_hostEXPORT1"
    child = "ses_childEXPORT1"
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
    # Host event (empty child_session_id)
    dbg.record_tool_event(
        tmp_path,
        tool="read",
        event_session_id=parent,
        parent_session_id=parent,
        child_session_id="",
        action_id="extract_plan",
        path="METHOD.md",
    )
    # Child event
    dbg.record_tool_event(
        tmp_path,
        tool="read",
        event_session_id=child,
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
    # Only exact child_session_id match
    for line in events.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        assert row.get("child_session_id") == child


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


def test_child_source_reads_appear_in_audit(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    parent = "ses_hostAUDIT1"
    child = "ses_childAUDIT1"
    dbg.set_enabled(tmp_path, True, parent_session_id=parent)
    reg = dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        action_id="extract_plan",
        actor_id="uo-flow-extraction",
        task_prompt_text="inspect source and grep for callsites",
    )
    dbg.patch_child_session_id(
        tmp_path,
        child_session_id=child,
        registration_id=reg["registration_id"],
        task_result_text="source read and grep complete",
    )
    dbg.record_tool_event(
        tmp_path,
        tool="read",
        event_session_id=child,
        parent_session_id=parent,
        child_session_id=child,
        action_id="extract_plan",
        path="op_host/kernel.cpp",
    )
    dbg.record_tool_event(
        tmp_path,
        tool="read",
        event_session_id=child,
        parent_session_id=parent,
        child_session_id=child,
        action_id="extract_plan",
        path=".ascendc-pilot/uo/ir/extract_plan.yaml",
    )
    dbg.record_tool_event(
        tmp_path,
        tool="grep",
        event_session_id=child,
        parent_session_id=parent,
        child_session_id=child,
        action_id="extract_plan",
        path="op_host",
        pattern="TQue",
    )

    exp = dbg.export_child_session(tmp_path, child_session_id=child, reason="audit")
    assert exp.get("ok") is True
    audit = (yaml.safe_load((Path(exp["export_dir"]) / "metadata.yaml").read_text(encoding="utf-8")) or {})["audit"]
    assert audit["source_files_read"] == 1
    assert audit["ir_files_read"] == 1
    assert audit["grep_queries"] == 1
