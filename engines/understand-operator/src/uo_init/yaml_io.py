# -*- coding: utf-8 -*-
"""Minimal YAML helpers shared by uo_init update and Pilot adapters."""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def require_yaml() -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    return yaml


def read_yaml(path: Path) -> dict[str, Any]:
    require_yaml()
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    require_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )
