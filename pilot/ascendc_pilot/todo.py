"""Workflow progress for OpenCode native Todo (todowrite) — not chat Markdown."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ascendc_pilot.paths import agent_root, ensure_agent_layout
from ascendc_pilot.workflows import actions_for_phase, get_workflow, label_zh_for, state_ids

# OpenCode todowrite status values
_NATIVE_STATUS = {
    "done": "completed",
    "current": "in_progress",
    "pending": "pending",
}

# OpenCode todowrite requires ``priority`` on every item (SchemaError if missing).
_NATIVE_PRIORITY = {
    "in_progress": "high",
    "pending": "medium",
    "completed": "low",
}


def todo_path(project_root: Path) -> Path:
    """Legacy path kept for tests; chat must not render this file."""
    try:
        return agent_root(project_root) / "todo.md"
    except ValueError:
        # Architecture not pinned yet (pre-start / unit mocks).
        return Path(project_root).expanduser().resolve() / ".ascendc-pilot" / "todo.md"


def _phase_mark(phase_ids: list[str], phase: str, status: str) -> list[dict[str, str]]:
    current_idx = phase_ids.index(phase) if phase in phase_ids else -1
    phases: list[dict[str, str]] = []
    for i, pid in enumerate(phase_ids):
        if status == "passed":
            mark = "done"
        elif current_idx < 0:
            mark = "pending"
        elif i < current_idx:
            mark = "done"
        elif i == current_idx:
            mark = "current"
        else:
            mark = "pending"
        phases.append({"id": pid, "status": mark})
    return phases


def build_todo(
    project_root: Path,
    state: dict[str, Any] | None = None,
    *,
    allowed_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Structured progress for native Todo sync (no chat Markdown payload)."""
    from ascendc_pilot.state import load_state

    st = dict(state or load_state(project_root) or {})
    wid = str(st.get("workflow_id") or "")
    phase = str(st.get("phase") or "")
    status = str(st.get("status") or "")

    try:
        from ascendc_pilot.user_goal import is_auto_session, load_user_goal

        goal = load_user_goal(project_root)
        auto = is_auto_session(goal)
    except Exception:  # noqa: BLE001
        goal = None
        auto = False
    if auto and str((goal or {}).get("status") or "") in {"active", "revising"}:
        native_items: list[dict[str, str]] = []
        phases: list[dict[str, str]] = []
        for item in goal.get("public_plan") or []:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id") or "")
            label = str(item.get("summary_zh") or pid)
            raw = str(item.get("status") or "pending")
            if raw in {"passed", "skipped", "done"}:
                mark = "done"
                status_native = "completed"
            elif raw == "in_progress":
                mark = "current"
                status_native = "in_progress"
            else:
                mark = "pending"
                status_native = "pending"
            phases.append({"id": pid, "label_zh": label, "status": mark})
            native_items.append(
                {
                    "id": pid,
                    "content": label,
                    "status": status_native,
                    "priority": _NATIVE_PRIORITY.get(status_native, "medium"),
                }
            )
        in_prog = [it for it in native_items if it["status"] == "in_progress"]
        if len(in_prog) > 1:
            keep = in_prog[0]["id"]
            for it in native_items:
                if it["status"] == "in_progress" and it["id"] != keep:
                    it["status"] = "pending"
        return {
            "workflow_id": wid,
            "run_id": st.get("run_id") or "",
            "phase": phase,
            "phase_label_zh": "",
            "status": status,
            "sync": "opencode_native_todowrite",
            "phases": phases,
            "native_items": native_items,
            "open_items": [],
            "next_actions": [],
        }

    if not wid:
        return {
            "workflow_id": "",
            "sync": "opencode_native_todowrite",
            "phases": [],
            "native_items": [],
            "open_items": [],
            "next_actions": [],
            "todo_sync": {
                "tool": "todowrite",
                "merge": False,
                "require_full_list": True,
                "require_ids": True,
                "items": [],
                "instruction_zh": "无活动 workflow；勿写 Todo。",
            },
        }

    try:
        meta = get_workflow(wid)
    except KeyError:
        meta = {}

    phase_ids = state_ids(wid) if wid else []
    if not phase_ids:
        phase_ids = [str(s.get("id") or "") for s in (meta.get("states") or []) if isinstance(s, dict)]

    phases: list[dict[str, str]] = []
    native_items: list[dict[str, str]] = []
    for row in _phase_mark(phase_ids, phase, status):
        pid = row["id"]
        mark = row["status"]
        label = label_zh_for(wid, pid)
        if label in {"确认进入规划", "批准规划"}:
            label = "完成当前步骤" if mark != "done" else "已完成"
        phases.append({"id": pid, "label_zh": label, "status": mark})
        status_native = _NATIVE_STATUS.get(mark, "pending")
        native_items.append(
            {
                "id": pid,
                "content": label,
                "status": status_native,
                "priority": _NATIVE_PRIORITY.get(status_native, "medium"),
            }
        )

    # Enforce at most one in_progress
    in_prog = [it for it in native_items if it["status"] == "in_progress"]
    if len(in_prog) > 1:
        keep = in_prog[0]["id"]
        for it in native_items:
            if it["status"] == "in_progress" and it["id"] != keep:
                it["status"] = "pending"

    open_items = []
    for it in st.get("open_items") or []:
        if not isinstance(it, dict):
            continue
        open_items.append(
            {
                "id": str(it.get("id") or ""),
                "label_zh": str(it.get("label_zh") or it.get("id") or ""),
                "status": str(it.get("status") or "open"),
            }
        )

    actions = allowed_actions
    if actions is None and phase:
        try:
            actions = actions_for_phase(wid, phase)
        except Exception:  # noqa: BLE001
            actions = []
    next_actions = []
    for a in actions or []:
        if not isinstance(a, dict):
            continue
        next_actions.append(
            {
                "id": str(a.get("id") or ""),
                "label_zh": str(a.get("label_zh") or a.get("id") or ""),
            }
        )

    return {
        "workflow_id": wid,
        "run_id": st.get("run_id") or "",
        "phase": phase,
        "phase_label_zh": label_zh_for(wid, phase) if phase else "",
        "status": status,
        "sync": "opencode_native_todowrite",
        "phases": phases,
        "native_items": native_items,
        "open_items": open_items,
        "next_actions": next_actions,
    }


def _todo_sync_block(
    native_items: list[dict[str, str]],
    *,
    merge: bool,
) -> dict[str, Any]:
    return {
        "tool": "todowrite",
        "merge": merge,
        "require_full_list": True,
        "require_ids": True,
        "forbid_partial_overwrite": True,
        "items": list(native_items),
    }


def write_todo(
    project_root: Path,
    state: dict[str, Any] | None = None,
    *,
    allowed_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Refresh structured todo only — do not write chat Markdown boards."""
    try:
        arch = None
        if isinstance(state, dict):
            arch = str(state.get("architecture") or "").strip() or None
        ensure_agent_layout(project_root, arch=arch)
    except ValueError as exc:
        if "ARCHITECTURE_MISSING" not in str(exc):
            raise
    return build_todo(project_root, state, allowed_actions=allowed_actions)


def attach_todo(
    payload: dict[str, Any],
    project_root: Path,
    *,
    state: dict[str, Any] | None = None,
    allowed_actions: list[dict[str, Any]] | None = None,
    sync_merge: bool | None = None,
) -> dict[str, Any]:
    """Attach structured ``todo`` for native todowrite; never attach ``todo_md``."""
    actions = allowed_actions
    if actions is None and isinstance(payload.get("allowed_actions"), list):
        actions = payload["allowed_actions"]
    st = state
    if st is None and payload.get("workflow_id"):
        st = payload
    board = write_todo(project_root, st, allowed_actions=actions)
    if sync_merge is None:
        if payload.get("fresh_start") is True:
            merge = False
        elif payload.get("resumed") is True:
            merge = True
        else:
            merge = True
    else:
        merge = bool(sync_merge)
    board["todo_sync"] = _todo_sync_block(list(board.get("native_items") or []), merge=merge)
    out = dict(payload)
    out.pop("todo_md", None)
    out["todo"] = board
    return out
