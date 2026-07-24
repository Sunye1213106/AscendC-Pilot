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
    assert [it["content"] for it in items[:6]] == [
        "环境准备",
        "范围确认",
        "结构抽取",
        "语义闭合",
        "导出与校验",
        "产物审查",
    ]
    assert items[0]["status"] == "in_progress"
    assert items[0]["id"] == "prepare"
    assert all(it["status"] == "pending" for it in items[1:])
    assert sum(1 for it in items if it["status"] == "in_progress") == 1
    sync = todo.get("todo_sync") or {}
    assert sync.get("merge") is False
    assert sync.get("require_full_list") is True
    assert sync.get("require_ids") is True
    assert sync.get("items") == items
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
    assert build_todo(tmp_path, st)["phase"] == "scope"
    from ascendc_pilot.todo import attach_todo

    attached = attach_todo({"workflow_id": "uo-init"}, tmp_path, state=st)
    assert (attached.get("todo") or {}).get("todo_sync", {}).get("merge") is True
    assert len((attached.get("todo") or {}).get("todo_sync", {}).get("items") or []) == 6
