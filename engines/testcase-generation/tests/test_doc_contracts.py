"""Doc contracts: public surface = 3 TG skills under AscendC-Pilot layout."""

from __future__ import annotations

from pathlib import Path

# engines/testcase-generation/tests → repo root
ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "skills" / "workflows"
SKILLS_ROOT = ROOT / "skills"
AGENTS = ROOT / "agents"
GENERATED_AGENTS = ROOT / "generated" / "opencode" / "agents"

PUBLIC_SKILLS = ("tg-init", "tg-plan", "tg-solve")
MAX_LINES = 220


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_install_lists_public_tg_skills() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    for name in PUBLIC_SKILLS:
        assert name in ps1 and name in sh


def test_public_skill_shells_within_line_limit() -> None:
    for name in PUBLIC_SKILLS:
        path = SKILLS / name / "SKILL.md"
        assert path.is_file(), f"missing {path}"
        n = _line_count(path)
        assert n <= MAX_LINES, f"{path} has {n} lines (max {MAX_LINES})"


def test_generated_tg_agents_exist() -> None:
    for name in ("tg-csv-contract.md", "tg-init-audit.md", "tg-semantic-bind.md"):
        path = GENERATED_AGENTS / name
        assert path.is_file(), f"missing {path}"
        assert _line_count(path) <= 400


def test_readme_mentions_three_tg_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "/tg-init" in readme and "/tg-plan" in readme and "/tg-solve" in readme


def test_paths_md_hard_isolation() -> None:
    text = (SKILLS_ROOT / "PATHS.md").read_text(encoding="utf-8")
    assert "硬隔离" in text or "只读" in text
    assert ".ascendc-pilot" in text


def test_install_skips_tg_domain_review_agent() -> None:
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    # Retired agent must not be in the primary agent install list.
    assert "tg-domain-review" not in ps1.split("foreach ($name in @(")[1].split("))")[0]
    assert "tg-domain-review" not in sh


def test_tg_dispatch_mentions_plugin_paths() -> None:
    skill = (SKILLS / "tg-init" / "SKILL.md").read_text(encoding="utf-8")
    assert "acp" in skill or "Pilot" in skill or "TG" in skill
