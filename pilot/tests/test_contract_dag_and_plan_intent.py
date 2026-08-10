from __future__ import annotations

from pathlib import Path


def test_plan_intent_not_primary_interactive() -> None:
    from ascendc_pilot.actions.tg_primary import PRIMARY_TG_ACTIONS
    from ascendc_pilot.workflows import action_by_id

    assert "plan_intent" not in PRIMARY_TG_ACTIONS
    intent = action_by_id("tg-plan", "plan_intent")
    assert intent is not None
    assert intent.get("execution_mode") == "deterministic"
    assert intent.get("agent_id") == "deterministic-tg-engine"


def test_contract_dag_checker_passes(repo_root: Path | None = None) -> None:
    import sys

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "scripts"))
    from check_contract_dag import check_contract_dag

    errors = check_contract_dag(root)
    assert errors == [], errors
