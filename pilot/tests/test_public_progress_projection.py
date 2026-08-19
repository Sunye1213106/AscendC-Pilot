from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.planning.public_progress import project_public_plan
from ascendc_pilot.planning.task_plan import write_task_plan
from ascendc_pilot.user_goal import load_user_goal
from ascendc_pilot.user_goal_core import write_user_goal
from ascendc_pilot.todo import build_todo


def _template() -> list[dict[str, str]]:
    return [
        {"id": "acquire_change", "summary_zh": "获取 PR 与代码", "status": "pending"},
        {"id": "ensure_knowledge", "summary_zh": "建立算子理解", "status": "pending"},
        {"id": "review_change", "summary_zh": "审查改动并确定影响范围", "status": "pending"},
        {"id": "generate_cases", "summary_zh": "规划并生成测试用例", "status": "pending"},
        {"id": "validate_cases", "summary_zh": "回放验证", "status": "pending"},
        {"id": "deliver", "summary_zh": "输出结果", "status": "pending"},
    ]


def _plan(*, review: str = "in_progress", tg_init: str = "pending", tg_plan: str = "pending", tg_solve: str = "pending") -> dict:
    return {
        "schema": "pilot-task-plan/v1",
        "steps": [
            {"id": "workspace_acquire", "kind": "harness_action", "workflow_id": "", "status": "passed"},
            {"id": "uo-init", "kind": "workflow", "workflow_id": "uo-init", "status": "passed"},
            {"id": "ce-review", "kind": "workflow", "workflow_id": "ce-review", "status": review},
            {"id": "tg-init", "kind": "workflow", "workflow_id": "tg-init", "status": tg_init},
            {"id": "tg-plan", "kind": "workflow", "workflow_id": "tg-plan", "status": tg_plan},
            {"id": "tg-solve", "kind": "workflow", "workflow_id": "tg-solve", "status": tg_solve},
        ],
        "acceptance": ["required_obligations_covered", "cases_validated"],
        "acceptance_status": {
            "required_obligations_covered": "pending",
            "cases_validated": "pending",
        },
    }


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {str(row["id"]): row for row in rows}


def test_uo_completion_projects_review_as_current() -> None:
    rows = _by_id(project_public_plan(_plan(), _template()))
    assert rows["acquire_change"]["status"] == "passed"
    assert rows["ensure_knowledge"]["status"] == "passed"
    assert rows["review_change"]["status"] == "in_progress"
    assert rows["generate_cases"]["status"] == "pending"


def test_review_completion_projects_tg_as_current() -> None:
    plan = _plan(review="passed", tg_init="in_progress")
    rows = _by_id(project_public_plan(plan, _template()))
    assert rows["review_change"]["status"] == "passed"
    assert rows["generate_cases"]["status"] == "in_progress"


def test_generate_cases_waits_for_both_tg_init_and_plan() -> None:
    plan = _plan(review="passed", tg_init="passed", tg_plan="in_progress")
    rows = _by_id(project_public_plan(plan, _template()))
    assert rows["generate_cases"]["status"] == "in_progress"


def test_deliver_requires_taskplan_terminal_and_acceptance() -> None:
    plan = _plan(review="passed", tg_init="passed", tg_plan="passed", tg_solve="passed")
    rows = _by_id(project_public_plan(plan, _template()))
    assert rows["validate_cases"]["status"] == "passed"
    assert rows["deliver"]["status"] == "pending"

    plan["acceptance_status"] = {
        "required_obligations_covered": "passed",
        "cases_validated": "passed",
    }
    rows = _by_id(project_public_plan(plan, _template()))
    assert rows["deliver"]["status"] == "in_progress"
    rows = _by_id(project_public_plan(plan, _template(), goal_status="completed"))
    assert rows["deliver"]["status"] == "passed"


def test_solve_only_plan_projects_generation_done_and_validation_current() -> None:
    plan = {
        "steps": [
            {"id": "tg-solve", "workflow_id": "tg-solve", "status": "in_progress"},
        ],
        "acceptance": ["cases_validated"],
        "acceptance_status": {"cases_validated": "pending"},
    }
    rows = _by_id(project_public_plan(plan, _template()))
    assert rows["generate_cases"]["status"] == "passed"
    assert rows["validate_cases"]["status"] == "in_progress"


def test_load_user_goal_ignores_stale_persisted_public_status(tmp_path: Path) -> None:
    stale = _template()
    stale[1]["status"] = "in_progress"
    stale[2]["status"] = "pending"
    write_user_goal(
        tmp_path,
        {
            "schema": "pilot-user-goal/v2",
            "status": "active",
            "session_kind": "auto",
            "public_plan": stale,
        },
    )
    write_task_plan(tmp_path, _plan())

    goal = load_user_goal(tmp_path)
    assert goal is not None
    rows = _by_id(goal["public_plan"])
    assert rows["ensure_knowledge"]["status"] == "passed"
    assert rows["review_change"]["status"] == "in_progress"

    board = build_todo(tmp_path, state={"workflow_id": "ce-review", "status": "running"})
    native = {item["id"]: item for item in board["native_items"]}
    assert native["ensure_knowledge"]["status"] == "completed"
    assert native["review_change"]["status"] == "in_progress"

    # Persistence remains YAML-compatible; projection happens at the API boundary.
    raw = yaml.safe_load(
        (tmp_path / ".ascendc-pilot" / "control" / "user_goal.yaml").read_text(encoding="utf-8")
    )
    assert raw["public_plan"][1]["status"] == "in_progress"
