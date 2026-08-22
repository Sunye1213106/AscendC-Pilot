"""Finalizer stamps run-scoped YAML before the output-contract identity check."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.actions.runtime import (
    _check_output_contract,
    _finalize_inject_artifact_identity,
    _finalize_restore_bind_parts,
)
from ascendc_pilot.observation import IDENTITY_CONTRACT, classify_failure
from ascendc_pilot.paths import agent_root, ensure_agent_layout
from ascendc_pilot.state import start_workflow

_ARCH = "arch0"


def _session(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "workflow_id": "tg-init",
        "phase": "bind",
        "action_id": "bind_init",
        "actor_id": "tg-analyst",
        "role_id": "producer",
        "action_session_id": "sess-bind",
        "prepare_nonce": "nonce-bind",
        "lease_id": "lease-bind",
        "execution_mode": "subagent",
        "staging_contract_id": "tg-bind-staging-v1",
        "output_contract_id": "tg-bind-staging-v1",
    }


def test_finalize_restores_bind_identity_without_stamping_llm_yaml(tmp_path: Path) -> None:
    from testcase_agent.bind_parts import emit_bind_parts

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    state = start_workflow(root, "tg-init", architecture=_ARCH, op_name="toy")
    run_id = str(state.get("run_id") or "")
    parts = agent_root(root, _ARCH) / "runs" / run_id / "actions" / "bind_init" / "parts"
    emit_bind_parts(
        parts,
        scan={
            "kind": "script_repo",
            "contract": {"entry": "run_x.py", "case_arg": "--case", "columns": ["D"]},
            "inventory": {"tables": [{"columns": ["D"], "kind": "csv"}]},
        },
        identity={
            "run_id": run_id,
            "workflow_id": "tg-init",
            "action_id": "bind_init",
            "produced_by": "pilot-finalizer",
        },
    )
    bind = yaml.safe_load((parts / "bind.yaml").read_text(encoding="utf-8"))
    bind["run_id"] = "LLM_FORGED"
    bind["mapping"]["D"]["encoding"] = "TND: literal"
    (parts / "bind.yaml").write_text(yaml.safe_dump(bind, allow_unicode=True), encoding="utf-8")
    session = _session(run_id)
    restored = _finalize_restore_bind_parts(
        root, session=session, action_id="bind_init"
    )
    assert restored.get("ok") is True, restored
    injected = _finalize_inject_artifact_identity(
        root, session=session, action_id="bind_init", contract_id="tg-bind-staging-v1"
    )
    assert injected.get("ok") is True, injected
    assert injected.get("skipped") is True
    bind = yaml.safe_load((parts / "bind.yaml").read_text(encoding="utf-8"))
    assert bind["run_id"] == run_id
    assert bind["run_id"] != "LLM_FORGED"
    assert bind["artifact_identity"]["run_id"] == run_id
    assert bind["mapping"]["D"]["encoding"] == "TND: literal"
    checked = _check_output_contract(
        root,
        "tg-bind-staging-v1",
        run_id=run_id,
        workflow_id="tg-init",
        phase="bind",
        action_id="bind_init",
        actor_id="tg-analyst",
        role_id="producer",
        action_session_id="sess-bind",
        lease_id="lease-bind",
        prepare_nonce="nonce-bind",
    )
    assert checked.get("ok") is True, checked
    assert not checked.get("identity_errors")


def test_identity_contract_does_not_send_llm_to_rewrite_run_id() -> None:
    c = classify_failure(
        error_code="ARTIFACT_IDENTITY_MISSING",
        action_id="bind_init",
        source="finalize_action",
        execution_mode="subagent",
        workflow_id="tg-init",
        phase="bind",
        messages=["run-scoped artifact missing identity"],
    )
    assert c["failure_class"] == IDENTITY_CONTRACT
    assert c["retryable"] is True
    assert not (c.get("rework_action_ids") or [])
