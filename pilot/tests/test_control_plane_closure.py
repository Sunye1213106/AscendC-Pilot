"""Six-stage UO control-plane closure: no skip, fail-closed, run-bound receipts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from ascendc_pilot.actions import finalize_action, prepare_action
from ascendc_pilot.actions.runtime import _check_output_contract
from ascendc_pilot.paths import agent_root, ensure_agent_layout, uo_root
from ascendc_pilot.runs import issue_receipt
from ascendc_pilot.spec_hashes import workflow_spec_hash
from ascendc_pilot.state import advance_phase, describe_next, load_state, save_state, start_workflow


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _issue(project: Path, action_id: str, *, actor_id: str = "ascendc-pilot") -> Path:
    state = load_state(project)
    return issue_receipt(
        project,
        actor_type="controller" if actor_id == "ascendc-pilot" else "deterministic_engine",
        actor_id=actor_id,
        action_id=action_id,
        workflow_spec_hash=workflow_spec_hash(str(state.get("workflow_id") or "uo-init")),
        input_hashes={"fixture": "in"},
        output_hashes={"fixture": "out"},
        checker_result={"ok": True},
        nonce=f"nonce-{action_id}",
        _internal=True,
    )


def _satisfy_prepare_gate(project: Path) -> None:
    uo = uo_root(project)
    _write(uo / "manifest.yaml", {"version": 1, "op_name": "x"})
    _write(uo / "operator.yaml", {"version": 1, "op_name": "x"})
    state = load_state(project)
    run_id = str(state.get("run_id") or "")
    if run_id:
        _write(
            uo / "runs" / run_id / "scope" / "scope_validated.yaml",
            {
                "status": "confirmed",
                "run_id": run_id,
                "workflow_id": str(state.get("workflow_id") or "uo-init"),
                "action_id": "scope_validated",
                "source": "machine",
                "auto": True,
            },
        )


def test_advance_denied_while_prepare_pipeline_incomplete(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    result = advance_phase(tmp_path, "extract")
    assert result["ok"] is False
    assert result.get("error") == "PIPELINE_INCOMPLETE"
    assert "prepare" in (result.get("missing_actions") or [])
    assert load_state(tmp_path)["phase"] == "prepare"


def test_wrong_phase_action_is_denied(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True, architecture="arch35")
    denied = prepare_action(tmp_path, "analyze")
    assert denied["ok"] is False
    assert denied.get("error") in {"action_not_allowed", "ACTION_NOT_ALLOWED"}


def test_unknown_contract_fails_closed() -> None:
    result = _check_output_contract(Path("."), "definitely-not-a-registered-contract-v9")
    assert result["ok"] is False
    assert result.get("error") == "unknown_contract"
    assert not result.get("skipped")


def test_missing_contract_id_fails_closed() -> None:
    result = _check_output_contract(Path("."), "")
    assert result["ok"] is False
    assert result.get("error") == "missing_contract_id"


def test_finalize_denied_after_phase_switch(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True, architecture="arch35")
    state = load_state(tmp_path)
    _write(
        agent_root(tmp_path) / "state" / "active_action.yaml",
        {
            "version": 1,
            "run_id": state["run_id"],
            "workflow_id": "uo-init",
            "phase": "extract",
            "action_id": "extract",
            "status": "prepared",
        },
    )
    state["phase"] = "analyze"
    state["phase_label_zh"] = "确定性 CodeMap Pass"
    save_state(tmp_path, state)
    result = finalize_action(tmp_path, "extract")
    assert result["ok"] is False
    assert result.get("error") in {"session_phase_mismatch", "action_not_allowed"}


def test_finalize_denied_when_not_active_action(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True, architecture="arch35")
    state = load_state(tmp_path)
    _write(
        agent_root(tmp_path) / "state" / "active_action.yaml",
        {
            "version": 1,
            "run_id": state["run_id"],
            "workflow_id": "uo-init",
            "phase": "extract",
            "action_id": "analyze",
            "status": "prepared",
        },
    )
    result = finalize_action(tmp_path, "extract")
    assert result["ok"] is False
    assert result.get("error") in {"not_active_action", "no_session", "action_not_allowed"}


def test_old_run_receipt_does_not_satisfy_current_run(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    old_run = str(load_state(tmp_path)["run_id"])
    _issue(tmp_path, "prepare")
    new_state = start_workflow(tmp_path, "uo-init", architecture="arch35")
    assert new_state["run_id"] != old_run
    result = advance_phase(tmp_path, "extract")
    assert result["ok"] is False
    assert result.get("error") == "PIPELINE_INCOMPLETE"
    assert "prepare" in (result.get("missing_actions") or [])


def test_old_artifact_alone_cannot_advance(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    _satisfy_prepare_gate(tmp_path)
    result = advance_phase(tmp_path, "extract")
    assert result["ok"] is False
    assert result.get("error") == "PIPELINE_INCOMPLETE"


def test_prepare_receipt_and_gate_allow_advance(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    next_step = describe_next(tmp_path)
    assert (next_step.get("recommended_next_action") or {}).get("id") == "prepare"
    _issue(tmp_path, "prepare")
    _satisfy_prepare_gate(tmp_path)
    result = advance_phase(tmp_path, "extract")
    assert result["ok"] is True, result
    assert load_state(tmp_path)["phase"] == "extract"


def test_completed_prepare_pipeline_blocks_duplicate_prepare(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    _issue(tmp_path, "prepare")
    denied = prepare_action(tmp_path, "prepare")
    assert denied["ok"] is False
    assert denied["error"] == "PIPELINE_COMPLETE_ADVANCE_REQUIRED"


def test_finalize_after_prepare_does_not_nameerror_on_apply_result(tmp_path: Path) -> None:
    """Regression: finalize_action used unbound apply_result (ses_00c6 / uo-init prepare)."""
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    with patch(
        "ascendc_pilot.actions.runtime.invoke_engine",
        return_value={"ok": True, "engine": "uo-prepare-stub"},
    ):
        result = prepare_action(tmp_path, "prepare")
    assert result.get("auto_finalize") is True
    fin = result.get("finalize") or {}
    assert isinstance(fin, dict)
    # Must not crash with NameError; checker payload always exposes apply.
    checker = fin.get("checker_result") or {}
    assert "apply" in checker
    assert checker["apply"] == {}
