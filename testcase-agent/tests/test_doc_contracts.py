"""Doc contracts: public surface = 3 skills; shell files <=200 lines; hard keywords."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
AGENTS = ROOT / "agents"
PROMPTS = ROOT / "prompts"

PUBLIC_SKILLS = ("tg-init", "tg-plan", "tg-solve")
RETIRED_SKILLS = ("tg-contract", "tg-domain-review")
MAX_LINES = 200


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_install_skill_names_public_only() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    for name in PUBLIC_SKILLS:
        assert name in ps1 and name in sh
    # Public install lists must not include retired as SkillNames entries
    assert re.search(r'\$SkillNames\s*=\s*@\((?:[^\)]|\n)*?"tg-contract"', ps1) is None
    assert re.search(r"^SKILL_NAMES=\([^\n)]*tg-contract", sh, re.M) is None
    assert "RetiredSkillNames" in ps1
    assert "RETIRED_SKILL_NAMES" in sh


def test_public_skill_shells_within_line_limit() -> None:
    for name in PUBLIC_SKILLS:
        path = SKILLS / name / "SKILL.md"
        n = _line_count(path)
        assert n <= MAX_LINES, f"{path} has {n} lines (max {MAX_LINES})"
        assert n >= 40, f"{path} too short ({n}); expect 8-question template"


def test_main_agents_and_prompts_within_line_limit() -> None:
    shells = [
        AGENTS / "tg-csv-contract.md",
        AGENTS / "tg-init-audit.md",
        AGENTS / "tg-domain-review.md",
        PROMPTS / "init" / "dispatch.md",
        PROMPTS / "init" / "workflow.md",
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
        ("tg-init", ["uo-query", "MUST NOT", "confidence: high", "Purpose", "Trigger", "Quality Gate"]),
        ("tg-plan", ["MUST NOT", "Allow solve", "Purpose", "Trigger", "init.status"]),
        ("tg-solve", ["uo-query", "MUST NOT", "approved", "Purpose", "Trigger", "Quality Gate"]),
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


def test_readme_three_commands_only() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "tg-init" in readme and "tg-plan" in readme and "tg-solve" in readme
    assert "tg-init deprecated" not in readme.lower()
    assert "用户只接触三个命令" in readme or "三个命令" in readme


def test_tg_init_allows_uo_query_bind_without_writing_uo() -> None:
    text = (SKILLS / "tg-init" / "SKILL.md").read_text(encoding="utf-8")
    assert "TG 绑定断边" in text or "绑定断边" in text
    assert "$OUT_ROOT" in text or "OUT_ROOT" in text
    assert "禁止本 Skill 调 uo-query 修断边" not in text
    assert "$UO_ROOT/**" in text or "UO_ROOT" in text
    esc = (SKILLS / "tg-init" / "references" / "tg-uo-query-escalation.md").read_text(encoding="utf-8")
    assert "只写 `$OUT_ROOT`" in esc or "只写 $OUT_ROOT" in esc or "OUT_ROOT" in esc
    assert "key_shape_resolve" in esc
    assert "merge" in esc.lower() and "uo_query_resolve" in esc
    dispatch = (PROMPTS / "init" / "dispatch.md").read_text(encoding="utf-8")
    assert "TG 绑定断边" in dispatch
    assert "$UO_ROOT" in dispatch


def test_paths_md_hard_isolation() -> None:
    text = (SKILLS / "PATHS.md").read_text(encoding="utf-8")
    assert "硬隔离" in text or "只读" in text
    assert ".testcase-generator" in text or "OUT_ROOT" in text


def _checklist_ids_from_audit_md() -> set[str]:
    text = (SKILLS / "tg-init" / "references" / "tg-init-audit.md").read_text(encoding="utf-8")
    return set(re.findall(r"\|\s*`([a-z0-9_]+)`\s*\|", text))


def test_audit_checklist_ids_subseteq_schema_and_constants() -> None:
    from testcase_agent.resolve_policy import AUDIT_CHECKLIST_IDS, VERIFY_GATE_IDS

    checklist = _checklist_ids_from_audit_md()
    # drop non-id table cells if any (layer column uses verify+audit without backticks alone)
    assert "confidence_high_only" in checklist
    assert "not_input_derivable" not in checklist  # skip doc, not a check id

    schema = (AGENTS / "references" / "init-audit-schema.md").read_text(encoding="utf-8")
    for cid in AUDIT_CHECKLIST_IDS:
        assert cid in checklist, f"constant {cid} missing from audit md table"
        assert f"id: {cid}" in schema or f"- id: {cid}" in schema, f"{cid} missing from schema"

    assert set(VERIFY_GATE_IDS).issubset(set(AUDIT_CHECKLIST_IDS))
    assert set(VERIFY_GATE_IDS).issubset(checklist)


def test_verify_gate_keys_match_constants() -> None:
    from testcase_agent.resolve_policy import VERIFY_GATE_IDS, require_full_csv_closure
    from testcase_agent.io import write_yaml

    # minimal empty out → fail, but gates keys must be present
    import tempfile
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp:
        out = P(tmp)
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


def test_install_copies_required_agents_only() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "required only" in ps1.lower() or "RequiredAgents" in ps1
    assert "REQUIRED_AGENTS" in sh
    # must not glob-copy all tg-*.md as install source of truth
    assert "Get-ChildItem $AgentsSrc -Filter" not in ps1
    assert 'for src_agent in "$AGENTS_SRC"/tg-*.md' not in sh


def test_csv_contract_schema_confidence_rule() -> None:
    text = (AGENTS / "references" / "csv-contract-schema.md").read_text(encoding="utf-8")
    assert "proposed" in text and "medium" in text
    assert "仅" in text or "MUST" in text or "仅**" in text
    assert "high" in text


def test_workflow_plugin_root_mentions_cursor() -> None:
    text = (PROMPTS / "init" / "workflow.md").read_text(encoding="utf-8")
    assert ".cursor" in text
    assert "PATHS.md" in text
