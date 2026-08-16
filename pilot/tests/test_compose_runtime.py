"""Composer / runtime-context validation tests."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(REPO / "pilot") not in sys.path:
    sys.path.insert(0, str(REPO / "pilot"))


def test_compose_validate_clean():
    from compose_runtime import validate

    errors = validate(REPO)
    assert errors == [], errors


def test_execution_contract_audit_clean():
    from check_execution_contracts import audit

    errors = audit(REPO)
    assert errors == [], errors


def test_uo_actions_match_engine_and_prompt_boundary():
    from ascendc_pilot.workflows import WORKFLOWS

    actions = {a["id"]: a for a in WORKFLOWS["uo-init"]["actions"]}

    prepare = actions["prepare"]
    assert prepare["execution_mode"] == "deterministic"
    assert prepare["agent_id"] == "deterministic-uo-engine"
    assert not prepare.get("task_prompt_id")
    assert prepare.get("actors") == ["deterministic-uo-engine"]

    assert "resolve" not in actions
    assert "apply_gap_patch" not in actions
    assert "review" not in actions
    assert set(actions) == {"prepare", "extract", "analyze", "commit", "verify"}

    for action_id in ("prepare", "extract", "analyze", "commit", "verify"):
        action = actions[action_id]
        assert action["execution_mode"] == "deterministic"
        assert action["agent_id"] == "deterministic-uo-engine"
        assert not action.get("task_prompt_id")
        assert action.get("actors") == ["deterministic-uo-engine"]

    for action in WORKFLOWS["uo-update"]["actions"]:
        assert action["execution_mode"] == "deterministic"
        assert action["agent_id"] == "deterministic-uo-engine"
        assert action.get("actors") == ["deterministic-uo-engine"]
        assert not action.get("task_prompt_id")

    query = next(a for a in WORKFLOWS["uo-query"]["actions"] if a["id"] == "kb_lookup")
    assert query["task_prompt_id"] == "uo/codemap-query"
    assert WORKFLOWS["uo-query"].get("host_driver") is False

    investigate = {a["id"]: a for a in WORKFLOWS["uo-investigate"]["actions"]}
    inv = investigate["investigate"]
    assert inv["execution_mode"] == "subagent"
    assert inv["agent_id"] == "uo-gap-investigator"
    assert inv["task_prompt_id"] == "uo/investigate-gaps"


def test_tg_and_ce_execution_bindings_are_explicit():
    from ascendc_pilot.workflows import WORKFLOWS

    for workflow_id in ("tg-init", "tg-plan", "tg-solve"):
        for action in WORKFLOWS[workflow_id]["actions"]:
            if action["execution_mode"] == "deterministic":
                assert action["agent_id"] == "deterministic-tg-engine"
                assert action["actors"] == ["deterministic-tg-engine"]
                assert not action.get("task_prompt_id")

    ce = next(a for a in WORKFLOWS["ce-review"]["actions"] if a["id"] == "code_review")
    assert ce["execution_mode"] == "subagent"
    assert ce["agent_id"] == "ce-reviewer"
    assert ce["actors"] == ["ce-reviewer"]
    assert ce["task_prompt_id"] == "ce/standalone-review"
    verify = next(a for a in WORKFLOWS["ce-verify"]["actions"] if a["id"] == "code_review")
    assert verify["task_prompt_id"] == "ce/code-review"

    intent = WORKFLOWS["ce-intent"]
    assert intent["cognitive_skill_id"] == "code-engineering"
    assert WORKFLOWS["ce-impact"]["cognitive_skill_id"] == "code-engineering"
    assert WORKFLOWS["ce-verify"]["cognitive_skill_id"] == "code-engineering"
    assert WORKFLOWS["ce-review"]["cognitive_skill_id"] == "code-review"
    assert "code-edit" not in WORKFLOWS
    assert "git-ops" not in WORKFLOWS
    assert "perf-analyze" not in WORKFLOWS
    assert intent["phases"] == [
        "intent",
        "kb_ready",
        "decompose",
        "review",
        "locate",
        "confirm",
    ]


def test_compose_and_prune_runtime_context(tmp_path: Path):
    from compose_runtime import compose_host
    from prune_runtime_context import prune

    out = tmp_path / "opencode"
    result = compose_host(REPO, "opencode", out_root=out)
    assert result["ok"]

    # prune() works on generated/<host>; mirror the temporary compose there so
    # the test does not mutate committed/generated state.
    generated = REPO / "generated" / "_test_prune"
    if generated.exists():
        import shutil

        shutil.rmtree(generated)
    import shutil

    shutil.copytree(out, generated)
    try:
        pruned = prune(REPO, "_test_prune")
        assert pruned["ok"], pruned
        agents = generated / "agents"
        prompts = generated / "prompts" / "tasks" / "uo"
        assert not (agents / "deterministic-uo-engine.md").exists()
        assert not (agents / "deterministic-tg-engine.md").exists()
        assert (agents / "uo-gap-investigator.md").is_file()
        assert (agents / "uo-query.md").is_file()
        assert (prompts / "codemap-query.md").is_file()
        assert (prompts / "investigate-gaps.md").is_file()
        assert not (prompts / "kb-review.md").exists()
        assert not (prompts / "kb-lookup.md").exists()

        init_skill = (generated / "skills" / "uo-init" / "SKILL.md").read_text(encoding="utf-8")
        assert "| `extract` | `deterministic` | `engine` |" in init_skill
        assert "| `verify` | `deterministic` | `engine` |" in init_skill
        assert "deterministic-uo-engine" not in init_skill
        assert "| `resolve` |" not in init_skill

        tg_skill = (generated / "skills" / "tg-solve" / "SKILL.md").read_text(encoding="utf-8")
        assert "| `solve_precheck` | `deterministic` | `engine` |" in tg_skill
        assert "deterministic-tg-engine" not in tg_skill
        pilot_agent = (generated / "agents" / "ascendc-pilot.md").read_text(encoding="utf-8")
        uo_query_agent = (generated / "agents" / "uo-query.md").read_text(encoding="utf-8")
        assert "Select-Object *" in pilot_agent
        assert "grep: deny" in uo_query_agent
        assert "external_directory: allow" in pilot_agent
        assert "external_directory: allow" in uo_query_agent
        assert "read: allow" in pilot_agent
        assert "read: allow" in uo_query_agent
        assert "task: allow" in pilot_agent
        assert "skill: false" in uo_query_agent
        assert "grep: false" in uo_query_agent
        assert "There is no session `prompt.md`" in uo_query_agent
        assert "acp uo-query --project" in uo_query_agent
        assert "Do not switch to MCP" in uo_query_agent
        from compose_runtime import validate_generated

        errors = validate_generated(REPO, host="_test_prune")
        assert errors == [], errors
    finally:
        shutil.rmtree(generated, ignore_errors=True)


def test_native_opencode_commands_are_generated(tmp_path: Path):
    from compose_opencode_commands import compose

    result = compose(tmp_path)
    assert result["ok"]
    commands = tmp_path / "generated" / "opencode" / "commands"
    for name in (
        "uo-init",
        "uo-update",
        "uo-query",
        "uo-investigate",
        "tg-init",
        "tg-plan",
        "tg-solve",
        "ce-review",
        "ce-impact",
        "ce-intent",
        "ce-verify",
    ):
        path = commands / f"{name}.md"
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8")
        assert "agent: ascendc-pilot" in text
        assert "subtask: false" in text
        if name == "uo-query":
            assert "pilot_run" in text
            assert "不要 `pilot_run`" in text
            assert "先对人说出路由" in text
            assert "acp run-action auto" not in text
        else:
            assert "acp run-action auto" in text


def test_cognitive_skill_ids_include_code_engineering():
    from compose_runtime import COGNITIVE_SKILL_IDS, _host_remap_skill_paths

    assert "code-engineering" in COGNITIVE_SKILL_IDS
    remapped = _host_remap_skill_paths(
        "method:skills/code-engineering/** and `skills/code-engineering`",
        host="opencode",
    )
    assert remapped == (
        "method:cognitive-skills/code-engineering/** and `cognitive-skills/code-engineering`"
    )
