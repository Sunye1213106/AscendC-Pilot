#!/usr/bin/env python3
"""Lint Domain / Prompt / Workflow instruction architecture."""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOMAIN = REPO / "skills" / "domain"
WORKFLOWS = REPO / "skills" / "workflows"
PROMPTS = REPO / "prompts" / "tasks"

DELETED_CAPS = ("tilingkey-closure", "structured-review", "obligation-analysis")

# Prompt harness leakage (natural language should not teach Pilot mechanics)
PROMPT_BAD = re.compile(
    r"\b(workflow_id|action_id|run_id|finalize|staging|allowed_write|"
    r"Bundle identity|output_contract|contract id|execution_mode)\b",
    re.I,
)

# Domain Skill must not include another Domain SKILL.md
DOMAIN_SKILL_INCLUDE = re.compile(
    r"skills/domain/(?!_shared)([a-z0-9-]+)/SKILL\.md"
    r"|^\s*\.\./[a-z0-9-]+/SKILL\.md",
    re.I | re.M,
)

# Workflow must not restate E eligibility / proof acceptance as domain authority
WORKFLOW_DOMAIN_LEAK = re.compile(
    r"(E\s*只来自|SOUND_GRADES|source_lemma|PROVED\s*\|\s*REFUTED|"
    r"derived\s*!=\s*exact|value domain\s*!=\s*reachable)",
    re.I,
)

# Domain Skill must not teach Harness protocol (see docs/design/where-does-this-go.md)
DOMAIN_HARNESS_LEAK = re.compile(
    r"\b(declare_workflow_passed|execution_mode|allowed_write_paths|"
    r"output_contract_id|action_session_id|prepare_nonce|lease_id|"
    r"acp\s+finalize|finalize_action)\b",
    re.I,
)


def _errors() -> list[str]:
    errors: list[str] = []

    # Deleted capability dirs must be gone
    for cap in DELETED_CAPS:
        if (REPO / "skills" / "capabilities" / cap).exists():
            errors.append(f"deleted capability still present: skills/capabilities/{cap}")

    # Residual references to deleted capability ids (sources only)
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
            # allow mentioning deleted names in this lint file / historical fag reports
            if path.name == "check_skill_architecture.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for cap in DELETED_CAPS:
                if cap in text:
                    # action.yaml may still be regenerated; source specs must be clean
                    if "capabilities" in path.parts and path.name == "capability.yaml":
                        errors.append(f"residual capability package: {path.as_posix()}")
                    elif path.suffix == ".py" and "specs.py" in path.name:
                        errors.append(f"specs still names {cap}: {path.as_posix()}")
                    elif path.suffix == ".md" and "domain" in path.parts:
                        errors.append(f"domain text names deleted cap {cap}: {path.as_posix()}")
                    elif path.suffix == ".md" and "workflows" in path.parts:
                        errors.append(f"workflow text names deleted cap {cap}: {path.as_posix()}")
                    elif "prompts" in path.parts:
                        errors.append(f"prompt names deleted cap {cap}: {path.as_posix()}")

    # Domain SKILL.md rules
    for skill_md in sorted(DOMAIN.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        n = len(text.splitlines())
        if n > 200:
            errors.append(f"DOMAIN_SKILL_TOO_LONG {skill_md.as_posix()}: {n}>200")
        # no include of other domain SKILL.md
        for m in DOMAIN_SKILL_INCLUDE.finditer(text):
            other = m.group(1) if m.lastindex else m.group(0)
            self_id = skill_md.parent.name
            if other and other != self_id:
                errors.append(
                    f"DOMAIN_CROSS_SKILL_INCLUDE {skill_md.as_posix()}: references domain/{other}/SKILL.md"
                )
        for i, line in enumerate(text.splitlines(), 1):
            if DOMAIN_HARNESS_LEAK.search(line):
                errors.append(
                    f"DOMAIN_HARNESS_LEAK {skill_md.as_posix()}:{i}: {line.strip()[:80]}"
                )
        # Every domain skill must ship high-signal gotchas (progressive disclosure L2).
        gotchas = skill_md.parent / "references" / "gotchas.md"
        if not gotchas.is_file():
            errors.append(f"DOMAIN_MISSING_GOTCHAS {gotchas.as_posix()}")
        # resolve relative reference paths listed as `references/...` or `_shared/...`
        for rel in re.findall(r"`((?:references|_shared)/[^`]+\.md)`", text):
            # _shared is under domain/
            if rel.startswith("_shared/"):
                target = DOMAIN / rel
            else:
                target = skill_md.parent / rel
            if not target.is_file():
                errors.append(f"broken reference {rel} from {skill_md.as_posix()}")

    # Prompts harness leakage
    if PROMPTS.is_dir():
        for p in PROMPTS.rglob("*.md"):
            text = p.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if PROMPT_BAD.search(line):
                    errors.append(f"PROMPT_HARNESS_LEAK {p.as_posix()}:{i}: {line.strip()[:80]}")

    # Workflow domain leak
    for skill_md in sorted(WORKFLOWS.glob("*/SKILL.md")):
        # skip generated actions table body lightly; scan full text for domain invariants
        text = skill_md.read_text(encoding="utf-8")
        # strip generated actions block
        begin, end = "<!-- BEGIN GENERATED ACTIONS -->", "<!-- END GENERATED ACTIONS -->"
        if begin in text and end in text:
            pre, rest = text.split(begin, 1)
            _, post = rest.split(end, 1)
            text = pre + post
        if WORKFLOW_DOMAIN_LEAK.search(text):
            errors.append(f"WORKFLOW_DOMAIN_LEAK {skill_md.as_posix()}")

    # Dual authority sniff: E eligibility should live under tg-closure / source-lemma-proof only
    e_files: list[Path] = []
    for path in DOMAIN.rglob("*.md"):
        t = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\bE\b.*只来自|SOUND_GRADES|exclusion.*certificate", t, re.I):
            e_files.append(path)
    # allow tg-closure + shared + failure-patterns under those trees
    for path in e_files:
        ok_prefix = (
            "tg-closure",
            "source-lemma-proof",
            "_shared",
        )
        if path.parts[-3] not in ok_prefix and path.parent.name not in ok_prefix:
            # path like domain/tg-closure/references/x.md -> parts include tg-closure
            if "tg-closure" not in path.parts and "source-lemma-proof" not in path.parts and "_shared" not in path.parts:
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
