"""Deterministic environment capability snapshot for producer session packs."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _which(name: str) -> str | None:
    return shutil.which(name)


def _source_scope(project_root: Path, *, run_id: str = "") -> dict[str, Any]:
    from ascendc_pilot.paths import runs_root, uo_root

    roots: list[str] = []
    files: list[str] = []
    confirmed = False
    rid = str(run_id or "").strip()
    candidates = []
    if rid:
        candidates.append(runs_root(project_root) / rid / "scope" / "scope_confirmed.yaml")
    # Latest-ish fallback
    scope_dir = runs_root(project_root)
    if scope_dir.is_dir():
        for p in sorted(scope_dir.glob("*/scope/scope_confirmed.yaml"), reverse=True):
            candidates.append(p)
            break
    boundary = _load_yaml(uo_root(project_root) / "ir" / "operator_boundary.yaml")
    for key in ("roots", "source_roots", "include_roots"):
        for r in boundary.get(key) or []:
            s = str(r).replace("\\", "/").strip()
            if s and s not in roots:
                roots.append(s)
    for path in candidates:
        data = _load_yaml(path)
        if not data:
            continue
        confirmed = True
        for r in data.get("roots") or data.get("source_roots") or []:
            s = str(r).replace("\\", "/").strip()
            if s and s not in roots:
                roots.append(s)
        for f in data.get("files") or data.get("confirmed_files") or []:
            if isinstance(f, dict):
                s = str(f.get("path") or f.get("file_path") or "").replace("\\", "/").strip()
            else:
                s = str(f).replace("\\", "/").strip()
            if s and s not in files:
                files.append(s)
        break
    if not roots:
        # Sensible defaults under operator project
        for d in ("op_host", "op_kernel", "common", "op_graph"):
            if (project_root / d).is_dir() and d not in roots:
                roots.append(d)
    return {
        "confirmed": confirmed,
        "files": len(files),
        "file_paths": files[:200],
        "roots": roots,
    }


def build_environment_capabilities(
    project_root: Path,
    *,
    architecture: str = "",
    run_id: str = "",
    host: str = "opencode",
) -> dict[str, Any]:
    """Build a small deterministic capability document for producer sessions."""
    root = Path(project_root).resolve()
    acp = _which("acp")
    rg = _which("rg") or _which("ripgrep")
    python = _which("python") or _which("python3")
    scope = _source_scope(root, run_id=run_id)

    cann_root = None
    cann_ready = False
    cann_issues: list[str] = []
    try:
        from uo_init import paths as uo_paths

        cann_path, cann_issues = uo_paths.require_cann_ready()
        cann_root = cann_path.as_posix() if cann_path is not None else None
        cann_ready = not cann_issues
    except Exception as exc:  # noqa: BLE001
        cann_issues = [f"uo_init.paths unavailable: {exc}"]

    return {
        "version": 1,
        "kind": "environment_capabilities",
        "host": host,
        "platform": platform.system().lower(),
        "project_root": root.as_posix(),
        "architecture": str(architecture or "").strip() or None,
        "tools": {
            "read": "available",
            "grep": "available",
            "bash": "available",
            "acp": "available" if acp else "missing",
            "rg": "available" if rg else "missing",
            "python": "available" if python else "missing",
        },
        "paths": {
            "acp": acp,
            "rg": rg,
            "python": python,
            "cann_root": cann_root,
        },
        "cann": {
            "ready": cann_ready,
            "root": cann_root,
            "issues": cann_issues[:12],
            "env_hints": ["UO_CANN_ROOT", "ASCEND_CANN_PACKAGE_PATH", "CANN_ROOT"],
        },
        "source_scope": scope,
        "commands": {
            "python": python,
            "acp": acp,
            "rg": rg,
        },
        "note": (
            "Deterministic prepare snapshot. UO parse requires cann.ready=true. "
            "Use UO KB queries or a bounded source read within source_scope."
        ),
    }


def write_environment_capabilities(
    session_dir: Path,
    project_root: Path,
    *,
    architecture: str = "",
    run_id: str = "",
    host: str = "opencode",
) -> Path:
    if yaml is None:
        raise RuntimeError("PyYAML required")
    path = Path(session_dir) / "environment_capabilities.yaml"
    data = build_environment_capabilities(
        project_root, architecture=architecture, run_id=run_id, host=host
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )
    return path


def source_scope_for_lease(project_root: Path, *, run_id: str = "") -> dict[str, list[str]]:
    """Roots/files for Lease allowed_source_* (posix, project-relative preferred)."""
    scope = _source_scope(project_root, run_id=run_id)
    roots = [str(r).replace("\\", "/").lstrip("/") for r in (scope.get("roots") or []) if str(r).strip()]
    files = [
        str(f).replace("\\", "/").lstrip("/")
        for f in (scope.get("file_paths") or [])
        if str(f).strip()
    ]
    return {"allowed_source_roots": roots, "allowed_source_files": files}
