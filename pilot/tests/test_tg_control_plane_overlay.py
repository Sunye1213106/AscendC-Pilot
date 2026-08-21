"""TG workflow ordering after the product-model rebuild."""

from __future__ import annotations

from pathlib import Path

import ascendc_pilot.actions as actions
from ascendc_pilot.human_confirm import primary_interactive_steps
from ascendc_pilot.workflows import WORKFLOWS, action_by_id, phase_pipeline


def test_tg_pipelines_are_explicit() -> None:
    assert phase_pipeline("tg-init", "kb_ready") == ["kb_check"]
    assert phase_pipeline("tg-init", "scan") == ["repo_scan"]
    assert phase_pipeline("tg-init", "bind") == ["bind_init", "bind_review", "bind_promote"]
    assert phase_pipeline("tg-init", "validate") == ["validate_init"]
    assert phase_pipeline("tg-init", "confirm") == []
    assert phase_pipeline("tg-plan", "gate") == ["plan_precheck"]
    assert phase_pipeline("tg-plan", "fuse") == ["plan_fuse", "plan_promote"]
    assert phase_pipeline("tg-plan", "validate") == ["plan_validate"]
    assert phase_pipeline("tg-plan", "approve") == ["plan_approve"]
    assert phase_pipeline("tg-solve", "gate") == ["solve_precheck"]
    assert phase_pipeline("tg-solve", "construct") == ["construct_cases", "construct_promote"]
    assert phase_pipeline("tg-solve", "replay") == ["replay_round"]
    assert phase_pipeline("tg-solve", "analyze") == ["analyze_round", "analyze_promote"]
    assert phase_pipeline("tg-solve", "certify") == ["solve_certify"]
    assert not (WORKFLOWS["tg-solve"].get("mode_overlays") or {})
    assert "lemma_mine" not in [a["id"] for a in WORKFLOWS["tg-solve"]["actions"]]


def test_tg_engines_registered() -> None:
    from ascendc_pilot.actions.engines import ENGINE_REGISTRY

    for key in (
        ("tg-init", "kb_check"),
        ("tg-init", "repo_scan"),
        ("tg-init", "bind_promote"),
        ("tg-init", "validate_init"),
        ("tg-plan", "plan_precheck"),
        ("tg-plan", "plan_promote"),
        ("tg-plan", "plan_validate"),
        ("tg-solve", "solve_precheck"),
        ("tg-solve", "construct_promote"),
        ("tg-solve", "replay_round"),
        ("tg-solve", "analyze_promote"),
        ("tg-solve", "solve_certify"),
    ):
        assert key in ENGINE_REGISTRY, key
    assert ("tg-solve", "lemma_mine") not in ENGINE_REGISTRY
    assert ("tg-init", "semantic_bind") not in ENGINE_REGISTRY


def test_tg_primary_actions_write_canonical_products() -> None:
    review = action_by_id("tg-init", "bind_review") or {}
    promote = action_by_id("tg-init", "bind_promote") or {}
    plan_action = action_by_id("tg-plan", "plan_approve") or {}
    assert review["execution_mode"] == "primary_review"
    assert review["agent_id"] == "ascendc-pilot"
    assert review.get("output_mode") == "return_value"
    assert not any("referee.yaml" in str(p) for p in (review.get("allowed_write_paths") or []))
    assert promote["execution_mode"] == "deterministic"
    assert "tg/init.yaml" in (promote.get("allowed_write_paths") or [])
    assert plan_action["execution_mode"] == "primary_interactive"
    assert "tg/plan.md" in (plan_action.get("allowed_write_paths") or [])


def test_staged_analyst_does_not_publish_canonical() -> None:
    bind = action_by_id("tg-init", "bind_init") or {}
    fuse = action_by_id("tg-plan", "plan_fuse") or {}
    construct = action_by_id("tg-solve", "construct_cases") or {}
    for row in (bind, fuse, construct):
        assert row.get("agent_id") == "tg-analyst"
        assert row.get("output_mode") == "staged"
        writes = row.get("allowed_write_paths") or []
        assert all("tg/init.yaml" not in p and "tg/plan.md" not in p for p in writes)
    axes = bind.get("fanout_axes") or []
    assert {a.get("id") for a in axes} == {"harness", "bind"}
    assert {a.get("task_prompt_id") for a in axes} == {"tg/bind-harness", "tg/bind-columns"}
    bind_axis = next(a for a in axes if a.get("id") == "bind")
    assert "profile" in str(bind_axis.get("focus") or "")
    assert "无参数" in str(bind_axis.get("focus") or "")


def test_reset_policy_only_touches_three_products() -> None:
    plan = WORKFLOWS["tg-plan"]["reset_policy"]
    solve = WORKFLOWS["tg-solve"]["reset_policy"]
    assert "tg/init.yaml" in plan["reinit_preserve"]
    assert "tg/plan.md" in solve["reinit_preserve"]
    assert "tg/worklog.md" in solve["reinit_delete"]


def test_tk_cover_is_removed() -> None:
    from ascendc_pilot.router import route
    from ascendc_pilot.workflows import list_user_workflows

    assert "tk-cover" not in WORKFLOWS
    assert "tg-solve" in list_user_workflows()
    routed = route("/tk-cover")
    assert routed.get("ok") is False


def test_ce_plan_has_no_scenario_overlay() -> None:
    from ascendc_pilot.workflows import get_workflow

    plan = get_workflow("ce-plan")
    apply = get_workflow("ce-apply")
    assert not (plan.get("mode_overlays") or {})
    assert not (apply.get("mode_overlays") or {})
    assert "scenario_knobs" not in [a["id"] for a in plan["actions"]]
    assert "scenario_knobs" not in [a["id"] for a in apply["actions"]]


def test_primary_steps_do_not_inherit_uo_scope_recipe(tmp_path: Path) -> None:
    steps = primary_interactive_steps("human_confirm", tmp_path, {})
    joined = "\n".join(steps)
    assert "uo-scope" not in joined
    assert "AskQuestion" in joined or "question UI" in joined.lower()
    assert "confirm" in joined
    assert "pilot_run" in joined
    assert "acp run-action" not in joined
    assert "interpret-user-turn" in joined
    assert "acp answer" not in joined


def test_actions_facade_replaces_generic_primary_steps(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        actions._runtime,
        "prepare_action",
        lambda *_args, **_kwargs: {
            "ok": True,
            "action_id": "plan_approve",
            "execution_mode": "primary_interactive",
            "interactive_steps": ["acp uo-scope scan"],
            "human_interaction_request": {"request_id": "req-test"},
        },
    )
    result = actions.prepare_action(tmp_path, "plan_approve")
    assert result["ok"] is True
    assert result["dispatch_task"] is False
    joined = "\n".join(result["interactive_steps"])
    assert "uo-scope" not in joined
    assert "approve" in joined
    assert "pilot_run" in joined
    assert "acp run-action" not in joined
    assert "interpret-user-turn" in joined
    assert "acp answer" not in joined


def test_plan_draft_binds_ce_plan_method() -> None:
    from ascendc_pilot.actions.runtime import _resolve_capability_method

    repo = Path(__file__).resolve().parents[2]
    action = action_by_id("ce-plan", "plan_draft")
    assert action is not None
    path = _resolve_capability_method(repo, action)
    assert path is not None
    assert path.name == "SKILL.md"
    assert "ce-plan-draft" in path.as_posix().replace("\\", "/")


def test_bind_review_return_value_skips_writable_check() -> None:
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.actions.runtime import _check_required_outputs_writable

    review = action_by_id("tg-init", "bind_review") or {}
    assert review.get("output_mode") == "return_value"
    assert OUTPUT_CONTRACT_PATHS["tg-bind-review-v1"] == []
    check = _check_required_outputs_writable(
        workflow_id="tg-init",
        action_id="bind_review",
        actor_id="ascendc-pilot",
        contract_id="tg-bind-review-v1",
        output_mode="return_value",
        write_paths=[],
        run_id="RUN",
        project_root=Path("."),
    )
    assert check.get("ok") is True
    assert check.get("skipped") is True
    assert check.get("error") != "OUTPUT_NOT_WRITABLE"
