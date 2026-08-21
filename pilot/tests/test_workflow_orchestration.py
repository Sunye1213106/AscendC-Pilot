"""Primary Todos own orchestration; no sixth skill; scripts must not invent slash chains."""

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
    assert "uo-init" not in wids
    assert "tg-init" not in wids
    assert "ce-review" in wids
    assert "tg-plan" in wids
    assert "tg-solve" in wids


def test_plan_for_does_not_expand_multi_operator_from_one_slash() -> None:
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
    assert ids == ["tg-solve#0", "tg-solve#1"]
    assert "uo-init#0" not in ids
    assert "ce-review#0" not in ids


def test_policies_do_not_parallel_task_workflows() -> None:
    needles = (
        "uo-query 可与 `/tg-init` 并行",
        "uo-query 可与 /tg-init 并行",
        "`/ce-review` 可与 `/tg-init` 并行",
        "occupancy 不冲突即可并行",
        "CE review 属于推理出来的依赖",
    )
    paths = [
        REPO / "pilot" / "policies" / "invariants" / "intent-reasoning.md",
        REPO / "pilot" / "policies" / "invariants" / "host-runtime-contract.md",
        REPO / "docs" / "getting-started" / "quickstart.md",
        REPO / "docs" / "architecture" / "workflows.md",
        REPO / "docs" / "test" / "golden-e2e-pr-cases.md",
        REPO / "agents" / "CONTEXT.md",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            assert needle not in text, f"{path} still has {needle!r}"


def test_intent_reasoning_forces_inits_before_consume() -> None:
    text = (REPO / "pilot" / "policies" / "invariants" / "intent-reasoning.md").read_text(
        encoding="utf-8"
    )
    assert "init 先于调查" in text
    assert "/ce-review" in text and "消费" in text
    assert "分析这个 PR 并生成" not in text
    assert "Todo：`auto` → `/uo-init` → `/tg-init` → `/uo-query`" not in text


def test_intent_reasoning_uo_update_is_refresh_not_chained_after_init() -> None:
    text = (REPO / "pilot" / "policies" / "invariants" / "intent-reasoning.md").read_text(
        encoding="utf-8"
    )
    assert "按缺口二选一" in text
    assert "不要再跑 `/uo-update`" in text
    assert "禁止把 `/uo-update` 紧挨着排在刚完成的 `/uo-init` 后面" in text
    assert "不要为理解 PR diff 去跑 `/uo-update`" in text
    assert "* `uo-init`；" not in text
    assert "* `uo-update`；" not in text
    assert "不要默认加入 `/ce-review`" in text


def test_intent_reasoning_missing_ask_ui_requires_question_not_narration() -> None:
    text = (REPO / "pilot" / "policies" / "invariants" / "intent-reasoning.md").read_text(
        encoding="utf-8"
    )
    assert "不等于" in text
    assert "确认框已弹出" in text
    assert "立刻用 `question`" in text
    assert "禁止用文字告诉用户「框应该已经弹出」" in text
    assert "ask_ui_shown=false" in text


def test_plan_for_orders_tg_init_before_ce_review() -> None:
    planned = plan_for(
        {
            "needed_workflows": ["ce-review", "tg-init", "tg-plan"],
            "source": {"kind": "none"},
        }
    )
    wids = [str(s.get("workflow_id") or s.get("id")) for s in planned["steps"]]
    assert wids.index("tg-init") < wids.index("ce-review")
    assert wids.index("ce-review") < wids.index("tg-plan")
