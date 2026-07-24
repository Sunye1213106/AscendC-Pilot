"""Tests for ascendc_pilot.debug mode."""

from __future__ import annotations

import json
from pathlib import Path

from ascendc_pilot import debug as dbg
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import start_workflow


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
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")

    off = dbg.record_tool_failure(tmp_path, tool="write", error="PRIMARY_PROTECTED_WRITE")
    assert off.get("skipped") is True

    dbg.set_enabled(tmp_path, True)
    assert dbg.is_enabled(tmp_path)

    # False positive success dump must not be recorded
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
    assert rec.get("entry", {}).get("kind") == "tool_failure"

    thrash = (
        "让我想想要不要 todowrite。严格来说是否应该 merge。"
        "纠结是否应该同步。我需要先想清楚 on the other hand but actually "
        "wait, should I? " * 50
    )
    thought = dbg.record_long_thought(tmp_path, thrash)
    assert thought.get("ok") is True
    assert thought.get("entry", {}).get("kind") == "long_nonlogical_thought"

    rows = dbg.list_anomalies(tmp_path)
    assert any(r.get("kind") == "tool_failure" for r in rows)
    assert any(r.get("kind") == "long_nonlogical_thought" for r in rows)
    assert not any("file</type>" in str(r.get("summary") or "") for r in rows)

    hook = dbg.hook_handle(
        "subagentStop",
        {"cwd": str(tmp_path), "subagent_type": "uo-semantic-resolve"},
    )
    assert hook.get("export", {}).get("ok") is True
    export_dir = Path(hook["export"]["export_dir"])
    assert (export_dir / "DEBUG_REPORT.md").is_file()
    assert "followup_message" in hook

    dbg.set_enabled(tmp_path, False)
    assert dbg.is_enabled(tmp_path) is False


def test_hook_skips_when_disabled(tmp_path: Path) -> None:
    dbg.set_enabled(tmp_path, False)
    out = dbg.hook_handle(
        "postToolUseFailure",
        {"cwd": str(tmp_path), "tool_name": "Shell", "error_message": "boom"},
    )
    assert out.get("skipped") is True


def test_cli_debug_enable_status(tmp_path: Path) -> None:
    from ascendc_pilot.cli import main

    assert main(["debug", "enable", "--project", str(tmp_path)]) == 0
    assert main(["debug", "status", "--project", str(tmp_path)]) == 0
    assert main(["debug", "disable", "--project", str(tmp_path)]) == 0
