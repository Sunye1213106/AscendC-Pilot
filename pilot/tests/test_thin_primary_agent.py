"""Thin Primary Agent: controller brief only; start rules live in Spec/invariants."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def test_thin_primary_agent_description() -> None:
    path = REPO / "agents" / "ascendc-pilot.yaml"
    meta = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    desc = str(meta.get("description") or "")

    assert "必须带齐" not in desc
    assert "tg-init/tg-plan" not in desc
    # No hardcoded start requirement list (may mention "默认 architecture" as a forbid).
    assert "才可 start" not in desc
    assert not (
        "--architecture" in desc and any(w in desc for w in ("uo-init", "uo-update", "tg-init"))
    )

    low = desc.lower()
    assert "pilot_run" in low
    assert "调用 PATH" not in desc
    assert "Get-Command acp" not in desc
    assert "没有 Host 工具就调用" not in desc
    assert "acp.exe" not in desc
    assert "workflow" in low or "entry" in desc.lower()

    assert meta.get("id") == "ascendc-pilot"
    assert meta.get("role") == "controller"
    assert meta.get("mode") == "primary"
    skills = meta.get("skill_ids") or meta.get("max_skill_ids") or []
    assert "workflow-orchestration" not in skills
    assert "operator-analysis" in skills
    assert "read_scopes" in meta
    assert "write_scopes" in meta
    assert meta.get("machine_constraints") or meta.get("forbidden")


def test_spec_still_requires_architecture_for_uo_update() -> None:
    from ascendc_pilot.workflows import workflow_requires_architecture

    assert workflow_requires_architecture("uo-update") is True

    inv = (REPO / "pilot" / "policies" / "invariants" / "control-invariants.md").read_text(
        encoding="utf-8"
    )
    item6 = next(line for line in inv.splitlines() if line.startswith("6."))
    assert "uo-update" in item6
    assert "--architecture" in item6 or "architecture" in item6
