# -*- coding: utf-8 -*-
"""Isolated PR workspace adapter.

A PR URL is an explicit remote source identity. It must never silently reuse
whatever local fork happens to be open in the Host. ``git_workspace`` owns
provider/mirror/worktree mechanics; this adapter enforces isolation and
structure-only operator × architecture resolution from changed-files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import git_workspace as _git

extract_pr_url = _git.extract_pr_url
parse_pr_ref = _git.parse_pr_ref
is_isolated_pr_tree = _git.is_isolated_pr_tree
isolated_pr_dest = _git.isolated_pr_dest

_SHARED_DIR_NAMES = frozenset({"common", "shared"})
_ARCH_RE = re.compile(r"^arch[0-9A-Za-z._-]+$", re.I)


def _is_operator_root(path: Path, *, worktree: Path | None = None) -> bool:
    return bool(_git._is_operator_root(path, worktree=worktree))


def _add_root(
    out: list[Path], seen: set[Path], candidate: Path, *, worktree: Path | None = None
) -> None:
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    if resolved in seen or not _is_operator_root(resolved, worktree=worktree):
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
            _add_root(out, seen, child, worktree=worktree)
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
            if _is_operator_root(cur, worktree=wt):
                _add_root(roots, seen, cur, worktree=wt)
                hit = True
                break
            if cur == wt or cur.parent == cur:
                break
            cur = cur.parent
        if not hit:
            for candidate in _shared_family_operators(wt, rel):
                _add_root(roots, seen, candidate, worktree=wt)
    if not roots and _is_operator_root(wt, worktree=wt):
        _add_root(roots, seen, wt, worktree=wt)
    return roots


def _file_belongs_to_operator(
    rel: str, operator_root: Path, *, worktree: Path | None = None
) -> bool:
    posix = Path(rel).as_posix().replace("\\", "/").strip("/")
    name = operator_root.name
    if worktree is not None:
        try:
            prefix = Path(operator_root).resolve().relative_to(Path(worktree).resolve()).as_posix()
        except ValueError:
            prefix = name
        prefix = prefix.replace("\\", "/").strip("/")
        if prefix and (posix == prefix or posix.startswith(prefix + "/")):
            return True
    marker = f"/{name}/"
    padded = f"/{posix}/"
    return marker in padded


def changed_architectures(
    operator_root: Path,
    changed_files: list[str],
    *,
    worktree: Path | None = None,
) -> list[str]:
    """Architecture tokens in changed paths that belong to one operator."""
    root = Path(operator_root)
    out: list[str] = []
    for rel in changed_files:
        if not _file_belongs_to_operator(rel, root, worktree=worktree):
            continue
        parts = Path(rel).parts
        try:
            search = parts[parts.index(root.name) :]
        except ValueError:
            search = parts
        for token in search:
            if _ARCH_RE.fullmatch(token) and token not in out:
                out.append(token)
    return out


def operator_arch_matrix(worktree: Path, changed_files: list[str]) -> list[dict[str, Any]]:
    """Per-operator architecture tokens from changed-files. No Glob of the repo root."""
    wt = Path(worktree)
    rows: list[dict[str, Any]] = []
    for root in detect_operator_roots(wt, changed_files):
        rows.append(
            {
                "operator_root": str(root),
                "operator_name": root.name,
                "architectures": changed_architectures(root, changed_files, worktree=wt),
            }
        )
    return rows


def _normalize_operator_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept matrix rows (``architectures[]``) or flattened pairs (``architecture``)."""
    if not rows:
        return []
    if any(isinstance(row.get("architectures"), list) for row in rows):
        out: list[dict[str, Any]] = []
        for row in rows:
            root = str(row.get("operator_root") or "").strip()
            if not root:
                continue
            arches = [str(a).strip() for a in (row.get("architectures") or []) if str(a).strip()]
            arch = str(row.get("architecture") or "").strip()
            if arch and arch not in arches:
                arches.append(arch)
            out.append(
                {
                    "operator_root": root,
                    "operator_name": str(row.get("operator_name") or Path(root).name),
                    "architectures": arches,
                }
            )
        return out
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        root = str(row.get("operator_root") or "").strip()
        if not root:
            continue
        if root not in grouped:
            grouped[root] = {
                "operator_root": root,
                "operator_name": str(row.get("operator_name") or Path(root).name),
                "architectures": [],
            }
            order.append(root)
        arch = str(row.get("architecture") or "").strip()
        if arch and arch not in grouped[root]["architectures"]:
            grouped[root]["architectures"].append(arch)
    return [grouped[key] for key in order]


def flatten_operator_targets(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand ``[(operator, architectures[])]`` into ``(operator, architecture)`` pairs."""
    pairs: list[dict[str, Any]] = []
    for row in matrix:
        root = str(row.get("operator_root") or "").strip()
        if not root:
            continue
        name = str(row.get("operator_name") or Path(root).name)
        arches = [str(a).strip() for a in (row.get("architectures") or []) if str(a).strip()]
        if not arches:
            pairs.append(
                {
                    "operator_root": root,
                    "operator_name": name,
                    "architecture": "",
                }
            )
            continue
        for arch in arches:
            pairs.append(
                {
                    "operator_root": root,
                    "operator_name": name,
                    "architecture": arch,
                }
            )
    return pairs


def resolve_targets_or_ask(
    acquire: dict[str, Any],
    *,
    workflow_id: str = "",
    host_root: str | Path | None = None,
) -> dict[str, Any]:
    """Pin unique (op, arch) pairs from a PR acquire, or AskQuestion when undetermined."""
    worktree_raw = str(acquire.get("worktree_head") or "").strip()
    worktree = Path(worktree_raw) if worktree_raw else None
    files = [str(x) for x in (acquire.get("changed_files") or []) if str(x)]
    raw_targets = [row for row in (acquire.get("operator_targets") or []) if isinstance(row, dict)]
    matrix = _normalize_operator_matrix(raw_targets)
    if not matrix and worktree is not None:
        matrix = operator_arch_matrix(worktree, files)
    if not matrix:
        roots = [Path(p) for p in (acquire.get("operator_roots") or []) if str(p).strip()]
        for root in roots:
            matrix.append(
                {
                    "operator_root": str(root),
                    "operator_name": root.name,
                    "architectures": changed_architectures(root, files, worktree=worktree),
                }
            )

    common = {
        "pr_url": str((acquire.get("source") or {}).get("url") or acquire.get("pr_url") or ""),
        "worktree_head": worktree_raw,
        "workspace_mode": str(acquire.get("workspace_mode") or "isolated_pr"),
        "source_revision": str(acquire.get("head_sha") or ""),
        "changed_files": files,
        "changeset": dict(acquire.get("changeset") or {}),
        "workflow_id": workflow_id,
        "project": str(host_root or worktree_raw or ""),
    }

    if not matrix:
        options: list[dict[str, str]] = []
        if worktree is not None:
            try:
                scanned = _git.list_operator_roots(worktree)
            except Exception:  # noqa: BLE001
                scanned = []
            options = [
                {"label": p.name, "value": str(p), "description": str(p)} for p in scanned
            ]
        return {
            "ok": False,
            "needs_human_decision": True,
            "decision_kind": "project",
            "reason_code": "OPERATOR_ROOTS_EMPTY",
            "operator_roots": [],
            "operator_targets": [],
            **common,
            "message_zh": (
                "PR changed-files 无法结构化归属到含 op_host/ 或 op_kernel/ 的算子目录。"
                "请从 clone 内结构中选择本次要分析的算子。"
            ),
            "ask_question": {
                "prompt_zh": "请选择要分析的算子目录（含 op_host/ 或 op_kernel/）",
                "options": options,
                "allow_free_text": bool(not options),
                "field": "project",
            },
        }

    missing = [row for row in matrix if not list(row.get("architectures") or [])]
    if missing:
        options = []
        for row in missing:
            root = Path(str(row.get("operator_root") or ""))
            try:
                scanned = _git.detect_architectures(root)
            except Exception:  # noqa: BLE001
                scanned = []
            for arch in scanned:
                options.append(
                    {
                        "label": f"{row.get('operator_name') or root.name}/{arch}",
                        "value": f"{root}::{arch}",
                    }
                )
        return {
            "ok": False,
            "needs_human_decision": True,
            "decision_kind": "architecture",
            "reason_code": "PR_ARCHITECTURE_UNRESOLVED",
            "operator_roots": [str(row.get("operator_root") or "") for row in matrix],
            "operator_targets": matrix,
            "architecture_options": [str(opt.get("value") or "") for opt in options],
            **common,
            "message_zh": (
                "PR 路径未带 arch* token。请从该算子仓内已有 architecture 中选择（选项原样）。"
            ),
            "ask_question": {
                "prompt_zh": "请选择本次分析的 architecture",
                "options": options,
                "allow_free_text": False,
                "field": "architecture",
            },
        }

    pairs = flatten_operator_targets(matrix)
    first = pairs[0]
    return {
        "ok": True,
        **common,
        "project": first["operator_root"],
        "architecture": first["architecture"],
        "operator_roots": [str(row.get("operator_root") or "") for row in matrix],
        "operator_targets": pairs,
        "changed_architectures": list(matrix[0].get("architectures") or []) if len(matrix) == 1 else [],
    }


def acquire_pull_request(
    url: str,
    *,
    run_id: str = "",
    goal_id: str = "",
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Fetch exact PR head into a new folder under the Host open directory.

    ``workspace_root`` is the OpenCode open directory (anchor). Checkout lands in
    ``<anchor>/.ascendc-pr/<host>--<owner>--<repo>--pr-<n>/``. Bare mirrors stay
    in cache. Local mode is selected by absence of a PR URL, not by skipping
    checkout into a local fork.
    """
    parsed = _git.parse_pr_ref(url)
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
        if _git.looks_like_pilot_checkout(anchor):
            return {
                "ok": False,
                "error": "PILOT_CHECKOUT_FORBIDDEN",
                "message_zh": (
                    "当前目录是 AscendC-Pilot 仓，禁止把算子源码 clone 进来。"
                    "请打开算子目录、算子仓根目录，或空的 OpenCode 工作区后再贴 PR。"
                ),
            }

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
        return {
            "ok": False,
            "error": "EMPTY_SHA",
            "message_zh": "PR head SHA 为空，无法建立隔离 workspace。",
        }

    changed = _git.changed_files(mirror, base_sha, head_sha)
    diff_text = ""
    if base_sha and head_sha:
        diff = _git._run_git(["diff", f"{base_sha}...{head_sha}"], cwd=mirror)
        diff_text = diff.stdout or ""
    digest = _git._diff_digest(diff_text)

    if ws_arg:
        dest = isolated_pr_dest(
            anchor,
            host=str(parsed["host"]),
            owner=str(parsed["owner"]),
            repo=str(parsed["repo"]),
            number=int(parsed["number"]),
        )
        materialized = _git.create_worktree(mirror, dest, exact_head, run_id=instance)
        if not materialized.get("ok"):
            return materialized
        head_path = Path(materialized["path"])
        ws_home = dest
    else:
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
    matrix = operator_arch_matrix(head_path, changed)
    pairs = flatten_operator_targets(matrix)
    changed_arches = list(matrix[0].get("architectures") or []) if len(matrix) == 1 else []
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
        "operator_targets": pairs,
        "changed_architectures": changed_arches,
        "architectures": (
            _git.detect_architectures(roots[0]) if len(roots) == 1 else []
        ),
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


def capture_isolated_operator_diff(
    operator_root: str | Path,
    *,
    architecture: str = "",
    base_sha: str = "",
    head_sha: str = "",
) -> dict[str, Any]:
    """Slice PR diff to one operator from an already-materialized isolated clone."""
    del architecture
    root = Path(operator_root).expanduser()
    try:
        root = root.resolve()
    except OSError:
        pass
    top_got = _git._run_git(["rev-parse", "--show-toplevel"], cwd=root)
    if top_got.returncode != 0:
        return {
            "ok": False,
            "reason_code": "PR_ISOLATED_NOT_GIT",
            "message_zh": "隔离 PR 工作区不是 git checkout，无法切片 diff。",
        }
    top = Path((top_got.stdout or "").strip() or str(root))
    try:
        rel = root.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        rel = "."
    pathspec = "." if rel in {".", ""} else rel
    head = str(head_sha or "").strip() or _git._resolve_sha(top, "HEAD")
    base = str(base_sha or "").strip()
    if not base:
        for ref in ("origin/HEAD", "origin/master", "origin/main"):
            candidate = _git._resolve_sha(top, ref)
            if candidate and candidate != head:
                merge = _git._run_git(["merge-base", candidate, head], cwd=top)
                base = (merge.stdout or "").strip() or candidate
                if base:
                    break
    if not base or not head:
        return {
            "ok": False,
            "reason_code": "PR_EMPTY_DIFF",
            "message_zh": "隔离 PR 工作区缺少 base/head SHA。",
            "source": "isolated_pr",
        }
    got = _git._run_git(["diff", f"{base}...{head}", "--", pathspec], cwd=top)
    diff = got.stdout or ""
    payload = {
        "ok": bool(diff.strip()),
        "source": "isolated_pr",
        "diff": diff,
        "base_sha": base,
        "head_sha": head,
        "pathspec": pathspec,
    }
    if not payload["ok"]:
        payload["reason_code"] = "PR_EMPTY_DIFF"
        payload["message_zh"] = "已取得隔离 PR 工作区，但该算子 pathspec 下 diff 为空。"
    return payload
