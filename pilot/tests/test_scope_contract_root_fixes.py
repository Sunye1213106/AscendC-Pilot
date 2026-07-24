"""Root fixes for ses_070d: contract path, MCP hard-require, cd&&acp authorize."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_NONEMPTY_GLOBS, OUTPUT_CONTRACT_PATHS
from ascendc_pilot.actions.runtime import _check_output_contract
from ascendc_pilot.authorize import authorize
from ascendc_pilot.authorize.lease import extract_pilot_command
from ascendc_pilot.gates import gate_scope_receipt
from ascendc_pilot.state import start_workflow


def test_scope_confirmed_contract_is_run_scoped_not_summary() -> None:
    paths = OUTPUT_CONTRACT_PATHS["scope-confirmed-v1"]
    assert "uo/summary/scope_confirmed.yaml" not in paths
    assert "runs" not in paths  # bare dir check removed
    joined = ",".join(paths)
    assert "uo/runs/{run_id}/scope/scope_confirmed.yaml" in joined
    assert "uo/runs/{run_id}/scope/receipt.yaml" in joined
    assert "uo/runs/*/" not in joined
    assert "uo/cbm/index_meta.json" in joined
    assert "scope-confirmed-v1" in OUTPUT_CONTRACT_NONEMPTY_GLOBS


def test_output_contract_accepts_run_scoped_scope(tmp_path: Path) -> None:
    start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    run = tmp_path / ".ascendc-pilot" / "uo" / "runs" / "UO_RUN_T" / "scope"
    run.mkdir(parents=True)
    (run / "scope_confirmed.yaml").write_text(
        "status: confirmed\nrun_id: UO_RUN_T\nworkflow_id: uo-init\n"
        "action_id: scope_confirmation\nconfirmed_file_list: [{path: a.cpp}]\n",
        encoding="utf-8",
    )
    (run / "receipt.yaml").write_text("status: pass\nrun_id: UO_RUN_T\n", encoding="utf-8")
    cbm = tmp_path / ".ascendc-pilot" / "uo" / "cbm"
    cbm.mkdir(parents=True)
    (cbm / "index_meta.json").write_text(
        json.dumps({"indexed_via": "mcp", "cbm_project": "p", "indexed_at": "t"}),
        encoding="utf-8",
    )
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
    summary = tmp_path / ".ascendc-pilot" / "uo" / "summary"
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


def test_gate_scope_receipt_requires_mcp(tmp_path: Path) -> None:
    state = start_workflow(tmp_path, "uo-init", phase="scope", force_phase=True)
    run_id = str(state.get("run_id") or "")
    uo = tmp_path / ".ascendc-pilot" / "uo"
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
    assert gate_scope_receipt(tmp_path, uo).get("ok") is False
    cbm = uo / "cbm"
    cbm.mkdir(parents=True)
    (cbm / "index_meta.json").write_text(
        json.dumps({"indexed_via": "mcp", "cbm_project": "x"}),
        encoding="utf-8",
    )
    assert gate_scope_receipt(tmp_path, uo).get("ok") is True


def test_extract_pilot_strips_cd_wrapper() -> None:
    cmd = r'cd "D:\PR-review\TEST\op" && acp route "建立知识库"'
    assert extract_pilot_command(cmd) == 'acp route "建立知识库"'
    assert extract_pilot_command("rm -rf / && acp next") is None
    assert extract_pilot_command("acp next --project .") == "acp next --project ."


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
