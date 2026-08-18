# -*- coding: utf-8 -*-
"""CE lean persist: LLM read diet, oral review, tg-plan intent ingest."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.human_confirm import build_ask, is_hosted_confirm
from ascendc_pilot.ownership import ACTION_READ_PATHS
from ascendc_pilot.paths import ce_root, ensure_agent_layout, tg_root
from ascendc_pilot.state import start_workflow
from ascendc_pilot.workflows import get_workflow, phase_pipeline
from ascendc_pilot.workflows.specs import WORKFLOWS


def test_review_and_apply_llm_reads_exclude_ce_glob() -> None:
    review = ACTION_READ_PATHS["ce-review"]["code_review"]
    apply_patch = ACTION_READ_PATHS["ce-apply"]["patch"]
    apply_review = ACTION_READ_PATHS["ce-apply"]["code_review"]
    for paths in (review, apply_patch, apply_review):
        assert "ce/**" not in paths
        assert "ce/intent/plan.md" in paths or "ce/apply/todo.md" in paths
    assert "ce/intent/plan.md" in review
    assert "ce/apply/todo.md" in apply_patch


def test_ce_review_summary_is_persist_confirm() -> None:
    assert phase_pipeline("ce-review", "summary") == ["review_persist"]
    persist = next(a for a in WORKFLOWS["ce-review"]["actions"] if a["id"] == "review_persist")
    assert persist["execution_mode"] == "primary_interactive"
    code_review = next(a for a in WORKFLOWS["ce-review"]["actions"] if a["id"] == "code_review")
    assert "summary" not in (code_review.get("phases") or [])


def test_review_persist_ask_options(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "ce-review", architecture="arch35")
    assert is_hosted_confirm(tmp_path, "review_persist")
    ask = build_ask(tmp_path, action_id="review_persist")
    values = [str(o.get("value") or "") for o in ask.get("options") or []]
    assert "confirm" in values
    assert "persist" in values


def test_apply_report_ask_includes_persist(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "ce-apply", architecture="arch35")
    ask = build_ask(tmp_path, action_id="apply_report")
    values = [str(o.get("value") or "") for o in ask.get("options") or []]
    assert "persist" in values
    assert "confirm" in values


def test_persist_review_copies_parts(tmp_path: Path) -> None:
    from code_engineering.review_persist import persist_review_reports

    ensure_agent_layout(tmp_path, arch="arch35")
    run_id = "r1"
    parts = (
        tmp_path
        / ".ascendc-pilot"
        / "arch35"
        / "runs"
        / run_id
        / "actions"
        / "code_review"
        / "parts"
    )
    parts.mkdir(parents=True)
    (parts / "spec.yaml").write_text(
        "schema: ce-review-spec/v1\naxis: spec\nfindings:\n  - loc: op_host/a.cpp:3\n",
        encoding="utf-8",
    )
    oral = persist_review_reports(tmp_path, architecture="arch35", run_id=run_id, persist=False)
    review = ce_root(tmp_path, arch="arch35") / "review"
    assert oral["persisted"] is False
    assert (review / "persist.yaml").is_file()
    func = review / "functional_report.yaml"
    assert not func.is_file() or "op_host/a.cpp:3" not in func.read_text(encoding="utf-8")
    written = persist_review_reports(tmp_path, architecture="arch35", run_id=run_id, persist=True)
    assert written["persisted"] is True
    assert "op_host/a.cpp:3" in (review / "functional_report.yaml").read_text(encoding="utf-8")


def test_build_tg_plan_intent_is_ce_change_scoped() -> None:
    from code_engineering.change_test_intent import build_tg_plan_intent

    doc = build_tg_plan_intent(
        impact={"affected_keys_sample": [7, 16], "key_dims": ["DType"]},
        architecture="arch35",
        op_name="DemoOp",
    )
    assert doc["schema"] == "tg-plan-intent/v1"
    assert doc["mode"] == "ce_change_scoped"
    assert doc["target_keys"] == [7, 16]
    assert doc["target_mode"] == "explicit_keys"
    assert doc["do_not_widen_to_declared_set"] is True


def test_plan_fuse_reads_ce_intent_without_writing_plan_intent(tmp_path: Path) -> None:
    from testcase_agent.products import collect_intent_sources

    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "tg-plan", architecture="arch35", op_name="DemoOp")
    ce_intent = ce_root(tmp_path, arch="arch35") / "impact" / "tg_plan_intent.yaml"
    ce_intent.parent.mkdir(parents=True, exist_ok=True)
    ce_intent.write_text(
        yaml.safe_dump(
            {
                "schema": "tg-plan-intent/v1",
                "mode": "ce_change_scoped",
                "source": "ce-impact",
                "target_mode": "explicit_keys",
                "target_keys": [10, 20],
                "do_not_widen_to_declared_set": True,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    doc = collect_intent_sources(tmp_path, architecture="arch35")
    kinds = [row.get("kind") for row in doc.get("sources") or []]
    assert "ce_tg_plan_intent" in kinds
    assert not (tg_root(tmp_path, arch="arch35") / "plan" / "plan_intent.yaml").exists()


def test_empty_ce_keys_still_surface_as_intent_source(tmp_path: Path) -> None:
    from testcase_agent.products import collect_intent_sources

    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "tg-plan", architecture="arch35", op_name="DemoOp")
    ce_intent = ce_root(tmp_path, arch="arch35") / "impact" / "tg_plan_intent.yaml"
    ce_intent.parent.mkdir(parents=True, exist_ok=True)
    ce_intent.write_text(
        yaml.safe_dump(
            {
                "schema": "tg-plan-intent/v1",
                "mode": "ce_change_scoped",
                "source": "ce-impact",
                "target_mode": "explicit_keys",
                "target_keys": [],
                "do_not_widen_to_declared_set": True,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    doc = collect_intent_sources(tmp_path, architecture="arch35")
    payload = next(row["doc"] for row in doc["sources"] if row["kind"] == "ce_tg_plan_intent")
    assert payload.get("target_keys") == []
    assert payload.get("do_not_widen_to_declared_set") is True


def test_resolve_tg_mode_does_not_become_ce_overlay(tmp_path: Path) -> None:
    from ascendc_pilot.workflows import resolve_tg_mode

    ensure_agent_layout(tmp_path, arch="arch35")
    ce_intent = ce_root(tmp_path, arch="arch35") / "impact" / "tg_plan_intent.yaml"
    ce_intent.parent.mkdir(parents=True, exist_ok=True)
    ce_intent.write_text("schema: tg-plan-intent/v1\nmode: ce_change_scoped\n", encoding="utf-8")
    assert resolve_tg_mode(tmp_path) == ""
    overlay = get_workflow("tg-plan", project_root=tmp_path, mode=None)
    assert not overlay.get("_active_mode")


def test_obligation_ledger_contract_includes_tg_plan_intent() -> None:
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS

    assert "ce/impact/tg_plan_intent.yaml" in OUTPUT_CONTRACT_PATHS["obligation-ledger-v1"]
    assert "ce/review/persist.yaml" in OUTPUT_CONTRACT_PATHS["review-persist-v1"]
