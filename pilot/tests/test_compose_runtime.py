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


def test_uo_actions_match_engine_and_prompt_boundary():
    from ascendc_pilot.workflows import WORKFLOWS

    actions = {a["id"]: a for a in WORKFLOWS["uo-init"]["actions"]}

    prepare = actions["prepare"]
    assert prepare["execution_mode"] == "deterministic"
    assert not prepare.get("agent_id")
    assert not prepare.get("task_prompt_id")
    assert prepare.get("actors") == []

    resolve = actions["resolve"]
    assert resolve["execution_mode"] == "subagent"
    assert resolve["agent_id"] == "uo-semantic-resolver"
    assert resolve["task_prompt_id"] == "uo/resolve-gaps"

    for action_id in ("prepare", "extract", "analyze", "apply_gap_patch", "commit", "review"):
        action = actions[action_id]
        assert action["execution_mode"] == "deterministic"
        assert not action.get("agent_id")
        assert not action.get("task_prompt_id")
        assert action.get("actors") == []

    for action in WORKFLOWS["uo-update"]["actions"]:
        assert action["execution_mode"] == "deterministic"
        assert not action.get("agent_id")
        assert not action.get("task_prompt_id")

    query = next(a for a in WORKFLOWS["uo-query"]["actions"] if a["id"] == "kb_lookup")
    assert query["task_prompt_id"] == "uo/codemap-query"


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
        assert (agents / "uo-semantic-resolver.md").is_file()
        assert (agents / "uo-query.md").is_file()
        assert (prompts / "codemap-query.md").is_file()
        assert not (prompts / "kb-review.md").exists()
        assert not (prompts / "kb-lookup.md").exists()

        init_skill = (generated / "skills" / "uo-init" / "SKILL.md").read_text(encoding="utf-8")
        assert "| `extract` | `deterministic` | `engine` |" in init_skill
        assert "| `review` | `deterministic` | `engine` |" in init_skill
    finally:
        shutil.rmtree(generated, ignore_errors=True)
