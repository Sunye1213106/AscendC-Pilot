#!/usr/bin/env python3
"""Instruction-ownership lint: routing heuristics live in the router, not Policy."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Cognitive routing heuristics — the uo-query router owns these.
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
    "pilot/policies/invariants/host-runtime-contract.md",
    "scripts/compose_opencode_commands.py",
)

ROUTER = "skills/operator-analysis/routing/uo-query.md"
OWNERS = (
    "skills/operator-analysis/capabilities/uo-query/METHOD.md",
    ROUTER,
)

# Agent-facing sources must not teach removed CLI or stacked recovery wording.
STALE_CLI_FILES = (
    "scripts/compose_runtime.py",
    "opencode-plugin/ascendc-pilot.ts",
    "tools/codemap/kb-query/METHOD.md",
    "agents/uo-query.yaml",
    "agents/CONTEXT.md",
    "agents/ascendc-pilot.yaml",
    "skills/operator-analysis/capabilities/uo-query/METHOD.md",
    "skills/operator-analysis/routing/uo-query.md",
    "skills/operator-analysis/references/codemap-query-gotchas.md",
    "prompts/tasks/uo/codemap-query.md",
)

STALE_CLI_PHRASES = (
    "--mode locate",
    "--mode <mode>",
    "--mode compile",
    "丢掉 `--mode`",
    "If the stub still contains `--mode`",
    "旧 CLI",
    "旧 mode",
    "**短问**",
    "**深问**",
    "调用 PATH 上的",
)

# Model-facing trees must not contain the human CLI name (including prohibitions).
MODEL_FACING_ROOTS = (
    "agents",
    "skills",
    "prompts",
    "tools",
    "pilot/policies/invariants",
    "pilot/policies/pilot-control",
)
GENERATED_ACP_ROOTS = (
    "generated/opencode/agents",
    "generated/opencode/skills",
    "generated/opencode/commands",
)
_ACP_WORD = re.compile(r"\bacp\b")


def errors(repo: Path | None = None) -> list[str]:
    root = (repo or REPO).resolve()
    out: list[str] = []
    for rel in CONTROL_FILES:
        text = (root / rel).read_text(encoding="utf-8")
        for phrase in HEURISTIC_PHRASES:
            if phrase in text:
                out.append(f"HEURISTIC_IN_CONTROL {rel}: {phrase!r} belongs in uo-query router")
        if "FIRST_QUERY" in text:
            out.append(f"HEURISTIC_IN_CONTROL {rel}: 'FIRST_QUERY' belongs in uo-query router")
        if "--mode compile" in text:
            out.append(f"STALE_COMPILE {rel}: query compile is removed")
    router = root / ROUTER
    if not router.is_file() or not router.read_text(encoding="utf-8").strip():
        out.append(f"missing {ROUTER}")
    else:
        rtext = router.read_text(encoding="utf-8")
        if "相关 ≠ 单域" not in rtext:
            out.append(f"{ROUTER} must own 相关 ≠ 单域")
        if "直接调用" not in rtext or "委派" not in rtext:
            out.append(f"{ROUTER} must say 直接调用 / 委派")
        if "分别委派" not in rtext or "综合只在主控" not in rtext:
            out.append(f"{ROUTER} must say 分别委派 / 综合只在主控")
        if "compile" in rtext:
            out.append(f"{ROUTER} must not mention compile")
        if "数量由主控判断" in rtext:
            out.append(f"{ROUTER} must not defer split count to 数量由主控判断")
    for rel in OWNERS:
        if not (root / rel).is_file():
            out.append(f"missing owner {rel}")
    method = root / "skills/operator-analysis/capabilities/uo-query/METHOD.md"
    if method.is_file():
        mtext = method.read_text(encoding="utf-8")
        if "不要传 `--mode`" not in mtext:
            out.append("METHOD must say 不要传 `--mode` (one prohibition, no recovery stack)")
        if "丢掉" in mtext:
            out.append("METHOD must not stack 丢掉 recovery on top of 不要传 `--mode`")
    for rel in STALE_CLI_FILES:
        path = root / rel
        if not path.is_file():
            out.append(f"missing {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in STALE_CLI_PHRASES:
            if phrase in text:
                out.append(f"STALE_CLI {rel}: {phrase!r}")
    scan_roots = list(MODEL_FACING_ROOTS)
    for rel_root in GENERATED_ACP_ROOTS:
        if (root / rel_root).is_dir():
            scan_roots.append(rel_root)
    for rel_root in scan_roots:
        base = root / rel_root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".md", ".yaml", ".yml"}:
                continue
            rel = path.relative_to(root).as_posix()
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _ACP_WORD.search(line):
                    out.append(f"ACP_IN_MODEL_FACING {rel}:{i}: {line.strip()[:160]}")
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
