"""Public user-goal API with TaskPlan-derived progress.

The persistence/workflow implementation remains in ``user_goal_core``. This
facade makes TaskPlan the single source of truth for user-facing progress while
preserving the existing user-goal schema and public API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ascendc_pilot import user_goal_core as _core
from ascendc_pilot.user_goal_core import *  # noqa: F401,F403
from ascendc_pilot.planning.public_progress import project_public_plan


def _project_goal(goal: dict[str, Any] | None, project_root: Path | str) -> dict[str, Any] | None:
    if not goal:
        return goal
    template = [
        dict(item)
        for item in (goal.get("public_plan") or [])
        if isinstance(item, dict)
    ]
    if not template:
        return goal
    try:
        from ascendc_pilot.planning.task_plan import load_task_plan

        plan = load_task_plan(project_root)
    except Exception:  # noqa: BLE001
        plan = None
    if not plan:
        return goal
    out = dict(goal)
    out["public_plan"] = project_public_plan(
        plan,
        template,
        goal_status=str(goal.get("status") or "active"),
    )
    return out


def load_user_goal(project_root: Path | str) -> dict[str, Any] | None:
    """Load Goal metadata and derive public status from the current TaskPlan."""

    return _project_goal(_core.load_user_goal(project_root), project_root)


def mark_workflow_passed(project_root: Path | str, workflow_id: str) -> dict[str, Any] | None:
    """Advance the existing implementation, then persist its TaskPlan projection."""

    result = _core.mark_workflow_passed(project_root, workflow_id)
    if result is None:
        return None

    root = Path(project_root).expanduser().resolve()
    raw_goal = _core.load_user_goal(root)
    projected = _project_goal(raw_goal, root)
    if projected and projected != raw_goal:
        projected = _core.write_user_goal(root, projected)

    out = dict(result)
    if projected:
        out["goal"] = projected
        out["progress_line"] = _core.progress_line_zh(projected)
    return out


def __getattr__(name: str) -> Any:
    """Delegate private compatibility helpers to the implementation module."""

    return getattr(_core, name)
