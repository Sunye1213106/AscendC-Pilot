# -*- coding: utf-8 -*-
"""Deterministic Workspace Manager. LLM must never clone."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ALLOWED_PR_HOSTS = frozenset({"gitcode.com", "github.com", "gitcode.net"})
_PR_PATH = re.compile(
    r"^/?(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:pulls|pull|merge_requests)/(?P<num>\d+)",
    re.I,
)


def cache_root() -> Path:
    raw = (os.environ.get("ASCENDC_WORKSPACE_CACHE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cache" / "ascendc-pilot"


def parse_pr_ref(url: str) -> dict[str, Any]:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in ALLOWED_PR_HOSTS:
        return {"ok": False, "error": "PR_HOST_NOT_ALLOWED", "host": host}
    match = _PR_PATH.search(parsed.path or "")
    if not match:
        return {"ok": False, "error": "PR_URL_SHAPE"}
    owner = match.group("owner")
    repo = match.group("repo")
    number = int(match.group("num"))
    clone_url = f"https://{host}/{owner}/{repo}.git"
    return {
        "ok": True,
        "host": host,
        "owner": owner,
        "repo": repo,
        "number": number,
        "clone_url": clone_url,
        "url": str(url).strip(),
    }


def _run_git(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=True,
        text=True,
    )


def ensure_bare_mirror(clone_url: str, *, host: str, owner: str, repo: str) -> dict[str, Any]:
    dest = cache_root() / "repos" / host / owner / f"{repo}.git"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_dir() and (dest / "HEAD").is_file():
        fetched = _run_git(["fetch", "--prune", "origin"], cwd=dest)
        if fetched.returncode != 0:
            # Still usable if fetch fails (offline tests with local mirror).
            return {"ok": True, "path": dest, "fetched": False, "warning": fetched.stderr[-400:]}
        return {"ok": True, "path": dest, "fetched": True}
    cloned = _run_git(["clone", "--bare", clone_url, str(dest)])
    if cloned.returncode != 0:
        return {
            "ok": False,
            "error": "MIRROR_CLONE_FAILED",
            "message_zh": (cloned.stderr or cloned.stdout)[-400:],
        }
    return {"ok": True, "path": dest, "fetched": True, "cloned": True}


def _resolve_sha(mirror: Path, ref: str) -> str:
    got = _run_git(["rev-parse", ref], cwd=mirror)
    if got.returncode == 0:
        return (got.stdout or "").strip()
    return ""


def fetch_pr_refs(mirror: Path, number: int) -> dict[str, str]:
    """Best-effort PR head/base shas from a bare mirror."""
    for spec in (
        f"pull/{number}/head",
        f"pulls/{number}/head",
        f"merge-requests/{number}/head",
        f"refs/pull/{number}/head",
    ):
        _run_git(["fetch", "origin", f"{spec}:refs/pull/{number}/head"], cwd=mirror)
    head = _resolve_sha(mirror, f"refs/pull/{number}/head") or _resolve_sha(mirror, "HEAD")
    base = (
        _resolve_sha(mirror, "origin/HEAD")
        or _resolve_sha(mirror, "origin/master")
        or _resolve_sha(mirror, "origin/main")
        or _resolve_sha(mirror, "HEAD")
    )
    return {"head_sha": head, "base_sha": base}


def create_worktree(mirror: Path, dest: Path, sha: str) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    if not sha:
        return {"ok": False, "error": "EMPTY_SHA"}
    added = _run_git(["worktree", "add", "--detach", str(dest), sha], cwd=mirror)
    if added.returncode != 0:
        # Fallback: clone the mirror into dest at sha (tests / old git).
        cloned = _run_git(["clone", str(mirror), str(dest)])
        if cloned.returncode != 0:
            return {
                "ok": False,
                "error": "WORKTREE_FAILED",
                "message_zh": (added.stderr or cloned.stderr)[-400:],
            }
        _run_git(["checkout", sha], cwd=dest)
    return {"ok": True, "path": dest, "sha": sha}


def _diff_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def changed_files(mirror: Path, base_sha: str, head_sha: str) -> list[str]:
    if not base_sha or not head_sha:
        return []
    got = _run_git(["diff", "--name-only", f"{base_sha}...{head_sha}"], cwd=mirror)
    if got.returncode != 0:
        return []
    return [line.strip() for line in (got.stdout or "").splitlines() if line.strip()]


def detect_operator_roots(worktree: Path, files: list[str]) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for rel in files:
        cur = (worktree / rel).parent if not (worktree / rel).is_dir() else (worktree / rel)
        while True:
            if (cur / "op_host").is_dir() or (cur / "op_kernel").is_dir():
                if cur not in seen:
                    seen.add(cur)
                    roots.append(cur)
                break
            if cur == worktree or cur.parent == cur:
                break
            cur = cur.parent
    if not roots and ((worktree / "op_host").is_dir() or (worktree / "op_kernel").is_dir()):
        roots.append(worktree)
    return roots


def detect_architectures(operator_root: Path) -> list[str]:
    names: list[str] = []
    for folder in ("op_host", "op_kernel"):
        base = operator_root / folder
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir() and child.name.lower().startswith("arch"):
                if child.name not in names:
                    names.append(child.name)
    return names


def acquire_pull_request(
    url: str,
    *,
    goal_id: str,
) -> dict[str, Any]:
    """Clone/fetch/worktree a PR. Deterministic. Never called by an LLM Action."""
    parsed = parse_pr_ref(url)
    if not parsed.get("ok"):
        return parsed
    mirror_hit = ensure_bare_mirror(
        str(parsed["clone_url"]),
        host=str(parsed["host"]),
        owner=str(parsed["owner"]),
        repo=str(parsed["repo"]),
    )
    if not mirror_hit.get("ok"):
        return mirror_hit
    mirror = Path(mirror_hit["path"])
    shas = fetch_pr_refs(mirror, int(parsed["number"]))
    head_sha = str(shas.get("head_sha") or "")
    base_sha = str(shas.get("base_sha") or "")
    ws = cache_root() / "workspaces" / str(goal_id or "goal")
    head_dir = ws / "head"
    base_dir = ws / "base"
    head_wt = create_worktree(mirror, head_dir, head_sha or _resolve_sha(mirror, "HEAD"))
    if not head_wt.get("ok"):
        return head_wt
    if base_sha and base_sha != head_sha:
        create_worktree(mirror, base_dir, base_sha)
    files = changed_files(mirror, base_sha, head_sha)
    diff = _run_git(["diff", f"{base_sha}...{head_sha}"], cwd=mirror)
    digest = _diff_digest(diff.stdout or "")
    roots = detect_operator_roots(Path(head_wt["path"]), files)
    return {
        "ok": True if files or head_sha else False,
        "error": "" if (files or head_sha) else "EMPTY_DIFF",
        "source": parsed,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "diff_digest": digest,
        "changed_files": files,
        "worktree_head": str(head_wt["path"]),
        "worktree_base": str(base_dir) if base_dir.is_dir() else "",
        "operator_roots": [str(p) for p in roots],
        "architectures": detect_architectures(roots[0]) if len(roots) == 1 else [],
        "changeset": {
            "schema": "pilot-changeset/v1",
            "base_sha": base_sha,
            "head_sha": head_sha,
            "diff_digest": digest,
            "changed_files": files,
        },
    }
