# -*- coding: utf-8 -*-

from __future__ import annotations

from ascendc_pilot.planning.task_plan import current_workflow_id, mark_step_passed, plan_for


def _workflow_steps(plan):
    return [
        step["workflow_id"]
        for step in plan["steps"]
        if step.get("kind") == "workflow"
    ]


def test_pr_test_generation_closes_script_chain():
    plan = plan_for(
        {
            "needed_workflows": ["tg-solve"],
            "source": {"kind": "pull_request", "url": "https://github.com/acme/ops/pull/1"},
        }
    )
    assert [step["id"] for step in plan["steps"]] == [
        "workspace_acquire",
        "uo-init",
        "tg-init",
        "tg-plan",
        "tg-solve",
    ]
    assert _workflow_steps(plan) == ["uo-init", "tg-init", "tg-plan", "tg-solve"]


def test_task_plan_next_workflow_is_stable_after_each_completion():
    plan = plan_for(
        {
            "needed_workflows": ["tg-solve"],
            "source": {"kind": "pull_request", "url": "https://github.com/acme/ops/pull/1"},
        },
        {"has_uo": True, "uo_stale": False},
    )
    assert _workflow_steps(plan) == ["tg-init", "tg-plan", "tg-solve"]
    assert current_workflow_id(plan) == "tg-init"
    plan = mark_step_passed(plan, "workspace_acquire")
    assert current_workflow_id(plan) == "tg-init"
    plan = mark_step_passed(plan, "tg-init")
    assert current_workflow_id(plan) == "tg-plan"
    plan = mark_step_passed(plan, "tg-plan")
    assert current_workflow_id(plan) == "tg-solve"
    plan = mark_step_passed(plan, "tg-solve")
    assert current_workflow_id(plan) == ""
    assert plan["status"] == "steps_complete"


def test_fresh_uo_is_not_reinitialized():
    plan = plan_for(
        {
            "needed_workflows": ["tg-solve"],
            "source": {"kind": "local"},
        },
        {"has_uo": True, "uo_stale": False},
    )
    assert _workflow_steps(plan) == ["tg-init", "tg-plan", "tg-solve"]


def test_stale_uo_closes_to_update_not_init():
    plan = plan_for(
        {
            "needed_workflows": ["tg-solve"],
            "source": {"kind": "local"},
        },
        {"has_uo": True, "uo_stale": True},
    )
    assert _workflow_steps(plan) == ["uo-update", "tg-init", "tg-plan", "tg-solve"]


def test_user_named_uo_init_is_not_replaced_with_update():
    plan = plan_for(
        {
            "needed_workflows": ["uo-init", "tg-solve"],
            "source": {"kind": "local"},
        },
        {"has_uo": True, "uo_stale": True},
    )
    assert _workflow_steps(plan) == ["uo-init", "tg-init", "tg-plan", "tg-solve"]
