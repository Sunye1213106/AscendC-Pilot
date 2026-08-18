"""Certificate predicates read the three TG products, not tg/closure."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.actions.scenario_certificate import (
    evaluate_scenario_certificate,
    harness_row_pass,
)
from ascendc_pilot.gates import gate_scenario_coverage_sound
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.workflows import WORKFLOWS


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


def test_missing_products_certificate_is_not_ok(tmp_path: Path) -> None:
    op = _layout(tmp_path)
    cert = evaluate_scenario_certificate(op, architecture="arch35")
    assert cert["ok"] is False
    gate = gate_scenario_coverage_sound(op, architecture="arch35")
    assert gate["ok"] is False


def test_tg_solve_complete_gates_include_worklog() -> None:
    solve = WORKFLOWS["tg-solve"]
    assert "worklog_closed" in (solve.get("complete_gates") or [])
    assert "scenario_coverage_sound" not in (solve.get("complete_gates") or [])
