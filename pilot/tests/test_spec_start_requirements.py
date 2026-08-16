"""Spec start requirements: architecture builders vs .uo consumers."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_uo_update_requires_architecture() -> None:
    from ascendc_pilot.workflows import workflow_requires_architecture

    assert workflow_requires_architecture("uo-update") is True


def test_workflows_needing_architecture_are_uo_builders() -> None:
    from ascendc_pilot.workflows import (
        workflows_needing_architecture,
        workflows_needing_uo_product,
    )

    assert set(workflows_needing_architecture()) == {"uo-init", "uo-update"}
    assert set(workflows_needing_uo_product()) == {
        "tg-init",
        "tg-plan",
        "tg-solve",
        "ce-review",
        "ce-impact",
        "ce-intent",
        "ce-apply",
        "ce-handoff",
        "ce-verify",
        "uo-query",
        "uo-investigate",
    }


def test_ascendc_pilot_agent_does_not_hardcode_architecture_lists() -> None:
    text = (REPO / "agents" / "ascendc-pilot.yaml").read_text(encoding="utf-8")
    assert "必须带齐" not in text
    assert not ("--architecture" in text and "uo-update" in text and "tg-init" in text)


def test_control_invariants_item_11_mentions_uo_update_and_uo_product() -> None:
    text = (REPO / "pilot" / "policies" / "invariants" / "control-invariants.md").read_text(
        encoding="utf-8"
    )
    item11 = next(line for line in text.splitlines() if line.startswith("11."))
    assert "uo-update" in item11
    assert ".uo" in item11


def test_compose_projection_includes_uo_update_and_uo_first() -> None:
    import sys

    scripts = REPO / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from compose_runtime import _start_requirements_line

    line = _start_requirements_line(REPO)
    assert "uo-update" in line
    assert "uo-init" in line
    assert ".uo" in line
