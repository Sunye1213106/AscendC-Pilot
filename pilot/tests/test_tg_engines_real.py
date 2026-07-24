"""Pilot TG engines must call real domain APIs — not write success markers."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.actions.engines import (
    OUTPUT_CONTRACT_NONEMPTY_GLOBS,
    OUTPUT_CONTRACT_PATHS,
    invoke_engine,
)
from ascendc_pilot.actions.runtime import _check_output_contract
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import start_workflow
from ascendc_pilot.workflows.specs import WORKFLOWS


def test_tg_contract_build_requires_consumer_root(tmp_path: Path) -> None:
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root)
    (root / ".ascendc-pilot" / "uo" / "manifest.yaml").write_text(
        "op_name: synth_tg\n",
        encoding="utf-8",
    )
    result = invoke_engine(root, "tg-init", "contract_build", ctx={"op_name": "synth_tg"})
    assert result.get("ok") is False
    assert "TEST_SCRIPT_ROOT" in str(result.get("error") or "")


def test_tg_plan_build_not_marker_only(tmp_path: Path) -> None:
    """plan_build must fail without consumer/KB rather than write pilot_plan_build.yaml."""
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root)
    (root / ".ascendc-pilot" / "uo" / "manifest.yaml").write_text("op_name: synth_tg\n", encoding="utf-8")
    result = invoke_engine(
        root,
        "tg-plan",
        "plan_build",
        ctx={"op_name": "synth_tg", "level": "L0"},
    )
    assert result.get("ok") is False
    marker = root / ".ascendc-pilot" / "tg" / "realization" / "pilot_plan_build.yaml"
    assert not marker.is_file()


def test_tg_z3_solve_not_marker_only(tmp_path: Path) -> None:
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root)
    (root / ".ascendc-pilot" / "uo" / "manifest.yaml").write_text("op_name: synth_tg\n", encoding="utf-8")
    result = invoke_engine(root, "tg-solve", "z3_solve", ctx={"op_name": "synth_tg"})
    assert result.get("ok") is False
    marker = root / ".ascendc-pilot" / "tg" / "realization" / "pilot_z3_solve.yaml"
    assert not marker.is_file()


def test_output_contracts_require_concrete_tg_artifacts() -> None:
    assert OUTPUT_CONTRACT_PATHS["csv-contract-v1"] != ["tg"]
    joined = ",".join(OUTPUT_CONTRACT_PATHS["csv-contract-v1"])
    assert "realization_map.yaml" in joined
    assert "binding_inventory.yaml" in joined
    assert "llm_bind_prompt_bundle.yaml" in joined
    assert "binding_gaps.yaml" in joined
    assert "unresolved.yaml" in joined
    assert "understand_contract.json" in joined
    assert OUTPUT_CONTRACT_PATHS["plan-scope-v1"] == ["tg/plan/levels/*/plan_scope.yaml"]
    assert OUTPUT_CONTRACT_PATHS["solve-precheck-v1"] == ["tg/plan/levels/*/human_supplement.yaml"]
    assert "tg/solve/**/realize_report.yaml" in OUTPUT_CONTRACT_PATHS["cover-confirm-v1"]
    assert "plan-build-v1" in OUTPUT_CONTRACT_NONEMPTY_GLOBS
    assert "z3-solve-v1" in OUTPUT_CONTRACT_NONEMPTY_GLOBS


def test_tg_init_agents_omit_dead_csv_contract_producer() -> None:
    agents = {a["id"] for a in WORKFLOWS["tg-init"]["agents"]}
    assert "tg-csv-contract" not in agents
    assert "deterministic-tg-engine" in agents
    assert "tg-semantic-bind" in agents


def test_plan_build_contract_rejects_empty_dir(tmp_path: Path) -> None:
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root)
    (root / ".ascendc-pilot" / "tg" / "plan").mkdir(parents=True, exist_ok=True)
    checked = _check_output_contract(root, "plan-build-v1")
    assert checked.get("ok") is False


def test_contract_build_is_deterministic_engine() -> None:
    actions = WORKFLOWS["tg-init"]["actions"]
    contract = next(a for a in actions if a["id"] == "contract_build")
    assert contract["role_id"] == "deterministic_engine"


def test_start_persists_pilot_params(tmp_path: Path) -> None:
    root = tmp_path / "op"
    root.mkdir()
    consumer = tmp_path / "scripts"
    consumer.mkdir()
    state = start_workflow(
        root,
        "tg-plan",
        op_name="synth_tg",
        test_script_root=consumer.as_posix(),
        level="L0",
    )
    assert state.get("op_name") == "synth_tg"
    assert state.get("test_script_root") == consumer.as_posix()
    # CLI persistence is separate; engines resolve from state via context pack.
    from ascendc_pilot.context import build_context_pack

    pack = build_context_pack(root, intent="test", topic="plan")
    assert pack.get("op_name") == "synth_tg"
    assert pack.get("test_script_root") == consumer.as_posix()
    assert pack.get("level") == "L0"
