# -*- coding: utf-8 -*-
"""Expand LLM needed_capabilities into a legal internal Task Plan.

The planner holds the capability → existing workflow table. LLM staging must
not invent workflow order. Users never see this file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ascendc_pilot.paths import AGENT_DIR

TASK_PLAN_SCHEMA = "pilot-task-plan/v1"

# Public Todo copy for the golden NL path (test_generation).
PUBLIC_PLAN_TEST_GENERATION: tuple[dict[str, str], ...] = (
    {"id": "acquire_change", "summary_zh": "获取 PR 与代码"},
    {"id": "understand_change", "summary_zh": "分析改动影响"},
    {"id": "ensure_knowledge", "summary_zh": "建立算子理解"},
    {"id": "choose_scope", "summary_zh": "确定测试范围"},
    {"id": "generate_cases", "summary_zh": "生成测试用例"},
    {"id": "validate_cases", "summary_zh": "回放验证"},
    {"id": "deliver", "summary_zh": "输出结果"},
)

PUBLIC_PLAN_REVIEW: tuple[dict[str, str], ...] = (
    {"id": "acquire_change", "summary_zh": "获取改动"},
    {"id": "ensure_knowledge", "summary_zh": "建立算子理解"},
    {"id": "review_change", "summary_zh": "审查改动"},
    {"id": "deliver", "summary_zh": "输出结论"},
)

PUBLIC_PLAN_IMPLEMENT: tuple[dict[str, str], ...] = (
    {"id": "ensure_knowledge", "summary_zh": "建立算子理解"},
    {"id": "plan_change", "summary_zh": "问清需求并写出计划"},
    {"id": "apply_change", "summary_zh": "按计划改码"},
    {"id": "deliver", "summary_zh": "输出结果"},
)

PUBLIC_PLAN_KNOWLEDGE: tuple[dict[str, str], ...] = (
    {"id": "ensure_knowledge", "summary_zh": "建立算子理解"},
    {"id": "deliver", "summary_zh": "输出结果"},
)

_WORKFLOW_TO_PUBLIC = {
    "workspace_acquire": "acquire_change",
    "goal-intake": "acquire_change",
    "goal-impact": "understand_change",
    "uo-init": "ensure_knowledge",
    "uo-update": "ensure_knowledge",
    "ce-review": "review_change",
    "ce-plan": "plan_change",
    "ce-apply": "apply_change",
    "tg-init": "generate_cases",
    "tg-plan": "generate_cases",
    "tg-solve": "validate_cases",
}


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def task_plan_path(project_root: Path | str) -> Path:
    return Path(project_root).expanduser().resolve() / AGENT_DIR / "control" / "task_plan.yaml"


def load_task_plan(project_root: Path | str) -> dict[str, Any] | None:
    path = task_plan_path(project_root)
    if not path.is_file():
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


def write_task_plan(project_root: Path | str, doc: dict[str, Any]) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    path = task_plan_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(doc)
    payload.setdefault("schema", TASK_PLAN_SCHEMA)
    payload["updated_at"] = _now()
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return payload


def public_plan_for(capabilities: list[str]) -> list[dict[str, Any]]:
    caps = set(capabilities or [])
    if "test_generation" in caps:
        spec = PUBLIC_PLAN_TEST_GENERATION
    elif "implement" in caps:
        spec = PUBLIC_PLAN_IMPLEMENT
    elif "code_review" in caps:
        spec = PUBLIC_PLAN_REVIEW
    else:
        spec = PUBLIC_PLAN_KNOWLEDGE
    rows = []
    for item in spec:
        rows.append(
            {
                "id": item["id"],
                "summary_zh": item["summary_zh"],
                "status": "pending",
            }
        )
    if rows:
        rows[0]["status"] = "in_progress"
    return rows


def plan_kind(capabilities: list[str]) -> str:
    caps = set(capabilities or [])
    if "test_generation" in caps:
        return "generate_change_tests"
    if "implement" in caps:
        return "implement_change"
    if "code_review" in caps:
        return "review_change"
    return "ensure_knowledge"


def plan_for(
    llm_intent: dict[str, Any],
    available: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Expand capabilities + on-disk facts into legal existing workflows."""
    caps = [str(c).strip() for c in (llm_intent.get("needed_capabilities") or []) if str(c).strip()]
    state = dict(available or {})
    has_uo = bool(state.get("has_uo"))
    uo_stale = bool(state.get("uo_stale"))
    needs_uo = bool(
        set(caps)
        & {"knowledge", "test_generation", "code_review", "implement", "change_analysis"}
    )

    steps: list[dict[str, Any]] = []

    def _add(wid: str, *, kind: str = "workflow", summary_zh: str = "") -> None:
        if any(str(s.get("id")) == wid for s in steps):
            return
        steps.append(
            {
                "id": wid,
                "kind": kind,
                "workflow_id": wid if kind == "workflow" else "",
                "summary_zh": summary_zh or wid,
                "status": "pending",
            }
        )

    source = llm_intent.get("source") if isinstance(llm_intent.get("source"), dict) else {}
    if str(source.get("kind") or "") == "pull_request":
        _add("workspace_acquire", kind="harness_action", summary_zh="获取 PR 与代码")

    if needs_uo:
        if has_uo and uo_stale:
            _add("uo-update", summary_zh="刷新算子理解")
        elif not has_uo:
            _add("uo-init", summary_zh="建立算子理解")
        elif "knowledge" in caps and not uo_stale:
            # Fresh CodeMap already present; knowledge is satisfied.
            pass

    if "change_analysis" in caps:
        _add("goal-impact", summary_zh="分析改动并确定测试范围")

    if "implement" in caps:
        _add("ce-plan", summary_zh="问清需求并写出计划")
        _add("ce-apply", summary_zh="按计划改码")

    if "code_review" in caps:
        _add("ce-review", summary_zh="审查改动")

    if "test_generation" in caps:
        _add("tg-init", summary_zh="绑定测试脚本")
        _add("tg-plan", summary_zh="规划测试义务")
        _add("tg-solve", summary_zh="求解并生成用例")

    if steps:
        # First incomplete step is in_progress.
        for step in steps:
            if str(step.get("status")) == "pending":
                step["status"] = "in_progress"
                break

    kind = plan_kind(caps)
    acceptance = []
    if "test_generation" in caps:
        acceptance = ["required_obligations_covered", "cases_validated"]
    elif "code_review" in caps:
        acceptance = ["review_delivered"]
    elif "implement" in caps:
        acceptance = ["change_applied"]
    else:
        acceptance = ["knowledge_ready"]

    return {
        "schema": TASK_PLAN_SCHEMA,
        "kind": kind,
        "needed_capabilities": list(caps),
        "steps": steps,
        "acceptance": acceptance,
        "acceptance_status": {item: "pending" for item in acceptance},
        "source": dict(source),
        "created_at": _now(),
    }


def current_workflow_id(plan: dict[str, Any] | None) -> str:
    if not plan:
        return ""
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("status") or "") not in {"passed", "skipped"}:
            if str(step.get("kind") or "workflow") == "workflow":
                return str(step.get("workflow_id") or step.get("id") or "")
            continue
    return ""


def mark_step_passed(plan: dict[str, Any], step_id: str) -> dict[str, Any]:
    """Mark a plan step passed and advance the next pending step."""
    steps = [dict(s) for s in (plan.get("steps") or []) if isinstance(s, dict)]
    found = False
    for i, step in enumerate(steps):
        if str(step.get("id") or step.get("workflow_id") or "") != str(step_id):
            continue
        found = True
        step["status"] = "passed"
        for nxt in steps[i + 1 :]:
            if str(nxt.get("status") or "") in {"passed", "skipped"}:
                continue
            nxt["status"] = "in_progress"
            break
        break
    if not found:
        # Also match workflow_id when step id differs.
        for i, step in enumerate(steps):
            if str(step.get("workflow_id") or "") != str(step_id):
                continue
            step["status"] = "passed"
            for nxt in steps[i + 1 :]:
                if str(nxt.get("status") or "") in {"passed", "skipped"}:
                    continue
                nxt["status"] = "in_progress"
                break
            found = True
            break
    plan = dict(plan)
    plan["steps"] = steps
    remaining = [
        s
        for s in steps
        if str(s.get("status") or "") not in {"passed", "skipped"}
    ]
    if not remaining:
        acc = dict(plan.get("acceptance_status") or {})
        for key in plan.get("acceptance") or []:
            acc[str(key)] = "passed"
        plan["acceptance_status"] = acc
        plan["status"] = "completed"
    else:
        plan["status"] = "active"
    return plan


def acceptance_satisfied(plan: dict[str, Any] | None) -> bool:
    if not plan:
        return False
    if str(plan.get("status") or "") == "completed":
        return True
    steps = [s for s in (plan.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        return False
    return all(str(s.get("status") or "") in {"passed", "skipped"} for s in steps)


def public_id_for_workflow(workflow_id: str) -> str:
    return _WORKFLOW_TO_PUBLIC.get(str(workflow_id or "").strip(), "")


def invalidate_from(plan: dict[str, Any], *, from_step_id: str) -> dict[str, Any]:
    """Mark from_step and everything after it pending (keep earlier passed)."""
    steps = [dict(s) for s in (plan.get("steps") or []) if isinstance(s, dict)]
    reached = False
    for step in steps:
        sid = str(step.get("id") or step.get("workflow_id") or "")
        if sid == from_step_id or reached:
            reached = True
            if str(step.get("status") or "") != "skipped":
                step["status"] = "pending"
    if reached:
        for step in steps:
            if str(step.get("status") or "") == "pending":
                step["status"] = "in_progress"
                break
    out = dict(plan)
    out["steps"] = steps
    out["status"] = "active"
    acc = dict(out.get("acceptance_status") or {})
    for key in out.get("acceptance") or []:
        if str(acc.get(key) or "") == "passed":
            acc[str(key)] = "pending"
    out["acceptance_status"] = acc
    return out
