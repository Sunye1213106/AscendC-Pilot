# -*- coding: utf-8 -*-
"""Capture a reproducible Git change payload (in memory; yaml write is optional)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

_HUNK = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
_DIFF_FILE = re.compile(r"^\+\+\+\s+b/(.+)$|^\+\+\+\s+(.+)$")
_OLD_FILE = re.compile(r"^---\s+a/(.+)$|^---\s+(.+)$")


def parse_diff_ranges(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Map path → list of (start_line, end_line) for new-file hunks."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        fm = _DIFF_FILE.match(line)
        if fm:
            current = (fm.group(1) or fm.group(2) or "").strip()
            if current == "/dev/null":
                current = None
            continue
        hm = _HUNK.match(line)
        if hm and current:
            start = int(hm.group(3))
            count = int(hm.group(4) or "1")
            end = start + max(count, 1) - 1
            ranges.setdefault(current, []).append((start, end))
    return ranges


def parse_two_sided_spans(diff_text: str) -> list[dict[str, Any]]:
    """Preserve both old/new hunk spans and add/delete/modify/rename status."""
    rows: list[dict[str, Any]] = []
    old_path = ""
    new_path = ""
    for line in diff_text.splitlines():
        old = _OLD_FILE.match(line)
        if old:
            old_path = (old.group(1) or old.group(2) or "").strip()
            continue
        new = _DIFF_FILE.match(line)
        if new:
            new_path = (new.group(1) or new.group(2) or "").strip()
            continue
        hunk = _HUNK.match(line)
        if not hunk:
            continue
        old_start, old_count = int(hunk.group(1)), int(hunk.group(2) or "1")
        new_start, new_count = int(hunk.group(3)), int(hunk.group(4) or "1")
        if old_path == "/dev/null":
            status = "add"
        elif new_path == "/dev/null":
            status = "delete"
        elif old_path and new_path and old_path != new_path:
            status = "rename"
        else:
            status = "modify"
        rows.append({
            "status": status,
            "old": {"file": old_path or None, "start": old_start, "end": old_start + max(old_count, 1) - 1},
            "new": {"file": new_path or None, "start": new_start, "end": new_start + max(new_count, 1) - 1},
        })
    return rows

_SOURCE_SUFFIXES = {".cpp", ".cc", ".c", ".h", ".hpp", ".cuh", ".cu", ".py"}
_WIN_GIT_CANDIDATES = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files\Git\bin\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
)


def git_executable() -> str:
    """Resolve git even when OpenCode/acp inherit a thin PATH (Windows)."""
    explicit = (os.environ.get("GIT_EXECUTABLE") or os.environ.get("GIT") or "").strip()
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path)
        found_explicit = shutil.which(explicit)
        if found_explicit:
            return found_explicit
    found = shutil.which("git")
    if found:
        return found
    if os.name == "nt":
        for candidate in _WIN_GIT_CANDIDATES:
            if Path(candidate).is_file():
                return candidate
    return "git"


def _run_git(root: Path, *args: str, allow_diff: bool = False) -> str:
    proc = subprocess.run(
        [git_executable(), *args],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if allow_diff and proc.returncode in {0, 1}:
        return proc.stdout or ""
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout or ""


def _operator_scope(op_root: Path) -> tuple[Path, list[str], str]:
    """Run git at the repo root, pathspec-limited to the operator tree."""
    op = Path(op_root).expanduser().resolve()
    try:
        top_text = _run_git(op, "rev-parse", "--show-toplevel").strip()
    except RuntimeError:
        return op, [], ""
    if not top_text:
        return op, [], ""
    top = Path(top_text).resolve()
    try:
        prefix = op.relative_to(top).as_posix().replace("\\", "/").strip("/")
    except ValueError:
        return op, [], ""
    if prefix in {"", "."}:
        return top, [], ""
    return top, ["--", prefix], prefix + "/"


def _rewrite_diff_prefix(diff_text: str, prefix: str) -> str:
    if not prefix or not diff_text:
        return diff_text
    needle_a = f"a/{prefix}"
    needle_b = f"b/{prefix}"
    out: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        out.append(line.replace(needle_a, "a/").replace(needle_b, "b/"))
    return "".join(out)


def _untracked_diffs(git_cwd: Path, pathspec: list[str], prefix: str) -> str:
    listed = _run_git(git_cwd, "ls-files", "--others", "--exclude-standard", *pathspec)
    chunks: list[str] = []
    for raw in listed.splitlines():
        rel = raw.replace("\\", "/").strip()
        if not rel:
            continue
        op_rel = rel[len(prefix) :] if prefix and rel.startswith(prefix) else rel
        if Path(op_rel).suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        abs_path = git_cwd / rel
        if not abs_path.is_file():
            continue
        try:
            text = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "\0" in text[:4096]:
            continue
        lines = text.splitlines()
        body = "".join(f"+{line}\n" for line in lines)
        n = max(len(lines), 1)
        chunks.append(
            f"diff --git a/{op_rel} b/{op_rel}\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            f"+++ b/{op_rel}\n"
            f"@@ -0,0 +1,{n} @@\n"
            f"{body}"
        )
    return "".join(chunks)


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
    git_cwd, pathspec, prefix = _operator_scope(root)
    base_sha = _run_git(git_cwd, "rev-parse", base).strip()
    head_ref = head or "HEAD"
    head_sha = _run_git(git_cwd, "rev-parse", head_ref).strip()
    diff_args = ["diff", "--no-ext-diff", "--unified=3", base_sha]
    if head:
        diff_args.append(head_sha)
    diff_args.extend(pathspec)
    diff_text = _run_git(git_cwd, *diff_args, allow_diff=True)
    if not head:
        extra = _untracked_diffs(git_cwd, pathspec, prefix)
        if extra:
            diff_text = (diff_text.rstrip() + "\n" + extra) if diff_text.strip() else extra
    diff_text = _rewrite_diff_prefix(diff_text, prefix)
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
