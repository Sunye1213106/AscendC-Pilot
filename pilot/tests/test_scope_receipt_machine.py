# -*- coding: utf-8 -*-
"""scope_receipt accepts machine clang validation (no human file-list confirm)."""
from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.gates import gate_scope_receipt
from ascendc_pilot.paths import uo_root
from ascendc_pilot.state import start_workflow


def test_scope_receipt_accepts_machine_prepare_stamp(tmp_path: Path):
    """ses_00bf: prepare-chain stamped action_id=prepare; still machine-validated."""
    state = start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True)
    run_id = str(state["run_id"])
    scope = uo_root(tmp_path) / "runs" / run_id / "scope"
    scope.mkdir(parents=True)
    (scope / "scope_confirmed.yaml").write_text(
        yaml.safe_dump(
            {
                "status": "confirmed",
                "source": "machine",
                "auto": True,
                "run_id": run_id,
                "workflow_id": "uo-init",
                "action_id": "prepare",
                "probe_clean": True,
                "clang_scope_status": "complete",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    out = gate_scope_receipt(tmp_path, uo_root(tmp_path))
    assert out.get("ok") is True, out


def test_scope_receipt_requires_scope_confirmation_for_non_machine(tmp_path: Path):
    state = start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True)
    run_id = str(state["run_id"])
    scope = uo_root(tmp_path) / "runs" / run_id / "scope"
    scope.mkdir(parents=True)
    (scope / "scope_confirmed.yaml").write_text(
        yaml.safe_dump(
            {
                "status": "confirmed",
                "source": "human",
                "run_id": run_id,
                "workflow_id": "uo-init",
                "action_id": "prepare",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    out = gate_scope_receipt(tmp_path, uo_root(tmp_path))
    assert out.get("ok") is False
    assert out.get("error") == "SCOPE_RECEIPT_ACTION_MISMATCH"
