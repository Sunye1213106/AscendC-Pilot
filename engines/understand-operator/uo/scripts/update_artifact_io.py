"""Shared freshness helpers for uo-update change_set / update_plan artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml


def change_set_path(uo_root: Path) -> Path:
    return uo_root / "diff" / "change_set.yaml"


def update_plan_path(uo_root: Path) -> Path:
    return uo_root / "summary" / "update_plan.yaml"


def load_change_set_if_fresh(
    uo_root: Path,
    *,
    expected_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Return existing change_set when present (and fingerprint matches if given)."""
    path = change_set_path(uo_root)
    if not path.is_file():
        return None
    doc = read_yaml(path)
    if not isinstance(doc, dict) or not doc:
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
    if change_set is not None:
        plan_head = str(doc.get("head_revision") or "")
        cs_head = str(change_set.get("head_revision") or "")
        if plan_head and cs_head and plan_head != cs_head:
            return None
        plan_base = str(doc.get("base_revision") or "")
        cs_base = str(change_set.get("base_revision") or "")
        if plan_base and cs_base and plan_base != cs_base:
            return None
    return doc
