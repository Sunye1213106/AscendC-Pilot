# -*- coding: utf-8 -*-
"""CE lean persist: markdown plans, no CE yaml, tg-plan reads md."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
from ascendc_pilot.human_confirm import build_ask, is_hosted_confirm
from ascendc_pilot.ownership import ACTION_READ_PATHS, ACTION_WRITE_PATHS
from ascendc_pilot.paths import ce_root, ensure_agent_layout, tg_root
from ascendc_pilot.state import start_workflow
from ascendc_pilot.workflows.specs import WORKFLOWS
from ascendc_pilot.workflows import phase_pipeline


def test_review_and_apply_llm_reads_exclude_ce_glob() -> None:
    review = ACTION_READ_PATHS["ce-review"]["code_review"]
    apply_patch = ACTION_READ_PATHS["ce-apply"]["patch"]
    for paths in (review, apply_patch):
        assert "ce/**" not in paths
        assert any(p.startswith("ce/plan") for p in paths)
    assert "code_review" not in ACTION_READ_PATHS["ce-apply"]


def test_ce_writes_are_markdown_only() -> None:
    for wid, actions in ACTION_WRITE_PATHS.items():
        if not str(wid).startswith(("ce-", "handoff")):
            continue
        for aid, paths in actions.items():
            for path in paths:
                p = str(path).replace("\\", "/")
                if p.startswith("source:"):
                    continue
                if p.startswith("runs/"):
                    assert not p.endswith(".yaml"), (wid, aid, path)
                    continue
                assert not p.endswith(".yaml"), (wid, aid, path)


def test_ce_review_summary_is_report_confirm() -> None:
    assert phase_pipeline("ce-review", "summary") == ["review_report"]
    persist = next(a for a in WORKFLOWS["ce-review"]["actions"] if a["id"] == "review_report")
    assert persist["execution_mode"] == "primary_interactive"
    code_review = next(a for a in WORKFLOWS["ce-review"]["actions"] if a["id"] == "code_review")
    assert "summary" not in (code_review.get("phases") or [])
    assert code_review.get("output_mode") == "return_value"
    assert ACTION_WRITE_PATHS["ce-review"]["code_review"] == []


def test_review_report_ask_options(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "ce-review", architecture="arch35")
    assert is_hosted_confirm(tmp_path, "review_report")
    ask = build_ask(tmp_path, action_id="review_report")
    values = [str(o.get("value") or "") for o in ask.get("options") or []]
    assert "confirm" in values
    assert "rework" in values


def test_apply_report_ask_includes_review_and_tests(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "ce-apply", architecture="arch35")
    ask = build_ask(tmp_path, action_id="apply_report")
    values = [str(o.get("value") or "") for o in ask.get("options") or []]
    assert "confirm" in values
    assert "review" in values
    assert "persist" not in values


def test_plan_fuse_reads_ce_plan_markdown(tmp_path: Path) -> None:
    from testcase_agent.products import collect_intent_sources

    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "tg-plan", architecture="arch35", op_name="DemoOp")
    plan = ce_root(tmp_path, arch="arch35") / "plan" / "deter-band-schedule_plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# x\n\n## 测试内容\n\n- 应覆盖 deterBandScheduleMode\n", encoding="utf-8")
    yaml_bridge = ce_root(tmp_path, arch="arch35") / "impact" / "tg_plan_intent.yaml"
    yaml_bridge.parent.mkdir(parents=True, exist_ok=True)
    yaml_bridge.write_text("schema: tg-plan-intent/v1\nmode: ce_change_scoped\n", encoding="utf-8")
    doc = collect_intent_sources(tmp_path, architecture="arch35")
    kinds = [row.get("kind") for row in doc.get("sources") or []]
    assert "ce_plan" in kinds
    assert "ce_tg_plan_intent" not in kinds
    assert not (tg_root(tmp_path, arch="arch35") / "plan" / "plan_intent.yaml").exists()


def test_collect_intent_sources_reads_handoff(tmp_path: Path) -> None:
    from testcase_agent.products import collect_intent_sources

    ensure_agent_layout(tmp_path, arch="arch35")
    handoff = tmp_path / ".ascendc-pilot" / "arch35" / "session_handoff.md"
    handoff.write_text("# Session handoff\n\n- next: `/tg-plan`\n", encoding="utf-8")
    doc = collect_intent_sources(tmp_path, architecture="arch35")
    kinds = [row.get("kind") for row in doc.get("sources") or []]
    assert "session_handoff" in kinds


def test_output_contracts_have_no_ce_yaml() -> None:
    for cid, paths in OUTPUT_CONTRACT_PATHS.items():
        for path in paths:
            p = str(path).replace("\\", "/")
            if p.startswith("ce/") or p == "session_handoff.md":
                assert not p.endswith(".yaml"), (cid, path)
    assert "obligation-ledger-v1" not in OUTPUT_CONTRACT_PATHS
    assert "review-persist-v1" not in OUTPUT_CONTRACT_PATHS
    assert OUTPUT_CONTRACT_PATHS["ce-plan-v1"] == ["ce/plan/*_plan.md"]
    assert OUTPUT_CONTRACT_PATHS["session-handoff-v1"] == ["session_handoff.md"]
