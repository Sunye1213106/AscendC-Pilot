"""Spec start requirements: architecture workflows and model-facing projection."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_uo_update_requires_architecture() -> None:
    from ascendc_pilot.workflows import workflow_requires_architecture

    assert workflow_requires_architecture("uo-update") is True


def test_workflows_needing_architecture_set() -> None:
    from ascendc_pilot.workflows import workflows_needing_architecture
    from ascendc_pilot.workflows.model_checker import MATRIX_WORKFLOWS

    needed = set(workflows_needing_architecture())
    assert needed == set(MATRIX_WORKFLOWS)


def test_ascendc_pilot_agent_does_not_hardcode_architecture_lists() -> None:
    text = (REPO / "agents" / "ascendc-pilot.yaml").read_text(encoding="utf-8")
    assert "必须带齐" not in text
    # Thin controller: no Spec start-list duplication in agent yaml.
    assert not ("--architecture" in text and "uo-update" in text and "tg-init" in text)


def test_control_invariants_item_11_mentions_uo_update() -> None:
    text = (REPO / "pilot" / "policies" / "invariants" / "control-invariants.md").read_text(
        encoding="utf-8"
    )
    item11 = next(line for line in text.splitlines() if line.startswith("11."))
    assert "uo-update" in item11


def test_compose_projection_includes_uo_update() -> None:
    import sys

    scripts = REPO / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from compose_runtime import _start_requirements_line

    line = _start_requirements_line(REPO)
    assert "uo-update" in line
