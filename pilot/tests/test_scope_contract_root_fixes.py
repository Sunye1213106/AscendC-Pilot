"""Root fixes for ses_070d: contract path, MCP hard-require, cd&&acp authorize."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_NONEMPTY_GLOBS, OUTPUT_CONTRACT_PATHS
from ascendc_pilot.actions.runtime import _check_output_contract
from ascendc_pilot.authorize import authorize
from ascendc_pilot.authorize.lease import extract_pilot_command
from ascendc_pilot.gates import gate_scope_receipt
from ascendc_pilot.paths import uo_root
from ascendc_pilot.state import start_workflow


def test_scope_confirmed_contract_is_run_scoped_not_summary() -> None:
    paths = OUTPUT_CONTRACT_PATHS["scope-confirmed-v1"]
    assert "uo/summary/scope_confirmed.yaml" not in paths
    assert "runs" not in paths  # bare dir check removed
    joined = ",".join(paths)
    assert "uo/runs/{run_id}/scope/scope_confirmed.yaml" in joined
    assert "uo/runs/{run_id}/scope/receipt.yaml" in joined
    assert "uo/runs/*/" not in joined
    assert "scope-confirmed-v1" in OUTPUT_CONTRACT_NONEMPTY_GLOBS


def test_output_contract_accepts_run_scoped_scope(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    run = uo_root(tmp_path) / "runs" / "UO_RUN_T" / "scope"
    run.mkdir(parents=True)
    (run / "scope_confirmed.yaml").write_text(
        "status: confirmed\nrun_id: UO_RUN_T\nworkflow_id: uo-init\n"
        "action_id: scope_confirmation\nconfirmed_file_list: [{path: a.cpp}]\n",
        encoding="utf-8",
    )
    (run / "receipt.yaml").write_text("status: pass\nrun_id: UO_RUN_T\n", encoding="utf-8")
    checked = _check_output_contract(
        tmp_path,
        "scope-confirmed-v1",
        run_id="UO_RUN_T",
        workflow_id="uo-init",
        action_id="scope_confirmation",
        actor_id="ascendc-pilot",
    )
    assert checked.get("ok") is True, checked


def test_output_contract_rejects_summary_only_legacy(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    summary = uo_root(tmp_path) / "summary"
    summary.mkdir(parents=True)
    (summary / "scope_confirmed.yaml").write_text("status: confirmed\n", encoding="utf-8")
    checked = _check_output_contract(
        tmp_path,
        "scope-confirmed-v1",
        run_id="RUN_CURRENT",
        workflow_id="uo-init",
        action_id="scope_confirmation",
        actor_id="ascendc-pilot",
    )
    assert checked.get("ok") is False
    missing = checked.get("missing") or []
    assert any("runs/{run_id}/scope/scope_confirmed.yaml" in m or "RUN_CURRENT" in m for m in missing)


def test_gate_scope_receipt_requires_current_run_confirmation(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    run_id = str(state.get("run_id") or "")
    uo = uo_root(tmp_path)
    scope = uo / "runs" / run_id / "scope"
    scope.mkdir(parents=True)
    (scope / "scope_confirmed.yaml").write_text(
        yaml.safe_dump(
            {
                "status": "confirmed",
                "run_id": run_id,
                "workflow_id": "uo-init",
                "action_id": "scope_confirmation",
                "confirmed_file_list": [{"path": "a.cpp"}],
            }
        ),
        encoding="utf-8",
    )
    assert gate_scope_receipt(tmp_path, uo).get("ok") is True


def test_extract_pilot_strips_cd_wrapper() -> None:
    cmd = r'cd "D:\PR-review\TEST\op" && acp route "建立知识库"'
    assert extract_pilot_command(cmd) == 'acp route "建立知识库"'
    assert extract_pilot_command("rm -rf / && acp next") is None
    assert extract_pilot_command("acp next --project .") == "acp next --project ."


def test_extract_pilot_strips_env_prefix_before_acp() -> None:
    """ses_0662: $env:VAR=…; acp … must authorize as harness CLI."""
    cmd = "$env:UO_EXTRACT_MAX_NON_SINK = '1024'; acp run-action extract_plan"
    assert extract_pilot_command(cmd) == "acp run-action extract_plan"
    cmd2 = "UO_EXTRACT_MAX_NON_SINK=1024 acp run-action extract_plan --project ."
    assert extract_pilot_command(cmd2) == "acp run-action extract_plan --project ."


def test_authorize_allows_env_prefixed_acp(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    cmd = (
        "$env:UO_EXTRACT_MAX_NON_SINK = '1024'; "
        f'acp run-action extract_plan --project "{tmp_path}"'
    )
    verdict = authorize(tmp_path, tool="bash", command=cmd, agent="ascendc-pilot")
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") == "HARNESS_CLI"


def test_authorize_allows_cd_and_acp(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init")
    verdict = authorize(
        tmp_path,
        tool="bash",
        command=r'cd "D:\tmp\op" && acp route "为算子建立知识库"',
        agent="ascendc-pilot",
    )
    assert verdict.get("decision") == "allow"
    assert verdict.get("ok") is True


def test_authorize_still_denies_shell_write_into_ascendc_pilot(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    cmd = f'echo hi > "{tmp_path / ".ascendc-pilot" / "uo" / "runs" / "receipt.yaml"}"'
    verdict = authorize(tmp_path, tool="bash", command=cmd, agent="ascendc-pilot")
    assert verdict.get("decision") == "deny", verdict
    assert verdict.get("reason_code") == "BASH_PROTECTED_WRITE"


def test_output_contract_accepts_receipt_with_snapshot_run_id_only(tmp_path: Path) -> None:
    """ses_0663 deadlock: finalize_scope nested run_id under snapshot; contract must still pass."""
    from ascendc_pilot.actions.runtime import _contract_identity_ok

    start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    run = uo_root(tmp_path) / "runs" / "RUN_SNAP" / "scope"
    run.mkdir(parents=True)
    (run / "scope_confirmed.yaml").write_text(
        "status: confirmed\nrun_id: RUN_SNAP\nworkflow_id: uo-init\n"
        "action_id: scope_confirmation\nconfirmed_file_list: [{path: a.cpp}]\n",
        encoding="utf-8",
    )
    # Legacy shape: no top-level run_id (only snapshot.run_id) — previously ARTIFACT_IDENTITY_MISSING.
    (run / "receipt.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "status": "pass",
                "snapshot": {"run_id": "RUN_SNAP"},
                "artifact": {"type": "runs.receipt"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    id_check = _contract_identity_ok(
        run / "receipt.yaml",
        run_id="RUN_SNAP",
        workflow_id="uo-init",
        phase="scope",
        action_id="scope_confirmation",
        actor_id="ascendc-pilot",
        role_id="controller",
    )
    assert id_check.get("ok") is True, id_check

    checked = _check_output_contract(
        tmp_path,
        "scope-confirmed-v1",
        run_id="RUN_SNAP",
        workflow_id="uo-init",
        phase="scope",
        action_id="scope_confirmation",
        actor_id="ascendc-pilot",
        role_id="controller",
    )
    assert checked.get("ok") is True, checked


def test_authorize_allows_readonly_inspect_commands(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    allowed = [
        f'Get-ChildItem "{tmp_path}" -Directory',
        f'Get-ChildItem "{tmp_path}" | Select-Object Name, Mode',
        f'ls "{tmp_path}"',
        "pwd",
        f'cd "{tmp_path}"; Get-ChildItem',
        f'Test-Path "{tmp_path / ".ascendc-pilot"}"',
        f'tree "{tmp_path}"',
        f'rg -n "SaveStuff" "{tmp_path}"',
        f'grep -n "blob_" "{tmp_path}"',
        f'Select-String -Path "{tmp_path}\\*.cpp" -Pattern "set_"',
        f'Select-String -Path "{tmp_path}\\ir.yaml" -Pattern "sha256:" | Select-Object -First 20',
        f'findstr /n /c:"tiling" "{tmp_path}\\foo.cpp"',
        # Quoted findstr alternation must not be treated as a shell pipe.
        f'findstr /n "DoPreSfmgTiling\\|DoPreTiling\\|DoPostTiling" "{tmp_path}\\extract_plan_candidates.yaml"',
    ]
    for cmd in allowed:
        verdict = authorize(tmp_path, tool="bash", command=cmd, agent="ascendc-pilot")
        assert verdict.get("decision") == "allow", (cmd, verdict)
        assert verdict.get("reason_code") == "BASH_READONLY_INSPECT", (cmd, verdict)


def test_authorize_readonly_inspect_still_blocks_writes(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    denied = [
        f'Get-ChildItem "{tmp_path}" > "{tmp_path / "out.txt"}"',
        f'Get-ChildItem "{tmp_path}"; Remove-Item -Recurse "{tmp_path / "x"}"',
        f'mkdir "{tmp_path / "newdir"}"',
    ]
    for cmd in denied:
        verdict = authorize(tmp_path, tool="bash", command=cmd, agent="ascendc-pilot")
        assert verdict.get("decision") != "allow" or verdict.get("reason_code") != "BASH_READONLY_INSPECT", (
            cmd,
            verdict,
        )
        assert verdict.get("decision") in {"deny", "ask"}, (cmd, verdict)
