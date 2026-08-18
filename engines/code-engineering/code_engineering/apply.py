# -*- coding: utf-8 -*-
"""CE apply gates: current {slug}_plan.md has open todos; diff ⊆ plan files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from code_engineering.change.capture import capture
from code_engineering.plan_md import declared_source_files, resolve_active_plan, unfinished_todos


def apply_gate(
    project_root: Path | str,
    *,
    architecture: str,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed unless the active named plan exists and has unfinished todos."""
    arch = str(architecture or "").strip()
    if not arch:
        return {"ok": False, "engine": "apply_gate", "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    plan = resolve_active_plan(project_root, architecture=arch, state=state)
    if plan is None:
        return {
            "ok": False,
            "engine": "apply_gate",
            "reason_code": "APPLY_PLAN_MISSING",
            "message_zh": "没有当前 {slug}_plan.md。请先 /ce-plan。",
        }
    todos = unfinished_todos(plan)
    if not todos:
        return {
            "ok": False,
            "engine": "apply_gate",
            "reason_code": "APPLY_TODOS_DONE",
            "plan": plan.as_posix(),
            "message_zh": "当前计划没有未完成 todo。请 /ce-plan 改计划，或去 /tg-plan / /ce-review。",
        }
    return {
        "ok": True,
        "engine": "apply_gate",
        "plan": plan.as_posix(),
        "open_todo_count": len(todos),
        "open_todos": todos[:20],
    }


def _path_allowed(path: str, allowed: set[str]) -> bool:
    p = path.replace("\\", "/").lstrip("./")
    for raw in allowed:
        a = raw.replace("\\", "/").lstrip("./")
        if p == a or p.endswith("/" + a) or a.endswith("/" + p):
            return True
        if a and (p.startswith(a.rstrip("/") + "/") or a.startswith(p.rstrip("/") + "/")):
            return True
    return False


def patch_guard(
    project_root: Path | str,
    *,
    architecture: str,
    state: dict[str, Any] | None = None,
    capture_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Changed files must sit in the file set declared by the active plan markdown."""
    arch = str(architecture or "").strip()
    if not arch:
        return {"ok": False, "engine": "patch_guard", "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    plan = resolve_active_plan(project_root, architecture=arch, state=state)
    if plan is None:
        return {"ok": False, "engine": "patch_guard", "reason_code": "APPLY_PLAN_MISSING"}
    allowed = declared_source_files(plan)
    payload = capture_payload or capture(project_root, architecture=arch, output=None)
    changed = sorted(str(p).replace("\\", "/").lstrip("./") for p in (payload.get("diff_spans") or {}))
    extra = [p for p in changed if allowed and not _path_allowed(p, allowed)]
    ok = bool(changed) and (not allowed or not extra)
    return {
        "ok": ok,
        "engine": "patch_guard",
        "changed_files": changed,
        "extra_files": extra,
        "plan_file_count": len(allowed),
        "reason_code": "" if ok else ("PATCH_OUT_OF_ANCHORS" if extra else "PATCH_EMPTY_OR_UNANCHORED"),
    }
