#!/usr/bin/env python3
"""Fail when a production/runtime file reintroduces the retired CBM integration."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


PATTERN = re.compile(r"(?i)(codebase[-_ ]memory|\bcbm\b|cbm_project|cbm_db_path)")
ALLOWLIST = {
    "scripts/check_no_cbm.py",
}
SKIP_PARTS = {
    ".git",
    "_archive",
    "generated",
    ".ascendc-pilot",
    ".probe_cache",
    ".cursor",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
}
TEXT_EXTENSIONS = {".py", ".md", ".yaml", ".yml", ".json", ".ps1", ".sh", ".toml", ".txt"}


def find_violations(root: Path) -> list[str]:
    violations: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in SKIP_PARTS and not name.startswith(".tmp-") and not name.endswith(".egg-info")
        ]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            rel = path.relative_to(root).as_posix()
            if rel in ALLOWLIST:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(lines, start=1):
                if PATTERN.search(line):
                    violations.append(f"{rel}:{number}: {line.strip()}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    violations = find_violations(args.repo.resolve())
    if violations:
        print("retired CBM integration references found:")
        print("\n".join(violations))
        return 1
    print("CBM negative gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
