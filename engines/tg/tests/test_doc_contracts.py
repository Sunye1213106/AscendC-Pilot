"""Doc contracts: public surface = 3 TG skills; shells within limits; hard keywords."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

# engines/tg/tests → repo root
ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "skills"
AGENTS = ROOT / "agents"
PROMPTS = ROOT / "prompts"
TG_PROMPTS = ROOT / "prompts" / "tg"

PUBLIC_SKILLS = ("tg-init", "tg-plan", "tg-solve")
RETIRED_SKILLS = ("tg-contract", "tg-domain-review")
MAX_LINES = 220


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_install_lists_public_tg_skills() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    for name in PUBLIC_SKILLS:
        assert name in ps1 and name in sh
    # Unified installer must not treat retired names as user skills
    assert "tg-domain-review.md" in ps1 or "tg-domain-review" in sh
    assert "continue" in ps1.lower() or "tg-domain-review.md" in sh


def test_public_skill_shells_within_line_limit() -> None:
    for name in PUBLIC_SKILLS:
        path = SKILLS / name / "SKILL.md"
        n = _line_count(path)
        assert n <= MAX_LINES, f"{path} has {n} lines (max {MAX_LINES})"
        assert n >= 40, f"{path} too short ({n})"


def test_main_agents_and_prompts_within_line_limit() -> None:
    shells = [
        AGENTS / "tg-csv-contract.md",
        AGENTS / "tg-init-audit.md",
        TG_PROMPTS / "init" / "dispatch.md",
        PROMPTS / "plan" / "workflow.md",
        PROMPTS / "solve" / "workflow.md",
    ]
    for path in shells:
        assert path.is_file(), f"missing {path}"
        n = _line_count(path)
        assert n <= MAX_LINES, f"{path} has {n} lines (max {MAX_LINES})"


@pytest.mark.parametrize(
    "name,needles",
    [
        ("tg-init", ["uo-query", "MUST NOT", "confidence: high", "Purpose", "Trigger"]),
        ("tg-plan", ["MUST NOT", "Allow solve", "Purpose", "Trigger"]),
        ("tg-solve", ["MUST NOT", "approved", "Purpose", "Trigger"]),
    ],
)
def test_public_skill_hard_keywords(name: str, needles: list[str]) -> None:
    text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    for needle in needles:
        assert needle in text, f"{name} missing '{needle}'"


def test_retired_skills_point_to_tg_init() -> None:
    for name in RETIRED_SKILLS:
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        assert "/tg-init" in text or "tg-init" in text
        assert "退役" in text or "RETIRED" in text


def test_readme_mentions_three_tg_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "/tg-init" in readme and "/tg-plan" in readme and "/tg-solve" in readme


def test_tg_init_allows_uo_query_bind_without_writing_uo() -> None:
    text = (SKILLS / "tg-init" / "SKILL.md").read_text(encoding="utf-8")
    assert "绑定断边" in text or "uo-query" in text
    assert "OUT_ROOT" in text or "TG_ROOT" in text
    assert "$UO_ROOT" in text or "UO_ROOT" in text
    esc = (SKILLS / "tg-init" / "references" / "tg-uo-query-escalation.md").read_text(encoding="utf-8")
    assert "OUT_ROOT" in esc or "TG_ROOT" in esc
    assert "key_shape_resolve" in esc
    assert "uo_query_resolve" in esc
    dispatch = (TG_PROMPTS / "init" / "dispatch.md").read_text(encoding="utf-8")
    assert "UO_ROOT" in dispatch


def test_paths_md_hard_isolation() -> None:
    text = (SKILLS / "PATHS.md").read_text(encoding="utf-8")
    assert "硬隔离" in text or "只读" in text
    assert ".ascendc-agent" in text


def _checklist_ids_from_audit_md() -> set[str]:
    text = (SKILLS / "tg-init" / "references" / "tg-init-audit.md").read_text(encoding="utf-8")
    return set(re.findall(r"\|\s*`([a-z0-9_]+)`\s*\|", text))


def test_audit_checklist_ids_subseteq_schema_and_constants() -> None:
    from testcase_agent.resolve_policy import AUDIT_CHECKLIST_IDS, VERIFY_GATE_IDS

    checklist = _checklist_ids_from_audit_md()
    assert "confidence_high_only" in checklist
    assert "not_input_derivable" not in checklist

    schema = (AGENTS / "references" / "init-audit-schema.md").read_text(encoding="utf-8")
    for cid in AUDIT_CHECKLIST_IDS:
        assert cid in checklist, f"constant {cid} missing from audit md table"
        assert f"id: {cid}" in schema or f"- id: {cid}" in schema, f"{cid} missing from schema"

    assert set(VERIFY_GATE_IDS).issubset(set(AUDIT_CHECKLIST_IDS))
    assert set(VERIFY_GATE_IDS).issubset(checklist)


def test_verify_gate_keys_match_constants() -> None:
    from testcase_agent.io import write_yaml
    from testcase_agent.resolve_policy import VERIFY_GATE_IDS, require_full_csv_closure

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "realization").mkdir()
        write_yaml(out / "realization" / "binding_lexicon.yaml", {"version": 1, "key_derivations": []})
        result = require_full_csv_closure(out)
        gate_keys = set((result.get("gates") or {}).keys())
        assert set(VERIFY_GATE_IDS).issubset(gate_keys)


def test_legitimate_skips_doc_mentions_not_input_derivable() -> None:
    text = (SKILLS / "tg-init" / "references" / "legitimate-skips.md").read_text(encoding="utf-8")
    assert "not_input_derivable" in text
    assert "empty_tensor" in text
    audit = (SKILLS / "tg-init" / "references" / "tg-init-audit.md").read_text(encoding="utf-8")
    assert "legitimate-skips.md" in audit
    assert "not_input_derivable" in audit


def test_install_skips_tg_domain_review_agent() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "tg-domain-review.md" in ps1
    assert "tg-domain-review.md" in sh


def test_csv_contract_schema_confidence_rule() -> None:
    text = (AGENTS / "references" / "csv-contract-schema.md").read_text(encoding="utf-8")
    assert "proposed" in text and "medium" in text
    assert "high" in text


def test_tg_dispatch_mentions_plugin_paths() -> None:
    text = (TG_PROMPTS / "init" / "dispatch.md").read_text(encoding="utf-8")
    assert "PLUGIN_ROOT" in text or "OUT_ROOT" in text or "UO_ROOT" in text
