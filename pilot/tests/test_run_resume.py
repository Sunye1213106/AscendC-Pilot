"""Interrupted-run continue/reinit behavior for public workflow actions."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.cli import main as acp_main
from ascendc_pilot.paths import agent_root, ce_root, runs_root, state_root, tg_root, uo_root
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
    output = capsys.readouterr().out
    assert "EXISTING_RUN_NEEDS_DECISION" in output
    assert "ask_question" in output
    assert "继续上次" in output


def test_decision_continue_resumes_same_run(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init")
    result = apply_resume_decision(tmp_path, "uo-init", "continue")
    assert result["ok"] is True
    assert result.get("resumed") is True
    assert load_state(tmp_path)["run_id"] == state["run_id"]


def test_uo_init_reinit_wipes_current_uo_products_but_keeps_historical_runs(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init")
    old_run_id = state["run_id"]
    legacy_uo = uo_root(tmp_path)
    _write(legacy_uo / "manifest.yaml", {"op_name": "foo"})
    product = agent_root(tmp_path) / "uo" / "foo.arch35.uo"
    _write(product, "sqlite-placeholder")
    historical = runs_root(tmp_path) / "historical-run-keep"
    _write(historical / "marker.yaml", {"keep": True})

    result = apply_resume_decision(tmp_path, "uo-init", "reinit")
    assert result["ok"] is True
    assert result.get("fresh_start") is True
    assert not (legacy_uo / "manifest.yaml").is_file()
    assert not product.is_file()
    assert historical.is_dir()
    current = load_state(tmp_path)
    assert current["phase"] == "prepare"
    assert current["status"] == "running"
    assert current["run_id"] != old_run_id


def test_tg_reinit_preserves_committed_uo_product(tmp_path: Path) -> None:
    product = agent_root(tmp_path) / "uo" / "foo.arch35.uo"
    _write(product, "sqlite-placeholder")
    tg = tg_root(tmp_path)
    _write(tg / "init" / "status.yaml", {"confirmed": False})

    start_workflow(tmp_path, "tg-init")
    result = apply_resume_decision(tmp_path, "tg-init", "reinit")
    assert result["ok"] is True
    assert product.is_file()
    assert not (tg / "init" / "status.yaml").is_file()


def test_ce_reinit_keeps_uo_and_tg(tmp_path: Path) -> None:
    product = agent_root(tmp_path) / "uo" / "foo.arch35.uo"
    _write(product, "sqlite-placeholder")
    tg = tg_root(tmp_path)
    ce = ce_root(tmp_path)
    _write(tg / "plan" / "levels" / "L0" / "plan_scope.yaml", {"level": "L0"})
    _write(ce / "review" / "index.yaml", {"reviews": []})

    start_workflow(tmp_path, "ce-review")
    result = apply_resume_decision(tmp_path, "ce-review", "reinit")
    assert result["ok"] is True
    assert product.is_file()
    assert (tg / "plan" / "levels" / "L0" / "plan_scope.yaml").is_file()
    assert not (ce / "review" / "index.yaml").is_file()


def test_uo_update_reinit_keeps_committed_uo_product(tmp_path: Path) -> None:
    product = agent_root(tmp_path) / "uo" / "foo.arch35.uo"
    _write(product, "sqlite-placeholder")
    uo = uo_root(tmp_path)
    _write(uo / "diff" / "change_set.yaml", {"changes": [1]})
    _write(uo / "summary" / "update_plan.yaml", {"plan": "x"})

    start_workflow(tmp_path, "uo-update")
    result = apply_resume_decision(tmp_path, "uo-update", "reinit")
    assert result["ok"] is True
    assert product.is_file()
    assert not (uo / "diff" / "change_set.yaml").is_file()
    assert not (uo / "summary" / "update_plan.yaml").is_file()


def test_summary_uses_public_actions_and_resume_hint(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init")
    summary = build_run_resume_summary(tmp_path, workflow_id="uo-init")
    assert summary["has_existing_run"] is True
    public = {"prepare", "extract", "analyze", "commit", "verify"}
    artifact_ids = {str(item.get("action_id") or "") for item in summary["artifacts"]}
    assert artifact_ids
    assert artifact_ids.issubset(public)
    assert all(str(item.get("label_zh") or "").strip() for item in summary["artifacts"])
    assert "ask_question" in summary
    assert summary["resume_next_action"] in public


def test_ask_question_uses_current_workflow_name_for_tg_init(tmp_path: Path) -> None:
    start_workflow(tmp_path, "tg-init")
    summary = build_run_resume_summary(tmp_path, workflow_id="tg-init")
    question = summary["ask_question"]
    assert "tg-init" in question["header"] or "tg-init" in question["question"]


def test_owned_artifact_map_uses_public_uo_actions() -> None:
    owned = action_owned_artifacts("uo-init")
    for action_id in ("prepare", "extract", "analyze", "commit", "verify"):
        assert action_id in owned
    for retired in (
        "derive_key_fields",
        "export_kb",
        "export_adapter_pack",
        "normalize_predicates",
        "resolve",
        "apply_gap_patch",
        "review",
    ):
        assert retired not in owned
    assert any("codemap_analyze_receipt" in path for path in owned["analyze"])
    assert any("unresolved.yaml" in path for path in owned["analyze"])
    assert not any("derive_key_fields_receipt" in path for path in owned["analyze"])
    assert owned["commit"] == ("../uo/*.uo",)
    assert owned["verify"] == ("../uo/*.uo",)


def test_different_workflow_resume_does_not_cross_active_run(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init")
    continue_result = apply_resume_decision(tmp_path, "uo-init", "continue")
    assert continue_result["ok"] is True
    assert needs_resume_decision(tmp_path, "tg-init") is True
    cross = apply_resume_decision(tmp_path, "tg-init", "continue")
    assert cross["ok"] is False
    assert cross.get("error") == "cross_workflow_active_run"
    assert load_state(tmp_path)["run_id"] == state["run_id"]


def test_continue_scrubs_failed_analyze_owned_products(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", phase="analyze", force_phase=True)
    run_id = state["run_id"]
    uo = uo_root(tmp_path)
    _write(uo / "ir" / "codemap_analyze_receipt.yaml", {"ok": True})
    _write(uo / "ir" / "unresolved.yaml", {"blockers": ["x"]})
    # Retired products are intentionally not action-owned anymore. They are not
    # consumed by structural analyze/commit and resume must not resurrect their
    # old authority merely to scrub them.
    _write(uo / "ir" / "derive_key_fields_receipt.yaml", {"legacy": True})
    _write(uo / "ir" / "host_extract_receipt.yaml", {"keep": True})
    _write(
        state_root(tmp_path) / "active_action.yaml",
        {
            "version": 1,
            "run_id": run_id,
            "workflow_id": "uo-init",
            "phase": "analyze",
            "action_id": "analyze",
            "status": "finalize_failed",
        },
    )
    _write(
        runs_root(tmp_path) / run_id / "actions" / "analyze" / "session.yaml",
        {"status": "finalize_failed", "action_id": "analyze", "run_id": run_id},
    )
    state["status"] = "rework_required"
    save_state(tmp_path, state)

    result = apply_resume_decision(tmp_path, "uo-init", "continue")
    assert result["ok"] is True
    scrubbed = set((result.get("resume_scrub") or {}).get("scrubbed_actions") or [])
    assert "analyze" in scrubbed
    assert not (uo / "ir" / "codemap_analyze_receipt.yaml").is_file()
    assert not (uo / "ir" / "unresolved.yaml").is_file()
    assert (uo / "ir" / "derive_key_fields_receipt.yaml").is_file()
    assert (uo / "ir" / "host_extract_receipt.yaml").is_file()
    assert not (state_root(tmp_path) / "active_action.yaml").is_file()
    assert load_state(tmp_path)["status"] == "running"


def test_continue_scrubs_failed_verify_session_marker(tmp_path: Path) -> None:
    """Continue scrub clears the failed Action session for public verify."""
    state = start_workflow(tmp_path, "uo-init", phase="verify", force_phase=True)
    run_id = state["run_id"]
    session = runs_root(tmp_path) / run_id / "actions" / "verify" / "session.yaml"
    _write(session, {"status": "finalize_failed", "action_id": "verify", "run_id": run_id})
    _write(
        state_root(tmp_path) / "active_action.yaml",
        {
            "run_id": run_id,
            "workflow_id": "uo-init",
            "phase": "verify",
            "action_id": "verify",
            "status": "finalize_failed",
        },
    )
    state["status"] = "rework_required"
    save_state(tmp_path, state)

    result = apply_resume_decision(tmp_path, "uo-init", "continue")
    assert result["ok"] is True
    scrubbed = set((result.get("resume_scrub") or {}).get("scrubbed_actions") or [])
    assert "verify" in scrubbed
    assert not (state_root(tmp_path) / "active_action.yaml").is_file()
    assert load_state(tmp_path)["status"] == "running"
