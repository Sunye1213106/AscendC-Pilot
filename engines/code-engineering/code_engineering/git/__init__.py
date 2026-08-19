# -*- coding: utf-8 -*-
"""Git / PR URL → in-memory diff. Fetch is required when a PR URL is present."""

from __future__ import annotations

import os
import re
import ssl
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from code_engineering.change.capture import (
    _operator_scope,
    _rewrite_diff_prefix,
    _run_git,
    capture,
    parse_diff_ranges,
    parse_two_sided_spans,
)

ALLOWED_PR_HOSTS = frozenset({"gitcode.com", "github.com", "gitcode.net"})
_PR_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:gitcode\.com|github\.com|gitcode\.net)/[^\s)\]>'\"，。]+",
    re.I,
)
_FETCH_REFS = (
    "pull/{n}/head",
    "pulls/{n}/head",
    "merge-requests/{n}/head",
)
_DEFAULT_BASE_REFS = ("origin/HEAD", "origin/master", "origin/main", "HEAD")


def parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    """GitCode / GitHub / GitLab URL shape: .../pulls|pull|merge_requests/{n}."""
    parsed = urlparse(str(pr_url or "").strip())
    path_parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(path_parts) >= 7 and path_parts[0] == "api" and path_parts[1] == "v5":
        path_parts = path_parts[3:]
    marker = None
    for candidate in ("pulls", "pull", "merge_requests"):
        if candidate in path_parts:
            marker = candidate
            break
    if marker is None:
        raise ValueError("URL is not a GitCode/GitHub-style pull request")
    marker_index = path_parts.index(marker)
    if marker_index < 2 or marker_index + 1 >= len(path_parts):
        raise ValueError("URL missing owner, repo, or PR number")
    owner = path_parts[marker_index - 2]
    repo = path_parts[marker_index - 1]
    try:
        pr_number = int(path_parts[marker_index + 1])
    except ValueError as exc:
        raise ValueError("PR number is not an integer") from exc
    return owner, repo, pr_number


def extract_pr_url(text: str) -> str:
    """First allowlisted PR URL in intent / user text, or empty."""
    for match in _PR_URL_RE.finditer(str(text or "")):
        raw = match.group(0).rstrip(".,);]")
        try:
            parse_pr_url(raw)
        except ValueError:
            continue
        host = _norm_host(urlparse(raw).netloc)
        if host in ALLOWED_PR_HOSTS:
            return raw
    return ""


def _norm_host(host: str) -> str:
    return str(host or "").lower().split(":")[0].removeprefix("www.")


def _host_of(url: str) -> str:
    return _norm_host(urlparse(str(url or "")).netloc)


def _repo_slug(url: str) -> tuple[str, str]:
    parsed = urlparse(str(url or "").strip())
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return "", ""
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return owner, repo


def _path_slug(url: str) -> tuple[str, str]:
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    path = parsed.path if parsed.scheme == "file" else (parsed.path if parsed.scheme else raw)
    if parsed.scheme in {"http", "https", "ssh", "git"}:
        return "", ""
    try:
        from pathlib import Path as _Path

        parts = _Path(path).parts
    except Exception:
        parts = tuple(p for p in path.replace("\\", "/").split("/") if p)
    if len(parts) < 2:
        return "", ""
    owner, repo = str(parts[-2]), str(parts[-1])
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return owner, repo


def _matching_remote(git_cwd, owner: str, repo: str, host: str) -> str:
    listing = _run_git(git_cwd, "remote", "-v")
    want_host = _norm_host(host)
    for line in listing.splitlines():
        bits = line.split()
        if len(bits) < 2:
            continue
        name, remote_url = bits[0], bits[1]
        if "(push)" in line:
            continue
        if remote_url.startswith("git@") or _norm_host(urlparse(remote_url).netloc):
            remote_host = _host_of(remote_url)
            remote_owner, remote_repo = _repo_slug(remote_url)
        else:
            remote_host = ""
            remote_owner, remote_repo = _path_slug(remote_url)
        if remote_owner != owner or remote_repo != repo:
            continue
        if remote_host == want_host:
            return name
        if remote_url.startswith("git@"):
            rest = remote_url.split(":", 1)[-1].rstrip("/")
            if rest.endswith(".git"):
                rest = rest[: -len(".git")]
            ssh_host = _norm_host(remote_url.split("@", 1)[-1].split(":", 1)[0])
            ssh_owner, _, ssh_repo = rest.partition("/")
            if ssh_host == want_host and ssh_owner == owner and ssh_repo == repo:
                return name
        if not remote_host:
            return name
    return ""


def _default_base(git_cwd) -> str:
    for ref in _DEFAULT_BASE_REFS:
        try:
            sha = _run_git(git_cwd, "rev-parse", "--verify", ref).strip()
        except RuntimeError:
            continue
        if sha:
            return ref
    return "HEAD"


def _git_paths_from_diff_header(line: str) -> list[str]:
    text = str(line or "").strip()
    if not text.startswith("diff --git "):
        return []
    rest = text[len("diff --git ") :]
    parts = rest.split()
    out: list[str] = []
    for part in parts:
        path = part
        if path.startswith("a/") or path.startswith("b/"):
            path = path[2:]
        if path and path not in {"/dev/null", "dev/null"}:
            out.append(path.replace("\\", "/"))
    return out


def _path_in_operator_prefix(path: str, prefix: str) -> bool:
    pref = str(prefix or "").replace("\\", "/")
    rel = str(path or "").replace("\\", "/").lstrip("/")
    if not pref or not rel:
        return False
    if pref.endswith("/"):
        return rel == pref.rstrip("/") or rel.startswith(pref)
    return rel == pref or rel.startswith(pref + "/")


def _filter_diff_by_prefix(diff_text: str, prefix: str) -> str:
    """Keep unified-diff file chunks whose paths fall under the operator prefix."""
    pref = str(prefix or "").replace("\\", "/")
    if not pref or not diff_text:
        return diff_text
    chunks: list[str] = []
    current: list[str] = []
    keep = False

    def flush() -> None:
        nonlocal current, keep
        if current and keep:
            chunks.extend(current)
        current = []
        keep = False

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            flush()
            current = [line]
            keep = any(_path_in_operator_prefix(p, pref) for p in _git_paths_from_diff_header(line))
            continue
        if not current:
            continue
        current.append(line)
        if line.startswith("--- ") or line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("a/") or path.startswith("b/"):
                path = path[2:]
            if path not in {"/dev/null", "dev/null"} and _path_in_operator_prefix(path, pref):
                keep = True
    flush()
    return "".join(chunks)


def _scope_http_diff(diff_text: str, project_root: Any) -> tuple[str, str]:
    """Restrict an HTTP PR patch to the operator pathspec and rewrite a/b prefixes."""
    if not project_root:
        return str(diff_text or ""), ""
    _cwd, _pathspec, prefix = _operator_scope(project_root)
    del _cwd, _pathspec
    if not prefix:
        return str(diff_text or ""), ""
    scoped = _filter_diff_by_prefix(diff_text, prefix)
    return _rewrite_diff_prefix(scoped, prefix), prefix


def _payload_from_diff(
    *,
    diff_text: str,
    base_sha: str,
    head_sha: str,
    pr: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "ce-change-capture/v1",
        "ok": bool(str(diff_text or "").strip()),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "diff": diff_text,
        "diff_spans": {
            path: [[start, end] for start, end in spans]
            for path, spans in parse_diff_ranges(diff_text).items()
        },
        "two_sided_spans": parse_two_sided_spans(diff_text),
        "source": source,
        "pr": pr,
    }
    if not payload["ok"]:
        payload["reason_code"] = "PR_EMPTY_DIFF"
        payload["message_zh"] = "已取得 PR，但 diff 为空。"
    return payload


def _fetch_via_remote(project_root, pr_url: str, architecture: str) -> dict[str, Any]:
    owner, repo, number = parse_pr_url(pr_url)
    host = _norm_host(urlparse(pr_url).netloc)
    git_cwd, pathspec, prefix = _operator_scope(project_root)
    del prefix
    remote = _matching_remote(git_cwd, owner, repo, host)
    if not remote:
        return {
            "ok": False,
            "reason_code": "PR_REMOTE_MISMATCH",
            "message_zh": (
                f"本地 git remote 与 PR 仓库 {host}/{owner}/{repo} 不一致。"
                "请在对应算子仓打开后再审，不要把陌生 URL 加成 remote。"
            ),
            "pr": {"owner": owner, "repo": repo, "number": number, "url": pr_url},
        }
    last_err = ""
    for spec in _FETCH_REFS:
        ref = spec.format(n=number)
        try:
            _run_git(git_cwd, "fetch", remote, ref)
        except RuntimeError as exc:
            last_err = str(exc)
            continue
        head_sha = _run_git(git_cwd, "rev-parse", "FETCH_HEAD").strip()
        base_ref = _default_base(git_cwd)
        try:
            base_sha = _run_git(git_cwd, "merge-base", base_ref, "FETCH_HEAD").strip()
        except RuntimeError:
            base_sha = _run_git(git_cwd, "rev-parse", base_ref).strip()
        captured = capture(
            project_root,
            base=base_sha,
            head=head_sha,
            architecture=architecture,
            output=None,
        )
        captured["ok"] = bool(str(captured.get("diff") or "").strip())
        captured["source"] = "pr_fetch"
        captured["pr"] = {
            "owner": owner,
            "repo": repo,
            "number": number,
            "url": pr_url,
            "remote": remote,
            "ref": ref,
        }
        if not captured["ok"]:
            captured["reason_code"] = "PR_EMPTY_DIFF"
            captured["message_zh"] = "已 fetch PR，但算子目录下 diff 为空。"
        return captured
    return {
        "ok": False,
        "reason_code": "PR_FETCH_FAILED",
        "message_zh": "已匹配 remote，但 pull/head 引用 fetch 失败。",
        "error_detail": last_err[:400],
        "pr": {"owner": owner, "repo": repo, "number": number, "url": pr_url, "remote": remote},
    }


def _auth_headers(host: str) -> dict[str, str]:
    headers = {"User-Agent": "ascendc-pilot"}
    token = ""
    if "github" in host:
        token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/vnd.github.diff"
    else:
        token = (os.environ.get("GITCODE_TOKEN") or os.environ.get("GITCODE_ACCESS_TOKEN") or "").strip()
        if token:
            headers["Authorization"] = f"token {token}"
    return headers


def _http_get(url: str, headers: dict[str, str]) -> tuple[int, str, str]:
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=30, context=ssl.create_default_context()) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return int(getattr(resp, "status", 200) or 200), body, ""
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400] if exc.fp else ""
        return int(exc.code), "", detail or str(exc)
    except URLError as exc:
        return 0, "", str(exc.reason or exc)


def _http_pr_diff(pr_url: str, project_root: Any = None) -> dict[str, Any]:
    owner, repo, number = parse_pr_url(pr_url)
    host = _norm_host(urlparse(pr_url).netloc)
    headers = _auth_headers(host)
    if "github" in host:
        urls = [f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"]
    else:
        urls = [
            f"https://{host}/api/v5/repos/{owner}/{repo}/pulls/{number}.diff",
            f"https://{host}/api/v5/repos/{owner}/{repo}/pulls/{number}",
        ]
    last_status = 0
    last_detail = ""
    for url in urls:
        status, body, detail = _http_get(url, headers)
        last_status, last_detail = status, detail
        if status in {401, 403}:
            return {
                "ok": False,
                "reason_code": "PR_FETCH_AUTH_REQUIRED",
                "message_zh": "拉取 PR patch 需要登录令牌。请设置 GITHUB_TOKEN 或 GITCODE_TOKEN 后重试。",
                "pr": {"owner": owner, "repo": repo, "number": number, "url": pr_url},
            }
        if status == 200 and body.strip():
            if body.lstrip().startswith("{") and "diff --git" not in body:
                continue
            scoped, prefix = _scope_http_diff(body, project_root)
            payload = _payload_from_diff(
                diff_text=scoped,
                base_sha="",
                head_sha="",
                pr={"owner": owner, "repo": repo, "number": number, "url": pr_url},
                source="pr_http",
            )
            if prefix and not payload.get("ok"):
                payload["message_zh"] = (
                    "已取得 PR，但按当前算子目录裁剪后 diff 为空。"
                    "请在对应算子仓打开后再审。"
                )
            return payload
    return {
        "ok": False,
        "reason_code": "PR_FETCH_FAILED",
        "message_zh": "无法通过 git fetch 或 HTTPS 取得 PR patch。",
        "error_detail": f"http={last_status} {last_detail}"[:400],
        "pr": {"owner": owner, "repo": repo, "number": number, "url": pr_url},
    }


def fetch_pr_diff(
    project_root: str | Any,
    pr_url: str,
    *,
    architecture: str = "",
    base_sha: str = "",
    head_sha: str = "",
) -> dict[str, Any]:
    """Fetch PR patch via isolated clone, matching local remote, else allowlisted HTTPS."""
    host = _norm_host(urlparse(str(pr_url or "")).netloc)
    if host not in ALLOWED_PR_HOSTS:
        return {
            "ok": False,
            "reason_code": "PR_HOST_NOT_ALLOWED",
            "message_zh": f"不支持的 PR 主机 {host}。只接受 gitcode.com / github.com。",
        }
    isolated = _capture_isolated_pr(
        project_root, architecture=architecture, base_sha=base_sha, head_sha=head_sha
    )
    if isolated is not None:
        return isolated
    fetched = _fetch_via_remote(project_root, pr_url, architecture)
    if fetched.get("ok") or fetched.get("reason_code") in {"PR_EMPTY_DIFF"}:
        return fetched
    if fetched.get("reason_code") == "PR_REMOTE_MISMATCH":
        http = _http_pr_diff(pr_url, project_root)
        if http.get("ok") or http.get("reason_code") == "PR_FETCH_AUTH_REQUIRED":
            return http
        fetched["http_fallback"] = http.get("reason_code")
        return fetched
    http = _http_pr_diff(pr_url, project_root)
    if http.get("ok"):
        return http
    return fetched if fetched.get("reason_code") else http


def _capture_isolated_pr(
    project_root: str | Any,
    *,
    architecture: str = "",
    base_sha: str = "",
    head_sha: str = "",
) -> dict[str, Any] | None:
    try:
        import sys

        ws = Path(__file__).resolve().parents[3] / "workspace"
        if str(ws) not in sys.path:
            sys.path.insert(0, str(ws))
        import pr_workspace as pw  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return None
    if not pw.is_isolated_pr_tree(project_root):
        return None
    return pw.capture_isolated_operator_diff(
        project_root, architecture=architecture, base_sha=base_sha, head_sha=head_sha
    )


def capture_change(
    project_root: str | Any,
    *,
    architecture: str = "",
    base: str = "HEAD",
    head: str = "",
    pr_url: str = "",
    intent: str = "",
) -> dict[str, Any]:
    """Workspace diff, or PR fetch when a URL is present. No silent local fallback for PRs."""
    url = str(pr_url or "").strip() or extract_pr_url(intent)
    if url:
        base_sha = "" if str(base or "").strip() in {"", "HEAD"} else str(base).strip()
        return fetch_pr_diff(
            project_root,
            url,
            architecture=architecture,
            base_sha=base_sha,
            head_sha=str(head or "").strip(),
        )
    payload = capture(
        project_root,
        base=base,
        head=head,
        architecture=architecture,
        output=None,
    )
    payload["ok"] = bool(str(payload.get("diff") or "").strip())
    payload["source"] = "workspace"
    if not payload["ok"]:
        payload["reason_code"] = "NO_CODE_CHANGE"
        payload["message_zh"] = "没有可审查的代码改动（工作区 diff 为空）。"
    return payload
