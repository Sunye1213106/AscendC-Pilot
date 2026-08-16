"""scenario_targeted certificate must not false-green on construction-only."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.actions.scenario_certificate import (
    evaluate_scenario_certificate,
    harness_row_pass,
)
from ascendc_pilot.gates import gate_scenario_coverage_sound
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.workflows import get_workflow


def _dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _layout(tmp_path: Path) -> Path:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    return op


def test_harness_disabled_no_npu_is_not_pass() -> None:
    assert harness_row_pass({"ok": False, "reason": "disabled_no_npu"}) is False
    assert harness_row_pass({"ok": True, "reason": "disabled_no_npu"}) is False
    assert harness_row_pass({"ok": False, "verdict": "not_executed"}) is False
    assert harness_row_pass({"ok": True, "reason": "skipped_by_design"}) is True
    assert harness_row_pass({"ok": True}) is True


def test_construction_only_certificate_is_not_ok(tmp_path: Path) -> None:
    op = _layout(tmp_path)
    dest = op / ".ascendc-pilot" / "arch35" / "tg" / "closure" / "scenarios"
    _dump(
        dest / "construct.yaml",
        {
            "schema": "tg-targeted-construct/v1",
            "scenarios": [{"id": "P-CAST", "csv": "x.csv"}],
        },
    )
    _dump(
        dest / "harness_results.yaml",
        {
            "schema": "tg-harness-run/v1",
            "runs": [
                {
                    "id": "P-CAST",
                    "ok": False,
                    "reason": "harness_run_failed",
                }
            ],
        },
    )
    cert = evaluate_scenario_certificate(op, architecture="arch35")
    assert cert["construction_complete"] is True
    assert cert["required_harness_receipts_all_pass"] is False
    assert cert["replay_target_receipts_all_pass"] is False
    assert cert["ok"] is False
    gate = gate_scenario_coverage_sound(op, architecture="arch35")
    assert gate["ok"] is False


def test_scenario_targeted_complete_gates_include_coverage_sound() -> None:
    solve = get_workflow("tg-solve", mode="scenario_targeted")
    assert "scenario_coverage_sound" in (solve.get("complete_gates") or [])


def test_target_reached_true_fixture_can_pass(tmp_path: Path, monkeypatch) -> None:
    op = _layout(tmp_path)
    dest = op / ".ascendc-pilot" / "arch35" / "tg" / "closure" / "scenarios"
    _dump(
        dest / "construct.yaml",
        {
            "schema": "tg-targeted-construct/v1",
            "scenarios": [{"id": "CTI-CE-OBL-17", "csv": "x.csv", "obligation_id": "CE-OBL-17"}],
            "source_fingerprint": "abc",
            "uo_digest": "def",
        },
    )
    _dump(
        dest / "harness_results.yaml",
        {
            "schema": "tg-harness-run/v1",
            "runs": [{"id": "CTI-CE-OBL-17", "ok": True, "verdict": "pass"}],
        },
    )
    rec_dir = op / ".ascendc-pilot" / "arch35" / "tg" / "closure" / "replay_receipts"
    _dump(
        rec_dir / "CTI-CE-OBL-17.yaml",
        {
            "schema": "tg-replay-target-receipt/v1",
            "id": "CTI-CE-OBL-17",
            "obligation_id": "CE-OBL-17",
            "target_reached": True,
        },
    )
    monkeypatch.setattr(
        "ascendc_pilot.actions.scenario_certificate.live_source_fingerprint",
        lambda *_a, **_k: "abc",
    )
    monkeypatch.setattr(
        "ascendc_pilot.actions.scenario_certificate.live_uo_digest",
        lambda *_a, **_k: "def",
    )
    cert = evaluate_scenario_certificate(op, architecture="arch35")
    assert cert["construction_complete"] is True
    assert cert["required_harness_receipts_all_pass"] is True
    assert cert["replay_target_receipts_all_pass"] is True
    assert cert["source_fingerprint_fresh"] is True
    assert cert["uo_digest_fresh"] is True
    assert cert["ok"] is True
