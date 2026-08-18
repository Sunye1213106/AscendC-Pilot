# -*- coding: utf-8 -*-
"""Public progress projection for Host / Primary. Not engine stderr logs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ascendc_pilot.planning.task_plan import current_workflow_id, load_task_plan, public_id_for_workflow
from ascendc_pilot.user_goal import is_auto_session, load_user_goal, progress_line_zh

_ACTIVITY = {
    "acquire_change": "正在获取 PR 与代码",
    "understand_change": "正在分析 PR 改动对测试空间的影响",
    "ensure_knowledge": "正在建立或复用算子理解",
    "choose_scope": "正在确定测试范围",
    "generate_cases": "正在生成测试用例",
    "validate_cases": "正在回放验证",
    "deliver": "正在整理交付结果",
    "review_change": "正在审查改动",
    "plan_change": "正在整理改码计划",
    "apply_change": "正在按计划改码",
}


def public_projection(
    project_root: Path | str,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Host-facing progress. Never includes workflow phase jargon."""
    goal = load_user_goal(project_root)
    plan = load_task_plan(project_root)
    st = dict(state or {})
    wid = str(st.get("workflow_id") or "")
    stage = ""
    if is_auto_session(goal):
        for item in goal.get("public_plan") or []:
            if isinstance(item, dict) and str(item.get("status")) == "in_progress":
                stage = str(item.get("id") or "")
                break
        if not stage:
            stage = public_id_for_workflow(current_workflow_id(plan) or wid)
    else:
        stage = public_id_for_workflow(wid) or wid
    activity = _ACTIVITY.get(stage, progress_line_zh(goal) or "进行中")
    next_zh = ""
    if goal:
        steps = [s for s in (goal.get("public_plan") or []) if isinstance(s, dict)]
        seen = False
        for item in steps:
            if seen and str(item.get("status")) not in {"passed", "skipped"}:
                next_zh = str(item.get("summary_zh") or "")
                break
            if str(item.get("id")) == stage:
                seen = True
    findings = list((goal or {}).get("findings") or [])
    finding = ""
    if findings:
        last = findings[-1]
        finding = str(last.get("summary_zh") or last) if isinstance(last, dict) else str(last)
    return {
        "stage": stage,
        "activity": activity,
        "progress_line": progress_line_zh(goal),
        "finding": finding,
        "next": next_zh,
        "session_kind": str((goal or {}).get("session_kind") or ""),
    }


def message_zh_for_host(
    project_root: Path | str,
    *,
    state: dict[str, Any] | None = None,
    fallback: str = "",
) -> str:
    proj = public_projection(project_root, state=state)
    text = str(proj.get("activity") or proj.get("progress_line") or "").strip()
    return text or fallback
