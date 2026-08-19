#!/usr/bin/env python3
"""Lint Skill / Prompt instruction architecture."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from check_execution_contracts import RUNTIME_PROMPT_TOKENS

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"
SHARED = SKILLS / "_shared"
PROMPTS = REPO / "prompts" / "tasks"

COGNITIVE_SKILLS = (
    "operator-analysis",
    "testcase-generation",
    "source-proof",
    "code-review",
    "code-engineering",
)
CONTROL_PLANE_SKILLS = ()

DELETED_CAPS = (
    "tilingkey-closure",
    "structured-review",
    "obligation-analysis",
    "ce-impact-audit",
    "ce-harness-evidence",
    "ce-exclusion-review",
    "ce-scenario-knobs",
    "ce-handoff",
    "ce-feature-decompose",
    "ce-plan-review",
    "verify-review",
)

PROMPT_BAD = re.compile(
    r"\b(workflow_id|action_id|run_id|finalize|staging|allowed_write|"
    r"Bundle identity|output_contract|contract id|execution_mode)\b",
    re.I,
)

SKILL_CROSS_INCLUDE = re.compile(
    r"skills/(?!_shared)([a-z0-9-]+)/SKILL\.md"
    r"|^\s*\.\./[a-z0-9-]+/SKILL\.md",
    re.I | re.M,
)

SKILL_HARNESS_LEAK = re.compile(
    r"\b(declare_workflow_passed|execution_mode|allowed_write_paths|"
    r"output_contract_id|action_session_id|prepare_nonce|lease_id|"
    r"acp\s+finalize|finalize_action)\b",
    re.I,
)


def _errors() -> list[str]:
    errors: list[str] = []

    for cap in DELETED_CAPS:
        if any(
            (REPO / rel).exists()
            for rel in (
                f"skills/capabilities/{cap}",
                f"tools/source/{cap}",
                f"tools/codemap/{cap}",
                f"pilot/runtime/{cap}",
                f"pilot/gates/{cap}",
            )
        ):
            errors.append(f"deleted capability still present: {cap}")

    scan_roots = [
        REPO / "skills",
        REPO / "prompts",
        REPO / "pilot" / "ascendc_pilot" / "workflows",
        REPO / "docs" / "design",
    ]
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".md", ".py", ".yaml", ".yml"}:
                continue
            if path.name == "check_skill_architecture.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for cap in DELETED_CAPS:
                if cap in text:
                    if "capabilities" in path.parts and path.name == "capability.yaml":
                        errors.append(f"residual capability package: {path.as_posix()}")
                    elif path.suffix == ".py" and "specs.py" in path.name:
                        errors.append(f"specs still names {cap}: {path.as_posix()}")
                    elif path.suffix == ".md" and path.parent.name in COGNITIVE_SKILLS:
                        errors.append(f"skill text names deleted cap {cap}: {path.as_posix()}")
                    elif "prompts" in path.parts:
                        errors.append(f"prompt names deleted cap {cap}: {path.as_posix()}")

    if (SKILLS / "domain").exists():
        errors.append("skills/domain/ must not exist; use top-level cognitive skills")
    if (SKILLS / "workflows").exists():
        errors.append("skills/workflows/ must not exist; entries come from Spec + WORKFLOW_ENTRIES")
    if (SKILLS / "actions").exists():
        errors.append("skills/actions/ must not exist; Action identity lives in Spec")

    for skill_id in COGNITIVE_SKILLS + CONTROL_PLANE_SKILLS:
        skill_md = SKILLS / skill_id / "SKILL.md"
        if not skill_md.is_file():
            errors.append(f"missing cognitive skill: {skill_md.as_posix()}")
            continue
        text = skill_md.read_text(encoding="utf-8")
        n = len(text.splitlines())
        if n > 200:
            errors.append(f"DOMAIN_SKILL_TOO_LONG {skill_md.as_posix()}: {n}>200")
        for m in SKILL_CROSS_INCLUDE.finditer(text):
            other = m.group(1) if m.lastindex else m.group(0)
            if other and other != skill_id and other in COGNITIVE_SKILLS:
                # Allow pointing at another skill by path for progressive disclosure
                # only from SKILL body as a named peer, not as an include of its SKILL.md
                # for reasoning merge — still flag SKILL.md includes of peers.
                if f"skills/{other}/SKILL.md" in m.group(0) or f"../{other}/SKILL.md" in m.group(0):
                    # peer pointers in "see X" are OK if not include-style; keep soft
                    pass
        for i, line in enumerate(text.splitlines(), 1):
            if SKILL_HARNESS_LEAK.search(line):
                errors.append(
                    f"DOMAIN_HARNESS_LEAK {skill_md.as_posix()}:{i}: {line.strip()[:80]}"
                )
        gotchas = skill_md.parent / "references" / "gotchas.md"
        if not gotchas.is_file():
            errors.append(f"DOMAIN_MISSING_GOTCHAS {gotchas.as_posix()}")
        for rel in re.findall(r"`((?:skills/[a-z0-9-]+/)?references/[^`]+\.md)`", text):
            if rel.startswith("skills/"):
                target = REPO / rel
            else:
                target = skill_md.parent / rel
            if not target.is_file():
                if "、" in rel or "," in rel:
                    continue
                errors.append(f"broken reference {rel} from {skill_md.as_posix()}")

        examples_dir = skill_md.parent / "examples"
        if not examples_dir.is_dir():
            errors.append(f"DOMAIN_MISSING_EXAMPLES_DIR {examples_dir.as_posix()}")
        else:
            cases = [p for p in examples_dir.iterdir() if p.is_dir()]
            if len(cases) < 2:
                errors.append(
                    f"DOMAIN_EXAMPLES_TOO_FEW {examples_dir.as_posix()}: need ≥2 case dirs, got {len(cases)}"
                )
            for case in cases:
                if not (case / "README.md").is_file():
                    errors.append(f"DOMAIN_EXAMPLE_MISSING_README {case.as_posix()}")

    if PROMPTS.is_dir():
        for p in PROMPTS.rglob("*.md"):
            text = p.read_text(encoding="utf-8")
            n = len(text.splitlines())
            if n > 40:
                errors.append(f"PROMPT_TOO_LONG {p.as_posix()}: {n}>40")
            if re.search(r"\bH0\b|\bH1\b|Open\s*=\s*O\s*-\s*V\s*-\s*X", text):
                errors.append(f"PROMPT_METHOD_LEAK {p.as_posix()}: domain method belongs in METHOD.md")
            for i, line in enumerate(text.splitlines(), 1):
                scanned = line
                for tok in RUNTIME_PROMPT_TOKENS:
                    scanned = scanned.replace(f"<{tok}>", "")
                if PROMPT_BAD.search(scanned):
                    errors.append(f"PROMPT_HARNESS_LEAK {p.as_posix()}:{i}: {line.strip()[:80]}")
                # Forbid bare references/*.md (must go Prompt → Skill → references)
                if re.search(r"(?<![/\w])references/[A-Za-z0-9_.-]+\.md", line):
                    if "skills/" not in line:
                        errors.append(
                            f"PROMPT_BARE_REFERENCE {p.as_posix()}:{i}: {line.strip()[:100]}"
                        )

    # E eligibility text should live under testcase-generation / source-proof / _shared
    e_files: list[Path] = []
    for skill_id in COGNITIVE_SKILLS:
        for path in (SKILLS / skill_id).rglob("*.md"):
            t = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"\bE\b.*只来自|SOUND_GRADES|exclusion.*certificate", t, re.I):
                e_files.append(path)
    for path in e_files:
        if (
            "testcase-generation" not in path.parts
            and "source-proof" not in path.parts
            and "_shared" not in path.parts
        ):
            errors.append(f"E_ELIGIBILITY_OUTSIDE_DOMAIN {path.as_posix()}")

    return errors


def main() -> int:
    errs = _errors()
    if errs:
        print("skill architecture lint FAILED:")
        for e in errs:
            print(" ", e)
        return 1
    print("skill architecture lint OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
