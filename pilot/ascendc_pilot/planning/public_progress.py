"""Project user-facing progress from the persisted TaskPlan.

TaskPlan step status is the single source of truth. ``user_goal.public_plan``
keeps stable ids/labels for presentation, but its status values are only a
compatibility projection and must never advance independently.
"""

from __future__ import annotations

from typing import Any

from ascendc_pilot.planning.task_plan import public_id_for_workflow

_TERMINAL = {"passed", "skipped"}


def _task_public_id(step: dict[str, Any]) -> str:
    workflow_id = str(step.get("workflow_id") or "").strip()
    step_id = str(step.get("id") or "").strip()
    return public_id_for_workflow(workflow_id or step_id)


def _acceptance_satisfied_from_plan(plan: dict[str, Any]) -> bool:
    required = [str(item) for item in (plan.get("acceptance") or []) if str(item)]
    if not required:
        return True
    status = plan.get("acceptance_status") if isinstance(plan.get("acceptance_status"), dict) else {}
    return all(str(status.get(item) or "") == "passed" for item in required)


def project_public_plan(
    plan: dict[str, Any] | None,
    template: list[dict[str, Any]] | None,
    *,
    goal_status: str = "active",
) -> list[dict[str, Any]]:
    """Return public progress derived only from TaskPlan state.

    Multiple TaskPlan steps may map to one public row. ``tg-init`` maps to
    ``bind_harness``; ``tg-plan`` maps to ``generate_cases``. The public row is
    complete only after all mapped steps are terminal. ``deliver`` is synthetic:
    it can begin only after every TaskPlan step is terminal and acceptance is
    satisfied.
    """

    rows = [dict(item) for item in (template or []) if isinstance(item, dict)]
    if not rows or not isinstance(plan, dict):
        return rows

    grouped: dict[str, list[str]] = {}
    task_steps = [step for step in (plan.get("steps") or []) if isinstance(step, dict)]
    for step in task_steps:
        public_id = _task_public_id(step)
        if not public_id:
            continue
        grouped.setdefault(public_id, []).append(str(step.get("status") or "pending"))

    # A narrowly requested plan may omit earlier TG inits. Once a later TG
    # step is active, mark upstream public rows complete.
    later_tg = [
        str(step.get("status") or "pending")
        for step in task_steps
        if str(step.get("workflow_id") or step.get("id") or "") in {"tg-plan", "tg-solve"}
    ]
    if later_tg and any(state in {"in_progress", "passed", "skipped"} for state in later_tg):
        grouped.setdefault("bind_harness", ["passed"])
    if "generate_cases" not in grouped:
        solve_states = [
            str(step.get("status") or "pending")
            for step in task_steps
            if str(step.get("workflow_id") or step.get("id") or "") == "tg-solve"
        ]
        if solve_states:
            if any(state in {"in_progress", "passed", "skipped"} for state in solve_states):
                grouped["generate_cases"] = ["passed"]
            else:
                grouped["generate_cases"] = ["pending"]

    all_steps_terminal = bool(task_steps) and all(
        str(step.get("status") or "") in _TERMINAL for step in task_steps
    )
    acceptance_ok = _acceptance_satisfied_from_plan(plan)

    for row in rows:
        public_id = str(row.get("id") or "")
        if public_id == "deliver":
            if str(goal_status or "") == "completed":
                row["status"] = "passed"
            elif all_steps_terminal and acceptance_ok:
                row["status"] = "in_progress"
            else:
                row["status"] = "pending"
            continue

        states = grouped.get(public_id, [])
        if not states:
            row["status"] = "pending"
            continue
        if all(state == "skipped" for state in states):
            row["status"] = "skipped"
        elif all(state in _TERMINAL for state in states):
            row["status"] = "passed"
        elif any(state == "in_progress" for state in states):
            row["status"] = "in_progress"
        elif any(state in _TERMINAL for state in states):
            # Multi-target / grouped public work: some mapped steps are already
            # complete while another has not started yet.
            row["status"] = "in_progress"
        else:
            row["status"] = "pending"

    # Corrupt or hand-edited TaskPlans must not make OpenCode render two current
    # public rows. Prefer the first row in the stable public-plan order.
    current = [row for row in rows if str(row.get("status") or "") == "in_progress"]
    if len(current) > 1:
        keep = str(current[0].get("id") or "")
        for row in rows:
            if str(row.get("status") or "") == "in_progress" and str(row.get("id") or "") != keep:
                row["status"] = "pending"
    return rows
