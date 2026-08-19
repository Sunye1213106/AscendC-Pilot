#!/usr/bin/env python3
"""Regression runner for skills/<id>/examples/<case>/ directories.

Checks layout + expected artifact presence. Does not invoke an LLM.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def check_case(case_dir: Path) -> dict:
    readme = case_dir / "README.md"
    inp = case_dir / "input"
    exp = case_dir / "expected"
    ok = readme.is_file() and inp.is_dir() and exp.is_dir()
    expected_files = list(exp.rglob("*")) if exp.is_dir() else []
    expected_files = [p for p in expected_files if p.is_file()]
    if not expected_files:
        ok = False
    return {
        "path": case_dir.as_posix(),
        "ok": ok,
        "has_readme": readme.is_file(),
        "input_files": len(list(inp.rglob("*"))) if inp.is_dir() else 0,
        "expected_files": len(expected_files),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="skills/<id>/examples/<case> or examples root")
    ap.add_argument("--all", action="store_true", help="Scan cognitive + control-plane skill examples")
    args = ap.parse_args()

    cases: list[Path] = []
    if args.all or not args.path:
        for skill in (
            "operator-analysis",
            "testcase-generation",
            "source-proof",
            "code-review",
            "code-engineering",
        ):
            root = REPO / "skills" / skill / "examples"
            if root.is_dir():
                cases.extend(p for p in root.iterdir() if p.is_dir())
    else:
        p = Path(args.path)
        if not p.is_absolute():
            p = REPO / p
        if (p / "README.md").is_file():
            cases.append(p)
        elif p.is_dir():
            cases.extend(c for c in p.iterdir() if c.is_dir())

    results = [check_case(c) for c in sorted(cases)]
    ok = all(r["ok"] for r in results) and bool(results)
    print(json.dumps({"ok": ok, "count": len(results), "results": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
