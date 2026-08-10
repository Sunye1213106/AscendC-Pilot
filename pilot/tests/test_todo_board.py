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

    from ascendc_pilot.workflows import get_workflow

    phases = [
        str(p.get("id") if isinstance(p, dict) else p)
        for p in get_workflow("uo-init").get("phases") or []
    ]
    assert phases == ["prepare", "extract", "analyze", "resolve", "commit", "review"]
    assert [item["id"] for item in items] == phases
    assert all(str(item["content"]).strip() for item in items)
    assert items[0]["status"] == "in_progress"
    assert items[0]["priority"] == "high"
    assert all(item["status"] == "pending" for item in items[1:])
    assert all(item.get("priority") == "medium" for item in items[1:])
    assert sum(1 for item in items if item["status"] == "in_progress") == 1
    sync = todo.get("todo_sync") or {}
    assert sync.get("merge") is False
    assert sync.get("require_full_list") is True
    assert sync.get("require_ids") is True
    assert sync.get("items") == items
    assert not (tmp_path / ".ascendc-pilot" / "todo.md").is_file()


def test_todo_marks_current_public_phase_native(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init")
    state = load_state(tmp_path)
    state["phase"] = "analyze"
    state["phase_label_zh"] = "确定性 CodeMap Pass"
    save_state(tmp_path, state)

    board = write_todo(tmp_path, state)
    by_id = {phase["id"]: phase["status"] for phase in board["phases"]}
    assert by_id["prepare"] == "done"
    assert by_id["extract"] == "done"
    assert by_id["analyze"] == "current"
    assert by_id["resolve"] == "pending"

    native = {item["id"]: item["status"] for item in board["native_items"]}
    assert native["prepare"] == "completed"
    assert native["extract"] == "completed"
    assert native["analyze"] == "in_progress"
    priorities = {item["id"]: item["priority"] for item in board["native_items"]}
    assert priorities["prepare"] == "low"
    assert priorities["extract"] == "low"
    assert priorities["analyze"] == "high"
    assert build_todo(tmp_path, state)["phase"] == "analyze"

    from ascendc_pilot.todo import attach_todo

    attached = attach_todo({"workflow_id": "uo-init"}, tmp_path, state=state)
    assert (attached.get("todo") or {}).get("todo_sync", {}).get("merge") is True
    assert len((attached.get("todo") or {}).get("todo_sync", {}).get("items") or []) == 6
