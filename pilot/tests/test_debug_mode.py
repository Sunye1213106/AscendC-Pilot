"""Tests for ascendc_pilot.debug mode."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ascendc_pilot import debug as dbg
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import load_state, start_workflow


def _enable_parent_debug(tmp_path: Path, parent: str = "ses_hostTEST01") -> dict:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    dbg.set_enabled(tmp_path, True, parent_session_id=parent)
    return load_state(tmp_path) or {}


def _register_and_patch(
    tmp_path: Path,
    *,
    parent: str,
    child: str,
    action_id: str = "extract_plan",
    run_id: str = "",
    started_at: str = "",
) -> None:
    st = load_state(tmp_path) or {}
    dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        workflow_id=str(st.get("workflow_id") or ""),
        run_id=run_id or str(st.get("run_id") or ""),
        phase=str(st.get("phase") or ""),
        action_id=action_id,
        actor_id="uo-flow-extraction",
        started_at=started_at or dbg._now(),
        task_prompt_text="do extract_plan",
    )
    dbg.patch_child_session_id(
        tmp_path,
        child_session_id=child,
        parent_session_id=parent,
        action_id=action_id,
    )


def test_analyze_thought_flags_long_meta() -> None:
    short = "先跑 acp next，再 prepare。"
    assert dbg.analyze_thought(short, char_limit=100, meta_hits_min=3)["flagged"] is False

    thrash = (
        "让我想想要不要 todowrite。严格来说是否应该 merge=true。"
        "纠结一下实际上规则…我需要先想清楚 on the other hand but actually "
        "wait, should I sync? " * 40
    )
    a = dbg.analyze_thought(thrash, char_limit=200, meta_hits_min=3)
    assert a["flagged"] is True
    assert a["meta_count"] >= 3


def test_classify_skips_success_dumps() -> None:
    read_dump = (
        "<path>D:/x/method.md</path>\n<type>file</type>\n<content>\n"
        "1: # extract_plan — failure notes\nerror handling\n"
    )
    assert dbg.classify_tool_output_failure(tool="read", error=read_dump)["is_failure"] is False

    ok_bash = '{"ok": true, "step": "finalize", "errors": [], "message": "ok"}'
    assert dbg.classify_tool_output_failure(tool="bash", error=ok_bash)["is_failure"] is False

    bad = '{"ok": false, "phase_runtime": "finalize", "error_code": "RECEIPT_VERIFY_FAILED"}'
    assert dbg.classify_tool_output_failure(tool="bash", error=bad)["is_failure"] is True

    schema = "The todowrite tool was called with invalid arguments: SchemaError(Missing key priority)"
    assert dbg.classify_tool_output_failure(tool="todowrite", error=schema)["is_failure"] is True


def test_debug_record_and_export(tmp_path: Path) -> None:
    parent = "ses_hostTEST01"
    child = "ses_childTEST01"
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")

    off = dbg.record_tool_failure(tmp_path, tool="write", error="PRIMARY_PROTECTED_WRITE")
    assert off.get("skipped") is True

    dbg.set_enabled(tmp_path, True, parent_session_id=parent)
    assert dbg.is_enabled(tmp_path)

    skip = dbg.record_tool_failure(
        tmp_path,
        tool="read",
        error="<path>D:/x</path>\n<type>file</type>\n<content>\nerror notes\n",
    )
    assert skip.get("skipped") is True
    assert skip.get("reason") == "not_a_real_failure"

    rec = dbg.record_tool_failure(
        tmp_path,
        tool="write",
        error="PRIMARY_PROTECTED_WRITE denied",
        agent="ascendc-pilot",
        action_id="extract_plan",
    )
    assert rec.get("ok") is True

    thrash = (
        "让我想想要不要 todowrite。严格来说是否应该 merge。"
        "纠结是否应该同步。我需要先想清楚 on the other hand but actually "
        "wait, should I? " * 50
    )
    thought = dbg.record_long_thought(tmp_path, thrash)
    assert thought.get("ok") is True

    _register_and_patch(tmp_path, parent=parent, child=child)

    hook = dbg.hook_handle(
        "subagentStop",
        {
            "cwd": str(tmp_path),
            "subagent_type": "uo-semantic-resolve",
            "session_id": child,
            "parent_session_id": parent,
            "action_id": "extract_plan",
        },
    )
    assert hook.get("export", {}).get("ok") is True
    export_dir = Path(hook["export"]["export_dir"])
    assert (export_dir / "DEBUG_REPORT.md").is_file()
    assert (export_dir / "metadata.yaml").is_file()
    assert "followup_message" in hook
    assert not (export_dir / "transcript.md").is_file()

    dbg.set_enabled(tmp_path, False)
    assert dbg.is_enabled(tmp_path) is False


def test_transcript_copy_requires_session_id(tmp_path: Path, monkeypatch) -> None:
    """Refuse cwd mtime fishing of unrelated session-ses_*.md."""
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    dbg.set_enabled(tmp_path, True)

    # Plant an unrelated old session in cwd (the historical bug path).
    decoy = tmp_path / "session-ses_070dOLD.md"
    decoy.write_text("# old unrelated session\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    meta = dbg.export_session_bundle(tmp_path, reason="subagent_stop", subagent="task")
    export_dir = Path(meta["export_dir"])
    assert not list(export_dir.glob("transcript_*"))
    assert "no transcript" in str((meta.get("transcript") or {}).get("note") or "").lower() or not (
        meta.get("transcript") or {}
    ).get("ok")


def test_transcript_copy_binds_session_ids(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    dbg.set_enabled(tmp_path, True)

    host = tmp_path / "session-ses_hostABC123.md"
    child = tmp_path / "session-ses_childXYZ789.md"
    host.write_text("# host conversation\n", encoding="utf-8")
    child.write_text("# subagent conversation\n", encoding="utf-8")
    # Unrelated decoy must not be copied.
    (tmp_path / "session-ses_070dOLD.md").write_text("# decoy\n", encoding="utf-8")

    meta = dbg.export_session_bundle(
        tmp_path,
        reason="subagent_stop",
        subagent="uo-semantic-resolve",
        session_id="ses_childXYZ789",
        parent_session_id="ses_hostABC123",
    )
    export_dir = Path(meta["export_dir"])
    names = {p.name for p in export_dir.glob("transcript_*")}
    assert any("ses_childXYZ789" in n for n in names)
    assert any("ses_hostABC123" in n for n in names)
    assert not any("070dOLD" in n for n in names)


def test_extract_task_session_id_from_text() -> None:
    blob = '<task id="ses_06cd3568effe6X19NYVj3emR6H" state="completed">\n<summary/>\n</task>'
    assert dbg.extract_task_session_id_from_text(blob) == "ses_06cd3568effe6X19NYVj3emR6H"
    assert dbg.normalize_session_id("session-ses_06cd.md") == "ses_06cd"


def test_hook_skips_when_disabled(tmp_path: Path) -> None:
    dbg.set_enabled(tmp_path, False)
    out = dbg.hook_handle(
        "postToolUseFailure",
        {"cwd": str(tmp_path), "tool_name": "Shell", "error_message": "boom"},
    )
    assert out.get("skipped") is True


def test_cli_debug_enable_status(tmp_path: Path) -> None:
    from ascendc_pilot.cli import main

    assert main(["debug", "enable", "--project", str(tmp_path), "--parent-session-id", "ses_hostCLI"]) == 0
    ds = dbg.load_debug_session(tmp_path)
    assert ds.get("parent_session_id") == "ses_hostCLI"
    assert ds.get("debug_session_id")
    assert main(["debug", "status", "--project", str(tmp_path)]) == 0
    assert main(["debug", "disable", "--project", str(tmp_path)]) == 0


def test_debug_exports_only_current_parent_children(tmp_path: Path) -> None:
    parent = "ses_parentA"
    child = "ses_childOK01"
    _enable_parent_debug(tmp_path, parent)
    _register_and_patch(tmp_path, parent=parent, child=child, action_id="extract_plan")
    meta = dbg.export_child_session(tmp_path, child_session_id=child, reason="test")
    assert meta.get("ok") is True
    export_dir = Path(meta["export_dir"])
    assert export_dir.is_dir()
    assert list((tmp_path / ".ascendc-pilot" / "debug" / "exports").glob("*_*_" + child))


def test_old_project_sessions_not_exported(tmp_path: Path) -> None:
    parent = "ses_parentB"
    child = "ses_childNEW01"
    st = _enable_parent_debug(tmp_path, parent)
    old_run = "RUN_old99999999"
    (tmp_path / "session-ses_070dOLD.md").write_text("# stale history\n", encoding="utf-8")
    (tmp_path / f"session-{child}.md").write_text("# child\n", encoding="utf-8")
    reg = dbg.register_child(
        tmp_path,
        parent_session_id=parent,
        run_id=old_run,
        action_id="extract_plan",
        started_at=dbg._now(),
        task_prompt_text="x",
    )
    # The registration must be named: the run differs from the active one, so
    # there is no pending row for the current (run, action) to fall back on.
    patched = dbg.patch_child_session_id(
        tmp_path,
        child_session_id=child,
        parent_session_id=parent,
        run_id=old_run,
        action_id="extract_plan",
        registration_id=reg["registration_id"],
    )
    assert patched.get("ok") is True, patched
    out = dbg.export_child_session(tmp_path, child_session_id=child)
    assert out.get("skipped") and out.get("reason") == "run_id_mismatch"
    assert not list((tmp_path / ".ascendc-pilot" / "debug" / "exports").glob(f"*_{child}"))


def test_other_parent_session_not_exported(tmp_path: Path) -> None:
    parent = "ses_parentC"
    other_parent = "ses_parentOTHER"
    child = "ses_childC001"
    _enable_parent_debug(tmp_path, parent)
    st = load_state(tmp_path) or {}
    reg = dbg.register_child(
        tmp_path,
        parent_session_id=other_parent,
        run_id=str(st.get("run_id") or ""),
        action_id="extract_plan",
        started_at=dbg._now(),
        task_prompt_text="x",
    )
    patched = dbg.patch_child_session_id(
        tmp_path,
        child_session_id=child,
        parent_session_id=other_parent,
        action_id="extract_plan",
        registration_id=reg["registration_id"],
    )
    assert patched.get("ok") is True, patched
    out = dbg.export_child_session(tmp_path, child_session_id=child)
    assert out.get("skipped") and out.get("reason") == "parent_session_mismatch"


def test_exact_child_session_id_used(tmp_path: Path) -> None:
    parent = "ses_parentD"
    child = "ses_childXYZ789"
    _enable_parent_debug(tmp_path, parent)
    (tmp_path / "session-ses_070dOLD.md").write_text("# decoy\n", encoding="utf-8")
    (tmp_path / f"session-{child}.md").write_text("# exact child\n", encoding="utf-8")
    _register_and_patch(tmp_path, parent=parent, child=child)
    meta = dbg.export_child_session(tmp_path, child_session_id=child)
    export_dir = Path(meta["export_dir"])
    assert (export_dir / "transcript.md").read_text(encoding="utf-8") == "# exact child\n"
    assert "070dOLD" not in (export_dir / "metadata.yaml").read_text(encoding="utf-8")


def test_parent_transcript_never_substitutes_child(tmp_path: Path) -> None:
    parent = "ses_hostABC123"
    child = "ses_childXYZ789"
    _enable_parent_debug(tmp_path, parent)
    (tmp_path / f"session-{parent}.md").write_text("# host only\n", encoding="utf-8")
    _register_and_patch(tmp_path, parent=parent, child=child)
    meta = dbg.export_child_session(tmp_path, child_session_id=child)
    export_dir = Path(meta["export_dir"])
    assert not (export_dir / "transcript.md").is_file()
    md = yaml.safe_load((export_dir / "metadata.yaml").read_text(encoding="utf-8"))
    assert md.get("transcript_status") == "unavailable"


def test_transcript_unavailable_is_explicit(tmp_path: Path) -> None:
    parent = "ses_parentE"
    child = "ses_childMISSING"
    _enable_parent_debug(tmp_path, parent)
    _register_and_patch(tmp_path, parent=parent, child=child)
    meta = dbg.export_child_session(tmp_path, child_session_id=child)
    tr = meta.get("transcript") or {}
    assert tr.get("transcript_status") == "unavailable"
    assert tr.get("reason")


def test_child_stop_auto_exports_bundle(tmp_path: Path) -> None:
    parent = "ses_parentF"
    child = "ses_childAUTO1"
    _enable_parent_debug(tmp_path, parent)
    _register_and_patch(tmp_path, parent=parent, child=child, action_id="detect_score_pre")
    hook = dbg.hook_handle(
        "subagentStop",
        {
            "cwd": str(tmp_path),
            "session_id": child,
            "parent_session_id": parent,
            "action_id": "detect_score_pre",
        },
    )
    assert hook["export"]["ok"] is True
    export_dir = Path(hook["export"]["export_dir"])
    for name in (
        "metadata.yaml",
        "prompt.md",
        "tool_events.jsonl",
        "tool_failures.jsonl",
        "result.md",
        "artifact_manifest.yaml",
        "DEBUG_REPORT.md",
    ):
        assert (export_dir / name).is_file()


def test_parent_end_only_writes_current_session_index(tmp_path: Path) -> None:
    parent = "ses_parentG"
    child = "ses_childG001"
    _enable_parent_debug(tmp_path, parent)
    _register_and_patch(tmp_path, parent=parent, child=child)
    dbg.export_child_session(tmp_path, child_session_id=child)
    end = dbg.hook_handle("sessionEnd", {"cwd": str(tmp_path), "parent_session_id": parent})
    assert end["export"]["ok"] is True
    dbg_dir = tmp_path / ".ascendc-pilot" / "debug"
    assert (dbg_dir / "parent_session_summary.yaml").is_file()
    assert (dbg_dir / "children_index.yaml").is_file()
    idx = yaml.safe_load((dbg_dir / "children_index.yaml").read_text(encoding="utf-8"))
    assert len(idx.get("children") or []) == 1
    assert not list(dbg_dir.glob("transcript_*"))


def test_two_concurrent_children_do_not_cross_transcripts(tmp_path: Path) -> None:
    parent = "ses_parentH"
    child_a = "ses_childHAAA"
    child_b = "ses_childHBBB"
    _enable_parent_debug(tmp_path, parent)
    (tmp_path / f"session-{child_a}.md").write_text("# transcript A\n", encoding="utf-8")
    (tmp_path / f"session-{child_b}.md").write_text("# transcript B\n", encoding="utf-8")
    _register_and_patch(tmp_path, parent=parent, child=child_a, action_id="action_a")
    _register_and_patch(tmp_path, parent=parent, child=child_b, action_id="action_b")
    meta_b = dbg.export_child_session(tmp_path, child_session_id=child_b)
    meta_a = dbg.export_child_session(tmp_path, child_session_id=child_a)
    assert "transcript B" in (Path(meta_b["export_dir"]) / "transcript.md").read_text(encoding="utf-8")
    assert "transcript A" in (Path(meta_a["export_dir"]) / "transcript.md").read_text(encoding="utf-8")


def test_source_read_audit_from_tool_events(tmp_path: Path) -> None:
    parent = "ses_parentI"
    child = "ses_childI001"
    _enable_parent_debug(tmp_path, parent)
    _register_and_patch(tmp_path, parent=parent, child=child)
    dbg.record_tool_event(
        tmp_path,
        tool="read",
        parent_session_id=parent,
        child_session_id=child,
        path="src/kernel.cpp",
    )
    dbg.record_tool_event(
        tmp_path,
        tool="read",
        parent_session_id=parent,
        child_session_id=child,
        path=".ascendc-pilot/ir/graph.ir.yaml",
    )
    dbg.record_tool_event(
        tmp_path,
        tool="grep",
        parent_session_id=parent,
        child_session_id=child,
        pattern="foo",
    )
    dbg.record_tool_event(
        tmp_path,
        tool="write",
        parent_session_id=parent,
        child_session_id=child,
        path="out/plan.yaml",
    )
    meta = dbg.export_child_session(tmp_path, child_session_id=child)
    audit = (meta.get("audit") or {})
    assert audit.get("source_files_read") == 1
    assert audit.get("ir_files_read") == 1
    assert audit.get("grep_queries") == 1
    assert audit.get("written_artifacts") == 1
    assert audit.get("tool_call_count") == 4


def test_debug_integration_ab_children_only_their_bundles(tmp_path: Path) -> None:
    parent = "ses_parentINT"
    child_a = "ses_childINTA"
    child_b = "ses_childINTB"
    _enable_parent_debug(tmp_path, parent)
    (tmp_path / "session-ses_HISTOLD.md").write_text("# must never export\n", encoding="utf-8")
    (tmp_path / f"session-{child_a}.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / f"session-{child_b}.md").write_text("# B\n", encoding="utf-8")
    _register_and_patch(tmp_path, parent=parent, child=child_a, action_id="child_a")
    _register_and_patch(tmp_path, parent=parent, child=child_b, action_id="child_b")
    meta_b = dbg.export_child_session(tmp_path, child_session_id=child_b, reason="subagent_stop")
    meta_a = dbg.export_child_session(tmp_path, child_session_id=child_a, reason="subagent_stop")
    exports = list((tmp_path / ".ascendc-pilot" / "debug" / "exports").iterdir())
    assert len(exports) == 2
    names = " ".join(p.name for p in exports)
    assert child_a in names and child_b in names
    assert "HISTOLD" not in names
    assert "must never export" not in (Path(meta_a["export_dir"]) / "transcript.md").read_text()
    dbg.finalize_parent_index(tmp_path, parent_session_id=parent)
    idx = yaml.safe_load(
        (tmp_path / ".ascendc-pilot" / "debug" / "children_index.yaml").read_text(encoding="utf-8")
    )
    assert len(idx["children"]) == 2
