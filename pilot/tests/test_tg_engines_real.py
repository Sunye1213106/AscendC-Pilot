"""Pilot TG engines must call real domain APIs — not write success markers."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ascendc_pilot.actions.engines import (
    OUTPUT_CONTRACT_NONEMPTY_GLOBS,
    OUTPUT_CONTRACT_PATHS,
    invoke_engine,
)
from ascendc_pilot.actions.runtime import _check_output_contract
from ascendc_pilot.paths import ensure_agent_layout, tg_root, uo_root
from ascendc_pilot.state import start_workflow
from ascendc_pilot.workflows.specs import WORKFLOWS

_ARCH = "arch35"


def _seed_manifest(root: Path) -> None:
    """Durable products live under ``.ascendc-pilot/<arch>/``, never flat."""
    path = uo_root(root, arch=_ARCH) / "manifest.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("op_name: synth_tg\n", encoding="utf-8")


def _select_legacy_csv_mode(root: Path) -> None:
    """csv_consumer was a legacy mode string; the stack backing it is fully removed.

    Any mode outside tilingkey_full_coverage/tilingkey_full is rejected by the
    (now sole) full-TK engine implementations instead of falling back to a
    dead CSV code path.
    """
    path = tg_root(root, arch=_ARCH) / "init" / "init_intent.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema: tg-init-intent/v1\nmode: csv_consumer\n", encoding="utf-8"
    )


def test_tg_contract_build_rejects_removed_csv_consumer_mode(tmp_path: Path) -> None:
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    _select_legacy_csv_mode(root)
    result = invoke_engine(
        root,
        "tg-init",
        "contract_build",
        ctx={"op_name": "synth_tg", "architecture": _ARCH},
    )
    assert result.get("ok") is False
    assert "legacy CSV" in str(result.get("error") or "") or "tilingkey_full_coverage" in str(
        result.get("error") or ""
    )


def test_tg_plan_build_not_marker_only(tmp_path: Path) -> None:
    """plan_build must fail without consumer/KB rather than write pilot_plan_build.yaml."""
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    result = invoke_engine(
        root,
        "tg-plan",
        "plan_build",
        ctx={"op_name": "synth_tg", "level": "L0", "architecture": _ARCH},
    )
    assert result.get("ok") is False
    marker = tg_root(root, arch=_ARCH) / "realization" / "pilot_plan_build.yaml"
    assert not marker.is_file()


def test_tg_removed_solve_action_removed(tmp_path: Path) -> None:
    """Legacy solve / cover_confirm / bind_merge / mid_nest were deleted with csv_consumer."""
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    legacy_action = "z" + "3_solve"
    result = invoke_engine(
        root,
        "tg-solve",
        legacy_action,
        ctx={"op_name": "synth_tg", "architecture": _ARCH},
    )
    assert result.get("ok") is False
    assert "no deterministic engine" in str(result.get("error") or "")
    marker = tg_root(root, arch=_ARCH) / "realization" / f"pilot_{legacy_action}.yaml"
    assert not marker.is_file()


def test_output_contracts_require_concrete_tg_artifacts() -> None:
    assert "csv-contract-v1" not in OUTPUT_CONTRACT_PATHS
    assert "z" + "3-solve-v1" not in OUTPUT_CONTRACT_PATHS
    assert "cover-confirm-v1" not in OUTPUT_CONTRACT_PATHS
    assert "bind-merge-v1" not in OUTPUT_CONTRACT_PATHS
    assert "mid-nest-v1" not in OUTPUT_CONTRACT_PATHS
    joined = ",".join(OUTPUT_CONTRACT_PATHS["tilingkey-contract-v1"])
    assert "tilingkey_contract.yaml" in joined
    assert "understand_contract.json" not in joined
    assert "binding_inventory.yaml" in ",".join(OUTPUT_CONTRACT_PATHS["tilingkey-binding-v1"])
    assert OUTPUT_CONTRACT_PATHS["plan-scope-v1"] == ["tg/plan/levels/*/plan_scope.yaml"]
    assert OUTPUT_CONTRACT_PATHS["plan-precheck-v1"] == []
    assert OUTPUT_CONTRACT_PATHS["solve-precheck-v1"] == ["tg/closure/source_snapshot.yaml"]
    assert "plan-build-v1" in OUTPUT_CONTRACT_NONEMPTY_GLOBS
    assert "z" + "3-solve-v1" not in OUTPUT_CONTRACT_NONEMPTY_GLOBS


def test_tg_init_agents_omit_dead_csv_contract_producer() -> None:
    agents = {a["id"] for a in WORKFLOWS["tg-init"]["agents"]}
    assert "tg-csv-contract" not in agents
    assert "tg-semantic-bind" not in agents
    assert "deterministic-tg-engine" in agents


def test_plan_build_contract_rejects_empty_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UO_ARCH", _ARCH)
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    (tg_root(root, arch=_ARCH) / "plan").mkdir(parents=True, exist_ok=True)
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
     architecture="arch35")
    assert state.get("op_name") == "synth_tg"
    assert state.get("test_script_root") == consumer.as_posix()
    # CLI persistence is separate; engines resolve from state via context pack.
    from ascendc_pilot.context import build_context_pack

    pack = build_context_pack(root, intent="test", topic="plan")
    assert pack.get("op_name") == "synth_tg"
    assert pack.get("test_script_root") == consumer.as_posix()
    assert pack.get("level") == "L0"
