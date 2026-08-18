# -*- coding: utf-8 -*-
"""Named CE plans: ce/plan/{slug}_plan.md (markdown only, no yaml)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_TODO_OPEN = re.compile(r"^(\s*[-*]\s+\[ \])(.*)$")
_TODO_DONE = re.compile(r"^(\s*[-*]\s+\[[xX]\])(.*)$")
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
    return [row["text"] for row in all_todos(plan_path) if not row.get("done")]


def all_todos(plan_path: Path | str) -> list[dict[str, Any]]:
    """Parse checklist rows: ``{text, done, raw}``."""
    path = Path(plan_path)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m_done = _TODO_DONE.match(line)
        if m_done:
            rows.append(
                {
                    "text": m_done.group(2).strip(),
                    "done": True,
                    "raw": line,
                }
            )
            continue
        m_open = _TODO_OPEN.match(line)
        if m_open:
            rows.append(
                {
                    "text": m_open.group(2).strip(),
                    "done": False,
                    "raw": line,
                }
            )
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


def validate_plan_revision(
    *,
    before: list[dict[str, Any]],
    after_path: Path | str,
) -> dict[str, Any]:
    """Completed todos must still appear; new open todos are allowed."""
    after = all_todos(after_path)
    after_texts = {str(r.get("text") or "").strip() for r in after if r.get("text")}
    dropped: list[str] = []
    for row in before:
        text = str(row.get("text") or "").strip()
        if row.get("done") and text and text not in after_texts:
            dropped.append(text)
    ok = not dropped
    return {
        "ok": ok,
        "dropped_completed": dropped,
        "before_count": len(before),
        "after_count": len(after),
        "reason_code": "" if ok else "REVISE_DROPPED_COMPLETED_TODO",
        "message_zh": (
            "计划修订已保留已完成 todo。"
            if ok
            else f"修订丢掉了已完成 todo：{dropped[:5]}"
        ),
    }


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
