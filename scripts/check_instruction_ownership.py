#!/usr/bin/env python3
"""Instruction-ownership lint: investigation routing lives in Primary intent-reasoning."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

HEURISTIC_PHRASES = (
    "相关 ≠ 单域",
    "related ≠ 单域",
    "METHOD≥2",
    "METHOD >= 2",
    "METHOD ≥2",
)

CONTROL_FILES = (
    "pilot/policies/pilot-control/POLICY.md",
    "pilot/policies/invariants/control-invariants.md",
    "pilot/policies/invariants/host-runtime-contract.md",
    "scripts/compose_opencode_commands.py",
)

ROUTER = "pilot/policies/invariants/intent-reasoning.md"
OWNERS = (
    "skills/uo-query/SKILL.md",
    ROUTER,
)

ORCH_BANNED_FILES = (
    "pilot/policies/invariants/host-runtime-contract.md",
    "pilot/policies/invariants/control-invariants.md",
    "pilot/policies/invariants/human-voice-invariants.md",
    "scripts/compose_opencode_commands.py",
    "scripts/compose_runtime.py",
    "scripts/compose_runtime_legacy.py",
    "agents/ascendc-pilot.yaml",
    "opencode-plugin/pilot-driver.ts",
)
ORCH_BANNED_PHRASES = (
    "skills/workflow-orchestration",
    "Never workflow=auto",
    "Never `workflow=auto`",
    "Do not `workflow=auto`",
    "对照编排 skill",
)
STALE_CLI_FILES = (
    "scripts/compose_runtime.py",
    "opencode-plugin/ascendc-pilot.ts",
    "tools/codemap/kb-query/METHOD.md",
    "agents/uo-query.yaml",
    "agents/CONTEXT.md",
    "agents/ascendc-pilot.yaml",
    "skills/uo-query/SKILL.md",
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
                out.append(f"HEURISTIC_IN_CONTROL {rel}: {phrase!r} belongs in intent-reasoning")
        if "FIRST_QUERY" in text:
            out.append(f"HEURISTIC_IN_CONTROL {rel}: 'FIRST_QUERY' belongs in intent-reasoning")
        if "--mode compile" in text:
            out.append(f"STALE_COMPILE {rel}: query compile is removed")
    router = root / ROUTER
    if not router.is_file() or not router.read_text(encoding="utf-8").strip():
        out.append(f"missing {ROUTER}")
    else:
        rtext = router.read_text(encoding="utf-8")
        if "相关 ≠ 单域" not in rtext:
            out.append(f"{ROUTER} must own 相关 ≠ 单域")
        if "分别派" not in rtext and "分别委派" not in rtext:
            out.append(f"{ROUTER} must say 分别派")
        if "综合只在主控" not in rtext:
            out.append(f"{ROUTER} must say 综合只在主控")
        if "fanout" not in rtext.lower() and "隔离" not in rtext:
            out.append(f"{ROUTER} must keep fanout / context isolation")
    for rel in OWNERS:
        if not (root / rel).is_file():
            out.append(f"missing owner {rel}")
    method = root / "skills/uo-query/SKILL.md"
    if method.is_file():
        mtext = method.read_text(encoding="utf-8")
        if "不要传 `--mode`" in mtext or "禁止 `--mode`" in mtext:
            out.append("uo-query SKILL must not restate --mode; belongs in code-access invariant")
        if "丢掉" in mtext:
            out.append("uo-query SKILL must not stack 丢掉 recovery on --mode")
        if "相关 ≠ 单域" in mtext:
            out.append("uo-query SKILL must not own 相关 ≠ 单域; belongs in intent-reasoning")
        if "Dim=V" not in mtext or "无参数索引" not in mtext:
            out.append("uo-query SKILL must own the four uo-query forms")
    forms = root / "pilot/policies/invariants/code-access-invariants.md"
    if not forms.is_file():
        out.append("missing code-access-invariants.md")
    else:
        ftext = forms.read_text(encoding="utf-8")
        if "禁止 `--mode`" not in ftext:
            out.append("code-access invariant must own 禁止 `--mode`")
        if "四种形态之外" not in ftext:
            out.append("code-access invariant must keep the hard bound 禁止四种形态之外")
        if "Dim=V" in ftext or "Dim=<维名>" in ftext or "--file PATH" in ftext:
            out.append(
                "code-access invariant must not catalog uo-query forms; belongs in uo-query Skill"
            )
    restated = (
        "不要传 `--mode`",
        "禁止在 Task 正文写 `--mode`",
        "只有四种 `uo-query` 形态",
        "只有四种形态",
    )
    for rel_root in ("skills", "prompts", "agents"):
        base = root / rel_root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".md", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(root).as_posix()
            for phrase in restated:
                if phrase in text:
                    out.append(f"FORMS_RESTATED {rel}: {phrase!r} belongs in code-access invariant")
    for rel in STALE_CLI_FILES:
        path = root / rel
        if not path.is_file():
            out.append(f"missing {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in STALE_CLI_PHRASES:
            if phrase in text:
                out.append(f"STALE_CLI {rel}: {phrase!r}")
    for rel in ORCH_BANNED_FILES:
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in ORCH_BANNED_PHRASES:
            if phrase in text:
                out.append(f"STALE_ORCH {rel}: {phrase!r}")
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
