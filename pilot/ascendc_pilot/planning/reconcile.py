# -*- coding: utf-8 -*-
"""Interrupt → Goal constraints update + invalidate downstream Task Plan steps."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ascendc_pilot.goal_turn import REL_REVISE, classify_goal_turn

_DTYPE_DROP = re.compile(
    r"(不要|别用|去掉|排除|跳过)\s*(fp32|fp16|bf16|int8|int32|float|half)",
    re.I,
)


def apply_revision(project_root: Path | str, *, delta_text: str) -> dict[str, Any]:
    """Update Goal constraints from a revise turn and invalidate downstream work."""
    from ascendc_pilot.planning.task_plan import (
        invalidate_from,
        load_task_plan,
        write_task_plan,
    )
    from ascendc_pilot.user_goal import load_user_goal, write_user_goal

    root = Path(project_root).expanduser().resolve()
    delta = str(delta_text or "").strip()
    goal = load_user_goal(root)
    plan = load_task_plan(root)
    out: dict[str, Any] = {"ok": True, "revised": False, "invalidated": []}
    if not goal:
        return {"ok": False, "error": "NO_ACTIVE_GOAL"}

    constraints = dict(goal.get("constraints") or {})
    match = _DTYPE_DROP.search(delta)
    if match:
        dropped = str(match.group(2) or "").strip().lower()
        excluded = [str(x).lower() for x in (constraints.get("exclude_dtype") or [])]
        if dropped and dropped not in excluded:
            excluded.append(dropped)
        constraints["exclude_dtype"] = excluded
        out["exclude_dtype"] = excluded

    if delta:
        notes = list(constraints.get("revision_notes") or [])
        notes.append(delta)
        constraints["revision_notes"] = notes[-12:]

    goal["constraints"] = constraints
    if str(goal.get("status") or "") == "revising":
        goal["status"] = "active"
    write_user_goal(root, goal)
    out["revised"] = True

    if plan:
        # Keep acquire / UO; invalidate obligations and TG if constraints changed.
        from_id = "tg-plan"
        steps = [str(s.get("id") or "") for s in (plan.get("steps") or []) if isinstance(s, dict)]
        if "tg-plan" in steps:
            from_id = "tg-plan"
        elif "tg-init" in steps:
            from_id = "tg-init"
        elif steps:
            from_id = steps[-1]
        if from_id:
            plan = invalidate_from(plan, from_step_id=from_id)
            write_task_plan(root, plan)
            out["invalidated"] = from_id
            out["next_workflow_id"] = from_id
    return out


def reconcile_user_turn(project_root: Path | str, text: str) -> dict[str, Any]:
    """Classify the turn; on revise, update Goal and keep the same session."""
    classified = classify_goal_turn(text)
    relation = str(classified.get("relation") or "")
    if relation != REL_REVISE:
        return {"ok": True, "relation": relation, "classified": classified, "revised": False}
    applied = apply_revision(project_root, delta_text=text)
    applied["relation"] = relation
    applied["classified"] = classified
    return applied
