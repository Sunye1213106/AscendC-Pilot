#!/usr/bin/env python3
"""Authoring SSOT for shared skill references → self-contained projections.

Source: knowledge/shared-references/*.md
Default five files project to operator-analysis / testcase-generation /
source-proof / code-review. harness-oracle.md projects only to
testcase-generation.
Do not dump the default five into code-engineering.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SSOT = REPO / "knowledge" / "shared-references"
DEFAULT_SKILLS = (
    "operator-analysis",
    "testcase-generation",
    "source-proof",
    "code-review",
)
DEFAULT_NAMES = (
    "artifact-freshness.md",
    "completeness.md",
    "cpp-semantics.md",
    "evidence-quality.md",
    "finding-format.md",
)
# Named by a CE METHOD; do not grant ce-reviewer the whole TG skill tree.
SPECIAL_PROJECTIONS: dict[str, tuple[str, ...]] = {
    "harness-oracle.md": ("testcase-generation",),
}
# Back-compat aliases for tests.
SKILLS = DEFAULT_SKILLS
NAMES = DEFAULT_NAMES


def _pairs(repo: Path) -> list[tuple[Path, Path]]:
    src_root = repo / "knowledge" / "shared-references"
    out: list[tuple[Path, Path]] = []
    for name in DEFAULT_NAMES:
        src = src_root / name
        for skill in DEFAULT_SKILLS:
            out.append((src, repo / "skills" / skill / "references" / name))
    for name, skills in SPECIAL_PROJECTIONS.items():
        src = src_root / name
        for skill in skills:
            out.append((src, repo / "skills" / skill / "references" / name))
    return out


def sync(repo: Path | None = None) -> list[str]:
    root = (repo or REPO).resolve()
    errors: list[str] = []
    for src, dest in _pairs(root):
        if not src.is_file():
            errors.append(f"SHARED_REF_SSOT_MISSING {src.as_posix()}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
    return errors


def check(repo: Path | None = None) -> list[str]:
    root = (repo or REPO).resolve()
    errors: list[str] = []
    for src, dest in _pairs(root):
        if not src.is_file():
            errors.append(f"SHARED_REF_SSOT_MISSING {src.as_posix()}")
            continue
        if not dest.is_file():
            errors.append(f"SHARED_REF_PROJECTION_MISSING {dest.as_posix()}")
            continue
        if dest.read_bytes() != src.read_bytes():
            errors.append(
                f"SHARED_REF_DRIFT {dest.as_posix()} != {src.as_posix()} (run compose --sync)"
            )
    ce_forbidden = root / "skills" / "code-engineering" / "references"
    for name in DEFAULT_NAMES:
        leaked = ce_forbidden / name
        if leaked.is_file():
            errors.append(f"SHARED_REF_CE_LEAK {leaked.as_posix()}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--check", action="store_true", help="Verify projections match SSOT")
    parser.add_argument("--sync", action="store_true", help="Copy SSOT into skill packages")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    if args.sync:
        errs = sync(repo)
    else:
        errs = check(repo)
    if errs:
        print("shared-references FAILED:")
        for e in errs:
            print(" ", e)
        return 1
    print("shared-references OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
