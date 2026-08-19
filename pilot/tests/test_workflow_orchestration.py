"""Primary Goal Contract + goal-intake own orchestration; no sixth skill."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.planning.task_plan import plan_for
from ascendc_pilot.router import route
from ascendc_pilot.workflows import WORKFLOWS

REPO = Path(__file__).resolve().parents[2]


def test_orchestration_skill_directory_must_not_exist() -> None:
    assert not (REPO / "skills" / "workflow-orchestration").exists()


def test_nl_requires_primary_then_auto() -> None:
    hit = route("帮我给这个 PR 生成 case")
    assert hit.get("ok") is False
    assert hit.get("error") == "primary_agent_route_required"
    assert not hit.get("workflow_id")


def test_plan_for_never_inserts_goal_impact() -> None:
    planned = plan_for(
        {
            "needed_workflows": ["ce-review", "tg-plan", "tg-solve"],
            "source": {"kind": "pull_request", "url": "https://github.com/org/repo/pull/1"},
        },
        {"has_uo": True, "uo_stale": True, "has_tg_init": False},
    )
    wids = [str(s.get("workflow_id") or s.get("id")) for s in planned["steps"]]
    assert "goal-impact" not in wids
    assert "goal-impact" not in WORKFLOWS
    assert "uo-init" in wids
    assert "ce-review" in wids
    assert "tg-init" in wids
    assert "tg-plan" in wids
    assert "tg-solve" in wids


def test_plan_for_expands_multi_operator_targets() -> None:
    planned = plan_for(
        {
            "needed_workflows": ["tg-solve"],
            "source": {"kind": "pull_request", "url": "https://github.com/org/repo/pull/1"},
            "operator_targets": [
                {
                    "operator_root": "/ws/op_a",
                    "operator_name": "op_a",
                    "architecture": "arch35",
                },
                {
                    "operator_root": "/ws/op_b",
                    "operator_name": "op_b",
                    "architecture": "arch22",
                },
            ],
        }
    )
    ids = [str(s.get("id")) for s in planned["steps"] if str(s.get("kind")) == "workflow"]
    assert "uo-init#0" in ids
    assert "uo-init#1" in ids
    assert "ce-review#0" in ids
    assert "ce-review#1" in ids
    assert ids.index("uo-init#1") > ids.index("tg-solve#0")
