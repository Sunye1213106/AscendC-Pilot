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
    assert set(actions) == {
        "prepare",
        "propose_include_heal",
        "heal_promote",
        "extract",
        "analyze",
        "commit",
        "verify",
    }

    for action_id in ("prepare", "extract", "analyze", "commit", "verify", "heal_promote"):
        action = actions[action_id]
        assert action["execution_mode"] == "deterministic"
        assert action["agent_id"] == "deterministic-uo-engine"
        assert not action.get("task_prompt_id")
        assert action.get("actors") == ["deterministic-uo-engine"]

    propose = actions["propose_include_heal"]
    assert propose["execution_mode"] == "subagent"
    assert propose["agent_id"] == "uo-heal-analyst"
    assert propose["task_prompt_id"] == "uo/propose-include-heal"
    assert propose.get("output_mode") == "staged"
    assert propose.get("merge_action_id") == "heal_promote"

    for action in WORKFLOWS["uo-update"]["actions"]:
        assert action["execution_mode"] == "deterministic"
        assert action["agent_id"] == "deterministic-uo-engine"
        assert action.get("actors") == ["deterministic-uo-engine"]
        assert not action.get("task_prompt_id")

    query = next(a for a in WORKFLOWS["uo-query"]["actions"] if a["id"] == "kb_lookup")
    assert query["task_prompt_id"] == "uo/codemap-query"
    assert query.get("execution_variant") == "delegated_query"
    assert WORKFLOWS["uo-query"].get("host_driver") is False
    assert "execution_variants" not in WORKFLOWS["uo-query"]

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
    assert ce["action_method_id"] == "code-review/standalone-review"
    assert "ce-verify" not in WORKFLOWS
    assert "ce-intent" not in WORKFLOWS
    assert "ce-impact" not in WORKFLOWS
    assert "ce-handoff" not in WORKFLOWS

    plan = WORKFLOWS["ce-plan"]
    assert plan["cognitive_skill_id"] == "code-engineering"
    assert plan["slash"] == "/ce-plan"
    assert plan["phases"] == ["kb_ready", "grill", "draft", "confirm"]
    assert WORKFLOWS["ce-review"]["cognitive_skill_id"] == "code-review"
    assert "code-edit" not in WORKFLOWS
    assert "git-ops" not in WORKFLOWS
    assert "perf-analyze" not in WORKFLOWS
    assert WORKFLOWS["ce-apply"]["cognitive_skill_id"] == "code-engineering"
    assert WORKFLOWS["handoff"]["cognitive_skill_id"] == "code-engineering"
    assert WORKFLOWS["ce-apply"]["slash"] == "/ce-apply"
    assert WORKFLOWS["handoff"]["slash"] == "/handoff"


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
        assert (agents / "uo-heal-analyst.md").is_file()
        assert (agents / "uo-query.md").is_file()
        man_path = generated / "install-manifest.json"
        assert man_path.is_file(), "prune must write install-manifest.json"
        import json

        man = json.loads(man_path.read_text(encoding="utf-8"))
        assert man.get("owner") == "ascendc-pilot"
        assert "uo-query.md" in man.get("agents")
        assert "ascendc-pilot.md" in man.get("global_agents")
        assert "ce-helper.md" not in man.get("agents")
        assert "tg-playground.md" not in man.get("agents")
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
        assert "Get-ChildItem: allow" in pilot_agent
        assert "glob: allow" in pilot_agent
        assert "grep: deny" in uo_query_agent
        assert "external_directory: allow" in pilot_agent
        assert "external_directory: allow" in uo_query_agent
        assert "read: allow" in pilot_agent
        assert "read: allow" in uo_query_agent
        assert "uo-query: allow" in pilot_agent
        assert "ce-reviewer: allow" in pilot_agent
        assert "name: AscendC-Pilot" in pilot_agent
        assert "task: allow" not in pilot_agent
        fm = pilot_agent.split("---")[1]
        assert "pilot_run: allow" in fm
        assert "skill: allow" in fm
        assert "grep: allow" in fm
        assert "read: allow" in fm
        assert "glob: allow" in fm
        try:
            import yaml as _yaml
        except ImportError:
            _yaml = None
        if _yaml is not None:
            perm = _yaml.safe_load(fm)["permission"]
            assert "*" not in perm, perm
            assert perm["grep"] == "allow"
            assert perm["read"] == "allow"
            assert perm["glob"] == "allow"
            assert perm["list"] == "allow"
            assert perm["pilot_run"] == "allow"
        assert (generated / "agents" / "tg-analyst.md").exists()
        assert not (generated / "agents" / "tg-init-audit.md").exists()
        assert "Get-Command acp" not in pilot_agent
        assert "where acp" not in pilot_agent
        assert "主控当前会话 `acp uo-query`" not in pilot_agent
        assert "grep *" in fm
        assert "pilot_cli: allow" in fm
        if _yaml is not None:
            perm = _yaml.safe_load(fm)["permission"]
            assert perm.get("pilot_cli") == "allow"
            assert "acp" not in perm
        assert "skill: false" in uo_query_agent
        assert "grep: false" in uo_query_agent
        assert "There is no session `prompt.md`" not in uo_query_agent
        assert "If the Task stub names" in uo_query_agent
        assert "execution_variant = delegated_query" in uo_query_agent
        assert "edit: deny" in uo_query_agent
        assert "*: deny" in uo_query_agent or "'*': deny" in uo_query_agent
        assert "webfetch: deny" in uo_query_agent
        assert "task: deny" in uo_query_agent
        assert "glob: deny" in uo_query_agent
        tg_agent = (generated / "agents" / "tg-analyst.md").read_text(encoding="utf-8")
        assert "edit:" in tg_agent
        assert "host-runtime-contract" not in tg_agent.lower()
        assert "force_new" not in tg_agent
        assert "todo_sync" not in tg_agent
        assert "短问" not in tg_agent
        assert "深问" not in tg_agent
        assert "简单查询" not in tg_agent
        assert "复杂查询" not in tg_agent
        assert "查询方式说明" not in tg_agent
        assert "可见 LLM 路由" not in tg_agent
        tg_bytes = len(tg_agent.encode("utf-8"))
        tg_lines = tg_agent.count("\n") + 1
        assert tg_bytes < 10000, f"child agent pack regressed: {tg_bytes} bytes"
        assert tg_lines < 200, f"child agent pack regressed: {tg_lines} lines"
        assert "hidden: true" in tg_agent
        assert "*: deny" in tg_agent or "'*': deny" in tg_agent
        assert "pilot_cli: allow" in tg_agent
        assert "acp: allow" not in tg_agent
        assert "lsp: deny" in tg_agent
        analyst = (generated / "agents" / "ce-analyst.md").read_text(encoding="utf-8")
        assert "grep: deny" in analyst or "grep: false" in analyst
        assert "glob: deny" in analyst or "glob: false" in analyst
        primary = (generated / "agents" / "ascendc-pilot.md").read_text(encoding="utf-8")
        assert "Host Session Driver" in primary or "host_driver=False" in primary
        assert "edit:" in primary
        assert "uo-query --project" in uo_query_agent
        assert "Never bash" in uo_query_agent or "not bash" in uo_query_agent.lower()
        assert "bash: false" in uo_query_agent
        assert "pilot_run: false" in uo_query_agent
        assert "Do not switch to MCP" in uo_query_agent
        assert "Never `--mode`" in uo_query_agent
        assert "Do not call `--help`" in uo_query_agent
        assert "--mode <mode>" not in uo_query_agent
        assert "--mode locate" not in uo_query_agent
        assert "If the stub still contains" not in uo_query_agent
        assert "丢掉" not in uo_query_agent
        assert "direct_query" not in uo_query_agent
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
        "ce-plan",
        "ce-apply",
        "handoff",
    ):
        path = commands / f"{name}.md"
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8")
        assert "agent: ascendc-pilot" in text
        assert "subtask: false" in text
        if name == "uo-query":
            assert "pilot_run" in text
            assert "不要 `pilot_run`" in text
            assert "直接调用" in text
            assert "委派" in text
            assert "禁止在 Task 正文写 `--mode`" in text
            assert "丢掉" not in text
            assert "then call `acp run-action auto` again" not in text
            assert "call Host tool `pilot_run` again" in text or "pilot_run" in text
        elif name == "uo-init":
            assert "UO_ALREADY_READY" in text
            assert "then call `acp run-action auto` again" not in text
            assert "pilot_run" in text
        else:
            assert "then call `acp run-action auto` again" not in text
            assert "pilot_run" in text


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


def test_invariant_pack_includes_context_and_keeps_cognitive_set_closed():
    from compose_runtime import COGNITIVE_SKILL_IDS, _read_invariant_pack

    pack = _read_invariant_pack(REPO)
    assert "简单查询" in pack
    assert "短问" not in pack
    assert "深问" not in pack
    assert "同名不可互换" in pack
    assert "Open" in pack
    assert COGNITIVE_SKILL_IDS == (
        "operator-analysis",
        "testcase-generation",
        "source-proof",
        "code-review",
        "code-engineering",
    )
    maintainer = {
        "writing-for-pilot-skills",
        "diagnosing-pilot",
        "grill-pilot",
        "tdd-engines",
        "pilot-pr-review",
    }
    assert maintainer.isdisjoint(set(COGNITIVE_SKILL_IDS))
    for name in maintainer:
        assert not (REPO / ".cursor" / "skills" / name / "SKILL.md").is_file()


def test_compose_injects_context_not_maintainer_skills(tmp_path: Path):
    from compose_runtime import compose_host

    out = tmp_path / "cursor"
    result = compose_host(REPO, "cursor", out_root=out)
    assert result["ok"]
    compiled = " ".join(result["compiled"])
    assert "diagnosing-pilot" not in compiled
    assert "pilot-pr-review" not in compiled
    assert "tdd-engines" not in compiled
    primary = (out / "agents" / "ascendc-pilot.md").read_text(encoding="utf-8")
    assert "简单查询" in primary
    assert "短问" not in primary
    assert "深问" not in primary
    assert "同名不可互换" in primary
    oa = (out / "skills" / "operator-analysis" / "SKILL.md").read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in oa


def test_policy_ids_follow_execution_mode() -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    det = next(a for a in WORKFLOWS["uo-init"]["actions"] if a["id"] == "prepare")
    assert det["execution_mode"] == "deterministic"
    assert det.get("policy_ids") == []

    review = next(a for a in WORKFLOWS["ce-review"]["actions"] if a["id"] == "code_review")
    assert "source-authority" in review["policy_ids"]
    assert "pilot-control" not in review["policy_ids"]

    mine = next(a for a in WORKFLOWS["tg-solve"]["actions"] if a["id"] == "construct_cases")
    assert mine.get("output_mode") == "staged"
    assert "pilot-control" not in mine["policy_ids"]
    assert "language" not in mine["policy_ids"]

    confirm = next(a for a in WORKFLOWS["tg-init"]["actions"] if a["id"] == "human_confirm")
    assert confirm["execution_mode"] == "primary_interactive"
    assert confirm["policy_ids"] == ["pilot-control", "language"]


def test_cognitive_skill_md_does_not_cross_link_other_skill_refs() -> None:
    from compose_runtime import COGNITIVE_SKILL_IDS

    for sid in COGNITIVE_SKILL_IDS:
        text = (REPO / "skills" / sid / "SKILL.md").read_text(encoding="utf-8")
        for other in COGNITIVE_SKILL_IDS:
            if other == sid:
                continue
            needle = f"skills/{other}/references/"
            assert needle not in text, f"{sid} SKILL.md links {needle}"
        for method in (REPO / "skills" / sid).glob("capabilities/**/METHOD.md"):
            body = method.read_text(encoding="utf-8")
            for other in COGNITIVE_SKILL_IDS:
                if other == sid:
                    continue
                needle = f"skills/{other}/references/"
                assert needle not in body, f"{method} links {needle}"

