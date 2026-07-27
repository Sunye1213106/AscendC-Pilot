"""Shared freshness helpers for uo-update change_set / update_plan artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml


def change_set_path(uo_root: Path) -> Path:
    return uo_root / "diff" / "change_set.yaml"


def update_plan_path(uo_root: Path) -> Path:
    return uo_root / "summary" / "update_plan.yaml"


def _git_head(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return (result.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def load_change_set_if_fresh(
    uo_root: Path,
    *,
    repo_root: Path | None = None,
    expected_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Return change_set only when it matches current git HEAD and KB base revision.

    Freshness rules (all required when reusing):
    - ``change_set.head_revision == git rev-parse HEAD``
    - ``change_set.base_revision == manifest.source.revision``
    - optional ``expected_fingerprint`` match when provided
    """
    path = change_set_path(uo_root)
    if not path.is_file():
        return None
    doc = read_yaml(path)
    if not isinstance(doc, dict) or not doc:
        return None

    manifest = read_yaml(uo_root / "manifest.yaml") or {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    base_expected = str(source.get("revision") or "").strip()
    cs_base = str(doc.get("base_revision") or "").strip()
    cs_head = str(doc.get("head_revision") or "").strip()
    if not base_expected or not cs_base or cs_base != base_expected:
        return None

    root = Path(repo_root) if repo_root is not None else Path(str(source.get("root") or "")).resolve()
    if not str(root) or not root.is_dir():
        return None
    head_now = _git_head(root)
    if not head_now or not cs_head or cs_head != head_now:
        return None

    if expected_fingerprint is not None:
        fp = str(doc.get("fingerprint") or doc.get("source_fingerprint") or "")
        if fp and fp != expected_fingerprint:
            return None
    return doc


def load_update_plan_if_fresh(
    uo_root: Path,
    *,
    change_set: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return existing update_plan when present and consistent with change_set."""
    path = update_plan_path(uo_root)
    if not path.is_file():
        return None
    doc = read_yaml(path)
    if not isinstance(doc, dict) or not doc:
        return None
    if change_set is None:
        # Plan alone is never fresh without a verified change_set.
        return None
    plan_head = str(doc.get("head_revision") or "")
    cs_head = str(change_set.get("head_revision") or "")
    if plan_head and cs_head and plan_head != cs_head:
        return None
    plan_base = str(doc.get("base_revision") or "")
    cs_base = str(change_set.get("base_revision") or "")
    if plan_base and cs_base and plan_base != cs_base:
        return None
    return doc
