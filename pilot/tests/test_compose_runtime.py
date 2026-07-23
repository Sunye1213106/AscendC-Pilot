"""Composer / compositional source validation tests."""

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


def test_action_composition_fields_present():
    from ascendc_pilot.workflows.specs import WORKFLOWS

    act = next(a for a in WORKFLOWS["uo-init"]["actions"] if a["id"] == "key_resolution")
    assert act["agent_id"] == "uo-key-resolve"
    assert act["role_id"] == "producer"
    assert "evidence" in act["policy_ids"]
    assert "semantic-resolution" in act["capability_ids"]
    assert act["action_method_id"] == "uo-init/key-resolution"
    assert act["task_prompt_id"] == "uo/key-resolution"
    assert act["actors"] == ["uo-key-resolve"]


def test_compose_host_smoke(tmp_path: Path):
    from compose_runtime import compose_host

    # Compose into real generated path for opencode (side effect ok in CI)
    result = compose_host(REPO, "opencode")
    assert result["ok"]
    skill = REPO / "generated" / "opencode" / "skills" / "uo-init" / "SKILL.md"
    agent = REPO / "generated" / "opencode" / "agents" / "uo-key-resolve.md"
    prompt = REPO / "generated" / "opencode" / "prompts" / "tasks" / "uo" / "key-resolution.md"
    assert skill.is_file()
    assert agent.is_file()
    assert prompt.is_file()
    text = skill.read_text(encoding="utf-8")
    assert "Composition index" in text
    assert "pilot-control" in text
