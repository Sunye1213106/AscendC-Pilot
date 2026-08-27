from __future__ import annotations

from pathlib import Path


def test_plan_intent_action_removed() -> None:
    from ascendc_pilot.human_confirm import PRIMARY_TG_ACTIONS
    from ascendc_pilot.workflows import action_by_id

    assert "plan_intent" not in PRIMARY_TG_ACTIONS
    assert action_by_id("tg-plan", "plan_intent") is None
    assert action_by_id("tg-plan", "plan_scope") is None
    assert action_by_id("tg-plan", "plan_fuse") is None
    assert action_by_id("tg-plan", "plan_narrate") is None
    ingest = action_by_id("tg-plan", "plan_ingest")
    assert ingest is not None
    assert ingest.get("execution_mode") == "primary_review"
    assert ingest.get("skill_id") == "test-plan"
    assert not str(ingest.get("method_ref") or "").strip()
    assert ingest.get("output_mode") == "return_value"
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
