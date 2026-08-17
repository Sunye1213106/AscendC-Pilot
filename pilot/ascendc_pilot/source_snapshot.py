"""Immutable operator source snapshots for replay evidence binding."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def cache_root() -> Path:
    raw = (os.environ.get("ASCENDC_SNAPSHOT_CACHE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cache" / "ascendc-pilot" / "workspaces"


def snapshot_identity(project_root: Path) -> dict[str, Any]:
    fp = ""
    revision = None
    try:
        from testcase_agent.closure.ledger import baseline_fingerprint

        base = baseline_fingerprint(project_root) or {}
        fp = str(base.get("source_fingerprint") or "")
        revision = str(base.get("source_revision") or "") or None
    except Exception:  # noqa: BLE001
        fp = ""
        revision = None
    dirty = _dirty_patch_digest(project_root)
    workspace_id = f"SRC_{fp[:12]}" if fp else "SRC_unknown"
    return {
        "schema": "pilot-source-snapshot/v1",
        "source_fingerprint": fp,
        "git_revision": revision,
        "dirty_patch_digest": dirty,
        "workspace_id": workspace_id,
    }


def bind_snapshot_env(ident: dict[str, Any]) -> None:
    path = str(ident.get("workspace_path") or "").strip()
    if path:
        os.environ["ASCENDC_SNAPSHOT_WORKSPACE"] = path
    fp = str(ident.get("source_fingerprint") or "").strip()
    if fp:
        os.environ["ASCENDC_SOURCE_FINGERPRINT"] = fp


def _git_executable() -> str:
    explicit = (os.environ.get("GIT_EXECUTABLE") or os.environ.get("GIT") or "").strip()
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path)
        found = shutil.which(explicit)
        if found:
            return found
    found = shutil.which("git")
    if found:
        return found
    if os.name == "nt":
        for candidate in (
            r"C:\Program Files\Git\cmd\git.exe",
            r"C:\Program Files\Git\bin\git.exe",
            r"C:\Program Files (x86)\Git\cmd\git.exe",
        ):
            if Path(candidate).is_file():
                return candidate
    return "git"


def _run_git(project_root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            [_git_executable(), "-C", str(project_root), *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    except OSError:
        return None


def _dirty_patch_digest(project_root: Path) -> str:
    proc = _run_git(project_root, "diff", "HEAD")
    if proc is None or proc.returncode not in {0, 1}:
        return ""
    blob = (proc.stdout or "").encode("utf-8")
    if not blob.strip():
        return ""
    return hashlib.sha256(blob).hexdigest()


def materialize_source_snapshot(project_root: Path) -> dict[str, Any]:
    """Copy/archive operator sources into a fingerprint-addressed cache workspace."""
    ident = snapshot_identity(project_root)
    dest = cache_root() / str(ident.get("workspace_id") or "SRC_unknown")
    dest.mkdir(parents=True, exist_ok=True)
    root = Path(project_root).expanduser().resolve()
    # Copy the live operator tree (including uncommitted overlay). ``git archive
    # HEAD`` would snapshot the last commit and, from a nested operator dir,
    # extract the whole repo — both hide the PR worktree used by /uo-update.
    for role in ("op_host", "op_kernel", "common", "op_graph"):
        src = root / role
        if src.is_dir():
            target = dest / role
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(src, target)
    ident["workspace_path"] = dest.as_posix()
    ident["ok"] = dest.is_dir()
    if yaml is not None:
        meta = dest / "snapshot.yaml"
        meta.write_text(yaml.safe_dump(ident, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ident
