# -*- coding: utf-8 -*-
"""Resource ACL for read-like shell commands.

`forbid_read` only means something if it is enforced per *resource*, not per
*tool*. A window handed a shell will reach a denied path through `Get-Content`
without any intent to evade -- its task told it to read the file and one door
was open. This module extracts the file arguments of read-like commands so they
can be checked against the same Action lease the Read tool uses.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

# Shell heads that emit file contents. Directory listings (ls / Get-ChildItem)
# are deliberately absent: structure probing leaks no artifact body.
_READ_HEADS = frozenset(
    {
        "cat",
        "type",
        "gc",
        "get-content",
        "head",
        "tail",
        "more",
        "less",
        "sed",
        "awk",
        "rg",
        "grep",
        "egrep",
        "fgrep",
        "findstr",
        "select-string",
        "sls",
        "python",
        "python3",
        "py",
    }
)
# `python -c "open(...)"` is a read; a plain script invocation is not our call.
_INLINE_PY = re.compile(r"-c\s|open\s*\(", re.I)
_GIT_READ = re.compile(r"^git\s+(show|diff|cat-file|log)\b", re.I)
_FLAG = re.compile(r"^[-/+]")
_PATHISH = re.compile(r"[\\/]|\.(ya?ml|md|json|jsonl|csv|txt|log|cpp|h|hpp|cc|py)$", re.I)


def _segments(command: str) -> list[str]:
    text = str(command or "")
    parts = re.split(r"\|\||&&|[|;\n]", text)
    return [p.strip() for p in parts if p.strip()]


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=False)
    except ValueError:
        return segment.split()


def extract_read_paths(command: str) -> list[str]:
    """Path-looking arguments of read-like segments, in command order."""
    out: list[str] = []
    for seg in _segments(command):
        tokens = _tokens(seg)
        if not tokens:
            continue
        head = tokens[0].strip().strip('"').strip("'").replace("\\", "/")
        head = head.rsplit("/", 1)[-1].lower()
        for suffix in (".exe", ".cmd", ".ps1"):
            if head.endswith(suffix):
                head = head[: -len(suffix)]
        is_git = bool(_GIT_READ.match(seg.strip()))
        if not is_git and head not in _READ_HEADS:
            continue
        if head in {"python", "python3", "py"} and not _INLINE_PY.search(seg):
            continue
        for raw in tokens[1:]:
            tok = raw.strip().strip('"').strip("'")
            if not tok or _FLAG.match(tok):
                continue
            if is_git and ":" in tok and not re.match(r"^[A-Za-z]:[\\/]", tok):
                # `git show <rev>:<path>` — the ACL cares about the path half.
                tok = tok.split(":", 1)[1]
            if not tok or not _PATHISH.search(tok):
                continue
            norm = tok.replace("\\", "/")
            if norm not in out:
                out.append(norm)
    return out


def _rel_under_agent_dir(path: str, project_root: Path | None) -> str | None:
    """Path relative to the operator's ``.ascendc-pilot`` dir, or None."""
    text = str(path or "").replace("\\", "/")
    marker = "/.ascendc-pilot/"
    if marker in text:
        return text.split(marker, 1)[1]
    if text.startswith(".ascendc-pilot/"):
        return text.split("/", 1)[1]
    if project_root is None:
        return None
    try:
        resolved = (Path(project_root) / text).resolve()
    except (OSError, ValueError):
        return None
    posix = resolved.as_posix()
    if marker in posix:
        return posix.split(marker, 1)[1]
    return None


def shell_read_denial(
    command: str,
    *,
    lease: dict[str, Any] | None,
    project_root: Path | None,
    agent: str = "",
) -> dict[str, Any] | None:
    """First lease-denied read target in ``command``, or None.

    Only the artifact tree is gated. Operator source and repo files keep the
    existing looser shell rules, so honest navigation is unaffected while the
    session-pack fences the Read tool enforces stop being tool-specific.
    """
    if not lease or str(lease.get("status") or "") != "active":
        return None
    if not (lease.get("forbidden_read_paths") or lease.get("allowed_read_paths")):
        return None
    from ascendc_pilot.authorize.lease import lease_allows_read_path, lease_authorizes_actor

    if not lease_authorizes_actor(lease, agent):
        # Actor identity is judged by the caller; here we only fence resources.
        return None
    for path in extract_read_paths(command):
        rel = _rel_under_agent_dir(path, project_root)
        if rel is None:
            continue
        check = lease_allows_read_path(lease, rel)
        if check.get("ok"):
            continue
        return {
            "error": str(check.get("error") or "ACTION_READ_SCOPE_DENIED"),
            "path": path,
            "rel": rel,
            "allowed_read_paths": list(lease.get("allowed_read_paths") or []),
            "forbidden_read_paths": list(lease.get("forbidden_read_paths") or []),
        }
    return None
