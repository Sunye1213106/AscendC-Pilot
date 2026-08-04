"""Phase-1 control-plane closure: no skip, fail-closed contracts, run-bound receipts."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.actions.runtime import (
    _check_output_contract,
    finalize_action,
    prepare_action,
)
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


def _issue(project: Path, action_id: str, *, actor_id: str = "deterministic-uo-engine") -> Path:
    st = load_state(project)
    return issue_receipt(
        project,
        actor_type="deterministic_engine",
        actor_id=actor_id,
        action_id=action_id,
        workflow_spec_hash=workflow_spec_hash(str(st.get("workflow_id") or "uo-init")),
        input_hashes={"fixture": "in"},
        output_hashes={"fixture": "out"},
        checker_result={"ok": True},
        nonce=f"nonce-{action_id}",
        _internal=True,
    )


def test_advance_denied_while_pipeline_incomplete(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init")
    result = advance_phase(tmp_path, "scope")
    assert result["ok"] is False
    assert result.get("error") == "PIPELINE_INCOMPLETE"
    assert "prepare_layout" in (result.get("missing_actions") or [])
    assert load_state(tmp_path)["phase"] == "prepare"


def test_prepare_skip_denied_returns_prerequisite(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    denied = prepare_action(tmp_path, "extract_tiling_key")
    assert denied["ok"] is False
    assert denied["error"] == "PIPELINE_SKIP_DENIED"
    assert denied.get("prerequisite_action") == "extract_host"


def test_unknown_contract_fails_closed() -> None:
    r = _check_output_contract(Path("."), "definitely-not-a-registered-contract-v9")
    assert r["ok"] is False
    assert r.get("error") == "unknown_contract"
    assert not r.get("skipped")


def test_missing_contract_id_fails_closed() -> None:
    r = _check_output_contract(Path("."), "")
    assert r["ok"] is False
    assert r.get("error") == "missing_contract_id"


def test_finalize_denied_after_phase_switch(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    st = load_state(tmp_path)
    _write(
        agent_root(tmp_path) / "state" / "active_action.yaml",
        {
            "version": 1,
            "run_id": st["run_id"],
            "workflow_id": "uo-init",
            "phase": "extract",
            "action_id": "extract_host",
            "status": "prepared",
        },
    )
    st["phase"] = "normalize"
    st["phase_label_zh"] = "规范化"
    save_state(tmp_path, st)
    fin = finalize_action(tmp_path, "extract_host")
    assert fin["ok"] is False
    assert fin.get("error") in {"session_phase_mismatch", "action_not_allowed"}


def test_finalize_denied_when_not_active_action(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    st = load_state(tmp_path)
    _write(
        agent_root(tmp_path) / "state" / "active_action.yaml",
        {
            "version": 1,
            "run_id": st["run_id"],
            "workflow_id": "uo-init",
            "phase": "extract",
            "action_id": "extract_kernel",
            "status": "prepared",
        },
    )
    fin = finalize_action(tmp_path, "extract_host")
    assert fin["ok"] is False
    assert fin.get("error") in {"not_active_action", "no_session", "action_not_allowed"}


def test_old_run_receipt_does_not_satisfy_current_run(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    st = load_state(tmp_path)
    old_run = str(st["run_id"])
    _issue(tmp_path, "prepare_layout")
    st2 = start_workflow(tmp_path, "uo-init")
    assert st2["run_id"] != old_run
    adv = advance_phase(tmp_path, "scope")
    assert adv["ok"] is False
    assert adv.get("error") == "PIPELINE_INCOMPLETE"
    assert "prepare_layout" in (adv.get("missing_actions") or [])


def test_old_run_artifact_alone_cannot_advance(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    _write(uo_root(tmp_path) / "manifest.yaml", {"version": 1, "op": "x"})
    adv = advance_phase(tmp_path, "scope")
    assert adv["ok"] is False
    assert adv.get("error") == "PIPELINE_INCOMPLETE"


def test_happy_path_prepare_advance_with_receipt(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    nxt = describe_next(tmp_path)
    assert (nxt.get("recommended_next_action") or {}).get("id") == "prepare_layout"
    _issue(tmp_path, "prepare_layout")
    uo = uo_root(tmp_path)
    _write(uo / "manifest.yaml", {"version": 1})
    _write(uo / "operator.yaml", {"op_name": "x"})
    adv = advance_phase(tmp_path, "scope")
    assert adv["ok"] is True, adv
    assert load_state(tmp_path)["phase"] == "scope"


def test_pipeline_complete_blocks_further_prepare(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init")
    _issue(tmp_path, "prepare_layout")
    denied = prepare_action(tmp_path, "prepare_layout")
    assert denied["ok"] is False
    assert denied["error"] == "PIPELINE_COMPLETE_ADVANCE_REQUIRED"


def test_uo_scope_scan_works_without_active_action(tmp_path: Path) -> None:
    """scope_scan via uo_scope helper does not require a prior prepare lease."""
    from ascendc_pilot.uo_scope import run_uo_scope

    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    active = agent_root(tmp_path) / "state" / "active_action.yaml"
    if active.is_file():
        active.unlink()
    result = run_uo_scope(tmp_path, step="scan", op_name="op")
    applied = result.get("applied") or {}
    assert applied.get("ok") is True, result
    obs = result.get("observation") or {}
    assert obs.get("action_id") == "scope_scan"
