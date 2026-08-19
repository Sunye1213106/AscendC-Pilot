# -*- coding: utf-8 -*-

from __future__ import annotations

from ascendc_pilot.planning.task_plan import current_workflow_id, mark_step_passed, plan_for


def _workflow_steps(plan):
    return [
        step["workflow_id"]
        for step in plan["steps"]
        if step.get("kind") == "workflow"
    ]


def test_pr_test_generation_does_not_expand_script_chain():
    plan = plan_for(
        {
            "needed_workflows": ["tg-solve"],
            "source": {"kind": "pull_request", "url": "https://github.com/acme/ops/pull/1"},
        }
    )
    assert [step["id"] for step in plan["steps"]] == [
        "workspace_acquire",
        "tg-solve",
    ]
    assert _workflow_steps(plan) == ["tg-solve"]


def test_task_plan_next_workflow_is_stable_after_each_completion():
    plan = plan_for(
        {
            "needed_workflows": ["tg-solve"],
            "source": {"kind": "pull_request", "url": "https://github.com/acme/ops/pull/1"},
        }
    )
    assert current_workflow_id(plan) == "tg-solve"
    plan = mark_step_passed(plan, "workspace_acquire")
    assert current_workflow_id(plan) == "tg-solve"
    plan = mark_step_passed(plan, "tg-solve")
    assert current_workflow_id(plan) == ""
    assert plan["status"] == "steps_complete"
