from __future__ import annotations

import fnmatch

DEFAULT_IGNORE_PATTERNS = [
    ".git/",
    ".venv/",
    "venv/",
    "node_modules/",
    ".understand/",
    ".understand-operator/",
    ".ascendc-agent/",
    ".testcase-generator/",
    "__pycache__/",
    ".pytest_cache/",
    "dist/",
    "build/",
    "*.pyc",
    "*.pyo",
    "*.egg-info/",
    ".mypy_cache/",
    ".ruff_cache/",
    "coverage.xml",
    "*.min.js",
    "*.min.css",
]


def should_ignore(rel_path: str, patterns: list[str]) -> bool:
    rel = rel_path.replace("\\", "/")
    ignored = False
    for pattern in patterns:
        if pattern.startswith("!"):
            neg = pattern[1:].strip()
            if fnmatch.fnmatch(rel, neg) or fnmatch.fnmatch(rel, f"**/{neg}"):
                ignored = False
            continue
        p = pattern.rstrip("/")
        if "/" in p:
            if rel.startswith(p + "/") or rel == p:
                ignored = True
        elif fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, f"**/{p}") or f"/{p}/" in f"/{rel}/":
            ignored = True
        elif rel.endswith("/" + p) or rel == p:
            ignored = True
    return ignored

