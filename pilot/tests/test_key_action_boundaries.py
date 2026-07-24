"""Phase-2 KEY triage / resolution responsibility boundaries."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.agents_registry import agent_write_scopes, path_matches_scope
from ascendc_pilot.gates import gate_key_resolve_receipt
from ascendc_pilot.paths import agent_root, ensure_agent_layout, uo_root
from ascendc_pilot.runs import issue_receipt
from ascendc_pilot.spec_hashes import workflow_spec_hash
from ascendc_pilot.state import load_state, start_workflow
from ascendc_pilot.workflows import actions_for_phase, phase_pipeline
from ascendc_pilot.workflows.pipeline import recommend_next_action


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_triage_write_scope_excludes_patch(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    _write(
        agent_root(tmp_path) / "state" / "active_action.yaml",
        {"action_id": "key_triage", "run_id": load_state(tmp_path)["run_id"]},
    )
    scopes = agent_write_scopes("uo-key-resolve", tmp_path)
    assert scopes == ["uo/ir/key_triage.yaml"]
    assert path_matches_scope("uo/ir/key_triage.yaml", scopes)
    assert not path_matches_scope("uo/ir/input_derivable_patch.yaml", scopes)


def test_resolution_write_scope_excludes_triage(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    _write(
        agent_root(tmp_path) / "state" / "active_action.yaml",
        {"action_id": "key_resolution", "run_id": load_state(tmp_path)["run_id"]},
    )
    scopes = agent_write_scopes("uo-key-resolve", tmp_path)
    assert "uo/ir/input_derivable_patch.yaml" in scopes
    assert not path_matches_scope("uo/ir/key_triage.yaml", scopes)


def test_key_resolve_gate_rejects_triage_receipt_only(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    uo = uo_root(tmp_path)
    _write(uo / "ir" / "input_derivable_gaps.yaml", {"gaps": [{"id": "KEY_A", "status": "open"}]})
    _write(uo / "ir" / "key_triage.yaml", {"keys": [{"id": "KEY_A", "complexity": "simple"}]})
    _write(uo / "ir" / "input_derivable_patch.yaml", {"items": [{"id": "KEY_A", "status": "accepted"}]})
    # Only triage receipt — must not satisfy resolution gate
    issue_receipt(
        tmp_path,
        actor_type="producer",
        actor_id="uo-key-resolve",
        action_id="key_triage",
        workflow_spec_hash=workflow_spec_hash("uo-init"),
        input_hashes={"a": "1"},
        output_hashes={"a": "1"},
        checker_result={"ok": True},
        nonce="triage",
        _internal=True,
    )
    r = gate_key_resolve_receipt(tmp_path, uo)
    assert r["ok"] is False
    assert r.get("has_receipt") is False


def test_key_resolve_gate_requires_resolution_receipt(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    uo = uo_root(tmp_path)
    _write(uo / "ir" / "input_derivable_gaps.yaml", {"gaps": [{"id": "KEY_A", "status": "open"}]})
    _write(uo / "ir" / "key_triage.yaml", {"keys": [{"id": "KEY_A"}]})
    _write(uo / "ir" / "input_derivable_patch.yaml", {"items": [{"id": "KEY_A"}]})
    issue_receipt(
        tmp_path,
        actor_type="producer",
        actor_id="uo-key-resolve",
        action_id="key_resolution",
        workflow_spec_hash=workflow_spec_hash("uo-init"),
        input_hashes={"a": "1"},
        output_hashes={"a": "1"},
        checker_result={"ok": True},
        nonce="res",
        _internal=True,
    )
    r = gate_key_resolve_receipt(tmp_path, uo)
    assert r["ok"] is True


def test_patch_file_alone_does_not_complete_resolution(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    uo = uo_root(tmp_path)
    _write(uo / "ir" / "input_derivable_gaps.yaml", {"gaps": [{"id": "KEY_A", "status": "open"}]})
    _write(uo / "ir" / "key_triage.yaml", {"keys": [{"id": "KEY_A"}]})
    _write(uo / "ir" / "input_derivable_patch.yaml", {"items": [{"id": "KEY_A"}]})
    r = gate_key_resolve_receipt(tmp_path, uo)
    assert r["ok"] is False


def test_uo_init_and_update_share_triage_resolution_order() -> None:
    init_pipe = phase_pipeline("uo-init", "resolve")
    upd_pipe = phase_pipeline("uo-update", "resolve")
    assert init_pipe[0] == "key_triage"
    assert init_pipe[1] == "key_resolution"
    assert upd_pipe[0] == "key_triage"
    assert upd_pipe[1] == "key_resolution"
    assert any(a["id"] == "key_triage" for a in actions_for_phase("uo-update", "resolve"))


def test_prepare_key_triage_injects_targets(tmp_path: Path) -> None:
    from ascendc_pilot.actions.runtime import prepare_action

    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    uo = uo_root(tmp_path)
    _write(uo / "ir" / "input_derivable_gaps.yaml", {"gaps": [{"id": "KEY_X", "status": "open"}]})
    prep = prepare_action(tmp_path, "key_triage")
    assert prep["ok"] is True, prep
    session = yaml.safe_load(
        (Path(prep["session_dir"]) / "session.yaml").read_text(encoding="utf-8")
    )
    assert session["dispatch_targets"]["target_ids"] == ["KEY_X"]
    assert "input_derivable_patch.yaml" in str(session["dispatch_targets"]["forbid_write"])


def test_prepare_key_resolution_uses_triage_targets(tmp_path: Path) -> None:
    from ascendc_pilot.actions.runtime import prepare_action

    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    uo = uo_root(tmp_path)
    _write(uo / "ir" / "input_derivable_gaps.yaml", {"gaps": [{"id": "KEY_A", "status": "open"}, {"id": "KEY_B", "status": "open"}]})
    _write(uo / "ir" / "key_triage.yaml", {"keys": [{"id": "KEY_A"}], "batches": [{"key_ids": ["KEY_A"]}]})
    issue_receipt(
        tmp_path,
        actor_type="producer",
        actor_id="uo-key-resolve",
        action_id="key_triage",
        workflow_spec_hash=workflow_spec_hash("uo-init"),
        input_hashes={"a": "1"},
        output_hashes={"a": "1"},
        checker_result={"ok": True},
        nonce="t",
        _internal=True,
    )
    prep = prepare_action(tmp_path, "key_resolution")
    assert prep["ok"] is True, prep
    session = yaml.safe_load(
        (Path(prep["session_dir"]) / "session.yaml").read_text(encoding="utf-8")
    )
    assert session["dispatch_targets"]["target_ids"] == ["KEY_A"]


def test_recommend_resolve_starts_at_triage(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    allowed = actions_for_phase("uo-init", "resolve")
    rec = recommend_next_action(tmp_path, workflow_id="uo-init", phase="resolve", allowed_actions=allowed)
    assert rec and rec["id"] == "key_triage"


def test_no_key_work_prepare_marks_not_applicable(tmp_path: Path) -> None:
    from ascendc_pilot.actions.runtime import prepare_action

    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="resolve", force_phase=True)
    prep = prepare_action(tmp_path, "key_triage")
    assert prep["ok"] is True, prep
    na = Path(prep["session_dir"]) / "not_applicable.yaml"
    assert na.is_file()
    data = yaml.safe_load(na.read_text(encoding="utf-8"))
    assert data["status"] == "not_applicable"
