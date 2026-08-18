"""Orchestration skill is the routing authority; no parallel Intent DAG."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.planning.task_plan import plan_for
from ascendc_pilot.workflows import WORKFLOWS

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills" / "workflow-orchestration"


def test_orchestration_skill_covers_eleven_slashes() -> None:
    io_text = (SKILL / "references" / "slash-io.md").read_text(encoding="utf-8")
    for slash in (
        "/uo-init",
        "/uo-update",
        "/uo-query",
        "/uo-investigate",
        "/ce-plan",
        "/ce-apply",
        "/ce-review",
        "/tg-init",
        "/tg-plan",
        "/tg-solve",
        "/handoff",
    ):
        assert slash in io_text
    assert "禁止 `pilot_run`" in io_text
    assert "脚本仓" in io_text and "可选" in io_text


def test_pipelines_include_uo_product_edge() -> None:
    text = (SKILL / "references" / "product-pipelines.md").read_text(encoding="utf-8")
    assert "/tg-init" in text
    assert ".uo" in text
    assert "goal-impact" not in text


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
    assert "uo-update" not in wids
    assert "tg-init" not in wids


def test_examples_cover_golden_nl_and_explicit_slash() -> None:
    golden = (SKILL / "examples" / "pr-analyze-and-cases" / "README.md").read_text(encoding="utf-8")
    slash = (SKILL / "examples" / "slash-tg-plan" / "README.md").read_text(encoding="utf-8")
    assert "ce-review" in golden and "tg-plan" in golden and "tg-solve" in golden
    assert "goal-impact" in golden  # forbidden name appears in the don't-do list
    assert "/tg-plan" in slash
    assert "只" in slash
