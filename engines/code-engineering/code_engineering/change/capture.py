# -*- coding: utf-8 -*-
"""Capture a reproducible Git change payload."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

from code_engineering.impact import parse_diff_ranges, parse_two_sided_spans


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def capture(
    project_root: Path | str,
    *,
    base: str = "HEAD",
    head: str = "",
    architecture: str = "",
    output: Path | str | None = None,
) -> dict[str, Any]:
    """Capture SHAs, unified diff, and parsed spans; optionally write YAML."""
    root = Path(project_root).expanduser().resolve()
    base_sha = _git(root, "rev-parse", base).strip()
    head_ref = head or "HEAD"
    head_sha = _git(root, "rev-parse", head_ref).strip()
    diff_args = ["diff", "--no-ext-diff", "--unified=3", base_sha]
    if head:
        diff_args.append(head_sha)
    diff_text = _git(root, *diff_args)
    payload: dict[str, Any] = {
        "schema": "ce-change-capture/v1",
        "base_sha": base_sha,
        "head_sha": head_sha,
        "diff": diff_text,
        "diff_spans": {
            path: [[start, end] for start, end in spans]
            for path, spans in parse_diff_ranges(diff_text).items()
        },
        "two_sided_spans": parse_two_sided_spans(diff_text),
    }
    if output is not None:
        path = Path(output)
        if not path.is_absolute():
            pilot = root / ".ascendc-pilot"
            path = pilot / architecture / path if architecture else pilot / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        payload["path"] = str(path)
    return payload


capture_change = capture
