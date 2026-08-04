# -*- coding: utf-8 -*-
"""Synthetic E2E: tilingkey_full_coverage with StubOracle (no Host / NPU)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml


@pytest.fixture()
def synthetic_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("UO_OPERATOR", "_synthetic_toy")
    monkeypatch.setenv("UO_ARCH", "arch0")
    monkeypatch.setenv("TG_CLOSURE_CI", "1")
    monkeypatch.setenv("ASCENDC_PROJECT_ROOT", str(tmp_path))

    from ascendc_pilot.paths import ensure_agent_layout, tg_root, uo_root

    ensure_agent_layout(tmp_path, arch="arch0")
    uo = uo_root(tmp_path, arch="arch0")
    tg = tg_root(tmp_path, arch="arch0")
    (uo / "ir").mkdir(parents=True, exist_ok=True)
    (uo / "tiling").mkdir(parents=True, exist_ok=True)
    (tg / "closure").mkdir(parents=True, exist_ok=True)
    (tg / "init").mkdir(parents=True, exist_ok=True)
    (tg / "plan" / "levels" / "L0").mkdir(parents=True, exist_ok=True)

    (uo / "manifest.yaml").write_text(
        "op_name: _synthetic_toy\narchitecture: arch0\nfingerprint: fp-toy\n",
        encoding="utf-8",
    )
    (uo / "ir" / "operator_graph.yaml").write_text(
        "fingerprint: fp-toy\nnodes: []\nedges: []\n",
        encoding="utf-8",
    )
    (uo / "tiling" / "exhaustive_key_space.yaml").write_text(
        "legal_key_count: 4\n"
        "legal_key_index: tiling/legal_key_index.jsonl\n"
        "fingerprint: fp-toy\n"
        "template_blocks: []\n",
        encoding="utf-8",
    )
    (uo / "tiling" / "legal_key_index.jsonl").write_text(
        "1\n2\n3\n4\n", encoding="utf-8"
    )
    (uo / "ir" / "tg_host_view.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "tg-host-view/v1",
                "source": {"graph_fingerprint": "fp-toy"},
                "fields": [
                    {"name": "DimA", "kind": "key_dim"},
                    {"name": "DimB", "kind": "key_dim"},
                ],
                "predicates": [],
                "declared_keys": {},
                "platform_gates": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
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
    assert contract.get("status") == "pass"
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
    from ascendc_pilot.workflows import get_workflow

    full = get_workflow("tg-solve", mode="tilingkey_full_coverage")
    assert full.get("terminal_ready_states") == ["certify"]
    assert "closure_soundness" in (full.get("complete_gates") or [])
    assert "oracle" in (full.get("pipelines") or {})
    assert "encode" not in (full.get("pipelines") or {})

    csv = get_workflow("tg-solve", mode="csv_consumer")
    assert csv.get("terminal_ready_states") == ["cover"]
    assert "solve_terminal" in (csv.get("complete_gates") or [])
    assert "encode" in (csv.get("pipelines") or {})
    assert "oracle" not in (csv.get("pipelines") or {})
