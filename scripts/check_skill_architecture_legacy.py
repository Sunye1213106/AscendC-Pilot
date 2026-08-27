#!/usr/bin/env python3
"""Lint Skill / Prompt instruction architecture."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from check_execution_contracts import RUNTIME_PROMPT_TOKENS

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "skills"
PROMPTS = REPO / "prompts" / "tasks"

CONTROL_PLANE_SKILLS = ()

# Router parents disclose axis HOW; they must stay short. Execution-step
# skills still target 80–150 and hard-cap at 200.
ROUTER_SKILLS = frozenset(
    {
        "bind-init",
        "test-plan",
        "solve",
        "standalone-review",
        "certify",
        "proof-review",
        "source-proof",
    }
)

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
    "bounded-semantic-batch",
    "sharded-llm-producer",
    "sharded-semantic-producer",
    "producer-self-check",
)

PROMPT_BAD = re.compile(
    r"\b(workflow_id|action_id|run_id|finalize|staging|allowed_write|"
    r"Bundle identity|output_contract|contract id|execution_mode)\b",
    re.I,
)

SKILL_HARNESS_LEAK = re.compile(
    r"\b(declare_workflow_passed|execution_mode|allowed_write_paths|"
    r"output_contract_id|action_session_id|prepare_nonce|lease_id|"
    r"acp\s+finalize|finalize_action)\b",
    re.I,
)


def _listed_skills() -> tuple[str, ...]:
    if not SKILLS.is_dir():
        return ()
    return tuple(sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md")))


def _errors() -> list[str]:
    errors: list[str] = []
    cognitive = _listed_skills()

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

    if (SKILLS / "domain").exists():
        errors.append("skills/domain/ must not exist")
    if (SKILLS / "workflows").exists():
        errors.append("skills/workflows/ must not exist")
    if (SKILLS / "actions").exists():
        errors.append("skills/actions/ must not exist")
    if (SKILLS / "_shared").exists():
        errors.append("skills/_shared/ must not exist")

    for skill_id in cognitive + CONTROL_PLANE_SKILLS:
        skill_md = SKILLS / skill_id / "SKILL.md"
        if not skill_md.is_file():
            errors.append(f"missing skill: {skill_md.as_posix()}")
            continue
        text = skill_md.read_text(encoding="utf-8")
        n = len(text.splitlines())
        if n < 80 and skill_id not in ROUTER_SKILLS:
            errors.append(f"DOMAIN_SKILL_TOO_SHORT {skill_md.as_posix()}: {n}<80")
        if n > 200:
            errors.append(f"DOMAIN_SKILL_TOO_LONG {skill_md.as_posix()}: {n}>200")
        for i, line in enumerate(text.splitlines(), 1):
            if SKILL_HARNESS_LEAK.search(line):
                errors.append(
                    f"DOMAIN_HARNESS_LEAK {skill_md.as_posix()}:{i}: {line.strip()[:80]}"
                )
        for rel in re.findall(r"`((?:skills/[a-z0-9-]+/)?references/[^`]+\.md)`", text):
            if rel.startswith("skills/"):
                target = REPO / rel
            else:
                target = skill_md.parent / rel
            if not target.is_file():
                if "、" in rel or "," in rel:
                    continue
                errors.append(f"broken reference {rel} from {skill_md.as_posix()}")

    for path in PROMPTS.rglob("*.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        stripped = re.sub(r"<[A-Z][A-Z0-9_]{2,}>", "", text)
        if PROMPT_BAD.search(stripped):
            for tok in RUNTIME_PROMPT_TOKENS:
                if tok in stripped and tok not in {"finalize"}:
                    errors.append(f"PROMPT_RUNTIME_LEAK {path.as_posix()}: {tok}")
                    break
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
    raise SystemExit(main())
