"""Canonical TG products: init.yaml / plan.md / worklog.md / cases table."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TG_ENGINE = ROOT / "engines" / "testcase-generation"
if str(TG_ENGINE) not in sys.path:
    sys.path.insert(0, str(TG_ENGINE))

from testcase_agent import products, test_repo


def test_script_repo_empty_mapping_fails() -> None:
    errors = products.validate_init(
        {
            "schema": products.INIT_SCHEMA,
            "kind": "script_repo",
            "table_kind": "csv",
            "entry": "run_fag.py",
            "case_arg": "--case",
            "modes": {"precision": ["only_grad"], "perf": ["profiler"]},
            "columns": [{"name": "B"}],
            "mapping": {},
            "domains": {"B": ["1", "2"]},
            "golden": {},
            "compare": {"atol": "1e-4"},
            "generate_inputs": {"fn": "gen"},
            "uo_digest": "abc",
        }
    )
    assert any("mapping" in e for e in errors)


def test_golden_only_precision_fails() -> None:
    errors = products.validate_init(
        {
            "schema": products.INIT_SCHEMA,
            "kind": "script_repo",
            "table_kind": "csv",
            "entry": "run_fag.py",
            "case_arg": "--case",
            "modes": {"precision": ["--golden-only"], "perf": ["profiler"]},
            "columns": [{"name": "B"}],
            "mapping": {"B": "uo:B"},
            "domains": {"B": ["1"]},
            "golden": {},
            "compare": {},
            "generate_inputs": {},
            "uo_digest": "abc",
        }
    )
    assert any("golden-only" in e for e in errors)


def test_plan_rejects_td_mode_and_requires_column_root() -> None:
    fence = {
        "schema": products.PLAN_SCHEMA,
        "mode": "tilingkey_full_coverage",
        "obligations": [
            {
                "id": "o1",
                "why": "dtype",
                "class": "replay",
                "control": {"columns": ["Missing"], "recipe": "set dtype"},
                "hit": {"pred": "key"},
                "uo": {"query": "dtype"},
                "cover": "L0",
            }
        ],
    }
    errors = products.validate_plan_fence(fence, init_columns=["B"])
    assert any("Missing" in e for e in errors)


def test_untestable_needs_reason() -> None:
    fence = {
        "schema": products.PLAN_SCHEMA,
        "obligations": [
            {
                "id": "o1",
                "why": "b",
                "class": "derived",
                "control": {"columns": ["B"], "recipe": "fix B"},
                "hit": {"formula": "B>0"},
                "uo": {"span": "x.cpp:1"},
                "cover": "L0",
            }
        ],
        "untestable": [{"id": "u1"}],
    }
    errors = products.validate_plan_fence(fence, init_columns=["B"])
    assert any("reason" in e for e in errors)


def test_worklog_open_ids() -> None:
    assert products.worklog_open_ids("open: [a, b]\n\n## a\n") == ["a", "b"]
    assert products.worklog_open_ids("open: []\n") == []


def test_scan_includes_xls(tmp_path: Path) -> None:
    (tmp_path / "cases.csv").write_text("B,N\n1,2\n", encoding="utf-8")
    (tmp_path / "cases.xlsx").write_bytes(b"not-a-real-xlsx")
    inv = test_repo.scan(tmp_path)
    kinds = [str(t.get("kind") or "") for t in (inv.get("tables") or [])]
    assert "csv" in kinds
    assert "xlsx" in kinds


def test_collect_intent_does_not_write(tmp_path: Path) -> None:
    (tmp_path / ".ascendc-pilot" / "arch35" / "ce" / "impact").mkdir(parents=True)
    intent = tmp_path / ".ascendc-pilot" / "arch35" / "ce" / "impact" / "tg_plan_intent.yaml"
    intent.write_text("mode: ce_change_scoped\ntarget_keys: [1]\n", encoding="utf-8")
    doc = products.collect_intent_sources(tmp_path, architecture="arch35")
    assert doc["sources"]
    assert not (tmp_path / ".ascendc-pilot" / "arch35" / "tg" / "plan" / "plan_intent.yaml").exists()
