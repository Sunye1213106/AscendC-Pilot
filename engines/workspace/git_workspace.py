# -*- coding: utf-8 -*-
"""Deterministic Workspace Manager. LLM must never clone."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ALLOWED_PR_HOSTS = frozenset({"gitcode.com", "github.com", "gitcode.net"})
_PR_PATH = re.compile(
    r"^/?(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:pulls|pull|merge_requests)/(?P<num>\d+)",
    re.I,
)
_PR_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:gitcode\.com|github\.com|gitcode\.net)/[^\s)\]>'\"，。]+",
    re.I,
)
_SHARED_DIR_NAMES = frozenset({"common", "shared"})
_SCAN_SUFFIXES = frozenset({".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx", ".c", ".txt", ".cmake"})
_SOURCE_SUFFIXES = frozenset({".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx", ".c"})
_VACANT_KEEP = frozenset({".opencode", ".cursor", ".vscode", ".idea", ".ascendc-pilot", ".gitignore"})


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


def extract_pr_url(text: str) -> str:
    """First allowlisted PR URL in intent / user text, or empty."""
    for match in _PR_URL_RE.finditer(str(text or "")):
        raw = match.group(0).rstrip(".,);]，。")
        parsed = parse_pr_ref(raw)
        if parsed.get("ok"):
            return str(parsed.get("url") or raw)
    return ""


def looks_like_pilot_checkout(path: Path | str | None) -> bool:
    """True when path looks like the AscendC-Pilot harness repo (do not clone into it)."""
    if path is None or not str(path).strip():
        return False
    root = Path(path).expanduser()
    try:
        root = root.resolve()
    except OSError:
        return False
    return (root / "pilot" / "ascendc_pilot").is_dir() and (root / "engines").is_dir()


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
            return {"ok": True, "path": dest, "fetched": False, "warning": fetched.stderr[-400:]}
        return {"ok": True, "path": dest, "fetched": True}
    cloned = _run_git(["clone", "--bare", clone_url, str(dest)])
    if cloned.returncode != 0:
        auth_hint = "获取 PR 失败：当前仓库可能需要 GitHub / GitCode 凭证。请设置 GITHUB_TOKEN 或 GITCODE_TOKEN 后重试，或改用本地代码。"
        return {
            "ok": False,
            "error": "MIRROR_CLONE_FAILED",
            "message_zh": auth_hint,
            "error_detail": (cloned.stderr or cloned.stdout)[-400:],
        }
    return {"ok": True, "path": dest, "fetched": True, "cloned": True}


def _resolve_sha(mirror: Path, ref: str) -> str:
    got = _run_git(["rev-parse", ref], cwd=mirror)
    if got.returncode == 0:
        return (got.stdout or "").strip()
    return ""


def _auth_headers(host: str) -> dict[str, str]:
    headers = {"User-Agent": "ascendc-pilot", "Accept": "application/json"}
    if "github" in host:
        token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    else:
        token = (os.environ.get("GITCODE_TOKEN") or os.environ.get("GITCODE_ACCESS_TOKEN") or "").strip()
        if token:
            headers["Authorization"] = f"token {token}"
    return headers


def fetch_pr_metadata(url: str) -> dict[str, Any]:
    """Provider adapter: GitHub / GitCode PR head/base. Never used by an LLM Action."""
    parsed = parse_pr_ref(url)
    if not parsed.get("ok"):
        return parsed
    host = str(parsed["host"])
    owner = str(parsed["owner"])
    repo = str(parsed["repo"])
    number = int(parsed["number"])
    if "github" in host:
        api = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
    else:
        api = f"https://{host}/api/v5/repos/{owner}/{repo}/pulls/{number}"
    req = Request(api, headers=_auth_headers(host), method="GET")
    try:
        with urlopen(req, timeout=20, context=ssl.create_default_context()) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = int(getattr(resp, "status", 200) or 200)
    except HTTPError as exc:
        code = int(exc.code)
        if code in {401, 403}:
            return {
                "ok": False,
                "error": "PR_FETCH_AUTH_REQUIRED",
                "message_zh": "获取 PR 失败：当前仓库需要 GitHub / GitCode 凭证。请设置 GITHUB_TOKEN 或 GITCODE_TOKEN 后重试，或改用本地代码。",
            }
        return {"ok": False, "error": "PR_METADATA_HTTP", "status": code}
    except URLError as exc:
        return {"ok": False, "error": "PR_METADATA_HTTP", "message_zh": str(exc.reason or exc)[:200]}
    if status != 200 or not body.strip():
        return {"ok": False, "error": "PR_METADATA_HTTP", "status": status}
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"ok": False, "error": "PR_METADATA_JSON"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "PR_METADATA_JSON"}
    head = data.get("head") if isinstance(data.get("head"), dict) else {}
    base = data.get("base") if isinstance(data.get("base"), dict) else {}
    head_sha = str(head.get("sha") or data.get("head_sha") or "").strip()
    base_sha = str(base.get("sha") or data.get("base_sha") or "").strip()
    base_ref = str(base.get("ref") or data.get("base_ref") or "").strip()
    if not head_sha and not base_sha:
        return {"ok": False, "error": "PR_METADATA_EMPTY"}
    return {
        "ok": True,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "base_ref": base_ref,
        "base_source": "provider",
    }


def fetch_pr_refs(mirror: Path, number: int) -> dict[str, str]:
    """Git fallback when provider metadata is unavailable."""
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
    return {
        "head_sha": head,
        "base_sha": base,
        "base_ref": "",
        "base_source": "default_branch_fallback",
    }


def worktree_home(
    *,
    host: str,
    owner: str,
    repo: str,
    number: int,
    head_sha: str,
    run_id: str,
) -> Path:
    sha12 = (head_sha or "unknown")[:12]
    rid = str(run_id or "run").strip() or "run"
    return (
        cache_root()
        / "workspaces"
        / str(host)
        / str(owner)
        / str(repo)
        / f"pr-{int(number)}"
        / sha12
        / rid
    )


def _safe_path_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-.")
    return token or "x"


def isolated_pr_dest(
    workspace_root: str | Path,
    *,
    host: str,
    owner: str,
    repo: str,
    number: int,
) -> Path:
    """Checkout target under the Host open directory. Never the open directory itself."""
    slug = (
        f"{_safe_path_token(host)}--"
        f"{_safe_path_token(owner)}--"
        f"{_safe_path_token(repo)}--"
        f"pr-{int(number)}"
    )
    return Path(workspace_root).expanduser() / ".ascendc-pr" / slug


def is_isolated_pr_tree(path: str | Path | None) -> bool:
    """True when path lives in a Host PR clone folder or a legacy cache worktree."""
    if path is None or not str(path).strip():
        return False
    root = Path(path).expanduser()
    try:
        root = root.resolve()
    except OSError:
        pass
    parts = [part.lower() for part in root.parts]
    if ".ascendc-pr" in parts:
        return True
    try:
        cache = (cache_root() / "workspaces").resolve()
        root.resolve().relative_to(cache)
        return True
    except Exception:  # noqa: BLE001
        return False


def _sha_matches(existing: str, wanted: str) -> bool:
    a = str(existing or "").strip().lower()
    b = str(wanted or "").strip().lower()
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def _lock_path(ws: Path) -> Path:
    return ws / "lock.yaml"


def acquire_workspace_lock(ws: Path, run_id: str) -> dict[str, Any]:
    rid = str(run_id or "").strip() or "run"
    lock = _lock_path(ws)
    if lock.is_file():
        try:
            import yaml

            data = yaml.safe_load(lock.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            data = {}
        other = str((data or {}).get("run_id") or "").strip()
        if other and other != rid:
            return {
                "ok": False,
                "error": "WORKSPACE_IN_USE",
                "message_zh": f"工作树正被另一个任务占用（run={other}）。请等待结束后再试。",
            }
    ws.mkdir(parents=True, exist_ok=True)
    body = (
        f"run_id: {rid}\n"
        f"locked_at: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
    )
    lock.write_text(body, encoding="utf-8")
    return {"ok": True, "path": str(lock)}


def create_worktree(mirror: Path, dest: Path, sha: str, *, run_id: str = "") -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not sha:
        return {"ok": False, "error": "EMPTY_SHA"}
    if dest.exists():
        if run_id:
            held = acquire_workspace_lock(dest.parent, run_id)
            if not held.get("ok"):
                return held
        existing = _resolve_sha(dest, "HEAD")
        if _sha_matches(existing, sha):
            return {"ok": True, "path": dest, "sha": existing or sha, "reused": True}
        if existing:
            checked = _run_git(["checkout", "--detach", sha], cwd=dest)
            if checked.returncode == 0:
                return {"ok": True, "path": dest, "sha": sha, "reused": True}
            fetched = _run_git(["fetch", "--all"], cwd=dest)
            if fetched.returncode == 0:
                checked = _run_git(["checkout", "--detach", sha], cwd=dest)
                if checked.returncode == 0:
                    return {"ok": True, "path": dest, "sha": sha, "reused": True}
            return {
                "ok": False,
                "error": "WORKTREE_SHA_MISMATCH",
                "message_zh": (
                    f"已有 checkout {dest} 的 HEAD={existing[:12]} 与目标 {sha[:12]} 不一致，"
                    "且无法原地 checkout。禁止 rmtree 算子源码。"
                ),
            }
        has_operator = (dest / "op_host").is_dir() or (dest / "op_kernel").is_dir()
        if has_operator:
            return {
                "ok": False,
                "error": "WORKTREE_EXISTS_NOT_GIT",
                "message_zh": (
                    f"{dest} 已有算子源码但不是可复用的 git checkout，拒绝 rmtree。"
                ),
            }
        # Leftover empty / metadata-only directory from a prior failed wipe.
        shutil.rmtree(dest, ignore_errors=True)
    if run_id:
        held = acquire_workspace_lock(dest.parent, run_id)
        if not held.get("ok"):
            return held
    added = _run_git(["worktree", "add", "--detach", str(dest), sha], cwd=mirror)
    if added.returncode != 0:
        cloned = _run_git(["clone", str(mirror), str(dest)])
        if cloned.returncode != 0:
            return {
                "ok": False,
                "error": "WORKTREE_FAILED",
                "message_zh": (added.stderr or cloned.stderr)[-400:],
            }
        _run_git(["checkout", "--detach", sha], cwd=dest)
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


def _is_operator_root(path: Path) -> bool:
    return (path / "op_host").is_dir() or (path / "op_kernel").is_dir()


def _add_root(roots: list[Path], seen: set[Path], candidate: Path) -> None:
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    if resolved in seen:
        return
    if not _is_operator_root(resolved):
        return
    seen.add(resolved)
    roots.append(resolved)


def list_operator_roots(worktree: Path, *, max_depth: int = 5) -> list[Path]:
    """Bounded walk for operator packages under a worktree."""
    roots: list[Path] = []
    seen: set[Path] = set()
    wt = Path(worktree)
    if _is_operator_root(wt):
        _add_root(roots, seen, wt)
        return roots
    stack: list[tuple[Path, int]] = [(wt, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth >= max_depth or not cur.is_dir():
            continue
        try:
            children = list(cur.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if _is_operator_root(child):
                _add_root(roots, seen, child)
                continue
            stack.append((child, depth + 1))
    return roots


def _shared_family_operators(worktree: Path, rel: str) -> list[Path]:
    parts = Path(rel).parts
    lowered = [p.lower() for p in parts]
    idx = -1
    for i, name in enumerate(lowered):
        if name in _SHARED_DIR_NAMES:
            idx = i
            break
    if idx < 0:
        return []
    parent = worktree.joinpath(*parts[:idx]) if idx else worktree
    out: list[Path] = []
    seen: set[Path] = set()
    if not parent.is_dir():
        return out
    try:
        children = list(parent.iterdir())
    except OSError:
        return out
    for child in children:
        if child.is_dir() and child.name.lower() not in _SHARED_DIR_NAMES:
            _add_root(out, seen, child)
    return out


def _basename_referenced_operators(worktree: Path, files: list[str], known: set[Path]) -> list[Path]:
    names = {Path(f).name for f in files if Path(f).suffix.lower() in _SOURCE_SUFFIXES}
    names = {n for n in names if n and len(n) > 3}
    if not names:
        return []
    hits: list[Path] = []
    seen: set[Path] = set(known)
    for op in list_operator_roots(worktree):
        if op in seen:
            continue
        matched = False
        for folder in ("op_host", "op_kernel"):
            base = op / folder
            if not base.is_dir():
                continue
            scanned = 0
            for path in base.rglob("*"):
                if scanned >= 400:
                    break
                if not path.is_file() or path.suffix.lower() not in _SCAN_SUFFIXES:
                    continue
                scanned += 1
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if any(name in text for name in names):
                    matched = True
                    break
            if matched:
                break
        if matched:
            _add_root(hits, seen, op)
    return hits


def detect_operator_roots(worktree: Path, files: list[str]) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    wt = Path(worktree)
    for rel in files:
        cur = (wt / rel).parent if not (wt / rel).is_dir() else (wt / rel)
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
            for fam in _shared_family_operators(wt, rel):
                _add_root(roots, seen, fam)
    if not roots:
        for extra in _basename_referenced_operators(wt, files, seen):
            _add_root(roots, seen, extra)
    if not roots and _is_operator_root(wt):
        _add_root(roots, seen, wt)
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


def _git_toplevel(path: Path) -> Path | None:
    if not path.is_dir():
        return None
    got = _run_git(["rev-parse", "--show-toplevel"], cwd=path)
    if got.returncode != 0:
        return None
    top = (got.stdout or "").strip()
    if not top:
        return None
    try:
        return Path(top).resolve()
    except OSError:
        return Path(top)


def _git_is_dirty(path: Path) -> bool:
    got = _run_git(["status", "--porcelain"], cwd=path)
    return bool((got.stdout or "").strip())


def _current_sha(path: Path) -> str:
    got = _run_git(["rev-parse", "HEAD"], cwd=path)
    if got.returncode != 0:
        return ""
    return (got.stdout or "").strip()


def _workspace_matches_pr(
    dest: Path, *, host: str, owner: str, repo: str, mirror: Path
) -> bool:
    remotes = (_run_git(["remote", "-v"], cwd=dest).stdout or "").lower().replace("\\", "/")
    slug = f"{host}/{owner}/{repo}".lower()
    if slug in remotes.replace(".git", ""):
        return True
    try:
        mirror_s = str(mirror.resolve()).lower().replace("\\", "/")
    except OSError:
        mirror_s = str(mirror).lower().replace("\\", "/")
    return mirror_s in remotes


def _workspace_is_vacant(dest: Path) -> bool:
    if not dest.exists():
        return True
    if not dest.is_dir():
        return False
    try:
        children = list(dest.iterdir())
    except OSError:
        return False
    for child in children:
        if child.name == ".git":
            continue
        if child.name in _VACANT_KEEP or child.name.startswith("."):
            continue
        return False
    return True


def _fetch_and_checkout(dest: Path, mirror: Path, sha: str) -> dict[str, Any]:
    if not sha:
        return {"ok": False, "error": "EMPTY_SHA", "message_zh": "PR head SHA 为空，无法检出。"}
    current = _current_sha(dest)
    if current == sha:
        return {"ok": True, "path": dest, "sha": sha, "already": True}
    if current and _git_is_dirty(dest):
        return {
            "ok": False,
            "error": "WORKSPACE_DIRTY",
            "message_zh": (
                f"OpenCode 工作区有未提交改动，无法检出 PR 到 {sha[:12]}。"
                "请提交或搁置改动，或把 --project 指到算子目录。"
            ),
        }
    fetched = _run_git(["fetch", str(mirror), sha], cwd=dest)
    if fetched.returncode != 0:
        fetched = _run_git(["fetch", "origin", sha], cwd=dest)
    if fetched.returncode != 0:
        return {
            "ok": False,
            "error": "WORKSPACE_FETCH_FAILED",
            "message_zh": (fetched.stderr or fetched.stdout or "fetch 失败")[-400:],
        }
    checked = _run_git(["-c", "advice.detachedHead=false", "checkout", "--detach", sha], cwd=dest)
    if checked.returncode != 0:
        checked = _run_git(
            ["-c", "advice.detachedHead=false", "checkout", "--detach", "FETCH_HEAD"],
            cwd=dest,
        )
    if checked.returncode != 0:
        return {
            "ok": False,
            "error": "WORKSPACE_CHECKOUT_FAILED",
            "message_zh": (checked.stderr or checked.stdout or "checkout 失败")[-400:],
        }
    return {"ok": True, "path": dest, "sha": sha}


def _init_fetch_checkout(dest: Path, mirror: Path, sha: str) -> dict[str, Any]:
    dest.mkdir(parents=True, exist_ok=True)
    git_dir = dest / ".git"
    if not git_dir.exists():
        inited = _run_git(["init"], cwd=dest)
        if inited.returncode != 0:
            return {
                "ok": False,
                "error": "WORKSPACE_CLONE_FAILED",
                "message_zh": (inited.stderr or inited.stdout or "git init 失败")[-400:],
            }
        added = _run_git(["remote", "add", "origin", str(mirror)], cwd=dest)
        if added.returncode != 0:
            _run_git(["remote", "set-url", "origin", str(mirror)], cwd=dest)
    else:
        _run_git(["remote", "set-url", "origin", str(mirror)], cwd=dest)
    return _fetch_and_checkout(dest, mirror, sha)


def materialize_workspace_head(
    dest: Path,
    mirror: Path,
    sha: str,
    *,
    host: str,
    owner: str,
    repo: str,
) -> dict[str, Any]:
    """Checkout PR head into the OpenCode workspace. Never rmtree the workspace."""
    root = Path(dest).expanduser()
    try:
        root = root.resolve()
    except OSError:
        pass
    if looks_like_pilot_checkout(root):
        return {
            "ok": False,
            "error": "PILOT_CHECKOUT_FORBIDDEN",
            "message_zh": (
                "当前目录是 AscendC-Pilot 仓，禁止把算子源码 clone 进来。"
                "请打开算子目录、算子仓根目录，或空的 OpenCode 工作区后再贴 PR。"
            ),
        }
    if _is_operator_root(root):
        return {"ok": True, "path": root, "skipped_checkout": True, "reason": "operator_package"}

    top = _git_toplevel(root) if root.is_dir() else None
    if top is not None:
        try:
            same_root = top.resolve() == root.resolve()
        except OSError:
            same_root = top == root
        if same_root:
            if _workspace_matches_pr(root, host=host, owner=owner, repo=repo, mirror=mirror):
                return _fetch_and_checkout(root, mirror, sha)
            ops = list_operator_roots(root)
            if ops:
                return {
                    "ok": True,
                    "path": root,
                    "skipped_checkout": True,
                    "reason": "local_operators",
                }
            return {
                "ok": False,
                "error": "WORKSPACE_REMOTE_MISMATCH",
                "message_zh": (
                    "当前 git 工作区不是这个 PR 对应的仓库。"
                    "请打开对应仓、算子目录，或空目录后再贴 PR。"
                ),
            }
        if _is_operator_root(root) or list_operator_roots(root):
            return {"ok": True, "path": root, "skipped_checkout": True, "reason": "nested_operator"}
        return {
            "ok": False,
            "error": "WORKSPACE_NESTED_GIT",
            "message_zh": (
                "当前目录是 git 仓库的子目录且未找到算子包。"
                "请打开仓根、算子目录或空目录。"
            ),
        }

    if root.is_dir() and list_operator_roots(root):
        return {"ok": True, "path": root, "skipped_checkout": True, "reason": "local_operators"}

    if _workspace_is_vacant(root):
        return _init_fetch_checkout(root, mirror, sha)

    return {
        "ok": False,
        "error": "WORKSPACE_NOT_EMPTY",
        "message_zh": (
            f"OpenCode 工作区 {root} 非空，且不是算子目录 / 对应 git 仓。"
            "请换空目录、打开算子包，或把 --project 指到算子路径。"
        ),
    }


def acquire_pull_request(
    url: str,
    *,
    run_id: str = "",
    goal_id: str = "",
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Fetch a PR and materialize source. Deterministic. Never called by an LLM Action.

    When ``workspace_root`` is set (OpenCode 工作区), checkout lands there and
    operator packages are discovered under it. Bare mirrors still live in cache.
    Without ``workspace_root``, keep the legacy cache worktree layout (tests).
    """
    parsed = parse_pr_ref(url)
    if not parsed.get("ok"):
        return parsed
    instance = str(run_id or goal_id or "run").strip() or "run"
    ws_arg = str(workspace_root or "").strip()
    if ws_arg:
        anchor = Path(ws_arg).expanduser()
        try:
            anchor = anchor.resolve()
        except OSError:
            pass
        if looks_like_pilot_checkout(anchor):
            return {
                "ok": False,
                "error": "PILOT_CHECKOUT_FORBIDDEN",
                "message_zh": (
                    "当前目录是 AscendC-Pilot 仓，禁止把算子源码 clone 进来。"
                    "请打开算子目录、算子仓根目录，或空的 OpenCode 工作区后再贴 PR。"
                ),
            }
    mirror_hit = ensure_bare_mirror(
        str(parsed["clone_url"]),
        host=str(parsed["host"]),
        owner=str(parsed["owner"]),
        repo=str(parsed["repo"]),
    )
    if not mirror_hit.get("ok"):
        return mirror_hit
    mirror = Path(mirror_hit["path"])
    meta = fetch_pr_metadata(str(parsed.get("url") or url))
    git_refs = fetch_pr_refs(mirror, int(parsed["number"]))
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
        if str(meta.get("error") or "") == "PR_FETCH_AUTH_REQUIRED":
            # Still try git refs; surface auth only if we have no shas at all.
            if not head_sha:
                return meta
    sha = head_sha or _resolve_sha(mirror, "HEAD")
    files = changed_files(mirror, base_sha, head_sha)
    diff = _run_git(["diff", f"{base_sha}...{head_sha}"], cwd=mirror)
    digest = _diff_digest(diff.stdout or "")
    skipped_checkout = False
    if ws_arg:
        dest = isolated_pr_dest(
            anchor,
            host=str(parsed["host"]),
            owner=str(parsed["owner"]),
            repo=str(parsed["repo"]),
            number=int(parsed["number"]),
        )
        head_wt = create_worktree(mirror, dest, sha, run_id=instance)
        if not head_wt.get("ok"):
            return head_wt
        head_path = Path(head_wt["path"])
        ws_home = dest
        base_path = ""
        skipped_checkout = False
    else:
        ws_home = worktree_home(
            host=str(parsed["host"]),
            owner=str(parsed["owner"]),
            repo=str(parsed["repo"]),
            number=int(parsed["number"]),
            head_sha=head_sha or "unknown",
            run_id=instance,
        )
        head_dir = ws_home / "head"
        base_dir = ws_home / "base"
        head_wt = create_worktree(mirror, head_dir, sha, run_id=instance)
        if not head_wt.get("ok"):
            return head_wt
        if base_sha and base_sha != head_sha:
            create_worktree(mirror, base_dir, base_sha, run_id=instance)
        head_path = Path(head_wt["path"])
        base_path = str(base_dir) if base_dir.is_dir() else ""
    if skipped_checkout and _is_operator_root(head_path):
        roots = [head_path]
    else:
        roots = detect_operator_roots(head_path, files)
        if not roots:
            roots = list_operator_roots(head_path)
    return {
        "ok": True if files or head_sha else False,
        "error": "" if (files or head_sha) else "EMPTY_DIFF",
        "source": parsed,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "base_ref": base_ref,
        "base_source": base_source,
        "diff_digest": digest,
        "changed_files": files,
        "worktree_head": str(head_path),
        "worktree_base": base_path,
        "workspace_home": str(ws_home),
        "run_id": instance,
        "skipped_checkout": skipped_checkout,
        "operator_roots": [str(p) for p in roots],
        "architectures": detect_architectures(roots[0]) if len(roots) == 1 else [],
        "changeset": {
            "schema": "pilot-changeset/v1",
            "base_sha": base_sha,
            "head_sha": head_sha,
            "base_ref": base_ref,
            "base_source": base_source,
            "diff_digest": digest,
            "changed_files": files,
        },
    }
