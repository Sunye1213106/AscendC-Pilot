# -*- coding: utf-8 -*-
"""User Goal control plane — product intent above Spec/Workflow.

Persists under ``.ascendc-pilot/control/user_goal.yaml``. Does not replace
Spec FSM; Primary uses it to chain tg-init → tg-plan → tg-solve for full
coverage NL intents, with human-voice progress at each step.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ascendc_pilot.paths import AGENT_DIR

USER_GOAL_SCHEMA = "pilot-user-goal/v1"
GOAL_TILINGKEY_FULL = "tilingkey_full_coverage_cases"
GOAL_CE_CHANGE = "ce_change_verify_chain"

# Phrases that mean "full tilingkey cases" product goal (not a single slash).
FULL_COVERAGE_PHRASES: tuple[str, ...] = (
    "全量",
    "全覆盖",
    "tilingkey case",
    "TilingKey case",
    "tilingkey 全覆盖",
    "TilingKey 全覆盖",
    "建立 TilingKey 全覆盖测试",
    "全量 tilingkey",
    "全量 TilingKey",
    "全量覆盖",
)

DEFAULT_STEPS: tuple[dict[str, str], ...] = (
    {
        "id": "ensure_uo",
        "workflow_id": "uo-init",
        "summary_zh": "建立知识库（若尚无 CodeMap）",
        "optional": "true",
    },
    {
        "id": "tg_init",
        "workflow_id": "tg-init",
        "summary_zh": "建立覆盖合同",
        "optional": "false",
    },
    {
        "id": "tg_plan",
        "workflow_id": "tg-plan",
        "summary_zh": "规划测试义务",
        "optional": "false",
    },
    {
        "id": "tg_solve",
        "workflow_id": "tg-solve",
        "summary_zh": "求解并生成用例",
        "optional": "false",
    },
)

_WORKFLOW_TO_STEP = {
    "uo-init": "ensure_uo",
    "uo-update": "ensure_uo",
    "tg-init": "tg_init",
    "tg-plan": "tg_plan",
    "tg-solve": "tg_solve",
}

CE_CHANGE_PHRASES: tuple[str, ...] = (
    "验证这次改动",
    "按 PR 定向",
    "影响分析并验证",
    "ChangeTestIntent",
    "定向生成 case",
    "ce change",
    "修这个 PR",
    "这次改动怎么测",
)

CE_STEPS: tuple[dict[str, str], ...] = (
    {"id": "ce_intent", "workflow_id": "ce-intent", "summary_zh": "问清并分解变更", "optional": "false"},
    {"id": "ce_apply", "workflow_id": "ce-apply", "summary_zh": "按锚点改码", "optional": "false"},
    {"id": "uo_refresh", "workflow_id": "uo-update", "summary_zh": "刷新 CodeMap", "optional": "false"},
    {"id": "ce_impact", "workflow_id": "ce-impact", "summary_zh": "影响分析并写出 ChangeTestIntent", "optional": "false"},
    {"id": "tg_targeted", "workflow_id": "tg-solve", "summary_zh": "定向构造并 Host Replay", "optional": "false"},
    {"id": "ce_verify", "workflow_id": "ce-verify", "summary_zh": "按 target_reached 关闭义务", "optional": "false"},
)

_CE_WORKFLOW_TO_STEP = {
    "ce-intent": "ce_intent",
    "ce-apply": "ce_apply",
    "uo-update": "uo_refresh",
    "ce-impact": "ce_impact",
    "tg-solve": "tg_targeted",
    "ce-verify": "ce_verify",
}


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def control_root(project_root: Path | str) -> Path:
    return Path(project_root).expanduser().resolve() / AGENT_DIR / "control"


def user_goal_path(project_root: Path | str) -> Path:
    return control_root(project_root) / "user_goal.yaml"


def matches_full_coverage_intent(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    low = s.lower()
    for phrase in FULL_COVERAGE_PHRASES:
        if phrase.lower() in low or phrase in s:
            return True
    return False


def matches_ce_change_intent(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    low = s.lower()
    for phrase in CE_CHANGE_PHRASES:
        if phrase.lower() in low or phrase in s:
            return True
    return False


def route_natural_goal(text: str) -> dict[str, Any] | None:
    """Map natural language to a predefined Goal Router chain (slash stays expert API)."""
    if matches_full_coverage_intent(text):
        return {
            "ok": True,
            "goal_id": GOAL_TILINGKEY_FULL,
            "workflow_id": "tg-init",
            "slash": "/tg-init",
            "method": "goal_router",
            "mode": "tilingkey_full_coverage",
        }
    if matches_ce_change_intent(text):
        return {
            "ok": True,
            "goal_id": GOAL_CE_CHANGE,
            "workflow_id": "ce-intent",
            "slash": "/ce-intent",
            "method": "goal_router",
            "mode": "scenario_targeted",
        }
    return None


def load_user_goal(project_root: Path | str) -> dict[str, Any] | None:
    path = user_goal_path(project_root)
    if not path.is_file():
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(doc, dict):
        return None
    if str(doc.get("goal_id") or "").strip() != GOAL_TILINGKEY_FULL:
        # Still return unknown goals for inspection; progress helpers no-op.
        return doc
    return doc


def write_user_goal(project_root: Path | str, doc: dict[str, Any]) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    ctrl = control_root(root)
    ctrl.mkdir(parents=True, exist_ok=True)
    payload = dict(doc)
    payload.setdefault("schema", USER_GOAL_SCHEMA)
    payload["updated_at"] = _now()
    path = user_goal_path(root)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return payload


def create_tilingkey_full_coverage_goal(
    project_root: Path | str,
    *,
    architecture: str = "",
    mode: str = "tilingkey_full_coverage",
    op_name: str = "",
    current_step: str = "tg_init",
    intent_text: str = "",
) -> dict[str, Any]:
    """Materialize the default full-coverage product goal."""
    root = Path(project_root).expanduser().resolve()
    op = (op_name or root.name).strip()
    arch = str(architecture or "").strip()
    label = f"全量 TilingKey 覆盖测试"
    if op:
        label = f"{op} 全量 TilingKey 覆盖测试"
    if arch:
        label = f"{op}（{arch}）全量 TilingKey 覆盖测试"
    steps = []
    for s in DEFAULT_STEPS:
        steps.append(
            {
                "id": s["id"],
                "workflow_id": s["workflow_id"],
                "summary_zh": s["summary_zh"],
                "optional": s["optional"] == "true",
                "status": "pending",
            }
        )
    # Mark steps before current as skipped/passed appropriately.
    reached = False
    for step in steps:
        if step["id"] == current_step:
            step["status"] = "in_progress"
            reached = True
        elif not reached and step["id"] == "ensure_uo" and current_step != "ensure_uo":
            step["status"] = "skipped"
        elif not reached:
            step["status"] = "pending"
    doc = {
        "schema": USER_GOAL_SCHEMA,
        "goal_id": GOAL_TILINGKEY_FULL,
        "label_zh": label,
        "intent_text": str(intent_text or label).strip(),
        "project": root.as_posix(),
        "architecture": arch,
        "op_name": op,
        "mode": mode,
        "steps": steps,
        "current_step": current_step,
        "status": "active",
        "created_at": _now(),
    }
    return write_user_goal(root, doc)


def _materialize_steps(spec: tuple[dict[str, str], ...], current_step: str) -> list[dict[str, Any]]:
    steps = []
    for s in spec:
        steps.append(
            {
                "id": s["id"],
                "workflow_id": s["workflow_id"],
                "summary_zh": s["summary_zh"],
                "optional": s["optional"] == "true",
                "status": "pending",
            }
        )
    reached = False
    for step in steps:
        if step["id"] == current_step:
            step["status"] = "in_progress"
            reached = True
        elif not reached and step.get("optional"):
            step["status"] = "skipped"
        elif not reached:
            step["status"] = "pending"
    return steps


def create_ce_change_goal(
    project_root: Path | str,
    *,
    architecture: str = "",
    op_name: str = "",
    current_step: str = "ce_intent",
    intent_text: str = "",
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    op = (op_name or root.name).strip()
    arch = str(architecture or "").strip()
    label = "按改动验证（ChangeTestIntent → TG targeted → Replay）"
    if op:
        label = f"{op} {label}"
    if arch:
        label = f"{op}（{arch}）按改动验证"
    doc = {
        "schema": USER_GOAL_SCHEMA,
        "goal_id": GOAL_CE_CHANGE,
        "label_zh": label,
        "intent_text": str(intent_text or label).strip(),
        "project": root.as_posix(),
        "architecture": arch,
        "op_name": op,
        "mode": "scenario_targeted",
        "steps": _materialize_steps(CE_STEPS, current_step),
        "current_step": current_step,
        "status": "active",
        "created_at": _now(),
    }
    return write_user_goal(root, doc)


def ensure_goal_for_intent(
    project_root: Path | str,
    *,
    intent_text: str,
    architecture: str = "",
    workflow_id: str = "",
    op_name: str = "",
) -> dict[str, Any] | None:
    """If NL matches a Goal Router chain, create or refresh goal; else None."""
    if matches_ce_change_intent(intent_text):
        existing = load_user_goal(project_root)
        if existing and str(existing.get("goal_id")) == GOAL_CE_CHANGE and str(existing.get("status")) == "active":
            return existing
        step = _CE_WORKFLOW_TO_STEP.get(str(workflow_id or "").strip(), "ce_intent")
        return create_ce_change_goal(
            project_root,
            architecture=architecture,
            op_name=op_name,
            current_step=step,
            intent_text=intent_text,
        )
    if not matches_full_coverage_intent(intent_text):
        # Explicit tg-* start under an existing goal still advances via complete.
        existing = load_user_goal(project_root)
        if existing and str(existing.get("status")) == "active":
            return existing
        return None
    existing = load_user_goal(project_root)
    if (
        existing
        and str(existing.get("goal_id")) == GOAL_TILINGKEY_FULL
        and str(existing.get("status")) == "active"
    ):
        # Keep architecture/op/intent if newly known.
        changed = False
        if architecture and not str(existing.get("architecture") or "").strip():
            existing["architecture"] = architecture
            changed = True
        if intent_text and not str(existing.get("intent_text") or "").strip():
            existing["intent_text"] = intent_text
            changed = True
        if changed:
            return write_user_goal(project_root, existing)
        return existing
    step = _WORKFLOW_TO_STEP.get(str(workflow_id or "").strip(), "tg_init")
    return create_tilingkey_full_coverage_goal(
        project_root,
        architecture=architecture,
        op_name=op_name,
        current_step=step if step != "ensure_uo" else "tg_init",
        intent_text=intent_text,
    )


def progress_line_zh(goal: dict[str, Any] | None) -> str:
    if not goal:
        return ""
    steps = [s for s in (goal.get("steps") or []) if isinstance(s, dict)]
    if not steps:
        return str(goal.get("label_zh") or "")
    # Count required steps only for N.
    required = [s for s in steps if not s.get("optional")]
    done = sum(1 for s in required if str(s.get("status")) in {"passed", "skipped"})
    total = len(required) or len(steps)
    cur_id = str(goal.get("current_step") or "")
    cur = next((s for s in steps if str(s.get("id")) == cur_id), None)
    cur_summary = str((cur or {}).get("summary_zh") or cur_id or "进行中")
    label = str(goal.get("label_zh") or "全量覆盖")
    # 1-based index of current required step.
    idx = done + 1 if done < total else total
    return f"{label} {idx}/{total}：正在{cur_summary}…"


def mark_workflow_passed(project_root: Path | str, workflow_id: str) -> dict[str, Any] | None:
    """Advance goal when a workflow completes; return updated goal + next hint."""
    goal = load_user_goal(project_root)
    if not goal or str(goal.get("status")) != "active":
        return None
    goal_id = str(goal.get("goal_id") or "")
    if goal_id == GOAL_CE_CHANGE:
        step_id = _CE_WORKFLOW_TO_STEP.get(str(workflow_id or "").strip())
    elif goal_id == GOAL_TILINGKEY_FULL:
        step_id = _WORKFLOW_TO_STEP.get(str(workflow_id or "").strip())
    else:
        return None
    if not step_id:
        return None
    steps = [dict(s) for s in (goal.get("steps") or []) if isinstance(s, dict)]
    next_workflow = ""
    next_summary = ""
    found = False
    for i, step in enumerate(steps):
        if str(step.get("id")) != step_id:
            continue
        found = True
        step["status"] = "passed"
        # Find next non-optional pending / in_progress
        for j in range(i + 1, len(steps)):
            nxt = steps[j]
            if nxt.get("optional") and str(nxt.get("status")) == "skipped":
                continue
            if str(nxt.get("status")) in {"passed", "skipped"}:
                continue
            nxt["status"] = "in_progress"
            goal["current_step"] = str(nxt.get("id"))
            next_workflow = str(nxt.get("workflow_id") or "")
            next_summary = str(nxt.get("summary_zh") or "")
            break
        else:
            goal["current_step"] = step_id
            goal["status"] = "completed"
        break
    if not found:
        return None
    goal["steps"] = steps
    write_user_goal(project_root, goal)
    from ascendc_pilot.human_voice import progress_zh

    just = ""
    for s in steps:
        if str(s.get("id")) == step_id:
            just = str(s.get("summary_zh") or step_id)
            break
    voice = progress_zh(
        goal=str(goal.get("label_zh") or ""),
        just_done=f"「{just}」已完成",
        next_step=(
            f"请启动「{next_summary}」（{next_workflow}）"
            if next_workflow
            else "目标已完成"
        ),
        need_you="",
    )
    return {
        "goal": goal,
        "next_workflow_id": next_workflow,
        "next_summary_zh": next_summary,
        "message_zh": voice,
        "progress_line": progress_line_zh(goal),
        "completed": str(goal.get("status")) == "completed",
    }


def conflict_ask(
    *,
    existing_label: str,
    existing_step: str,
    incoming_workflow: str,
) -> dict[str, Any]:
    """Human-voice AskQuestion when a conflicting run would clobber the goal."""
    from ascendc_pilot.human_voice import decision_question

    return decision_question(
        header="已有全覆盖目标进行中，如何处理？",
        goal=existing_label or "全量 TilingKey 覆盖测试",
        background=f"当前目标停在「{existing_step}」。你又请求启动 {incoming_workflow}。",
        decide="继续当前目标，还是放弃并重新开始？",
        consequences={
            "继续当前目标": "不新建冲突运行，按当前步骤推进",
            "重新开始全覆盖": "结束旧目标并按新请求重开串联",
            "停止": "不做变更",
        },
        options=[
            {"label": "继续当前目标", "value": "continue"},
            {"label": "重新开始全覆盖", "value": "reinit"},
            {"label": "停止", "value": "stop"},
        ],
    )
