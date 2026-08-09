"""Workflow TODO → OpenCode native todowrite items."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.state import load_state, save_state, start_workflow
from ascendc_pilot.todo import build_todo, write_todo


def test_start_attaches_native_items_not_todo_md(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init")
    assert "todo_md" not in state
    todo = state.get("todo") or {}
    assert todo.get("sync") == "opencode_native_todowrite"
    items = todo.get("native_items") or []
    # One item per phase, in spec order. Assert the ids — the Chinese labels
    # live in the Workflow Spec and restating them here only duplicates it.
    from ascendc_pilot.workflows import get_workflow

    phases = [
        str(p.get("id") if isinstance(p, dict) else p)
        for p in get_workflow("uo-init").get("phases") or []
    ]
    assert [it["id"] for it in items] == phases
    assert all(str(it["content"]).strip() for it in items)
    assert items[0]["status"] == "in_progress"
    assert items[0]["id"] == "prepare"
    assert items[0]["priority"] == "high"
    assert all(it["status"] == "pending" for it in items[1:])
    assert all(it.get("priority") == "medium" for it in items[1:])
    assert sum(1 for it in items if it["status"] == "in_progress") == 1
    sync = todo.get("todo_sync") or {}
    assert sync.get("merge") is False
    assert sync.get("require_full_list") is True
    assert sync.get("require_ids") is True
    assert sync.get("items") == items
    assert all("priority" in it for it in sync["items"])
    assert "priority" in str(sync.get("instruction_zh") or "")
    assert "禁止子集" in str(sync.get("instruction_zh") or "")
    assert "跳过" in str(sync.get("instruction_zh") or "")
    # Must not leave a chat Markdown board for the agent to paste
    assert not (tmp_path / ".ascendc-pilot" / "todo.md").is_file()


def test_todo_marks_current_phase_native(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init")
    st = load_state(tmp_path)
    st["phase"] = "scope"
    st["phase_label_zh"] = "范围确认"
    save_state(tmp_path, st)
    board = write_todo(tmp_path, st)
    by_id = {p["id"]: p["status"] for p in board["phases"]}
    assert by_id["prepare"] == "done"
    assert by_id["scope"] == "current"
    native = {it["id"]: it["status"] for it in board["native_items"]}
    assert native["prepare"] == "completed"
    assert native["scope"] == "in_progress"
    pri = {it["id"]: it["priority"] for it in board["native_items"]}
    assert pri["prepare"] == "low"
    assert pri["scope"] == "high"
    assert build_todo(tmp_path, st)["phase"] == "scope"
    from ascendc_pilot.todo import attach_todo

    attached = attach_todo({"workflow_id": "uo-init"}, tmp_path, state=st)
    assert (attached.get("todo") or {}).get("todo_sync", {}).get("merge") is True
    assert len((attached.get("todo") or {}).get("todo_sync", {}).get("items") or []) == 6
