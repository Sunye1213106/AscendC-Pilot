# -*- coding: utf-8 -*-
"""Isolated PR workspace adapter.

A PR URL is an explicit remote source identity. It must never silently reuse
whatever local fork happens to be open in the Host. ``git_workspace_legacy``
owns provider/mirror/worktree mechanics; this adapter enforces isolation and
structure-only operator scope resolution.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import git_workspace_legacy as _git

extract_pr_url = _git.extract_pr_url
parse_pr_ref = _git.parse_pr_ref

_SHARED_DIR_NAMES = frozenset({"common", "shared"})
_ARCH_RE = re.compile(r"^arch[0-9A-Za-z._-]+$", re.I)


def _is_operator_root(path: Path) -> bool:
    return (path / "op_host").is_dir() or (path / "op_kernel").is_dir()


def _add_root(out: list[Path], seen: set[Path], candidate: Path) -> None:
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    if resolved in seen or not _is_operator_root(resolved):
        return
    seen.add(resolved)
    out.append(resolved)


def _shared_family_operators(worktree: Path, rel: str) -> list[Path]:
    parts = Path(rel).parts
    lowered = [part.lower() for part in parts]
    shared_index = next(
        (idx for idx, name in enumerate(lowered) if name in _SHARED_DIR_NAMES),
        -1,
    )
    if shared_index < 0:
        return []
    parent = worktree.joinpath(*parts[:shared_index]) if shared_index else worktree
    if not parent.is_dir():
        return []
    out: list[Path] = []
    seen: set[Path] = set()
    try:
        children = sorted(parent.iterdir())
    except OSError:
        return []
    for child in children:
        if child.is_dir() and child.name.lower() not in _SHARED_DIR_NAMES:
            _add_root(out, seen, child)
    return out


def detect_operator_roots(worktree: Path, changed_files: list[str]) -> list[Path]:
    """Resolve candidates from changed paths and structural roots only."""
    wt = Path(worktree)
    roots: list[Path] = []
    seen: set[Path] = set()
    for rel in changed_files:
        target = wt / rel
        cur = target if target.is_dir() else target.parent
        hit = False
        while True:
            if _is_operator_root(cur):
                _add_root(roots, seen, cur)
                hit = True
                break
            if cur == wt or cur.parent == cur:
                break
            cur = cur.parent
        if not hit:
            for candidate in _shared_family_operators(wt, rel):
                _add_root(roots, seen, candidate)
    if not roots and _is_operator_root(wt):
        _add_root(roots, seen, wt)
    return roots


def changed_architectures(operator_root: Path, changed_files: list[str]) -> list[str]:
    """Architecture tokens explicitly present in changed paths under one operator."""
    root = Path(operator_root)
    out: list[str] = []
    for rel in changed_files:
        path = Path(rel)
        try:
            abs_path = (root.parents[0] / path).resolve()
        except OSError:
            abs_path = root / path
        # Use path tokens, not source text or operator names.
        for token in path.parts:
            if _ARCH_RE.fullmatch(token) and token not in out:
                out.append(token)
        # ``rel`` may be repository-relative while root is nested; token scan is
        # intentionally sufficient and deterministic.
        del abs_path
    return out


def acquire_pull_request(
    url: str,
    *,
    run_id: str = "",
    goal_id: str = "",
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Fetch exact PR head into an isolated cache worktree.

    ``workspace_root`` is accepted only for compatibility and deliberately
    ignored as a checkout target. Local mode is selected by absence of a PR URL.
    """
    del workspace_root
    parsed = _git.parse_pr_ref(url)
    if not parsed.get("ok"):
        return parsed

    instance = str(run_id or goal_id or "run").strip() or "run"
    mirror_hit = _git.ensure_bare_mirror(
        str(parsed["clone_url"]),
        host=str(parsed["host"]),
        owner=str(parsed["owner"]),
        repo=str(parsed["repo"]),
    )
    if not mirror_hit.get("ok"):
        return mirror_hit
    mirror = Path(mirror_hit["path"])

    meta = _git.fetch_pr_metadata(str(parsed.get("url") or url))
    git_refs = _git.fetch_pr_refs(mirror, int(parsed["number"]))
    if meta.get("ok"):
        head_sha = str(meta.get("head_sha") or git_refs.get("head_sha") or "")
        base_sha = str(meta.get("base_sha") or git_refs.get("base_sha") or "")
        base_ref = str(meta.get("base_ref") or "")
        base_source = "provider"
    else:
        head_sha = str(git_refs.get("head_sha") or "")
        base_sha = str(git_refs.get("base_sha") or "")
        base_ref = str(git_refs.get("base_ref") or "")
        base_source = "default_branch_fallback"
        if str(meta.get("error") or "") == "PR_FETCH_AUTH_REQUIRED" and not head_sha:
            return meta

    exact_head = head_sha or _git._resolve_sha(mirror, "HEAD")
    if not exact_head:
        return {"ok": False, "error": "EMPTY_SHA", "message_zh": "PR head SHA 为空，无法建立隔离 workspace。"}

    changed = _git.changed_files(mirror, base_sha, head_sha)
    diff = _git._run_git(["diff", f"{base_sha}...{head_sha}"], cwd=mirror)
    digest = _git._diff_digest(diff.stdout or "")

    ws_home = _git.worktree_home(
        host=str(parsed["host"]),
        owner=str(parsed["owner"]),
        repo=str(parsed["repo"]),
        number=int(parsed["number"]),
        head_sha=exact_head,
        run_id=instance,
    )
    head_dir = ws_home / "head"
    materialized = _git.create_worktree(mirror, head_dir, exact_head, run_id=instance)
    if not materialized.get("ok"):
        return materialized

    head_path = Path(materialized["path"])
    roots = detect_operator_roots(head_path, changed)
    changed_arches = changed_architectures(roots[0], changed) if len(roots) == 1 else []
    return {
        "ok": True,
        "error": "",
        "source": parsed,
        "workspace_mode": "isolated_pr",
        "base_sha": base_sha,
        "head_sha": exact_head,
        "base_ref": base_ref,
        "base_source": base_source,
        "diff_digest": digest,
        "changed_files": changed,
        "worktree_head": str(head_path),
        "worktree_base": "",
        "workspace_home": str(ws_home),
        "run_id": instance,
        "skipped_checkout": False,
        "operator_roots": [str(path) for path in roots],
        "changed_architectures": changed_arches,
        "architectures": _git.detect_architectures(roots[0]) if len(roots) == 1 else [],
        "changeset": {
            "schema": "pilot-changeset/v1",
            "base_sha": base_sha,
            "head_sha": exact_head,
            "base_ref": base_ref,
            "base_source": base_source,
            "diff_digest": digest,
            "changed_files": changed,
        },
    }
