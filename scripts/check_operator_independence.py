#!/usr/bin/env python3
"""Fail if Pilot production code depends on in-repo operator packages.

Allowed operator-dependent roots:
  - current operator ``.ascendc-pilot/`` (resolved at runtime)
  - ``tests/fixtures/`` (test programs only)

Forbidden:
  - ``operators/`` tree or ``import operators...``
  - production lookup of ``<pilot_repo>/operators/<name>``
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

SCAN_ROOTS = (
    "pilot",
    "engines",
    "skills",
    "tools",
    "agents",
    "prompts",
    "adapters",
    "scripts",
)

# scripts/tests and engines/*/tests are scanned lightly for import operators
# but may mention fixture paths.
SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    "generated",
    "node_modules",
    ".venv",
    "venv",
}

FORBIDDEN_IMPORT = re.compile(
    r"^\s*(from\s+operators(\.|$)|import\s+operators(\.|$|\s))",
    re.MULTILINE,
)
FORBIDDEN_PATH = re.compile(
    r"""(?<!tests/fixtures/)operators/[A-Za-z0-9_]+""",
)


def _iter_files(repo: Path) -> list[Path]:
    out: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = repo / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.suffix not in {".py", ".yaml", ".yml", ".md"}:
                continue
            # Historical FAG design notes under docs are out of SCAN_ROOTS.
            if "tests" in path.parts and path.suffix == ".md":
                continue
            out.append(path)
    return out


def _check_file(path: Path, repo: Path) -> list[str]:
    rel = path.relative_to(repo).as_posix()
    # Fixture packages and independence lint itself are exempt.
    if rel.startswith("tests/fixtures/"):
        return []
    if path.name == "check_operator_independence.py":
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    errs: list[str] = []
    if path.suffix == ".py":
        if FORBIDDEN_IMPORT.search(text):
            errs.append(f"{rel}: forbidden import of operators.*")
        # AST: import operators
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "operators" or alias.name.startswith("operators."):
                            errs.append(f"{rel}:{node.lineno}: import {alias.name}")
                if isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod == "operators" or mod.startswith("operators."):
                        errs.append(f"{rel}:{node.lineno}: from {mod}")
        except SyntaxError:
            pass
    # Path literals to Pilot operators/<name>/ (quoted short paths only).
    for m in re.finditer(
        r"""['"]((?:[\w./\\-]+)operators[/\\][\w./\\-]+)['"]""",
        text,
    ):
        frag = m.group(1).replace("\\", "/")
        if "tests/fixtures/" in frag:
            continue
        if "/.ascendc-pilot/" in frag:
            continue
        if "spec/operators/" in frag:
            # UO op_spec pin file under the ops tree — not Pilot operators/
            continue
        if frag.startswith("operators/") or "/operators/" in frag:
            if "check_operator_independence" in rel:
                continue
            errs.append(f"{rel}: path literal {frag!r}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    repo = args.repo.resolve()

    if (repo / "operators").is_dir():
        print("FAIL: AscendC-Pilot/operators/ directory must not exist", file=sys.stderr)
        return 1

    fag_fixture = repo / "tests" / "fixtures" / "flash_attention_score_grad"
    if fag_fixture.is_dir():
        print(
            "FAIL: real-operator fixture tests/fixtures/flash_attention_score_grad/ "
            "must not exist; use _synthetic_toy only",
            file=sys.stderr,
        )
        return 1

    errors: list[str] = []
    for path in _iter_files(repo):
        errors.extend(_check_file(path, repo))

    # Deduplicate while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for e in errors:
        if e not in seen:
            seen.add(e)
            uniq.append(e)

    if uniq:
        print(f"operator independence violations ({len(uniq)}):", file=sys.stderr)
        for e in uniq[:80]:
            print(f"  {e}", file=sys.stderr)
        if len(uniq) > 80:
            print(f"  ... and {len(uniq) - 80} more", file=sys.stderr)
        return 1
    print("ok: no operators/ tree; no production operators.* imports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
