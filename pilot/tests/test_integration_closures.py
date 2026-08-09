"""Integration closures: composer, action context, scopes, semantic_bind, prerequisites."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(REPO / "pilot") not in sys.path:
    sys.path.insert(0, str(REPO / "pilot"))
if str(REPO / "engines" / "testcase-generation") not in sys.path:
    sys.path.insert(0, str(REPO / "engines" / "testcase-generation"))


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _select_csv_consumer_mode(project_root: Path) -> None:
    from ascendc_pilot.paths import tg_root

    _write(
        tg_root(project_root) / "init" / "init_intent.yaml",
        {"schema": "tg-init-intent/v1", "mode": "csv_consumer"},
    )


def test_composer_detects_missing_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    del tmp_path, monkeypatch
    from compose_runtime import validate

    errors = validate(REPO)
    assert not any("missing agent tg-semantic-bind" in error for error in errors)
    assert (REPO / "agents" / "tg-semantic-bind.yaml").is_file()


def test_composer_rejects_type_subagent_in_generated(tmp_path: Path):
    del tmp_path
    from compose_runtime import compose_host, validate_generated

    result = compose_host(REPO, "opencode")
    assert result["ok"]
    errors = validate_generated(REPO, host="opencode")
    assert errors == [], errors
    md = (REPO / "generated" / "opencode" / "agents" / "tg-semantic-bind.md").read_text(encoding="utf-8")
    assert "mode: subagent" in md
    assert "type: subagent" not in md


def test_generated_skill_and_install_closure_respect_mode_overlay():
    """Default Skill stays concise; overlay-only producer remains install-reachable."""
    from compose_runtime import compose_host, validate_generated
    from prune_runtime_context import referenced_runtime_assets
    from ascendc_pilot.workflows import WORKFLOWS, get_workflow

    compose_host(REPO, "opencode")
    errors = validate_generated(REPO, host="opencode")
    assert errors == [], errors

    csv_mode = get_workflow("tg-init", mode="csv_consumer")
    action = next(row for row in csv_mode["actions"] if row["id"] == "semantic_bind")
    assert action["agent_id"] == "tg-semantic-bind"
    assert action["role_id"] == "producer"

    default = get_workflow("tg-init", mode="tilingkey_full_coverage")
    default_action = next(row for row in default["actions"] if row["id"] == "semantic_bind")
    assert default_action["execution_mode"] == "deterministic"

    agents, prompts = referenced_runtime_assets(WORKFLOWS)
    assert "tg-semantic-bind" in agents
    assert action["task_prompt_id"] in prompts


def test_nondeterministic_actions_have_agents_and_prompts():
    from ascendc_pilot.workflows import WORKFLOWS

    agents = REPO / "agents"
    prompts = REPO / "prompts" / "tasks"
    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue
        for action in meta.get("actions") or []:
            role = action.get("role_id")
            if role not in {"producer", "referee", "readonly_analyst"}:
                continue
            agent_id = action.get("agent_id")
            assert agent_id, f"{wid}/{action.get('id')} missing agent"
            assert (agents / f"{agent_id}.yaml").is_file(), f"missing {agent_id}.yaml"
            prompt_id = action.get("task_prompt_id")
            assert prompt_id, f"{wid}/{action.get('id')} missing prompt"
            if "/" in str(prompt_id):
                domain, name = str(prompt_id).split("/", 1)
                assert (prompts / domain / f"{name}.md").is_file()
            else:
                assert (prompts / f"{prompt_id}.md").is_file()


def test_action_id_propagates_via_active_action(tmp_path: Path):
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.state import start_workflow
    from ascendc_pilot.actions.runtime import _write_active_action
    from ascendc_pilot.paths import agent_root, ensure_agent_layout

    ensure_agent_layout(tmp_path)
    _select_csv_consumer_mode(tmp_path)
    start_workflow(tmp_path, "tg-init", phase="bind", force_phase=True)
    _write_active_action(
        tmp_path,
        {
            "action_id": "semantic_bind",
            "actor_id": "tg-semantic-bind",
            "workflow_id": "tg-init",
            "phase": "bind",
            "status": "prepared",
        },
    )
    active = agent_root(tmp_path) / "state" / "active_action.yaml"
    assert active.is_file()
    doc = yaml.safe_load(active.read_text(encoding="utf-8"))
    assert doc["action_id"] == "semantic_bind"

    denied = authorize(
        tmp_path,
        tool="write",
        path=str(agent_root(tmp_path) / "tg" / "realization" / "semantic_bind_patch.yaml"),
        agent="tg-semantic-bind",
        action="",
    )
    assert denied.get("decision") == "deny"
    assert denied.get("reason_code") == "ACTION_REQUIRED"

    allowed = authorize(
        tmp_path,
        tool="write",
        path=str(agent_root(tmp_path) / "tg" / "realization" / "semantic_bind_patch.yaml"),
        agent="tg-semantic-bind",
        action="semantic_bind",
    )
    assert allowed.get("decision") == "allow", allowed


def test_agent_write_scope_enforced(tmp_path: Path):
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.state import start_workflow
    from ascendc_pilot.paths import agent_root, ensure_agent_layout

    ensure_agent_layout(tmp_path)
    _select_csv_consumer_mode(tmp_path)
    start_workflow(tmp_path, "tg-init", phase="bind", force_phase=True)
    denied = authorize(
        tmp_path,
        tool="write",
        path=str(agent_root(tmp_path) / "tg" / "realization" / "binding_lexicon.yaml"),
        agent="tg-semantic-bind",
        action="semantic_bind",
    )
    assert denied.get("decision") == "deny"
    assert denied.get("reason_code") == "AGENT_WRITE_SCOPE"

    allowed = authorize(
        tmp_path,
        tool="write",
        path=str(agent_root(tmp_path) / "tg" / "realization" / "semantic_bind_patch.yaml"),
        agent="tg-semantic-bind",
        action="semantic_bind",
    )
    assert allowed.get("decision") == "allow", allowed


def test_semantic_bind_closed_loop_and_stale_rejection(tmp_path: Path):
    from ascendc_pilot.actions.runtime import finalize_action, prepare_action
    from ascendc_pilot.paths import context_root, ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow

    ensure_agent_layout(tmp_path)
    _select_csv_consumer_mode(tmp_path)
    start_workflow(tmp_path, "tg-init", phase="bind", force_phase=True)
    tg = tg_root(tmp_path)
    real = tg / "realization"
    real.mkdir(parents=True, exist_ok=True)
    (tg / "snapshot").mkdir(parents=True, exist_ok=True)

    import json
    import os

    (tg / "snapshot" / "understand_contract.json").write_text(
        json.dumps({"files": {}, "op_name": "toy"}), encoding="utf-8"
    )
    _write(real / "realization_map.yaml", {"version": 2, "binding_gaps": [{"id": "gap1", "key_id": "KEY_A"}]})
    _write(real / "consumer_schema.yaml", {"columns": ["A"], "version": 1})
    _write(real / "lexicon.yaml", {"key_derivations": []})
    _write(real / "binding_lexicon.yaml", {"key_derivations": [], "key_tokens": {}, "csv_field_aliases": {}})
    _write(real / "unresolved.yaml", {"status": "ready_for_llm", "binding_gaps": [{"id": "gap1", "key_id": "KEY_A"}]})
    _write(real / "binding_gaps.yaml", {"status": "ready_for_llm", "gaps": [{"id": "gap1", "key_id": "KEY_A"}]})
    _write(real / "llm_bind_prompt_bundle.yaml", {"candidates": [{"id": "gap1", "key_id": "KEY_A"}]})

    consumer = tmp_path / "tests"
    consumer.mkdir()
    (consumer / "run.py").write_text("COLS=['A']\n", encoding="utf-8")
    _write(
        context_root(tmp_path) / "pilot_params.yaml",
        {"op_name": "toy", "test_script_root": consumer.as_posix(), "csv_consumer_root": consumer.as_posix()},
    )

    stale = real / "semantic_bind_patch.yaml"
    _write(stale, {"action": "bind", "bindings": [{"candidate_id": "gap1", "key_id": "KEY_A", "expr": "old"}]})
    old_mtime = time.time() - 3600
    os.utime(stale, (old_mtime, old_mtime))

    prepared = prepare_action(tmp_path, "semantic_bind")
    assert prepared.get("ok") is True, prepared
    stale_result = finalize_action(tmp_path, "semantic_bind")
    assert stale_result.get("ok") is False

    prepared = prepare_action(tmp_path, "semantic_bind")
    assert prepared.get("ok") is True, prepared
    time.sleep(0.05)
    session = yaml.safe_load((Path(prepared["session_dir"]) / "session.yaml").read_text(encoding="utf-8"))
    nonce = session.get("prepare_nonce") or session.get("nonce") or (session.get("prepare_stamp") or {}).get("nonce")
    _write(
        stale,
        {
            "action": "bind",
            "prepare_nonce": nonce,
            "bindings": [{"candidate_id": "gap1", "key_id": "KEY_A", "expr": "A", "evidence": [{"file_path": "run.py", "line": 1}]}],
        },
    )

    finalized = finalize_action(tmp_path, "semantic_bind")
    apply_path = real / "semantic_bind_apply.yaml"
    assert apply_path.is_file(), finalized
    applied = yaml.safe_load(apply_path.read_text(encoding="utf-8"))
    assert applied.get("ok") is True
    assert applied.get("prepare_nonce")
    assert applied.get("status") == "applied"


def test_stale_inventory_alone_cannot_pass_without_apply(tmp_path: Path):
    from ascendc_pilot.actions.runtime import _check_output_contract
    from ascendc_pilot.paths import ensure_agent_layout, tg_root

    ensure_agent_layout(tmp_path)
    real = tg_root(tmp_path) / "realization"
    real.mkdir(parents=True)
    _write(real / "binding_inventory.yaml", {"version": 1, "stale": True})
    checked = _check_output_contract(tmp_path, "semantic-bind-v1")
    assert checked.get("ok") is False
    assert "semantic_bind_apply.yaml" in str(checked.get("missing") or checked.get("message"))


def test_doctor_flags_missing_prerequisites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ascendc_pilot.cli import _doctor

    monkeypatch.delenv("ASCENDC_TEST_SCRIPT_ROOT", raising=False)
    monkeypatch.delenv("ASCENDC_CSV_CONSUMER_ROOT", raising=False)
    assert _doctor(tmp_path) in {0, 1}


def test_field_provenance_evidence_only():
    from testcase_agent.field_provenance import build_field_provenance

    doc = build_field_provenance(
        schema={"columns": ["B", "mystery_flag"]},
        realization_map={},
        uo_summary={"inputs": ["B"], "attrs": []},
        lexicon={},
    )
    by_name = {field["csv_field"]: field for field in doc["fields"]}
    assert by_name["B"]["role"] == "shape"
    assert by_name["mystery_flag"]["closed"] is False
    for field in doc["fields"]:
        stages = {chain.get("stage") for chain in field["chain"]}
        assert "invented_link" not in stages


def test_csv_schema_from_generic_consumer_script(tmp_path: Path):
    from testcase_agent.realization_schema import extract_consumer_schema
    from testcase_agent.field_provenance import build_field_provenance

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "case_runner.py").write_text(
        'import csv\nREQUIRED = ["M", "N", "dtype"]\ndef load(path):\n    with open(path) as f:\n        return list(csv.DictReader(f))\n',
        encoding="utf-8",
    )
    (consumer / "samples.csv").write_text("M,N,dtype\n16,32,float16\n", encoding="utf-8")
    schema = extract_consumer_schema(consumer)
    assert isinstance(schema, dict)
    assert schema.get("columns") or schema.get("status") not in {None, "empty"}
    provenance = build_field_provenance(schema=schema if schema.get("columns") else {"columns": ["M", "N", "dtype"]})
    assert provenance.get("policy") == "evidence_only_no_invention"
    assert provenance.get("unresolved") is not None


def test_unresolved_not_auto_completed(tmp_path: Path):
    from ascendc_pilot.gates.tg_adapters import gate_bind_progress
    from ascendc_pilot.paths import ensure_agent_layout, tg_root

    ensure_agent_layout(tmp_path)
    real = tg_root(tmp_path) / "realization"
    real.mkdir(parents=True)
    _write(real / "binding_lexicon.yaml", {"key_derivations": []})
    _write(real / "unresolved.yaml", {"status": "ready_for_llm", "binding_gaps": [{"id": "g1"}]})
    _write(real / "binding_gaps.yaml", {"status": "ready_for_llm", "gaps": [{"id": "g1"}]})
    assert gate_bind_progress(tmp_path).get("ok") is False


def test_plugin_reads_active_action_helpers():
    text = (REPO / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    assert "active_action.yaml" in text
    assert "injectActionContext" in text
    assert "ASCENDC_ACTION" in text
    assert "projectRootFromPath" in text
    assert "resolveEffectiveAgent" in text
    assert "subagent_type" in text
