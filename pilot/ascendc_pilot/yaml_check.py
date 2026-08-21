"""Parse run-scoped YAML mappings and report structured syntax errors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def parse_yaml_mapping(path: Path | str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return ``(mapping, None)`` or ``(None, error)``. Missing files are not a syntax error."""
    p = Path(path)
    if not p.is_file():
        return None, None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return None, {
            "error": "BIND_PART_YAML_INVALID",
            "path": p.as_posix(),
            "message": str(exc),
        }
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        return None, {
            "error": "BIND_PART_YAML_INVALID",
            "path": p.as_posix(),
            "line": (int(mark.line) + 1) if mark is not None else None,
            "column": (int(mark.column) + 1) if mark is not None else None,
            "message": str(exc).strip(),
        }
    if doc is None:
        return {}, None
    if not isinstance(doc, dict):
        return None, {
            "error": "BIND_PART_YAML_INVALID",
            "path": p.as_posix(),
            "message": "YAML root must be a mapping",
        }
    return doc, None


def format_yaml_error_zh(err: dict[str, Any], *, heal_hint: bool = False) -> str:
    """Human-readable parse failure. Keep the word 无法解析 for tests and CLI."""
    line = err.get("line")
    column = err.get("column")
    loc = ""
    if line:
        loc += f" 第 {line} 行"
    if column:
        loc += f" 第 {column} 列"
    msg = f"无法解析 YAML{loc}：{err.get('message') or '语法错误'}"
    path = str(err.get("path") or "").strip()
    if path:
        msg += f" ({path})"
    if heal_hint:
        msg += "。先修缩进/注释，不要用注释对齐序列项。"
    return msg
