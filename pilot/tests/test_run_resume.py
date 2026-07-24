"""Tests for interrupted-run AskQuestion continue/reinit flow."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.cli import main as acp_main
from ascendc_pilot.paths import uo_root
from ascendc_pilot.run_resume import (
    apply_resume_decision,
    build_run_resume_summary,
    needs_resume_decision,
    normalize_decision,
)
from ascendc_pilot.state import load_state, start_workflow


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
