#!/usr/bin/env python3
"""Authoring SSOT for shared skill references → self-contained projections.

Source: knowledge/shared-references/*.md
Targets: skills/{operator-analysis,testcase-generation,source-proof,code-review}/references/
Do not project into code-engineering unless a METHOD names the file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SSOT = REPO / "knowledge" / "shared-references"
SKILLS = (
    "operator-analysis",
    "testcase-generation",
    "source-proof",
    "code-review",
)
NAMES = (
    "artifact-freshness.md",
    "completeness.md",
    "cpp-semantics.md",
    "evidence-quality.md",
    "finding-format.md",
)


def _pairs(repo: Path) -> list[tuple[Path, Path]]:
    src_root = repo / "knowledge" / "shared-references"
    out: list[tuple[Path, Path]] = []
    for name in NAMES:
        src = src_root / name
        for skill in SKILLS:
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
