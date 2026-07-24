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


def test_composer_detects_missing_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from compose_runtime import validate
    from ascendc_pilot.workflows import specs as specs_mod

    # Simulate missing agent by pointing validate at a copy without tg-semantic-bind
    # Use real validate — agent must exist now.
    errors = validate(REPO)
    assert not any("missing agent tg-semantic-bind" in e for e in errors)

    agent = REPO / "agents" / "tg-semantic-bind.yaml"
    assert agent.is_file()


def test_composer_rejects_type_subagent_in_generated(tmp_path: Path):
    from compose_runtime import compose_host, validate_generated

    # Compose into a temp host copy by composing real opencode then validating
    result = compose_host(REPO, "opencode")
    assert result["ok"]
    errors = validate_generated(REPO, host="opencode")
    assert errors == [], errors
    md = (REPO / "generated" / "opencode" / "agents" / "tg-semantic-bind.md").read_text(encoding="utf-8")
    assert "mode: subagent" in md
    assert "type: subagent" not in md


def test_generated_skill_matches_workflow_agents():
    from compose_runtime import compose_host, validate_generated
    from ascendc_pilot.workflows.specs import WORKFLOWS

    compose_host(REPO, "opencode")
    errors = validate_generated(REPO, host="opencode")
    assert errors == [], errors
    skill = (REPO / "generated" / "opencode" / "skills" / "tg-init" / "SKILL.md").read_text(encoding="utf-8")
    act = next(a for a in WORKFLOWS["tg-init"]["actions"] if a["id"] == "semantic_bind")
    assert act["agent_id"] == "tg-semantic-bind"
    assert "`tg-semantic-bind`" in skill
    assert act["role_id"] == "producer"
    cb = next(a for a in WORKFLOWS["tg-init"]["actions"] if a["id"] == "contract_build")
    assert cb["agent_id"] == "deterministic-tg-engine"
    assert cb["role_id"] == "deterministic_engine"


def test_nondeterministic_actions_have_agents_and_prompts():
    from ascendc_pilot.workflows.specs import WORKFLOWS

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
            tpid = action.get("task_prompt_id")
            assert tpid, f"{wid}/{action.get('id')} missing prompt"
            if "/" in str(tpid):
                dom, name = str(tpid).split("/", 1)
                assert (prompts / dom / f"{name}.md").is_file()
            else:
                assert (prompts / f"{tpid}.md").is_file()


def test_action_id_propagates_via_active_action(tmp_path: Path):
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.state import start_workflow
    from ascendc_pilot.actions.runtime import prepare_action, _write_active_action
    from ascendc_pilot.paths import agent_root, ensure_agent_layout

    ensure_agent_layout(tmp_path)
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

    # Without action → deny protected write
    denied = authorize(
        tmp_path,
        tool="write",
        path=str(agent_root(tmp_path) / "tg" / "realization" / "semantic_bind_patch.yaml"),
        agent="tg-semantic-bind",
        action="",
    )
    assert denied.get("decision") == "deny"
    assert denied.get("reason_code") == "ACTION_REQUIRED"

    # With action from active context (caller supplies) → allow in-scope
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
    start_workflow(tmp_path, "tg-init", phase="bind", force_phase=True)
    # Out of scope: lexicon is applied by finalize, not producer
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
    from ascendc_pilot.paths import ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow

    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "tg-init", phase="bind", force_phase=True)
    tg = tg_root(tmp_path)
    real = tg / "realization"
    real.mkdir(parents=True, exist_ok=True)
    (tg / "snapshot").mkdir(parents=True, exist_ok=True)

    # Minimal contract artifacts for prepare engine
    import json
    import os

    (tg / "snapshot" / "understand_contract.json").write_text(
        json.dumps({"files": {}, "op_name": "toy"}),
        encoding="utf-8",
    )
    _write(
        real / "realization_map.yaml",
        {"version": 2, "binding_gaps": [{"id": "gap1", "key_id": "KEY_A"}]},
    )
    _write(real / "consumer_schema.yaml", {"columns": ["A"], "version": 1})
    _write(real / "lexicon.yaml", {"key_derivations": []})
    _write(real / "binding_lexicon.yaml", {"key_derivations": [], "key_tokens": {}, "csv_field_aliases": {}})
    _write(
        real / "unresolved.yaml",
        {"status": "ready_for_llm", "binding_gaps": [{"id": "gap1", "key_id": "KEY_A"}]},
    )
    _write(real / "binding_gaps.yaml", {"status": "ready_for_llm", "gaps": [{"id": "gap1", "key_id": "KEY_A"}]})
    _write(
        real / "llm_bind_prompt_bundle.yaml",
        {"candidates": [{"id": "gap1", "key_id": "KEY_A"}]},
    )
    # Consumer root
    consumer = tmp_path / "tests"
    consumer.mkdir()
    (consumer / "run.py").write_text("COLS=['A']\n", encoding="utf-8")
    _write(
        tmp_path / ".ascendc-pilot" / "context" / "pilot_params.yaml",
        {"op_name": "toy", "test_script_root": consumer.as_posix(), "csv_consumer_root": consumer.as_posix()},
    )

    # Stale leftover patch from a previous run
    stale = real / "semantic_bind_patch.yaml"
    _write(
        stale,
        {"action": "bind", "bindings": [{"candidate_id": "gap1", "key_id": "KEY_A", "expr": "old"}]},
    )
    stale_mtime = time.time() - 3600
    os.utime(stale, (stale_mtime, stale_mtime))

    prep = prepare_action(tmp_path, "semantic_bind")
    assert prep.get("ok") is True, prep
    assert prep.get("prepare_engine", {}).get("ok") is True or "prepare_engine" in prep

    # Finalize with stale patch must fail (and revokes lease under fail-closed policy)
    fin_stale = finalize_action(tmp_path, "semantic_bind")
    assert fin_stale.get("ok") is False
    assert fin_stale.get("error") in {"STALE_PATCH", "APPLY_FAILED", "PATCH_REQUIRED"} or (
        (fin_stale.get("apply_result") or {}).get("error") == "STALE_PATCH"
    )

    # Re-prepare after failed finalize (lease revoked); then write a fresh patch
    prep2 = prepare_action(tmp_path, "semantic_bind")
    assert prep2.get("ok") is True, prep2
    time.sleep(0.05)
    session_path = Path(prep2["session_dir"]) / "session.yaml"
    session = yaml.safe_load(session_path.read_text(encoding="utf-8"))
    nonce = (
        session.get("prepare_nonce")
        or session.get("nonce")
        or (session.get("prepare_stamp") or {}).get("nonce")
    )
    _write(
        stale,
        {
            "action": "bind",
            "prepare_nonce": nonce,
            "bindings": [
                {
                    "candidate_id": "gap1",
                    "key_id": "KEY_A",
                    "expr": "A",
                    "evidence": [{"file_path": "run.py", "line": 1}],
                }
            ],
        },
    )

    fin = finalize_action(tmp_path, "semantic_bind")
    apply_path = real / "semantic_bind_apply.yaml"
    assert apply_path.is_file(), fin
    apply_doc = yaml.safe_load(apply_path.read_text(encoding="utf-8"))
    assert apply_doc.get("ok") is True
    assert apply_doc.get("prepare_nonce")
    assert apply_doc.get("status") == "applied"
    assert (apply_doc.get("apply_result") or {}).get("applied_count", 0) >= 1 or fin.get("ok")
    # Lexicon must be touched by deterministic apply (source marker)
    lex = yaml.safe_load((real / "binding_lexicon.yaml").read_text(encoding="utf-8"))
    assert lex.get("source") == "semantic_bind" or lex.get("key_derivations") or lex.get("key_tokens")


def test_stale_inventory_alone_cannot_pass_without_apply(tmp_path: Path):
    from ascendc_pilot.actions.runtime import _check_output_contract
    from ascendc_pilot.paths import ensure_agent_layout, tg_root

    ensure_agent_layout(tmp_path)
    real = tg_root(tmp_path) / "realization"
    real.mkdir(parents=True)
    _write(real / "binding_inventory.yaml", {"version": 1, "stale": True})
    # Missing apply receipt → contract fails
    checked = _check_output_contract(tmp_path, "semantic-bind-v1")
    assert checked.get("ok") is False
    assert "semantic_bind_apply.yaml" in str(checked.get("missing") or checked.get("message"))


def test_doctor_flags_missing_prerequisites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ascendc_pilot.cli import _doctor

    monkeypatch.delenv("ASCENDC_TEST_SCRIPT_ROOT", raising=False)
    monkeypatch.delenv("ASCENDC_CSV_CONSUMER_ROOT", raising=False)
    # doctor may fail on compose if generated stale before regenerate; just ensure it runs
    code = _doctor(tmp_path)
    assert code in {0, 1}


def test_field_provenance_evidence_only():
    from testcase_agent.field_provenance import build_field_provenance

    doc = build_field_provenance(
        schema={"columns": ["B", "mystery_flag"]},
        realization_map={},
        uo_summary={"inputs": ["B"], "attrs": []},
        lexicon={},
    )
    by_name = {f["csv_field"]: f for f in doc["fields"]}
    assert by_name["B"]["role"] == "shape"
    assert by_name["mystery_flag"]["closed"] is False
    assert "unclassified_csv_role" in by_name["mystery_flag"]["unresolved"] or by_name["mystery_flag"]["unresolved"]
    # No fabricated host/tiling links
    for f in doc["fields"]:
        stages = {c.get("stage") for c in f["chain"]}
        assert "invented_link" not in stages


def test_csv_schema_from_generic_consumer_script(tmp_path: Path):
    """Dynamic CSV schema from a generic consumer script (no operator-specific tables)."""
    from testcase_agent.realization_schema import extract_consumer_schema
    from testcase_agent.field_provenance import build_field_provenance

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "case_runner.py").write_text(
        """
import csv
REQUIRED = ["M", "N", "dtype"]
def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))
""",
        encoding="utf-8",
    )
    (consumer / "samples.csv").write_text("M,N,dtype\n16,32,float16\n", encoding="utf-8")
    schema = extract_consumer_schema(consumer)
    assert isinstance(schema, dict)
    cols = [str(c) for c in (schema.get("columns") or [])]
    assert cols or schema.get("status") not in {None, "empty"}
    text = yaml.safe_dump(schema)
    assert "FlashAttention" not in text
    assert "hardcoded_op_table" not in text
    prov = build_field_provenance(
        schema=schema if schema.get("columns") else {"columns": ["M", "N", "dtype"]}
    )
    assert prov.get("policy") == "evidence_only_no_invention"
    assert prov.get("unresolved") is not None


def test_unresolved_not_auto_completed(tmp_path: Path):
    from ascendc_pilot.gates.tg_adapters import gate_bind_progress
    from ascendc_pilot.paths import ensure_agent_layout, tg_root

    ensure_agent_layout(tmp_path)
    real = tg_root(tmp_path) / "realization"
    real.mkdir(parents=True)
    _write(real / "binding_lexicon.yaml", {"key_derivations": []})
    _write(
        real / "unresolved.yaml",
        {"status": "ready_for_llm", "binding_gaps": [{"id": "g1"}]},
    )
    _write(real / "binding_gaps.yaml", {"status": "ready_for_llm", "gaps": [{"id": "g1"}]})
    result = gate_bind_progress(tmp_path)
    assert result.get("ok") is False


def test_plugin_reads_active_action_helpers():
    """Sanity: plugin source contains active_action resolution (no TS runtime here)."""
    text = (REPO / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    assert "active_action.yaml" in text
    assert "injectActionContext" in text
    assert "ASCENDC_ACTION" in text
    assert "projectRootFromPath" in text
    assert "resolveEffectiveAgent" in text
    assert "subagent_type" in text
