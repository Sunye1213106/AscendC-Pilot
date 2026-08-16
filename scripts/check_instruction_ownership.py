#!/usr/bin/env python3
"""Instruction-ownership lint: routing heuristics live in METHOD, not Policy."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Cognitive routing heuristics — METHOD (and engine compiler) own these.
HEURISTIC_PHRASES = (
    "相关 ≠ 单域",
    "related ≠ 单域",
    "METHOD≥2",
    "METHOD >= 2",
    "METHOD ≥2",
)

# Control-plane files must not copy the UO query playbook.
CONTROL_FILES = (
    "pilot/policies/pilot-control/POLICY.md",
    "pilot/policies/invariants/control-invariants.md",
    "scripts/compose_opencode_commands.py",
)

OWNERS = (
    "skills/operator-analysis/capabilities/uo-query/METHOD.md",
    "skills/operator-analysis/capabilities/uo-query-router/METHOD.md",
)


def errors(repo: Path | None = None) -> list[str]:
    root = (repo or REPO).resolve()
    out: list[str] = []
    for rel in CONTROL_FILES:
        text = (root / rel).read_text(encoding="utf-8")
        for phrase in HEURISTIC_PHRASES:
            if phrase in text:
                out.append(f"HEURISTIC_IN_CONTROL {rel}: {phrase!r} belongs in uo-query METHOD")
        if "FIRST_QUERY" in text:
            out.append(f"HEURISTIC_IN_CONTROL {rel}: 'FIRST_QUERY' belongs in uo-query METHOD / compiler")
    router = root / "skills/operator-analysis/capabilities/uo-query-router/METHOD.md"
    if not router.is_file() or not router.read_text(encoding="utf-8").strip():
        out.append("missing uo-query-router METHOD.md")
    else:
        rtext = router.read_text(encoding="utf-8")
        if "相关 ≠ 单域" not in rtext:
            out.append("uo-query-router METHOD.md must own 相关 ≠ 单域")
        if "host_step.tasks" not in rtext:
            out.append("uo-query-router METHOD.md must describe compiler fanout authority")
    for rel in OWNERS:
        if not (root / rel).is_file():
            out.append(f"missing owner {rel}")
    return out


def main() -> int:
    errs = errors()
    if errs:
        print("instruction ownership lint FAILED:")
        for e in errs:
            print(" ", e)
        return 1
    print("instruction ownership lint OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
