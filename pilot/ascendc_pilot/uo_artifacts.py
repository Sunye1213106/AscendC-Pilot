# -*- coding: utf-8 -*-
"""YAML helpers for Pilot (replaces uo.scripts._ir_io for ACP)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from uo_init.yaml_io import read_yaml, require_yaml, write_yaml
except ImportError:  # pragma: no cover
    import yaml

    def require_yaml():
        return yaml

    def read_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}

    def write_yaml(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )


def write_yaml_if_changed(path: Path, data: dict[str, Any]) -> bool:
    write_yaml(path, data)
    return True
