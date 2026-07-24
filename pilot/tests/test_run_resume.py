"""Tests for interrupted-run AskQuestion continue/reinit flow."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.cli import main as acp_main
from ascendc_pilot.paths import runs_root, state_root, uo_root
from ascendc_pilot.run_resume import (
    apply_resume_decision,
    build_run_resume_summary,
    needs_resume_decision,
    normalize_decision,
)
from ascendc_pilot.state import load_state, save_state, start_workflow


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_normalize_decision_labels() -> None:
    assert normalize_decision("continue") == "continue"
    assert normalize_decision("继续上次 (Recommended)") == "continue"
    assert normalize_decision("删除重开") == "reinit"
    assert normalize_decision("bogus") is None


def test_start_requires_askquestion_when_running(tmp_path: Path, capsys) -> None:
    start_workflow(tmp_path, "uo-init")
    assert needs_resume_decision(tmp_path, "uo-init") is True
    code = acp_main(["start", "uo-init", "--project", str(tmp_path)])
    assert code == 2
    out = capsys.readouterr().out
    assert "EXISTING_RUN_NEEDS_DECISION" in out
    assert "ask_question" in out
    assert "继续上次" in out


def test_decision_continue_resumes(tmp_path: Path) -> None:
    st = start_workflow(tmp_path, "uo-init")
    run_id = st["run_id"]
    result = apply_resume_decision(tmp_path, "uo-init", "continue")
    assert result["ok"] is True
    assert result.get("resumed") is True
    assert load_state(tmp_path)["run_id"] == run_id


def test_decision_reinit_wipes_uo(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init")
    uo = uo_root(tmp_path)
    _write(uo / "manifest.yaml", {"op_name": "foo"})
    _write(uo / "ir" / "extract_plan_candidates.yaml", {"version": 1})
    assert (uo / "manifest.yaml").is_file()

    result = apply_resume_decision(tmp_path, "uo-init", "reinit")
    assert result["ok"] is True
    assert result.get("decision") == "reinit"
    assert result.get("fresh_start") is True
    assert not (uo / "manifest.yaml").is_file()
    st = load_state(tmp_path)
    assert st["phase"] == "prepare"
    assert st["status"] == "running"
    assert st["run_id"] != result.get("wiped")  # new run


def test_summary_lists_complete_and_interrupt(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init")
    uo = uo_root(tmp_path)
    _write(uo / "manifest.yaml", {"ok": True})
    _write(uo / "ir" / "entrypoint_graph.yaml", {"nodes": []})
    summary = build_run_resume_summary(tmp_path, workflow_id="uo-init")
    assert summary["has_existing_run"] is True
    labels = {a["label_zh"] for a in summary["artifacts"] if a["present"]}
    assert "布局/manifest" in labels
    assert "入口图" in labels
    assert "ask_question" in summary
    assert summary["resume_next_action"]


def test_continue_scrubs_failed_extract_plan_products(tmp_path: Path) -> None:
    st = start_workflow(tmp_path, "uo-init")
    run_id = st["run_id"]
    uo = uo_root(tmp_path)

    # Upstream complete-ish inputs should be kept.
    _write(uo / "manifest.yaml", {"ok": True})
    _write(uo / "ir" / "entrypoint_graph.yaml", {"nodes": []})
    _write(uo / "ir" / "extract_plan_candidates.yaml", {"version": 1, "writer_candidates": []})

    # Dirty / failed extract_plan scene (no finalize receipt).
    _write(uo / "ir" / "extract_plan.yaml", {"version": 1, "writers": [{"name": "Foo"}]})
    _write(uo / "ir" / "host_subgraph.yaml", {"nodes": []})
    _write(uo / "ir" / "kernel_subgraph.yaml", {"nodes": []})
    _write(
        state_root(tmp_path) / "active_action.yaml",
        {
            "version": 1,
            "run_id": run_id,
            "action_id": "extract_plan",
            "status": "finalize_failed",
            "actor_id": "uo-semantic-resolve",
        },
    )
    _write(
        runs_root(tmp_path) / run_id / "actions" / "extract_plan" / "session.yaml",
        {"status": "finalize_failed", "action_id": "extract_plan", "run_id": run_id},
    )
    st["status"] = "rework_required"
    st["failed_gates"] = [{"id": "extract_plan_contract", "detail": {"error_code": "SCHEMA"}}]
    st["last_failure"] = {"message_zh": "extract_plan 分层构建失败"}
    save_state(tmp_path, st)

    result = apply_resume_decision(tmp_path, "uo-init", "continue")
    assert result["ok"] is True
    assert result.get("resumed") is True
    scrub = result.get("resume_scrub") or {}
    assert "extract_plan" in (scrub.get("scrubbed_actions") or [])
    assert not (uo / "ir" / "extract_plan.yaml").is_file()
    assert not (uo / "ir" / "host_subgraph.yaml").is_file()
    assert not (uo / "ir" / "kernel_subgraph.yaml").is_file()
    assert (uo / "ir" / "extract_plan_candidates.yaml").is_file()
    assert (uo / "ir" / "entrypoint_graph.yaml").is_file()
    assert not (state_root(tmp_path) / "active_action.yaml").is_file()
    assert not (runs_root(tmp_path) / run_id / "actions" / "extract_plan").is_dir()
    assert result.get("resume_next_action") == "extract_plan"
    assert load_state(tmp_path)["status"] == "running"
    assert load_state(tmp_path).get("failed_gates") == []
