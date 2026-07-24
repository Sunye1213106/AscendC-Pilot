"""Tests for interrupted-run AskQuestion continue/reinit flow."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.cli import main as acp_main
from ascendc_pilot.paths import agent_root, ce_root, runs_root, state_root, tg_root, uo_root
from ascendc_pilot.runs import issue_receipt
from ascendc_pilot.spec_hashes import workflow_spec_hash
from ascendc_pilot.run_resume import (
    action_owned_artifacts,
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


def _issue_receipt(project: Path, action_id: str) -> None:
    st = load_state(project)
    issue_receipt(
        project,
        actor_type="deterministic_engine",
        actor_id="deterministic-uo-engine",
        action_id=action_id,
        workflow_spec_hash=workflow_spec_hash(str(st.get("workflow_id") or "uo-init")),
        input_hashes={"fixture": "in"},
        output_hashes={"fixture": "out"},
        checker_result={"ok": True},
        nonce=f"nonce-{action_id}",
        _internal=True,
    )


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
    st = start_workflow(tmp_path, "uo-init")
    old_run_id = st["run_id"]
    uo = uo_root(tmp_path)
    _write(uo / "manifest.yaml", {"op_name": "foo"})
    _write(uo / "ir" / "extract_plan_candidates.yaml", {"version": 1})
    assert (uo / "manifest.yaml").is_file()

    other_run = runs_root(tmp_path) / "historical-run-keep"
    _write(other_run / "marker.yaml", {"keep": True})

    result = apply_resume_decision(tmp_path, "uo-init", "reinit")
    assert result["ok"] is True
    assert result.get("decision") == "reinit"
    assert result.get("fresh_start") is True
    assert not (uo / "manifest.yaml").is_file()
    assert other_run.is_dir(), "historical runs must be preserved on uo-init reinit"
    st = load_state(tmp_path)
    assert st["phase"] == "prepare"
    assert st["status"] == "running"
    assert st["run_id"] != old_run_id


def test_tg_reinit_keeps_uo_kb(tmp_path: Path) -> None:
    uo = uo_root(tmp_path)
    tg = tg_root(tmp_path)
    _write(uo / "manifest.yaml", {"op_name": "foo"})
    _write(uo / "checks" / "integrity.yaml", {"ok": True})
    _write(tg / "init" / "status.yaml", {"confirmed": False})

    start_workflow(tmp_path, "tg-init")
    result = apply_resume_decision(tmp_path, "tg-init", "reinit")
    assert result["ok"] is True
    assert (uo / "manifest.yaml").is_file()
    assert (uo / "checks" / "integrity.yaml").is_file()
    assert not (tg / "init" / "status.yaml").is_file()


def test_ce_reinit_keeps_uo_and_tg(tmp_path: Path) -> None:
    uo = uo_root(tmp_path)
    tg = tg_root(tmp_path)
    ce = ce_root(tmp_path)
    _write(uo / "manifest.yaml", {"op_name": "foo"})
    _write(tg / "plan" / "levels" / "L0" / "plan_scope.yaml", {"level": "L0"})
    _write(ce / "review" / "index.yaml", {"reviews": []})

    start_workflow(tmp_path, "ce-review")
    result = apply_resume_decision(tmp_path, "ce-review", "reinit")
    assert result["ok"] is True
    assert (uo / "manifest.yaml").is_file()
    assert (tg / "plan" / "levels" / "L0" / "plan_scope.yaml").is_file()
    assert not (ce / "review" / "index.yaml").is_file()


def test_uo_update_reinit_keeps_kb(tmp_path: Path) -> None:
    uo = uo_root(tmp_path)
    _write(uo / "manifest.yaml", {"op_name": "foo"})
    _write(uo / "ir" / "host_subgraph.yaml", {"nodes": []})
    _write(uo / "diff" / "change_set.yaml", {"changes": [1]})
    _write(uo / "summary" / "update_plan.yaml", {"plan": "x"})

    start_workflow(tmp_path, "uo-update")
    result = apply_resume_decision(tmp_path, "uo-update", "reinit")
    assert result["ok"] is True
    assert (uo / "manifest.yaml").is_file()
    assert (uo / "ir" / "host_subgraph.yaml").is_file()
    assert not (uo / "diff" / "change_set.yaml").is_file()
    assert not (uo / "summary" / "update_plan.yaml").is_file()


def test_summary_lists_complete_and_interrupt(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init")
    uo = uo_root(tmp_path)
    _write(uo / "manifest.yaml", {"ok": True})
    _write(uo / "ir" / "entrypoint_graph.yaml", {"nodes": []})
    summary = build_run_resume_summary(tmp_path, workflow_id="uo-init")
    assert summary["has_existing_run"] is True
    labels = {a["label_zh"] for a in summary["artifacts"] if a["present"]}
    assert "布局/manifest" in labels
    assert "抽取前评分" in labels
    assert "ask_question" in summary
    assert summary["resume_next_action"]


def test_ask_question_uses_current_workflow_name_for_tg_init(tmp_path: Path) -> None:
    start_workflow(tmp_path, "tg-init")
    summary = build_run_resume_summary(tmp_path, workflow_id="tg-init")
    aq = summary["ask_question"]
    assert "tg-init" in aq["header"] or "tg-init" in aq["question"]


def test_owned_artifact_map_from_contracts() -> None:
    owned = action_owned_artifacts("uo-init")
    assert "key_resolution" in owned
    assert "input_derivable" not in owned
    assert "apply_semantic_patch" in owned
    assert "rebuild_from_ledger" in owned
    assert any("input_derivable_patch" in p for p in owned["key_resolution"])


def test_different_workflow_resume_do_not_pollute(tmp_path: Path) -> None:
    uo_st = start_workflow(tmp_path, "uo-init")
    uo_run = uo_st["run_id"]
    cont = apply_resume_decision(tmp_path, "uo-init", "continue")
    assert cont["ok"] is True

    assert needs_resume_decision(tmp_path, "tg-init") is True
    cross = apply_resume_decision(tmp_path, "tg-init", "continue")
    assert cross["ok"] is False
    assert cross.get("error") == "cross_workflow_active_run"
    assert load_state(tmp_path)["run_id"] == uo_run


def test_continue_scrubs_failed_extract_plan_products(tmp_path: Path) -> None:
    st = start_workflow(tmp_path, "uo-init")
    run_id = st["run_id"]
    uo = uo_root(tmp_path)

    _write(uo / "manifest.yaml", {"ok": True})
    _write(uo / "ir" / "entrypoint_graph.yaml", {"nodes": []})
    _write(uo / "ir" / "extract_plan_candidates.yaml", {"version": 1, "writer_candidates": []})
    _issue_receipt(tmp_path, "detect_score_pre")

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
    st["phase"] = "extract"
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


def test_continue_scrubs_failed_key_resolution_and_semantic_ledger(tmp_path: Path) -> None:
    st = start_workflow(tmp_path, "uo-init")
    run_id = st["run_id"]
    uo = uo_root(tmp_path)

    _write(uo / "manifest.yaml", {"ok": True})
    _write(uo / "ir" / "key_triage.yaml", {"keys": []})
    _write(uo / "ir" / "input_derivable_patch.yaml", {"partial": True})
    _write(uo / "ir" / "semantic_resolution_ledger.yaml", {"entries": [{"bad": True}]})

    st["phase"] = "resolve"
    st["status"] = "rework_required"
    save_state(tmp_path, st)
    _write(
        state_root(tmp_path) / "active_action.yaml",
        {
            "run_id": run_id,
            "action_id": "key_resolution",
            "status": "finalize_failed",
        },
    )

    result = apply_resume_decision(tmp_path, "uo-init", "continue")
    assert result["ok"] is True
    scrub = result.get("resume_scrub") or {}
    scrubbed = set(scrub.get("scrubbed_actions") or [])
    assert "key_resolution" in scrubbed
    assert not (uo / "ir" / "input_derivable_patch.yaml").is_file()
    assert not (uo / "ir" / "semantic_resolution_ledger.yaml").is_file()
