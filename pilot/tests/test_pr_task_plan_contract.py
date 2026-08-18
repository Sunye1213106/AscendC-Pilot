# -*- coding: utf-8 -*-

from __future__ import annotations

from ascendc_pilot.planning.task_plan import current_workflow_id, mark_step_passed, plan_for


def _workflow_steps(plan):
    return [
        step["workflow_id"]
        for step in plan["steps"]
        if step.get("kind") == "workflow"
    ]


def test_pr_test_generation_expands_review_before_tg():
    plan = plan_for(
        {
            "needed_workflows": ["tg-solve"],
            "source": {"kind": "pull_request", "ref": "https://example.invalid/pull/1"},
        }
    )
    assert _workflow_steps(plan) == [
        "uo-init",
        "ce-review",
        "tg-init",
        "tg-plan",
        "tg-solve",
    ]


def test_task_plan_next_workflow_is_stable_after_completion():
    plan = plan_for(
        {
            "needed_workflows": ["tg-solve"],
            "source": {"kind": "pull_request", "ref": "https://example.invalid/pull/1"},
        }
    )
    assert current_workflow_id(plan) == "uo-init"
    plan = mark_step_passed(plan, "uo-init")
    assert current_workflow_id(plan) == "ce-review"
    plan = mark_step_passed(plan, "ce-review")
    assert current_workflow_id(plan) == "tg-init"
    plan = mark_step_passed(plan, "tg-init")
    assert current_workflow_id(plan) == "tg-plan"
    plan = mark_step_passed(plan, "tg-plan")
    assert current_workflow_id(plan) == "tg-solve"
