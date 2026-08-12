"""TG workflow ordering and primary-interactive control-plane regressions."""

from __future__ import annotations

from pathlib import Path

import ascendc_pilot.actions as actions
from ascendc_pilot.actions.tg_primary import primary_interactive_steps
from ascendc_pilot.workflows import WORKFLOWS, action_by_id, phase_pipeline


def test_tg_pipelines_are_explicit_and_fail_closed() -> None:
    assert phase_pipeline("tg-init", "gate") == ["integrity_gate", "init_audit"]
    assert phase_pipeline("tg-init", "confirm") == ["human_confirm"]
    assert phase_pipeline("tg-plan", "intent") == ["plan_intent"]
    assert phase_pipeline("tg-plan", "build") == ["plan_build"]
    assert phase_pipeline("tg-plan", "approve") == ["plan_approve"]
    # Default tilingkey_full_coverage closure loop
    assert phase_pipeline("tg-solve", "oracle") == ["oracle_probe"]
    assert phase_pipeline("tg-solve", "ledger") == ["closure_ledger"]
    assert phase_pipeline("tg-solve", "search") == ["closure_search"]
    assert phase_pipeline("tg-solve", "residual") == ["closure_residual"]
    assert phase_pipeline("tg-solve", "lemma") == [
        "lemma_leads",
        "lemma_evidence",
        "lemma_mine",
        "lemma_verify",
        "lemma_review",
        "lemma_apply",
        "lemma_loop",
    ]
    assert phase_pipeline("tg-solve", "audit") == ["closure_audit"]
    assert phase_pipeline("tg-solve", "certify") == ["closure_certify"]
    # Default mode is tilingkey_full_coverage; csv_consumer overlay removed.
    assert "csv_consumer" not in (WORKFLOWS["tg-solve"].get("mode_overlays") or {})
    assert "csv_consumer" not in (WORKFLOWS["tg-init"].get("mode_overlays") or {})
    assert phase_pipeline("tg-solve", "encode") == []
    assert phase_pipeline("tg-solve", "cover") == []


def test_tg_solve_closure_actions_registered() -> None:
    from ascendc_pilot.actions.engines import ENGINE_REGISTRY

    for action_id in (
        "oracle_probe",
        "closure_ledger",
        "closure_search",
        "closure_residual",
        "closure_construct",
        "closure_explain",
        "lemma_leads",
        "lemma_evidence",
        "lemma_mine",
        "lemma_verify",
        "lemma_review",
        "lemma_apply",
        "lemma_loop",
        "closure_audit",
        "closure_certify",
    ):
        assert ("tg-solve", action_id) in ENGINE_REGISTRY
        row = action_by_id("tg-solve", action_id) or {}
        assert row.get("id") == action_id
        # Domain cognition lives in skills/{operator-analysis,testcase-generation,source-proof,code-review}; capability_ids are retrieval-only.
        caps = set(row.get("capability_ids") or [])
        assert "tilingkey-closure" not in caps
        assert "structured-review" not in caps


def test_tg_primary_actions_have_named_controller_identity_and_precise_writes() -> None:
    init_action = action_by_id("tg-init", "human_confirm") or {}
    plan_action = action_by_id("tg-plan", "plan_approve") or {}

    assert init_action["execution_mode"] == "primary_interactive"
    assert init_action["agent_id"] == "ascendc-pilot"
    assert init_action["role_id"] == "controller"
    assert init_action["allowed_write_paths"] == [
        "tg/init/status.yaml",
        "tg/init/kb_fingerprint.yaml",
        "tg/init/confirmation.yaml",
    ]

    assert plan_action["execution_mode"] == "primary_interactive"
    assert plan_action["agent_id"] == "ascendc-pilot"
    assert plan_action["role_id"] == "controller"
    assert plan_action["allowed_write_paths"] == ["tg/plan/levels/*/human_supplement.yaml"]

    intent = action_by_id("tg-plan", "plan_intent") or {}
    assert intent["execution_mode"] == "deterministic"
    # Deterministic engines prune Host task prompts at registry normalize time.
    assert intent.get("task_prompt_id") in {None, ""}
    assert "tg/plan/plan_intent.yaml" in (intent.get("allowed_write_paths") or [])


def test_deterministic_tg_leases_cover_domain_engine_outputs() -> None:
    contract = action_by_id("tg-init", "contract_build") or {}
    plan = action_by_id("tg-plan", "plan_build") or {}
    solve = action_by_id("tg-solve", "closure_certify") or {}

    assert "tg/contract/**" in contract["allowed_write_paths"]
    assert "tg/plan/coverage_obligations.yaml" in contract["allowed_write_paths"]
    assert "context/pilot_params.yaml" in contract["allowed_write_paths"]
    assert "tg/extract/**" in plan["allowed_write_paths"]
    assert "tg/realization/**" in plan["allowed_write_paths"]
    assert any("tg/closure" in p for p in (solve.get("allowed_write_paths") or []))


def test_downstream_reinit_preserves_upstream_tg_contracts() -> None:
    plan = WORKFLOWS["tg-plan"]["reset_policy"]
    solve = WORKFLOWS["tg-solve"]["reset_policy"]
    assert plan["reinit_delete"] == ["tg/plan", "tg/solve", "tg/cases", "tg/extract"]
    assert "tg/init" in plan["reinit_preserve"]
    assert "tg/contract" in plan["reinit_preserve"]
    assert solve["reinit_delete"] == ["tg/solve", "tg/cases", "tg/closure"]
    assert "tg/plan" in solve["reinit_preserve"]
    assert "tg/extract" in solve["reinit_preserve"]


def test_tg_solve_lemma_mine_is_staged_producer() -> None:
    mine = action_by_id("tg-solve", "lemma_mine") or {}
    review = action_by_id("tg-solve", "lemma_review") or {}
    assert mine.get("execution_mode") == "subagent"
    assert mine.get("agent_id") == "tg-lemma-producer"
    assert mine.get("output_mode") == "staged"
    assert mine.get("merge_action_id") == "lemma_review"
    assert any("lemma_mine/parts" in p for p in (mine.get("allowed_write_paths") or []))
    assert review.get("agent_id") == "tg-closure-referee"
    assert review.get("referee_required") is True


def test_tk_cover_is_removed() -> None:
    from ascendc_pilot.router import route
    from ascendc_pilot.workflows import list_user_workflows

    assert "tk-cover" not in WORKFLOWS
    assert "tk-cover" not in list_user_workflows()
    assert "tg-solve" in list_user_workflows()
    routed = route("/tk-cover")
    assert routed.get("ok") is False


def test_plan_intent_is_deterministic() -> None:
    intent = action_by_id("tg-plan", "plan_intent")
    assert intent is not None
    assert intent.get("execution_mode") == "deterministic"
    assert intent.get("task_prompt_id") in {None, ""}
    assert intent.get("agent_id") == "deterministic-tg-engine"


def test_primary_steps_do_not_inherit_uo_scope_recipe(tmp_path: Path) -> None:
    steps = primary_interactive_steps("human_confirm", tmp_path, {})
    joined = "\n".join(steps)
    assert "uo-scope" not in joined
    assert "AskQuestion" in joined or "question UI" in joined.lower()
    assert "confirm" in joined
    assert "human_confirm --finalize" in joined
    assert "acp answer" in joined


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
    assert "plan_approve --finalize" in joined
    assert "acp answer" in joined
