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
            "source": {"kind": "pull_request", "url": "https://github.com/acme/ops/pull/1"},
        }
    )
    assert [step["id"] for step in plan["steps"]] == [
        "workspace_acquire",
        "uo-init",
        "ce-review",
        "tg-init",
        "tg-plan",
        "tg-solve",
    ]
    assert _workflow_steps(plan) == [
        "uo-init",
        "ce-review",
        "tg-init",
        "tg-plan",
        "tg-solve",
    ]


def test_task_plan_next_workflow_is_stable_after_each_completion():
    plan = plan_for(
        {
            "needed_workflows": ["tg-solve"],
            "source": {"kind": "pull_request", "url": "https://github.com/acme/ops/pull/1"},
        }
    )
    # workspace_acquire is a deterministic goal-intake harness action, not a workflow.
    assert current_workflow_id(plan) == "uo-init"
    plan = mark_step_passed(plan, "workspace_acquire")
    assert current_workflow_id(plan) == "uo-init"

    expected = [
        ("uo-init", "ce-review"),
        ("ce-review", "tg-init"),
        ("tg-init", "tg-plan"),
        ("tg-plan", "tg-solve"),
        ("tg-solve", ""),
    ]
    for just_done, next_wf in expected:
        plan = mark_step_passed(plan, just_done)
        assert current_workflow_id(plan) == next_wf

    assert plan["status"] == "steps_complete"
