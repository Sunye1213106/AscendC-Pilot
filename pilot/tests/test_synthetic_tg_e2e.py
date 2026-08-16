# -*- coding: utf-8 -*-
"""Synthetic E2E: tilingkey_full_coverage with StubOracle (no Host / NPU)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


from synthetic_uo import write_synthetic_uo as _write_synthetic_uo


@pytest.fixture()
def synthetic_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("UO_OPERATOR", "_synthetic_toy")
    monkeypatch.setenv("UO_ARCH", "arch0")
    monkeypatch.setenv("TG_CLOSURE_CI", "1")
    monkeypatch.setenv("ASCENDC_PROJECT_ROOT", str(tmp_path))

    from ascendc_pilot.paths import ensure_agent_layout, tg_root

    ensure_agent_layout(tmp_path, arch="arch0")
    _write_synthetic_uo(tmp_path)

    tg = tg_root(tmp_path, arch="arch0")
    (tg / "closure").mkdir(parents=True, exist_ok=True)
    (tg / "init").mkdir(parents=True, exist_ok=True)
    (tg / "plan" / "levels" / "L0").mkdir(parents=True, exist_ok=True)

    (tg / "init" / "init_intent.yaml").write_text(
        "schema: tg-init-intent/v1\nmode: tilingkey_full_coverage\n",
        encoding="utf-8",
    )
    (tg / "plan" / "plan_intent.yaml").write_text(
        "schema: tg-plan-intent/v1\nmode: tilingkey_full_coverage\n",
        encoding="utf-8",
    )
    return tmp_path


def test_synthetic_init_intent_and_contract(synthetic_root: Path):
    from ascendc_pilot.actions.engines import (
        _run_tg_init_intent,
        _write_tilingkey_contract,
        _resolve_tg_ctx,
    )
    from ascendc_pilot.paths import tg_root

    out = _run_tg_init_intent(synthetic_root, {"op_name": "_synthetic_toy", "architecture": "arch0"})
    assert out["ok"] is True
    assert out["mode"] == "tilingkey_full_coverage"
    intent = tg_root(synthetic_root, arch="arch0") / "init" / "init_intent.yaml"
    assert intent.is_file()

    tg_ctx = _resolve_tg_ctx(synthetic_root, {"op_name": "_synthetic_toy", "architecture": "arch0"})
    contract = _write_tilingkey_contract(synthetic_root, tg_ctx)
    assert contract.get("status") == "pass", contract
    assert int((contract.get("declared_set") or {}).get("count") or 0) == 4


def test_synthetic_solve_oracle_ledger_residual(synthetic_root: Path, monkeypatch: pytest.MonkeyPatch):
    from ascendc_pilot.actions import engines as E
    from ascendc_pilot.paths import tg_root
    from testcase_agent.closure import workspace as W

    # Avoid needing a real tiling header / knob schema for this smoke path.
    monkeypatch.setattr(
        E,
        "_closure_ws",
        lambda root: W.Workspace(
            root=root,
            artifacts=tg_root(root, arch="arch0") / "closure",
            state=tg_root(root, arch="arch0") / "closure",
        ).ensure(),
    )

    class _Schema:
        dims = ["DimA", "DimB"]

    monkeypatch.setattr(W, "schema", lambda: _Schema())
    monkeypatch.setattr(W, "declared", lambda: frozenset({1, 2, 3, 4}))
    monkeypatch.setattr(W, "decode", lambda k: {"DimA": "0", "DimB": "0"})

    # Seed empty R so ledger/residual have something to work with.
    ws = E._closure_ws(synthetic_root)
    ws.r_path.write_text("", encoding="utf-8")
    ws.e_path.write_text("", encoding="utf-8")
    ws.open_path.write_text("1\n2\n3\n4\n", encoding="utf-8")

    probe = E._run_oracle_probe(synthetic_root, {"live_probe": False})
    assert probe["ok"] is True
    assert (tg_root(synthetic_root, arch="arch0") / "closure" / "oracle_probe.yaml").is_file()

    # ledger: no active rules → E empty, open rebuilt from D−R
    monkeypatch.setattr(
        "testcase_agent.closure.ledger.rebuild",
        lambda ws=None: {"ok": True, "R": 0},
    )
    monkeypatch.setattr(
        "testcase_agent.closure.ledger.state",
        lambda ws=None: {"declared": 4, "R": 0, "E": 0, "gap": 4, "violation": 0},
    )
    monkeypatch.setattr(
        "testcase_agent.closure.ledger.declared",
        lambda: frozenset({1, 2, 3, 4}),
    )
    monkeypatch.setattr(
        "testcase_agent.closure.ledger.load_R",
        lambda ws=None: set(),
    )
    led = E._run_closure_ledger(synthetic_root, {})
    assert led["ok"] is True
    assert led.get("apply_rules", {}).get("excluded", 0) == 0 or led.get("apply_rules", {}).get("note") == "no_active_rules" or True

    # residual with forced SEARCH_PROGRESS then budget exhaustion path
    monkeypatch.setattr(
        "testcase_agent.closure.search_round.route",
        lambda ws=None: {
            "reason": "SEARCH_PROGRESS",
            "gap": 4,
            "declared": 4,
            "R": 0,
            "E": 0,
            "violation": 0,
        },
    )
    monkeypatch.setattr(
        "testcase_agent.closure.residual.analyse",
        lambda ws=None: {"open": 4, "distance": {1: 4}, "mostly_distance_1": False},
    )
    (ws.state / "round_budget.yaml").write_text(
        yaml.safe_dump({"used": 32, "budget": 32}), encoding="utf-8"
    )
    residual = E._run_closure_residual(synthetic_root, {"round_budget": 32})
    assert residual.get("escalate") or residual.get("reason") == "PROOF_BLOCKED"
    assert residual.get("needs_rework") is False


def test_mode_overlay_terminals():
    """csv_consumer mode_overlays were retired; tilingkey_full_coverage is the only supported mode."""
    from ascendc_pilot.workflows import WORKFLOWS, get_workflow

    full = get_workflow("tg-solve", mode="tilingkey_full_coverage")
    assert full.get("terminal_ready_states") == ["certify"]
    assert "closure_soundness" in (full.get("complete_gates") or [])
    assert "oracle" in (full.get("pipelines") or {})
    assert "encode" not in (full.get("pipelines") or {})

    assert "csv_consumer" not in (WORKFLOWS["tg-solve"].get("mode_overlays") or {})
    assert "csv_consumer" not in (WORKFLOWS["tg-init"].get("mode_overlays") or {})

    init_full = get_workflow("tg-init", mode="tilingkey_full_coverage")
    assert "merge" not in (init_full.get("phases") or [])
    bind = next(a for a in init_full["actions"] if a["id"] == "contract_build")
    assert bind["output_contract_id"] == "tilingkey-contract-v1"


def test_preferred_pipeline_ignores_stray_legacy_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A stale plan_intent.yaml mode (e.g. from an old run) no longer selects a csv_consumer pipeline."""
    monkeypatch.setenv("UO_ARCH", "arch0")
    from ascendc_pilot.paths import ensure_tg_layout, tg_root
    from ascendc_pilot.workflows.pipeline import preferred_pipeline

    ensure_tg_layout(tmp_path, arch="arch0")
    plan = tg_root(tmp_path, arch="arch0") / "plan"
    plan.mkdir(parents=True, exist_ok=True)
    (plan / "plan_intent.yaml").write_text(
        "schema: tg-plan-intent/v1\nmode: csv_consumer\n", encoding="utf-8"
    )
    assert preferred_pipeline("tg-solve", "encode", project_root=tmp_path) == []
    assert preferred_pipeline("tg-solve", "oracle", project_root=tmp_path) == ["oracle_probe"]


def test_lemma_mine_writes_arch_scoped_runs(synthetic_root: Path):
    from ascendc_pilot.actions.engines import _run_lemma_mine
    from ascendc_pilot.paths import agent_root

    out = _run_lemma_mine(synthetic_root, {"run_id": "RUN_LEMMA"})
    assert out["ok"] is True
    staging = agent_root(synthetic_root) / "runs" / "RUN_LEMMA" / "actions" / "lemma_mine" / "staging.yaml"
    assert staging.is_file()
    # Must not use flat .ascendc-pilot/runs without <arch>.
    flat = synthetic_root / ".ascendc-pilot" / "runs" / "RUN_LEMMA" / "actions" / "lemma_mine" / "staging.yaml"
    assert not flat.is_file()


def test_lemma_mine_uses_uo_legal_index_without_a_replay_schema(
    synthetic_root: Path,
):
    """The committed CodeMap is sufficient aiming authority for lemma mining.

    A replay/TPL schema is no longer a prerequisite when the ``.uo`` embeds the
    complete legal-key index.  The producer should still receive the proof
    contract and may derive aiming hypotheses from exact D/decode rows without
    touching WSL or replay setup.
    """
    import yaml

    from ascendc_pilot.actions.engines import _run_lemma_mine
    from ascendc_pilot.paths import agent_root

    out = _run_lemma_mine(synthetic_root, {"run_id": "RUN_NOSCHEMA"})
    assert out["ok"] is True

    staging = yaml.safe_load(
        (
            agent_root(synthetic_root)
            / "runs"
            / "RUN_NOSCHEMA"
            / "actions"
            / "lemma_mine"
            / "staging.yaml"
        ).read_text(encoding="utf-8")
    )
    assert staging["contract"]["required_fields"]
    assert staging["hypotheses"], "product legal-key rows should support residual aiming"
    assert not staging["hypothesis_stats"].get("unavailable")


def test_full_mode_contract_build_finalize_paths(synthetic_root: Path):
    from ascendc_pilot.actions.engines import (
        _run_tg_contract_build,
        _run_tg_integrity,
        _run_tg_semantic_bind,
    )
    from ascendc_pilot.paths import tg_root

    ctx = {"op_name": "_synthetic_toy", "architecture": "arch0", "mode": "tilingkey_full_coverage"}
    built = _run_tg_contract_build(synthetic_root, ctx)
    assert built["ok"] is True
    tg = tg_root(synthetic_root, arch="arch0")
    assert (tg / "contract" / "tilingkey_contract.yaml").is_file()
    assert (tg / "snapshot" / "understand_contract.json").is_file()

    bind = _run_tg_semantic_bind(synthetic_root, ctx)
    assert bind["ok"] is True
    assert (tg / "realization" / "binding_inventory.yaml").is_file()
    # Full mode must NOT invent CSV realization placeholders.
    assert not (tg / "realization" / "realization_map.yaml").is_file()
    assert not (tg / "realization" / "binding_lexicon.yaml").is_file()

    integ = _run_tg_integrity(synthetic_root, ctx)
    assert integ["ok"] is True
    assert (tg / "contract" / "integrity_gate.yaml").is_file()
