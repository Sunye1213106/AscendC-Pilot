# -*- coding: utf-8 -*-
"""Machine constraint tags must fence writes, not only live in YAML."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "pilot") not in sys.path:
    sys.path.insert(0, str(REPO / "pilot"))

from ascendc_pilot.agents_registry import (
    agent_skill_ceiling,
    forbidden_blocks_write,
    load_agent_meta,
)


def test_agent_yaml_uses_machine_constraints_not_only_forbidden() -> None:
    meta = load_agent_meta("tg-analyst", str(REPO))
    assert meta.get("machine_constraints")
    assert "write_uo_formal_products" in meta["machine_constraints"]
    ceiling = agent_skill_ceiling("tg-analyst", REPO)
    assert "bind-init" in ceiling
    assert "test-plan" in ceiling
    assert "solve" in ceiling
    assert "uo-query" in ceiling
    assert "test-modes" not in ceiling
    assert "lemma" not in ceiling
    assert "standalone-review" not in ceiling


def test_ce_analyst_ceiling_excludes_code_review() -> None:
    ceiling = agent_skill_ceiling("ce-analyst", REPO)
    assert "ce-plan-draft" in ceiling
    assert "standalone-review" not in ceiling


def test_forbidden_blocks_canonical_ce_and_tg_writes() -> None:
    assert (
        forbidden_blocks_write(
            "ce-analyst",
            "ce/plan/op_plan.md",
            project_root=REPO,
        )
        == "FORBIDDEN_WRITE_CANONICAL_CE_PLAN"
    )
    assert (
        forbidden_blocks_write(
            "tg-analyst",
            "tg/init.yaml",
            project_root=REPO,
        )
        == "FORBIDDEN_WRITE_UO_FORMAL_PRODUCTS"
    )
    assert (
        forbidden_blocks_write(
            "tg-analyst",
            "tg/plan.md",
            project_root=REPO,
        )
        == "FORBIDDEN_WRITE_UO_FORMAL_PRODUCTS"
    )
    assert (
        forbidden_blocks_write(
            "ce-analyst",
            "runs/r1/actions/plan_draft/notes.md",
            project_root=REPO,
        )
        is None
    )
