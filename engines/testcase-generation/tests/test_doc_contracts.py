"""Documentation/runtime contracts for TG workflow entry points."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILLS_ROOT = ROOT / "skills"
AGENTS = ROOT / "agents"

PUBLIC_WORKFLOWS = ("tg-init", "tg-plan", "tg-solve")


def test_install_lists_public_tg_skills() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    for name in PUBLIC_WORKFLOWS:
        assert name in ps1 and name in sh


def test_tg_model_agents_are_derived_from_workflow_spec() -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    expected: set[str] = set()
    for workflow_id in PUBLIC_WORKFLOWS:
        for action in WORKFLOWS[workflow_id].get("actions") or []:
            if not isinstance(action, dict):
                continue
            if str(action.get("execution_mode") or "") == "deterministic":
                continue
            agent_id = str(action.get("agent_id") or "").strip()
            if agent_id and agent_id != "ascendc-pilot":
                expected.add(agent_id)

    assert expected, "TG workflow has no model-facing agents"
    for agent_id in sorted(expected):
        path = AGENTS / f"{agent_id}.yaml"
        assert path.is_file(), f"workflow references missing agent {path}"

    # Deterministic engines are never selectable agents.
    assert "deterministic-tg-engine" not in expected


def test_readme_mentions_three_tg_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "/tg-init" in readme and "/tg-plan" in readme and "/tg-solve" in readme


def test_paths_md_hard_isolation() -> None:
    text = (SKILLS_ROOT / "PATHS.md").read_text(encoding="utf-8")
    assert "硬隔离" in text or "只读" in text
    assert ".ascendc-pilot" in text


def test_plan_evidence_does_not_requery_uo() -> None:
    evidence = (SKILLS_ROOT / "test-plan" / "references" / "evidence.md").read_text(encoding="utf-8")
    assert "kernel_tiling_view" not in evidence
    assert "不要再 query UO" in evidence
    skill = (SKILLS_ROOT / "test-plan" / "SKILL.md").read_text(encoding="utf-8")
    assert "不要再查图" in skill


def test_source_proof_atomic_layer_contract() -> None:
    skill = (SKILLS_ROOT / "source-proof" / "SKILL.md").read_text(encoding="utf-8")
    assert "两份 accepted" not in skill
    assert "所需的 accepted atomic certificates" in skill
    review = (SKILLS_ROOT / "proof-review" / "SKILL.md").read_text(encoding="utf-8")
    assert "layer=host 却直接声称 kernel" in review or "layer=host 却声称 kernel" in review
    schema = (ROOT / "schemas" / "source-proof" / "certificate-v1.yaml").read_text(encoding="utf-8")
    assert "- NA" in schema
    assert "UO_CALL_CLOSURE_RECEIPT" in schema


def test_install_skips_retired_tg_domain_review_agent() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "tg-domain-review" not in ps1.split("foreach ($name in @(")[1].split("))")[0]
    assert "tg-domain-review" not in sh
