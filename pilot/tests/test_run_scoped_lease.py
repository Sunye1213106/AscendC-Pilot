"""Run-scoped action lease: two families can prepare/finalize without clobbering."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.runtime import _finalize_bind_session_lease, _write_active_action
from ascendc_pilot.authorize.lease import (
    active_action_path,
    issue_action_lease,
    lease_path,
    load_lease,
)
from ascendc_pilot.occupancy import SESSION_ENV
from ascendc_pilot.paths import ensure_agent_layout, runs_root
from ascendc_pilot.state import load_state, start_workflow


def _session(op: Path, run_id: str, action_id: str, *, lease_id: str, nonce: str, wid: str) -> Path:
    sdir = runs_root(op, arch="arch35") / run_id / "actions" / action_id
    sdir.mkdir(parents=True, exist_ok=True)
    payload = {
        "prepare_nonce": nonce,
        "lease_id": lease_id,
        "run_id": run_id,
        "action_id": action_id,
        "workflow_id": wid,
        "phase": "construct" if wid == "tg-solve" else "patch",
        "session_dir": sdir.as_posix(),
    }
    import yaml

    (sdir / "session_state.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return sdir


def test_tg_and_ce_prepare_do_not_clobber_leases(tmp_path: Path, monkeypatch) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")

    monkeypatch.setenv(SESSION_ENV, "ses_tg")
    monkeypatch.setenv("ASCENDC_WORKFLOW_ID", "tg-solve")
    tg = start_workflow(op, "tg-solve", architecture="arch35", phase="construct", force_phase=True)
    tg_run = str(tg["run_id"])
    tg_state = load_state(op, workflow_id="tg-solve")
    tg_lease = issue_action_lease(
        op, state=tg_state, action_id="construct_cases", actor_id="tg-analyst"
    )
    tg_nonce = "nonce_tg_aaaaaaaa"
    _write_active_action(
        op,
        {
            "run_id": tg_run,
            "architecture": "arch35",
            "workflow_id": "tg-solve",
            "action_id": "construct_cases",
            "prepare_nonce": tg_nonce,
            "lease_id": tg_lease["lease_id"],
            "status": "prepared",
            "session_dir": str(
                runs_root(op, arch="arch35") / tg_run / "actions" / "construct_cases"
            ),
        },
    )
    tg_sdir = _session(
        op,
        tg_run,
        "construct_cases",
        lease_id=str(tg_lease["lease_id"]),
        nonce=tg_nonce,
        wid="tg-solve",
    )

    monkeypatch.setenv(SESSION_ENV, "ses_ce")
    monkeypatch.setenv("ASCENDC_WORKFLOW_ID", "ce-apply")
    ce = start_workflow(op, "ce-apply", architecture="arch35", phase="patch", force_phase=True)
    ce_run = str(ce["run_id"])
    ce_state = load_state(op, workflow_id="ce-apply")
    ce_lease = issue_action_lease(
        op, state=ce_state, action_id="patch", actor_id="ce-applier"
    )
    ce_nonce = "nonce_ce_bbbbbbbb"
    _write_active_action(
        op,
        {
            "run_id": ce_run,
            "architecture": "arch35",
            "workflow_id": "ce-apply",
            "action_id": "patch",
            "prepare_nonce": ce_nonce,
            "lease_id": ce_lease["lease_id"],
            "status": "prepared",
            "session_dir": str(
                runs_root(op, arch="arch35") / ce_run / "actions" / "patch"
            ),
        },
    )
    ce_sdir = _session(
        op,
        ce_run,
        "patch",
        lease_id=str(ce_lease["lease_id"]),
        nonce=ce_nonce,
        wid="ce-apply",
    )

    assert tg_run != ce_run
    assert tg_lease["lease_id"] != ce_lease["lease_id"]
    assert load_lease(op, run_id=tg_run).get("lease_id") == tg_lease["lease_id"]
    assert load_lease(op, run_id=ce_run).get("lease_id") == ce_lease["lease_id"]
    assert "runs" in lease_path(op, run_id=tg_run).as_posix().replace("\\", "/")
    assert active_action_path(op, run_id=tg_run).is_file()
    assert active_action_path(op, run_id=ce_run).is_file()

    tg_bind = _finalize_bind_session_lease(
        op,
        session={
            "prepare_nonce": tg_nonce,
            "lease_id": tg_lease["lease_id"],
            "run_id": tg_run,
            "action_id": "construct_cases",
            "workflow_id": "tg-solve",
            "phase": "construct",
            "session_dir": tg_sdir.as_posix(),
        },
        action_id="construct_cases",
        run_id=tg_run,
        wid="tg-solve",
        phase="construct",
        sdir=tg_sdir,
    )
    assert tg_bind is None, tg_bind

    ce_bind = _finalize_bind_session_lease(
        op,
        session={
            "prepare_nonce": ce_nonce,
            "lease_id": ce_lease["lease_id"],
            "run_id": ce_run,
            "action_id": "patch",
            "workflow_id": "ce-apply",
            "phase": "patch",
            "session_dir": ce_sdir.as_posix(),
        },
        action_id="patch",
        run_id=ce_run,
        wid="ce-apply",
        phase="patch",
        sdir=ce_sdir,
    )
    assert ce_bind is None, ce_bind
