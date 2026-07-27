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


def collect_allowed_roots(
    project_root: Path,
    op_name: str,
    *,
    repository_root: Path | None = None,
    common_root: Path | None = None,
    uo_root: Path | None = None,
) -> list[Path]:
    """Allowed roots: operator package + common/shared only (never bare parent)."""
    root = Path(project_root).resolve()
    roots: list[Path] = [root]
    if common_root is not None:
        cr = Path(common_root).resolve()
        if cr.is_dir() and cr not in roots:
            roots.append(cr)
    # Load common_rel from latest scope_scan when available.
    scan_common = ""
    workspace = None
    if uo_root is not None:
        try:
            from uo.scripts._ir_io import read_yaml

            scans = sorted(Path(uo_root).glob("runs/*/scope/scope_scan.yaml"), reverse=True)
            if scans:
                scan = read_yaml(scans[0]) or {}
                scan_common = str(scan.get("common_rel") or "").replace("\\", "/").strip("/")
                wr = scan.get("workspace_root") or scan.get("repository_root")
                if wr:
                    workspace = Path(str(wr)).resolve()
        except Exception:  # noqa: BLE001
            pass
    repo = Path(repository_root).resolve() if repository_root is not None else workspace
    if repo is None and root.parent.is_dir():
        # Only use parent as *repository locator* for common/, never as free allowed root.
        maybe_common = root.parent / "common"
        if maybe_common.is_dir():
            repo = root.parent
    if repo is not None:
        if scan_common:
            cand = (repo / scan_common).resolve()
            if cand.is_dir() and cand not in roots:
                roots.append(cand)
        common_dir = (repo / "common").resolve()
        if common_dir.is_dir() and common_dir not in roots:
            roots.append(common_dir)
    return roots


def resolve_scoped_source_path(
    project_root: Path,
    scoped_path: str,
    op_name: str,
    *,
    repository_root: Path | None = None,
    common_root: Path | None = None,
    uo_root: Path | None = None,
    architecture: str = "arch35",
) -> dict[str, Any]:
    """Resolve a confirmed-scope relative path to an existing file."""
    root = Path(project_root).resolve()
    raw = (scoped_path or "").replace("\\", "/").strip()
    attempts: list[dict[str, str]] = []
    candidates: list[Path] = []
    allowed_roots = collect_allowed_roots(
        root,
        op_name,
        repository_root=repository_root,
        common_root=common_root,
        uo_root=uo_root,
    )

    def _add(label: str, path: Path) -> None:
        attempts.append({"label": label, "path": str(path)})
        candidates.append(path)

    if raw:
        _add("project_root/rel", root / raw)
        stripped = strip_operator_prefix(raw, op_name)
        if stripped != raw:
            _add("project_root/strip_op_prefix", root / stripped)
        if repository_root is not None:
            repo = Path(repository_root).resolve()
            _add("repository_root/rel", repo / raw)
            if stripped != raw:
                _add("repository_root/strip_op_prefix", repo / stripped)
            # common-relative under repository
            if raw.startswith("common/") or "/common/" in raw:
                _add("repository_root/common", repo / raw)

    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        if not any(_is_under(ar, resolved) for ar in allowed_roots):
            continue
        rel = (
            resolved.relative_to(root).as_posix()
            if _is_under(root, resolved)
            else None
        )
        if rel is None:
            # Prefer repository-relative when under repo/common
            for ar in allowed_roots:
                if _is_under(ar, resolved):
                    try:
                        # If ar is common, keep common/... form
                        if ar.name == "common":
                            rel = f"common/{resolved.relative_to(ar).as_posix()}"
                        else:
                            rel = resolved.relative_to(ar).as_posix()
                        break
                    except ValueError:
                        continue
        return {
            "ok": True,
            "path": resolved,
            "rel": rel or resolved.as_posix(),
            "attempts": attempts,
            "allowed_roots": [str(r) for r in allowed_roots],
        }

    fallback = resolve_repo_source_path(root, raw, architecture=architecture)
    if fallback is None and repository_root is not None:
        fallback = resolve_repo_source_path(Path(repository_root), raw, architecture=architecture)
    if fallback is not None and fallback.is_file():
        resolved = fallback.resolve()
        if any(_is_under(ar, resolved) for ar in allowed_roots):
            attempts.append({"label": "resolve_repo_source_path", "path": str(resolved)})
            return {
                "ok": True,
                "path": resolved,
                "rel": resolved.relative_to(root).as_posix()
                if _is_under(root, resolved)
                else resolved.as_posix(),
                "attempts": attempts,
                "allowed_roots": [str(r) for r in allowed_roots],
            }

    return {
        "ok": False,
        "path": None,
        "rel": raw,
        "attempts": attempts,
        "allowed_roots": [str(r) for r in allowed_roots],
        "error": "SCOPE_PATH_UNRESOLVED",
    }


def resolve_confirmed_sources(
    project_root: Path,
    scoped_paths: list[str],
    op_name: str,
    *,
    repository_root: Path | None = None,
    common_root: Path | None = None,
    uo_root: Path | None = None,
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
            common_root=common_root,
            uo_root=uo_root,
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
