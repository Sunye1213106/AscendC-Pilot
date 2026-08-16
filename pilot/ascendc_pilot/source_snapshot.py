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


def _dirty_patch_digest(project_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "diff", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
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
    copied = False
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "archive", "--format=tar", "HEAD"],
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            import tarfile
            import io

            with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as tar:
                tar.extractall(dest)
            copied = True
    except Exception:  # noqa: BLE001
        copied = False
    if not copied:
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
