"""Canonical scoped source path resolution (shared; no operator-specific names)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts.source_path import resolve_repo_source_path


class ScopePathMismatchError(RuntimeError):
    code = "OPERATOR_BOUNDARY_SCOPE_PATH_MISMATCH"

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


def strip_operator_prefix(scoped_path: str, op_name: str) -> str:
    raw = (scoped_path or "").replace("\\", "/").strip().lstrip("./")
    prefix = f"{(op_name or '').strip().strip('/')}/"
    if prefix != "/" and raw.startswith(prefix):
        return raw[len(prefix) :]
    return raw


def _is_under(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def resolve_scoped_source_path(
    project_root: Path,
    scoped_path: str,
    op_name: str,
    *,
    repository_root: Path | None = None,
    architecture: str = "arch35",
) -> dict[str, Any]:
    """Resolve a confirmed-scope relative path to an existing file."""
    root = Path(project_root).resolve()
    raw = (scoped_path or "").replace("\\", "/").strip()
    attempts: list[dict[str, str]] = []
    candidates: list[Path] = []

    def _add(label: str, path: Path) -> None:
        attempts.append({"label": label, "path": str(path)})
        candidates.append(path)

    if raw:
        _add("project_root/rel", root / raw)
        stripped = strip_operator_prefix(raw, op_name)
        if stripped != raw:
            _add("project_root/strip_op_prefix", root / stripped)
        _add("project_parent/rel", root.parent / raw)
        if repository_root is not None:
            _add("repository_root/rel", Path(repository_root).resolve() / raw)

    allowed_roots = [root, root.parent]
    if repository_root is not None:
        allowed_roots.append(Path(repository_root).resolve())

    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        if not any(_is_under(ar, resolved) for ar in allowed_roots):
            continue
        return {
            "ok": True,
            "path": resolved,
            "rel": resolved.relative_to(root).as_posix()
            if _is_under(root, resolved)
            else resolved.as_posix(),
            "attempts": attempts,
        }

    fallback = resolve_repo_source_path(root, raw, architecture=architecture)
    if fallback is None and repository_root is not None:
        fallback = resolve_repo_source_path(Path(repository_root), raw, architecture=architecture)
    if fallback is not None and fallback.is_file():
        attempts.append({"label": "resolve_repo_source_path", "path": str(fallback)})
        return {
            "ok": True,
            "path": fallback.resolve(),
            "rel": fallback.resolve().relative_to(root).as_posix()
            if _is_under(root, fallback.resolve())
            else fallback.resolve().as_posix(),
            "attempts": attempts,
        }

    return {
        "ok": False,
        "path": None,
        "rel": raw,
        "attempts": attempts,
        "error": "SCOPE_PATH_UNRESOLVED",
    }


def resolve_confirmed_sources(
    project_root: Path,
    scoped_paths: list[str],
    op_name: str,
    *,
    repository_root: Path | None = None,
    architecture: str = "arch35",
    fail_if_none_readable: bool = True,
) -> dict[str, Any]:
    """Resolve confirmed scope paths; optionally fail-closed when none readable."""
    readable: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for rel in scoped_paths:
        result = resolve_scoped_source_path(
            project_root,
            rel,
            op_name,
            repository_root=repository_root,
            architecture=architecture,
        )
        if result.get("ok"):
            readable.append(
                {
                    "scoped_path": rel,
                    "resolved_path": str(result["path"]),
                    "rel": result.get("rel") or rel,
                }
            )
        else:
            failed.append({"scoped_path": rel, "attempts": result.get("attempts") or []})

    out: dict[str, Any] = {
        "confirmed_source_count": len(scoped_paths),
        "readable_source_count": len(readable),
        "readable": readable,
        "failed": failed,
        "sample_confirmed_paths": list(scoped_paths)[:8],
    }
    if fail_if_none_readable and scoped_paths and not readable:
        detail = {
            "project_root": str(Path(project_root).resolve()),
            "op_name": op_name,
            **out,
            "resolution_attempts": failed[:5],
        }
        raise ScopePathMismatchError(
            "OPERATOR_BOUNDARY_SCOPE_PATH_MISMATCH: confirmed sources present but none readable",
            detail=detail,
        )
    return out
