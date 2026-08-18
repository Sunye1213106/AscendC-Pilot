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
    # Prefer Clang-confirmed prepare output over coarse operator_boundary roots.
    candidates = [
        uo_root(project_root) / "summary" / "scope_set.yaml",
    ]
    if rid:
        candidates.append(runs_root(project_root) / rid / "scope" / "scope_set.yaml")
        candidates.append(runs_root(project_root) / rid / "source_scope.yaml")
        candidates.append(runs_root(project_root) / rid / "scope" / "scope_validated.yaml")
        candidates.append(runs_root(project_root) / rid / "scope" / "receipt.yaml")
    scope_dir = runs_root(project_root)
    if scope_dir.is_dir():
        for p in sorted(scope_dir.glob("*/scope/scope_set.yaml"), reverse=True):
            candidates.append(p)
            break
        for p in sorted(scope_dir.glob("*/scope/scope_validated.yaml"), reverse=True):
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
        raw_files = (
            data.get("confirmed_source_files")
            or data.get("allowed_source_files")
            or (data.get("frozen_scope") or {}).get("confirmed_source_files")
            or data.get("files")
            or data.get("confirmed_files")
            or []
        )
        collected: list[str] = []
        for f in raw_files if isinstance(raw_files, list) else []:
            if isinstance(f, dict):
                s = str(f.get("path") or f.get("file_path") or "").replace("\\", "/").strip()
            else:
                s = str(f).replace("\\", "/").strip()
            if s and s not in collected:
                collected.append(s)
        if not collected and not data.get("allowed_source_roots"):
            continue
        confirmed = True
        for r in (
            data.get("roots")
            or data.get("source_roots")
            or data.get("allowed_source_roots")
            or []
        ):
            s = str(r).replace("\\", "/").strip()
            if s and s not in roots:
                roots.append(s)
        for s in collected:
            if s not in files:
                files.append(s)
        break
    if not roots:
        # Derive roots from confirmed files when present; else coarse defaults.
        for f in files:
            top = f.split("/", 1)[0]
            if top and top not in roots and not top.startswith("."):
                roots.append(top)
        for d in ("op_host", "op_kernel", "common", "op_graph", "test_script"):
            if (project_root / d).is_dir() and d not in roots:
                roots.append(d)
        try:
            from ascendc_pilot.state import load_state

            tsr = str((load_state(project_root) or {}).get("test_script_root") or "").strip()
            if tsr and "test_script" not in roots:
                roots.append("test_script")
        except Exception:
            pass
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
            "pilot_cli": "available",
            "rg": "available" if rg else "missing",
            "python": "available" if python else "missing",
        },
        "paths": {
            "rg": rg,
            "python": python,
            "cann_root": cann_root,
        },
        "cann": {
            "ready": cann_ready,
            "root": cann_root,
            "issues": cann_issues[:12],
            "env_hints": [
                "UO_CANN_ROOT",
                "ASCEND_CANN_PACKAGE_PATH",
                "CANN_ROOT",
                "ASCEND_HOME_PATH",
                "<repo>/_cann/pkg",
                "~/.config/opencode/ascendc-cann-root",
            ],
        },
        "source_scope": scope,
        "commands": {
            "python": python,
            "rg": rg,
        },
        "note": (
            "Deterministic prepare snapshot. UO parse requires cann.ready=true. "
            "Use UO KB queries or a bounded source read within source_scope. "
            "OpenCode native grep/skill need rg on PATH; Host plugin recovers "
            "workflow SKILL.md without rg."
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
    """Roots/files for Lease allowed_source_* (posix, project-relative preferred).

    Prefer run-level ``runs/<run_id>/source_scope.yaml`` when present (set at start).
    """
    from ascendc_pilot.paths import runs_root

    rid = str(run_id or "").strip()
    if rid:
        try:
            scope_path = runs_root(project_root) / rid / "source_scope.yaml"
            cached = _load_yaml(scope_path)
            if cached.get("allowed_source_roots") or cached.get("allowed_source_files"):
                return {
                    "allowed_source_roots": [
                        str(x).replace("\\", "/").lstrip("/")
                        for x in (cached.get("allowed_source_roots") or [])
                        if str(x).strip()
                    ],
                    "allowed_source_files": [
                        str(x).replace("\\", "/").lstrip("/")
                        for x in (cached.get("allowed_source_files") or [])
                        if str(x).strip()
                    ],
                }
        except Exception:  # noqa: BLE001
            pass
    scope = _source_scope(project_root, run_id=run_id)
    roots = [str(r).replace("\\", "/").lstrip("/") for r in (scope.get("roots") or []) if str(r).strip()]
    files = [
        str(f).replace("\\", "/").lstrip("/")
        for f in (scope.get("file_paths") or [])
        if str(f).strip()
    ]
    return {"allowed_source_roots": roots, "allowed_source_files": files}


def run_source_scope_roots(project_root: Path, *, run_id: str = "") -> list[Path]:
    """ScopeSet confirmed roots ∩ current lease source roots. Never the whole repo."""
    scope = source_scope_for_lease(project_root, run_id=run_id)
    roots = [
        str(x).replace("\\", "/").lstrip("/")
        for x in (scope.get("allowed_source_roots") or [])
        if str(x).strip() and str(x).strip() not in {".", "./"}
    ]
    try:
        from ascendc_pilot.authorize.lease import load_lease
        from ascendc_pilot.state import load_state

        st = load_state(project_root) or {}
        rid = str(run_id or st.get("run_id") or "").strip()
        lease = load_lease(project_root, run_id=rid) if rid else {}
        lease_roots = [
            str(x).replace("\\", "/").lstrip("/")
            for x in (lease.get("allowed_source_roots") or [])
            if str(x).strip()
        ]
        if lease_roots:
            allowed = set(lease_roots)
            roots = [r for r in roots if r in allowed] or lease_roots
    except Exception:  # noqa: BLE001
        pass
    out: list[Path] = []
    seen: set[str] = set()
    for rel in roots:
        key = rel.replace("\\", "/")
        if key in seen or key in {".", ".."}:
            continue
        seen.add(key)
        out.append((Path(project_root) / rel).resolve())
    return out
