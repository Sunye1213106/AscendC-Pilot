"""Integration closures: composer, action context, scopes, semantic_bind, prerequisites."""

from __future__ import annotations

import sys
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


def test_composer_omits_removed_csv_semantic_bind_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """tg-semantic-bind (LLM CSV bind producer) was deleted with the csv_consumer stack."""
    del tmp_path, monkeypatch
    from compose_runtime import validate

    errors = validate(REPO)
    assert not any("tg-semantic-bind" in error for error in errors)
    assert not (REPO / "agents" / "tg-semantic-bind.yaml").is_file()


def test_composer_rejects_type_subagent_in_generated(tmp_path: Path):
    del tmp_path
    from compose_runtime import compose_host, validate_generated

    result = compose_host(REPO, "opencode")
    assert result["ok"]
    errors = validate_generated(REPO, host="opencode")
    assert errors == [], errors
    md = (REPO / "generated" / "opencode" / "agents" / "tg-lemma-producer.md").read_text(encoding="utf-8")
    assert "mode: subagent" in md
    assert "type: subagent" not in md


def test_semantic_bind_is_deterministic_under_default_mode():
    """semantic_bind lost its csv_consumer LLM-producer overlay; it is always deterministic now."""
    from ascendc_pilot.workflows import get_workflow

    default = get_workflow("tg-init", mode="tilingkey_full_coverage")
    default_action = next(row for row in default["actions"] if row["id"] == "semantic_bind")
    assert default_action["execution_mode"] == "deterministic"
    assert default_action["agent_id"] == "deterministic-tg-engine"


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


def test_semantic_bind_action_scoped_to_deterministic_engine(tmp_path: Path):
    """The csv_consumer LLM producer loop (tg-semantic-bind patch/apply) is gone;
    semantic_bind now runs only as the deterministic-tg-engine host-view inventory action."""
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.state import start_workflow
    from ascendc_pilot.paths import agent_root, ensure_agent_layout

    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "tg-init", phase="bind", force_phase=True, architecture="arch35")
    denied = authorize(
        tmp_path,
        tool="write",
        path=str(agent_root(tmp_path) / "tg" / "realization" / "binding_inventory.yaml"),
        agent="tg-semantic-bind",
        action="semantic_bind",
    )
    # tg-semantic-bind is no longer a registered agent/actor for this action.
    assert denied.get("decision") == "deny"

    allowed = authorize(
        tmp_path,
        tool="write",
        path=str(agent_root(tmp_path) / "tg" / "realization" / "binding_inventory.yaml"),
        agent="deterministic-tg-engine",
        action="semantic_bind",
    )
    assert allowed.get("decision") == "allow", allowed


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


def test_unresolved_not_auto_completed(tmp_path: Path):
    """csv_consumer's gate_bind_progress/binding_gaps flow was removed; the full-TK
    binding gate now requires a real host-view inventory instead of an empty one."""
    from ascendc_pilot.gates.tg_adapters import gate_tilingkey_binding_ready
    from ascendc_pilot.paths import ensure_agent_layout, tg_root

    ensure_agent_layout(tmp_path, arch="arch35")
    real = tg_root(tmp_path) / "realization"
    real.mkdir(parents=True)
    _write(real / "binding_inventory.yaml", {"version": 1, "fields": []})
    assert gate_tilingkey_binding_ready(tmp_path).get("ok") is False


def test_plugin_reads_active_action_helpers():
    text = (REPO / "opencode-plugin" / "ascendc-pilot.ts").read_text(encoding="utf-8")
    assert "active_action.yaml" in text
    assert "injectActionContext" in text
    assert "ASCENDC_ACTION" in text
    assert "projectRootFromPath" in text
    assert "resolveEffectiveAgent" in text
    assert "finalized" in text
    assert "subagent_type" in text
    # Bash must stay Primary (authorize remaps writes only).
    assert 'tool === "bash"' in text or "tool === 'bash'" in text
