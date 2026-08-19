# -*- coding: utf-8 -*-
"""Synthetic TG: init.yaml + plan.md products, no T=D overlay."""

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
    tg.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_repo_scan_and_validate_init(synthetic_root: Path):
    from ascendc_pilot.actions.tg_product import run_repo_scan, run_validate_init
    from testcase_agent.products import dump_init, INIT_SCHEMA
    from ascendc_pilot.paths import tg_root
    from ascendc_pilot.state import start_workflow

    state = start_workflow(
        synthetic_root,
        "tg-init",
        architecture="arch0",
        op_name="_synthetic_toy",
    )
    run_id = str(state.get("run_id") or "")
    scan = run_repo_scan(synthetic_root, {"architecture": "arch0", "run_id": run_id})
    assert scan.get("ok") is True
    dump_init(
        tg_root(synthetic_root, arch="arch0"),
        {
            "schema": INIT_SCHEMA,
            "kind": "default_input",
            "table_kind": "csv",
            "uo_digest": "deadbeef",
            "confirmed": False,
        },
    )
    out = run_validate_init(synthetic_root, {"architecture": "arch0", "run_id": run_id})
    assert out.get("ok") is True, out


def test_plan_validate_rejects_td_mode(synthetic_root: Path):
    from ascendc_pilot.actions.tg_product import run_plan_validate
    from testcase_agent.products import dump_init, INIT_SCHEMA
    from ascendc_pilot.paths import tg_root

    tg = tg_root(synthetic_root, arch="arch0")
    dump_init(
        tg,
        {
            "schema": INIT_SCHEMA,
            "kind": "default_input",
            "table_kind": "csv",
            "uo_digest": "deadbeef",
            "columns": [{"name": "B"}],
        },
    )
    (tg / "plan.md").write_text(
        "# plan\n\n```yaml\nschema: tg-plan/v1\nmode: tilingkey_full_coverage\nobligations: []\n```\n",
        encoding="utf-8",
    )
    out = run_plan_validate(synthetic_root, {"architecture": "arch0", "run_id": "RUN1"})
    assert out.get("ok") is False
    assert any("T=D" in e or "tilingkey_full_coverage" in e or "empty" in e for e in (out.get("errors") or []))


def test_no_td_overlay():
    from ascendc_pilot.workflows import WORKFLOWS

    assert not (WORKFLOWS["tg-solve"].get("mode_overlays") or {})
    ids = [a["id"] for a in WORKFLOWS["tg-solve"]["actions"]]
    assert "lemma_mine" not in ids
    assert "construct_cases" in ids


def test_repo_scan_asks_when_goal_wants_tests_and_root_empty(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_repo_scan
    from ascendc_pilot.user_goal import create_user_goal

    create_user_goal(
        synthetic_root,
        intent_text="生成针对性测例",
        llm_intent={
            "objective_zh": "生成针对性测例",
            "needed_capabilities": ["knowledge", "test_generation"],
            "source": {"kind": "local"},
        },
        architecture="arch0",
    )
    scan = run_repo_scan(synthetic_root, {"architecture": "arch0", "run_id": "R1"})
    assert scan.get("needs_human_decision") is True
    ask = scan.get("ask_question") or {}
    opts = ask.get("options") or []
    assert len(opts) >= 2
    values = {str(o.get("value") or "") for o in opts if isinstance(o, dict)}
    assert "have_repo" in values
    assert "no_repo_uo_query" in values
    assert scan.get("ok") is False


def test_repo_scan_asks_without_user_goal(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_repo_scan

    scan = run_repo_scan(synthetic_root, {"architecture": "arch0", "run_id": "R1"})
    assert scan.get("needs_human_decision") is True
    values = {
        str(o.get("value") or "")
        for o in ((scan.get("ask_question") or {}).get("options") or [])
        if isinstance(o, dict)
    }
    assert "have_repo" in values
    assert "no_repo_uo_query" in values


def test_repo_scan_default_input_sentinel_skips_ask(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_repo_scan

    scan = run_repo_scan(
        synthetic_root,
        {"architecture": "arch0", "run_id": "R1", "test_script_root": "no_repo_uo_query"},
    )
    assert scan.get("needs_human_decision") is not True
    assert scan.get("ok") is True
    assert str((scan.get("inventory") or {}).get("kind") or "") == "default_input"


def test_prepare_repo_scan_does_not_finalize_when_asking(synthetic_root: Path) -> None:
    from ascendc_pilot.actions import prepare_action
    from ascendc_pilot.state import load_state, save_state, start_workflow
    from ascendc_pilot.user_goal import create_user_goal

    start_workflow(
        synthetic_root,
        "tg-init",
        architecture="arch0",
        op_name="_synthetic_toy",
        phase="scan",
        force_phase=True,
    )
    create_user_goal(
        synthetic_root,
        intent_text="生成针对性测例",
        llm_intent={
            "objective_zh": "生成针对性测例",
            "needed_capabilities": ["knowledge", "test_generation"],
            "source": {"kind": "local"},
        },
        architecture="arch0",
    )
    state = load_state(synthetic_root) or {}
    state["phase"] = "scan"
    save_state(synthetic_root, state)
    prep = prepare_action(synthetic_root, "repo_scan")
    assert prep.get("needs_human_decision") is True
    assert prep.get("auto_finalize") is not True
    assert isinstance(prep.get("ask_question"), dict)
    assert len((prep.get("ask_question") or {}).get("options") or []) >= 2
    assert not (prep.get("finalize") or {}).get("ok")
