# -*- coding: utf-8 -*-
"""Named CE plans: ce/plan/{slug}_plan.md (markdown only, no yaml)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_TODO_OPEN = re.compile(r"^(\s*[-*]\s+\[ )\](.*)$")
_TODO_ANY = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+")
_PATH_TICK = re.compile(r"`([^`]+)`")
_SOURCE_HINT = re.compile(
    r"(?:op_host|op_kernel|common|test_script)/[A-Za-z0-9_./+\-]+\.[A-Za-z0-9]+"
)


def ce_root(project_root: Path | str, architecture: str) -> Path:
    arch = str(architecture or "").strip()
    return Path(project_root).expanduser().resolve() / ".ascendc-pilot" / arch / "ce"


def plan_dir(project_root: Path | str, architecture: str) -> Path:
    return ce_root(project_root, architecture) / "plan"


def list_plan_files(project_root: Path | str, architecture: str) -> list[Path]:
    root = plan_dir(project_root, architecture)
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*_plan.md") if p.is_file())


def unfinished_todos(plan_path: Path | str) -> list[str]:
    path = Path(plan_path)
    if not path.is_file():
        return []
    rows: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _TODO_OPEN.match(line)
        if m:
            rows.append(m.group(2).strip())
    return rows


def declared_source_files(plan_path: Path | str) -> set[str]:
    path = Path(plan_path)
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8")
    files: set[str] = set()
    for raw in _SOURCE_HINT.findall(text):
        files.add(raw.replace("\\", "/").lstrip("./"))
    for raw in _PATH_TICK.findall(text):
        rel = raw.replace("\\", "/").lstrip("./")
        if rel.startswith(("op_host/", "op_kernel/", "common/", "test_script/")):
            files.add(rel)
    return files


def active_plan_relpath(state: dict[str, Any] | None) -> str:
    if not isinstance(state, dict):
        return ""
    return str(state.get("active_plan") or "").strip().replace("\\", "/")


def resolve_active_plan(
    project_root: Path | str,
    *,
    architecture: str,
    state: dict[str, Any] | None = None,
) -> Path | None:
    rel = active_plan_relpath(state)
    root = Path(project_root).expanduser().resolve()
    arch = str(architecture or "").strip()
    if rel:
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = root / ".ascendc-pilot" / arch / rel if not rel.startswith(".ascendc-pilot/") else root / rel
        if candidate.is_file():
            return candidate
    files = list_plan_files(project_root, architecture)
    if len(files) == 1:
        return files[0]
    if files:
        return max(files, key=lambda p: p.stat().st_mtime)
    return None


def test_section(plan_path: Path | str) -> str:
    path = Path(plan_path)
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    for heading in ("## 测试内容", "## 测试需求", "## Test"):
        idx = text.find(heading)
        if idx >= 0:
            rest = text[idx:]
            nxt = re.search(r"\n## ", rest[3:])
            return rest if not nxt else rest[: nxt.start() + 3]
    return ""
