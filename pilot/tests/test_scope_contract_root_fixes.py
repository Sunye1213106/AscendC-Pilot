"""Prepare-scope contract and harness authorization regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_NONEMPTY_GLOBS, OUTPUT_CONTRACT_PATHS
from ascendc_pilot.actions.runtime import _check_output_contract
from ascendc_pilot.authorize import authorize
from ascendc_pilot.authorize.lease import extract_pilot_command
from ascendc_pilot.gates import gate_scope_receipt
from ascendc_pilot.paths import uo_root
from ascendc_pilot.state import start_workflow


@pytest.fixture(autouse=True)
def _arch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UO_ARCH", "arch35")


def test_prepare_contract_is_run_scoped() -> None:
    paths = OUTPUT_CONTRACT_PATHS["uo-prepare-v1"]
    joined = ",".join(paths)
    assert "uo/manifest.yaml" in joined
    assert "uo/operator.yaml" in joined
    assert "uo/ir/build_variant.yaml" in joined
    assert "uo/runs/{run_id}/scope/scope_validated.yaml" in joined
    assert "uo/runs/{run_id}/scope/receipt.yaml" in joined
    assert "uo/runs/*/" not in joined
    assert "uo-prepare-v1" in OUTPUT_CONTRACT_NONEMPTY_GLOBS


def _write_prepare_scope(tmp_path: Path, run_id: str) -> Path:
    """Production machine stamp (scope_validated), not parent Action prepare."""
    run = uo_root(tmp_path) / "runs" / run_id / "scope"
    run.mkdir(parents=True, exist_ok=True)
    receipt = {
        "status": "confirmed",
        "source": "machine",
        "auto": True,
        "run_id": run_id,
        "workflow_id": "uo-init",
        "phase": "prepare",
        "action_id": "scope_validated",
        "probe_clean": True,
        "clang_scope_status": "complete",
        "scope_files": [{"path": "a.cpp"}],
    }
    (run / "scope_validated.yaml").write_text(
        yaml.safe_dump(receipt, sort_keys=False),
        encoding="utf-8",
    )
    (run / "receipt.yaml").write_text(
        yaml.safe_dump({"ok": True, "gate": "scope_receipt", **receipt}, sort_keys=False),
        encoding="utf-8",
    )
    return run


def _write_layout_artifacts(tmp_path: Path) -> None:
    uo = uo_root(tmp_path)
    uo.mkdir(parents=True, exist_ok=True)
    (uo / "ir").mkdir(parents=True, exist_ok=True)
    (uo / "manifest.yaml").write_text("version: 1\n", encoding="utf-8")
    (uo / "operator.yaml").write_text("op_name: test_op\n", encoding="utf-8")
    (uo / "ir" / "build_variant.yaml").write_text("arch: arch35\n", encoding="utf-8")


def test_output_contract_accepts_current_run_prepare_scope(tmp_path: Path) -> None:
    state = start_workflow(
        tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35"
    )
    run_id = str(state["run_id"])
    _write_layout_artifacts(tmp_path)
    _write_prepare_scope(tmp_path, run_id)
    checked = _check_output_contract(
        tmp_path,
        "uo-prepare-v1",
        run_id=run_id,
        workflow_id="uo-init",
        phase="prepare",
        action_id="prepare",
        actor_id="ascendc-pilot",
        role_id="controller",
    )
    assert checked.get("ok") is True, checked


def test_ses_00bb_prepare_accepts_scope_validated_stamp(tmp_path: Path) -> None:
    """Engine stamps scope_validated; prepare finalize must not OWNER_MISMATCH."""
    state = start_workflow(
        tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35"
    )
    run_id = str(state["run_id"])
    _write_layout_artifacts(tmp_path)
    _write_prepare_scope(tmp_path, run_id)
    checked = _check_output_contract(
        tmp_path,
        "uo-prepare-v1",
        run_id=run_id,
        workflow_id="uo-init",
        phase="prepare",
        action_id="prepare",
        actor_id="ascendc-pilot",
        role_id="controller",
    )
    assert checked.get("ok") is True, checked
    gate = gate_scope_receipt(tmp_path, uo_root(tmp_path))
    assert gate.get("ok") is True, gate


def test_summary_only_scope_does_not_satisfy_prepare_contract(tmp_path: Path) -> None:
    state = start_workflow(
        tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35"
    )
    _write_layout_artifacts(tmp_path)
    summary = uo_root(tmp_path) / "summary"
    summary.mkdir(parents=True)
    (summary / "scope_validated.yaml").write_text("status: confirmed\n", encoding="utf-8")
    checked = _check_output_contract(
        tmp_path,
        "uo-prepare-v1",
        run_id=str(state["run_id"]),
        workflow_id="uo-init",
        phase="prepare",
        action_id="prepare",
        actor_id="ascendc-pilot",
        role_id="controller",
    )
    assert checked.get("ok") is False


def test_extract_pilot_strips_cd_and_env_wrappers() -> None:
    assert extract_pilot_command(r'cd "D:\PR-review\TEST\op" && acp route "建立 CodeMap"') == 'acp route "建立 CodeMap"'
    assert extract_pilot_command("rm -rf / && acp next") is None
    assert extract_pilot_command("acp next --project .") == "acp next --project ."
    assert extract_pilot_command("$env:X='1'; acp run-action extract") == "acp run-action extract"
    assert extract_pilot_command("X=1 acp run-action extract --project .") == "acp run-action extract --project ."


def test_authorize_allows_env_prefixed_public_action(tmp_path: Path) -> None:
    start_workflow(
        tmp_path, "uo-init", phase="extract", force_phase=True, architecture="arch35"
    )
    cmd = f'$env:UO_EXTRACT_MAX_NON_SINK = "1024"; acp run-action extract --project "{tmp_path}"'
    verdict = authorize(tmp_path, tool="bash", command=cmd, agent="ascendc-pilot")
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") == "HARNESS_CLI"


def test_authorize_allows_cd_and_acp(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    verdict = authorize(
        tmp_path,
        tool="bash",
        command=r'cd "D:\tmp\op" && acp route "为算子建立 CodeMap"',
        agent="ascendc-pilot",
    )
    assert verdict.get("decision") == "allow"
    assert verdict.get("ok") is True


def test_authorize_still_denies_shell_write_into_control_plane(tmp_path: Path) -> None:
    start_workflow(
        tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35"
    )
    cmd = f'echo hi > "{tmp_path / ".ascendc-pilot" / "uo" / "runs" / "receipt.yaml"}"'
    verdict = authorize(tmp_path, tool="bash", command=cmd, agent="ascendc-pilot")
    assert verdict.get("decision") == "deny", verdict
    assert verdict.get("reason_code") == "BASH_PROTECTED_WRITE"


def test_prepare_receipt_accepts_snapshot_run_id_shape(tmp_path: Path) -> None:
    from ascendc_pilot.actions.runtime import _contract_identity_ok

    state = start_workflow(
        tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35"
    )
    run_id = str(state["run_id"])
    run = _write_prepare_scope(tmp_path, run_id)
    (run / "receipt.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "status": "pass",
                "snapshot": {"run_id": run_id},
                "artifact": {"type": "runs.receipt"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    identity = _contract_identity_ok(
        run / "receipt.yaml",
        run_id=run_id,
        workflow_id="uo-init",
        phase="prepare",
        action_id="prepare",
        actor_id="ascendc-pilot",
        role_id="controller",
    )
    assert identity.get("ok") is True, identity


def test_authorize_readonly_inspection_without_model_write_scope(tmp_path: Path) -> None:
    start_workflow(
        tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35"
    )
    allowed = [
        f'Get-ChildItem "{tmp_path}" -Directory',
        f'ls "{tmp_path}"',
        "pwd",
        f'Test-Path "{tmp_path / ".ascendc-pilot"}"',
        f'rg -n "SaveStuff" "{tmp_path}"',
        f'grep -n "blob_" "{tmp_path}"',
    ]
    for cmd in allowed:
        verdict = authorize(tmp_path, tool="bash", command=cmd, agent="ascendc-pilot")
        assert verdict.get("decision") == "allow", (cmd, verdict)
        assert verdict.get("reason_code") == "BASH_READONLY_INSPECT", (cmd, verdict)


def test_authorize_readonly_inspection_still_blocks_writes(tmp_path: Path) -> None:
    start_workflow(
        tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35"
    )
    redirect = authorize(
        tmp_path,
        tool="bash",
        command=f'Get-ChildItem "{tmp_path}" > "{tmp_path / "out.txt"}"',
        agent="ascendc-pilot",
    )
    assert redirect.get("decision") == "allow", redirect
    mkdir = authorize(
        tmp_path,
        tool="bash",
        command=f'mkdir "{tmp_path / "newdir"}"',
        agent="ascendc-pilot",
    )
    assert mkdir.get("decision") == "allow", mkdir
    assert mkdir.get("reason_code") == "PRIMARY_BASH_ASK"
