# -*- coding: utf-8 -*-
"""User Goal v2 — product intent above internal workflows.

Persists under ``.ascendc-pilot/control/user_goal.yaml``. Natural-language
intake does not live here: the LLM Intent Action understands the user text;
this module only loads, saves, and advances the Goal after a Task Plan exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ascendc_pilot.paths import AGENT_DIR

USER_GOAL_SCHEMA = "pilot-user-goal/v2"
# Kept as kind labels only; no phrase router and no hardcoded workflow chain.
GOAL_GENERATE_CHANGE_TESTS = "generate_change_tests"
GOAL_TILINGKEY_FULL = "tilingkey_full_coverage_cases"
GOAL_CE_CHANGE = "ce_change_verify_chain"
GOAL_CE_REVIEW = "ce_review_pr"

SESSION_AUTO = "auto"
SESSION_EXPERT = "expert"


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def control_root(project_root: Path | str) -> Path:
    return Path(project_root).expanduser().resolve() / AGENT_DIR / "control"


def user_goal_path(project_root: Path | str) -> Path:
    return control_root(project_root) / "user_goal.yaml"


def load_user_goal(project_root: Path | str) -> dict[str, Any] | None:
    path = user_goal_path(project_root)
    if not path.is_file():
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


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


def is_auto_session(goal: dict[str, Any] | None) -> bool:
    if not goal:
        return False
    if str(goal.get("session_kind") or "") == SESSION_AUTO:
        return True
    return str(goal.get("schema") or "") == USER_GOAL_SCHEMA and bool(
        goal.get("needed_capabilities")
        or (goal.get("intent") or {}).get("needed_capabilities")
        or (goal.get("intent") or {}).get("needed_workflows")
    )


def create_user_goal(
    project_root: Path | str,
    *,
    intent_text: str,
    llm_intent: dict[str, Any],
    public_plan: list[dict[str, Any]] | None = None,
    architecture: str = "",
    op_name: str = "",
    session_kind: str = SESSION_AUTO,
    kind: str = "",
) -> dict[str, Any]:
    """Materialize a v2 Goal from LLM Intent staging (already validated)."""
    from ascendc_pilot.planning.task_plan import plan_kind, public_plan_for

    root = Path(project_root).expanduser().resolve()
    wfs = [
        str(w).strip()
        for w in (llm_intent.get("needed_workflows") or [])
        if str(w).strip()
    ]
    caps = [
        str(c).strip()
        for c in (llm_intent.get("needed_capabilities") or [])
        if str(c).strip()
    ]
    if not wfs and caps:
        from ascendc_pilot.harness.intent import workflows_from_capabilities

        wfs = workflows_from_capabilities(caps)
    if not caps and wfs:
        from ascendc_pilot.harness.intent import capabilities_from_workflows

        caps = capabilities_from_workflows(wfs)
    source = llm_intent.get("source") if isinstance(llm_intent.get("source"), dict) else {}
    objective = str(llm_intent.get("objective_zh") or intent_text or "").strip()
    plan = public_plan if public_plan is not None else public_plan_for(caps, workflows=wfs)
    goal_kind = str(kind or plan_kind(caps, workflows=wfs) or GOAL_GENERATE_CHANGE_TESTS)
    op = (op_name or root.name).strip()
    arch = str(architecture or "").strip()
    label = objective or "用户目标"
    if op and op not in label:
        label = f"{op}：{label}" if label else op
    doc = {
        "schema": USER_GOAL_SCHEMA,
        "goal_id": goal_kind,
        "session_kind": session_kind,
        "kind": goal_kind,
        "label_zh": label,
        "intent": {
            "text": str(intent_text or "").strip(),
            "needed_workflows": wfs,
            "needed_capabilities": caps,
            "objective_zh": objective,
        },
        "source": dict(source),
        "constraints": dict(llm_intent.get("constraints") or {})
        if isinstance(llm_intent.get("constraints"), dict)
        else {},
        "public_plan": list(plan),
        "decisions": [],
        "findings": [],
        "artifacts": {},
        "project": root.as_posix(),
        "architecture": arch,
        "op_name": op,
        "status": "active",
        "goal_version": 1,
        "intent_history": [
            {"version": 1, "text": str(intent_text or "").strip(), "at": _now()}
        ],
        "created_at": _now(),
    }
    return write_user_goal(root, doc)


def progress_line_zh(goal: dict[str, Any] | None) -> str:
    if not goal:
        return ""
    steps = [s for s in (goal.get("public_plan") or []) if isinstance(s, dict)]
    if not steps:
        return str(goal.get("label_zh") or "")
    done = sum(1 for s in steps if str(s.get("status")) in {"passed", "skipped"})
    total = len(steps)
    cur = next(
        (s for s in steps if str(s.get("status")) == "in_progress"),
        None,
    )
    if cur is None:
        cur = next(
            (s for s in steps if str(s.get("status")) not in {"passed", "skipped"}),
            None,
        )
    cur_summary = str((cur or {}).get("summary_zh") or "进行中")
    label = str(goal.get("label_zh") or "当前目标")
    idx = min(done + 1, total) if total else 1
    return f"{label} {idx}/{total}：正在{cur_summary}…"


def _sync_public_plan(goal: dict[str, Any], workflow_id: str, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    from ascendc_pilot.planning.task_plan import executed_public_ids, public_id_for_workflow

    pub_id = public_id_for_workflow(workflow_id)
    executed = executed_public_ids(plan)
    if pub_id:
        executed.add(pub_id)
    steps = [dict(s) for s in (goal.get("public_plan") or []) if isinstance(s, dict)]
    if not steps:
        return goal
    if pub_id:
        reached = False
        for step in steps:
            sid = str(step.get("id") or "")
            if sid == pub_id:
                reached = True
                # Keep in_progress until a later public step starts, except
                # terminal deliver which is marked passed when the goal completes.
                if sid in {"deliver"}:
                    step["status"] = "passed"
                elif str(step.get("status")) != "passed":
                    step["status"] = "in_progress"
            elif not reached:
                # Prefix passed only for public steps that have already executed.
                if sid in executed and str(step.get("status")) != "skipped":
                    step["status"] = "passed"
            elif str(step.get("status")) == "in_progress":
                step["status"] = "pending"
        if workflow_id == "tg-solve":
            for step in steps:
                if str(step.get("id")) in {"generate_cases", "validate_cases"}:
                    step["status"] = "passed"
                elif str(step.get("id")) == "deliver":
                    step["status"] = "in_progress"
        if workflow_id == "goal-impact":
            for step in steps:
                if str(step.get("id")) in {"understand_change", "choose_scope"}:
                    step["status"] = "passed"
                elif str(step.get("id")) == "generate_cases" and str(step.get("status")) != "passed":
                    step["status"] = "in_progress"
    goal = dict(goal)
    goal["public_plan"] = steps
    return goal


def mark_workflow_passed(project_root: Path | str, workflow_id: str) -> dict[str, Any] | None:
    """Advance an auto Goal via Task Plan. Expert slash does not chain."""
    goal = load_user_goal(project_root)
    if not goal or str(goal.get("status")) != "active":
        return None
    if not is_auto_session(goal):
        return None

    from ascendc_pilot.human_voice import progress_zh
    from ascendc_pilot.planning.task_plan import (
        acceptance_failure_zh,
        acceptance_satisfied,
        current_workflow_id,
        evaluate_acceptance,
        load_task_plan,
        mark_step_passed,
        write_task_plan,
    )

    plan = load_task_plan(project_root)
    if not plan:
        return None
    wid = str(workflow_id or "").strip()
    plan = mark_step_passed(plan, wid)
    arch = str(goal.get("architecture") or "")
    acc = evaluate_acceptance(plan, project_root, architecture=arch)
    plan["acceptance_status"] = acc
    remaining = [
        s
        for s in (plan.get("steps") or [])
        if isinstance(s, dict) and str(s.get("status") or "") not in {"passed", "skipped"}
    ]
    accepted = acceptance_satisfied(plan, project_root, architecture=arch)
    if not remaining and accepted:
        plan["status"] = "completed"
    write_task_plan(project_root, plan)
    goal = _sync_public_plan(goal, wid, plan)

    next_workflow = current_workflow_id(plan)
    completed = bool(accepted and not next_workflow)
    acceptance_failed = bool(not remaining and not accepted)
    if completed:
        goal["status"] = "completed"
        for step in goal.get("public_plan") or []:
            if isinstance(step, dict) and str(step.get("status")) != "skipped":
                step["status"] = "passed"
    write_user_goal(project_root, goal)

    next_summary = ""
    for step in plan.get("steps") or []:
        if isinstance(step, dict) and str(step.get("workflow_id") or step.get("id")) == next_workflow:
            next_summary = str(step.get("summary_zh") or next_workflow)
            break
    if not next_summary:
        for step in goal.get("public_plan") or []:
            if isinstance(step, dict) and str(step.get("status")) == "in_progress":
                next_summary = str(step.get("summary_zh") or "")
                break

    fail_zh = acceptance_failure_zh(plan, acc) if acceptance_failed else ""
    voice = progress_zh(
        goal=str(goal.get("label_zh") or ""),
        just_done=f"「{wid}」已完成" if wid else "本阶段已完成",
        next_step=(
            fail_zh
            if acceptance_failed
            else (f"继续「{next_summary}」" if next_workflow else "目标已完成")
        ),
        need_you="",
    )
    return {
        "goal": goal,
        "next_workflow_id": next_workflow if not completed else "",
        "next_summary_zh": (
            fail_zh
            if acceptance_failed
            else (next_summary if not completed else "目标已完成")
        ),
        "message_zh": voice,
        "progress_line": progress_line_zh(goal),
        "completed": completed,
        "acceptance_failed": acceptance_failed,
        "acceptance_status": acc,
    }


def conflict_ask(
    *,
    existing_label: str,
    existing_step: str,
    incoming_workflow: str,
) -> dict[str, Any]:
    from ascendc_pilot.human_voice import decision_question

    return decision_question(
        header="已有目标进行中，如何处理？",
        goal=existing_label or "当前目标",
        background=f"当前目标停在「{existing_step}」。你又请求启动 {incoming_workflow}。",
        decide="继续当前目标，还是放弃并重新开始？",
        consequences={
            "继续当前目标": "不新建冲突运行，按当前步骤推进",
            "重新开始": "结束旧目标并按新请求重开",
            "停止": "不做变更",
        },
        options=[
            {"label": "继续当前目标", "value": "continue"},
            {"label": "重新开始", "value": "reinit"},
            {"label": "停止", "value": "stop"},
        ],
    )


def pause_user_goal(project_root: Path | str, *, reason: str = "switch") -> dict[str, Any] | None:
    goal = load_user_goal(project_root)
    if not goal or str(goal.get("status") or "") not in {"active", "revising"}:
        return goal
    goal["status"] = "paused"
    goal["paused_reason"] = str(reason or "switch")
    return write_user_goal(project_root, goal)


def resume_user_goal(project_root: Path | str) -> dict[str, Any] | None:
    goal = load_user_goal(project_root)
    if not goal or str(goal.get("status") or "") != "paused":
        return goal
    goal["status"] = "active"
    goal.pop("paused_reason", None)
    return write_user_goal(project_root, goal)


def request_goal_revision(project_root: Path | str, delta_text: str) -> dict[str, Any]:
    """First-class plan revision: update constraints and invalidate downstream."""
    from ascendc_pilot.paths import runs_root
    from ascendc_pilot.state import load_state, save_state

    root = Path(project_root).expanduser().resolve()
    delta = str(delta_text or "").strip()
    goal = load_user_goal(root)
    if goal:
        history = list(goal.get("intent_history") or [])
        version = int(goal.get("goal_version") or 1) + 1
        history.append({"version": version, "text": delta, "at": _now()})
        goal["goal_version"] = version
        goal["intent_history"] = history
        if delta:
            intent = dict(goal.get("intent") or {})
            prev = str(intent.get("text") or goal.get("intent_text") or "").strip()
            intent["text"] = (prev + "\n" + delta).strip() if prev else delta
            goal["intent"] = intent
            goal["intent_text"] = intent["text"]
        goal["status"] = "revising"
        write_user_goal(root, goal)

    try:
        from ascendc_pilot.planning.reconcile import apply_revision

        apply_revision(root, delta_text=delta)
    except Exception:  # noqa: BLE001
        pass

    st = load_state(root) or {}
    wid = str(st.get("workflow_id") or "")
    out: dict[str, Any] = {
        "revise_requested": True,
        "workflow_id": wid,
        "paused": False,
        "message_zh": "已记下补充需求，将在当前计划上修订，不会整段重走。",
    }
    if delta:
        st["pending_goal_revision"] = delta
        if wid == "ce-plan":
            prev_intent = str(st.get("intent") or "")
            st["intent"] = (prev_intent + "\n" + delta).strip() if prev_intent else delta
        save_state(root, st)

    if wid == "ce-apply":
        arch = str(st.get("architecture") or "")
        run_id = str(st.get("run_id") or "")
        try:
            from code_engineering.plan_md import all_todos, resolve_active_plan

            plan = resolve_active_plan(root, architecture=arch, state=st)
            baseline = {
                "schema": "ce-plan-revise-baseline/v1",
                "delta_text": delta,
                "plan": str(plan) if plan else "",
                "todos": all_todos(plan) if plan else [],
            }
            if run_id:
                dest = runs_root(root, arch=arch or None) / run_id / "actions" / "plan_revise"
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "delta.md").write_text(delta + "\n", encoding="utf-8")
                (dest / "baseline.yaml").write_text(
                    yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
        except Exception:  # noqa: BLE001
            pass
        try:
            from ascendc_pilot.state.machine import rework_phase

            rework = rework_phase(root, to="revise", reason_code="GOAL_REVISED")
            out["rework"] = {"from": rework.get("from"), "to": rework.get("to")}
        except Exception as exc:  # noqa: BLE001
            out["rework_error"] = str(exc)[:200]
    return out
