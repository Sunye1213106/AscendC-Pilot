from __future__ import annotations

from pathlib import Path


def test_plan_intent_action_removed() -> None:
    from ascendc_pilot.human_confirm import PRIMARY_TG_ACTIONS
    from ascendc_pilot.workflows import action_by_id

    assert "plan_intent" not in PRIMARY_TG_ACTIONS
    assert action_by_id("tg-plan", "plan_intent") is None
    scope = action_by_id("tg-plan", "plan_scope")
    assert scope is not None
    assert scope.get("execution_mode") == "subagent"
    assert scope.get("skill_id") == "test-plan"
    assert scope.get("method_ref") == "target-planning.md"
    assert scope.get("output_mode") == "return_value"
    fuse = action_by_id("tg-plan", "plan_fuse")
    assert fuse is not None
    assert fuse.get("execution_mode") == "subagent"
    assert fuse.get("output_mode") == "return_value"
    narrate = action_by_id("tg-plan", "plan_narrate")
    assert narrate is not None
    assert narrate.get("execution_mode") == "primary_review"
    assert narrate.get("output_mode") == "return_value"
    pre = action_by_id("tg-plan", "plan_precheck")
    assert pre is not None
    assert pre.get("execution_mode") == "deterministic"


def test_contract_dag_checker_passes(repo_root: Path | None = None) -> None:
    import sys

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "scripts"))
    from check_contract_dag import check_contract_dag

    errors = check_contract_dag(root)
    assert errors == [], errors
