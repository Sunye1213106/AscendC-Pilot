"""TG workflow ordering and primary-interactive control-plane regressions."""

from __future__ import annotations

from pathlib import Path

import ascendc_pilot.actions as actions
from ascendc_pilot.actions.tg_primary import primary_interactive_steps
from ascendc_pilot.workflows import WORKFLOWS, action_by_id, phase_pipeline


def test_tg_pipelines_are_explicit_and_fail_closed() -> None:
    assert phase_pipeline("tg-init", "gate") == ["integrity_gate", "init_audit"]
    assert phase_pipeline("tg-init", "confirm") == ["human_confirm"]
    assert phase_pipeline("tg-plan", "build") == ["plan_build"]
    assert phase_pipeline("tg-plan", "approve") == ["plan_approve"]
    assert phase_pipeline("tg-solve", "encode") == ["z3_solve"]
    assert phase_pipeline("tg-solve", "cover") == ["cover_confirm"]


def test_tg_primary_actions_have_named_controller_identity_and_precise_writes() -> None:
    init_action = action_by_id("tg-init", "human_confirm") or {}
    plan_action = action_by_id("tg-plan", "plan_approve") or {}

    assert init_action["execution_mode"] == "primary_interactive"
    assert init_action["agent_id"] == "ascendc-pilot"
    assert init_action["role_id"] == "controller"
    assert init_action["allowed_write_paths"] == ["tg/init/status.yaml"]

    assert plan_action["execution_mode"] == "primary_interactive"
    assert plan_action["agent_id"] == "ascendc-pilot"
    assert plan_action["role_id"] == "controller"
    assert plan_action["allowed_write_paths"] == ["tg/plan/levels/*/human_supplement.yaml"]


def test_downstream_reinit_preserves_upstream_tg_contracts() -> None:
    plan = WORKFLOWS["tg-plan"]["reset_policy"]
    solve = WORKFLOWS["tg-solve"]["reset_policy"]
    assert plan["reinit_delete"] == ["tg/plan", "tg/solve"]
    assert "tg/init" in plan["reinit_preserve"]
    assert solve["reinit_delete"] == ["tg/solve"]
    assert "tg/plan" in solve["reinit_preserve"]


def test_primary_steps_do_not_inherit_uo_scope_recipe(tmp_path: Path) -> None:
    steps = primary_interactive_steps("human_confirm", tmp_path, {})
    joined = "\n".join(steps)
    assert "uo-scope" not in joined
    assert "AskQuestion: confirm | rework | stop" in joined
    assert "human_confirm --finalize" in joined


def test_actions_facade_replaces_generic_primary_steps(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        actions._runtime,
        "prepare_action",
        lambda *_args, **_kwargs: {
            "ok": True,
            "action_id": "plan_approve",
            "execution_mode": "primary_interactive",
            "interactive_steps": ["acp uo-scope scan"],
        },
    )
    result = actions.prepare_action(tmp_path, "plan_approve")
    assert result["ok"] is True
    assert result["dispatch_task"] is False
    assert "uo-scope" not in "\n".join(result["interactive_steps"])
    assert "AskQuestion: approve | rework | stop" in "\n".join(result["interactive_steps"])


def test_semantic_bind_runtime_prompt_removes_producer_finalize(monkeypatch, tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    method = tmp_path / "method.md"
    prompt.write_text("然后执行：`acp run-action semantic_bind --finalize`", encoding="utf-8")
    method.write_text(
        "4. 执行 `acp run-action semantic_bind --finalize`（finalize 会应用补丁并校验）。",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        actions._runtime,
        "prepare_action",
        lambda *_args, **_kwargs: {
            "ok": True,
            "action_id": "semantic_bind",
            "prompt_path": prompt.as_posix(),
            "method_path": method.as_posix(),
        },
    )

    result = actions.prepare_action(tmp_path, "semantic_bind")
    assert result["ok"] is True
    assert "然后执行：`acp run-action semantic_bind --finalize`" not in prompt.read_text(encoding="utf-8")
    assert "不得执行 finalize" in method.read_text(encoding="utf-8")
