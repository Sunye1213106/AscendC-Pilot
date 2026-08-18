"""Advance / rework / complete / next — state machine operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ascendc_pilot.state import (
    TERMINAL,
    _apply_progress,
    _bump_no_progress,
    _status_message_zh,
    load_state,
    record_gate,
    save_state,
)


def describe_next(project_root: Path) -> dict[str, Any]:
    from ascendc_pilot.obligations import collect_obligations, open_obligations
    from ascendc_pilot.workflows import actions_for_phase, get_workflow, label_zh_for, rework_targets
    from ascendc_pilot.workflows.pipeline import recommend_next_action

    state = load_state(project_root)
    if not state:
        return {"ok": False, "error": "no_active_workflow", "message_zh": "无活动工作流"}
    wid = str(state.get("workflow_id") or "")
    phase = str(state.get("phase") or "")
    meta = get_workflow(wid, project_root=project_root)
    fresh = collect_obligations(project_root, wid)
    state["open_items"] = open_obligations(fresh)
    state.pop("all_obligations", None)
    save_state(project_root, state)

    status = str(state.get("status") or "running")
    phase_actions = actions_for_phase(wid, phase, project_root=project_root)
    lf = state.get("last_failure") if isinstance(state.get("last_failure"), dict) else {}

    # Status-first decision (never phase → allowed_actions alone).
    allowed: list[Any] = []
    rework: list[Any] = []
    human_required: dict[str, Any] | None = None

    if status == "human_required":
        allowed = []
        rework = []
        legal = list(
            lf.get("legal_recovery_actions")
            or [
                "inspect_failure",
                "retry_after_environment_fix",
                "abort_run",
            ]
        )
        option_catalog = [
            {
                "label": "环境已修好，继续重试失败 Action",
                "value": "retry_after_environment_fix",
                "description": "pilot_cli retry-after-environment-fix --project <算子目录>",
            },
            {
                "label": "查看结构化失败信息",
                "value": "inspect_failure",
                "description": "pilot_cli inspect-failure --project <算子目录>",
            },
            {
                "label": "终止本次运行",
                "value": "abort_run",
                "description": "pilot_cli abort --project <算子目录>",
            },
        ]
        options = [row for row in option_catalog if row["value"] in legal]
        if not options:
            options = [row for row in option_catalog if row["value"] in {"inspect_failure", "abort_run"}]
        error = str(lf.get("error_code") or lf.get("reason_code") or "unknown")
        detail = str(lf.get("message_zh") or "").strip()
        if "retry_after_environment_fix" in legal:
            recommended_zh = "修好环境后重试"
        else:
            recommended_zh = "查看失败原因"
        ask = {
            "header": f"{wid or 'workflow'} 需要人工介入",
            "question": (
                f"{wid or 'workflow'} 已停止：{error}"
                + (f"。{detail}" if detail else "")
                + f"\n推荐：{recommended_zh}。换话题可直接说新问题（不重问上一题）。"
            ).strip(),
            "options": options,
        }
        human_required = {
            "required_actor": "maintainer",
            "legal_actions": legal,
            "message_zh": (
                f"{wid or 'workflow'} 已停止：{error}"
                + (f"。{detail}" if detail else "")
                + f" 推荐：{recommended_zh}。换话题可直接说新问题。"
            ).strip(),
            "ask_question": ask,
        }
    elif status == "rework_required":
        allowed = []
        reason_codes = []
        if lf.get("error_code"):
            reason_codes.append(str(lf["error_code"]))
        if lf.get("failure_class"):
            reason_codes.append(str(lf["failure_class"]))
        if not reason_codes:
            reason_codes = [str(lf.get("reason_code") or "REWORK_REQUIRED")]
        phase_rework = rework_targets(wid, phase, reason_code=str(lf.get("reason_code") or ""))
        action_ids = [str(aid) for aid in (lf.get("rework_action_ids") or []) if str(aid)]
        if not action_ids and lf.get("action_id"):
            action_ids = [str(lf["action_id"])]
        rework = [
            {
                "action_id": aid,
                "reason_codes": reason_codes,
                "allowed_outputs": [],
                "retry_command": f"python -m ascendc_pilot run-action {aid}",
                "phase_rework_targets": phase_rework,
            }
            for aid in action_ids
        ]
    elif status == "waiting_for_confirmation":
        allowed = []
        rework = []
    elif status == "running":
        allowed = phase_actions
        rework = []
    elif status == "passed":
        allowed = []
        rework = []
    else:
        # blocked / failed / invalid — no normal actions
        allowed = []
        rework = []
        if status in {"blocked", "failed"}:
            human_required = {
                "required_actor": "maintainer",
                "legal_actions": ["inspect_failure", "abort_run"],
                "message_zh": (
                    f"工作流已{status}。"
                    "推荐：查看失败原因。换话题可直接说新问题。"
                ),
            }

    recommended = None
    if status == "running":
        recommended = recommend_next_action(
            project_root,
            workflow_id=wid,
            phase=phase,
            allowed_actions=allowed,
        )

    payload: dict[str, Any] = {
        "ok": True,
        "workflow_id": wid,
        "run_id": state.get("run_id"),
        "phase": phase,
        "phase_label_zh": label_zh_for(wid, phase),
        "status": status,
        "open_items": state["open_items"],
        "allowed_actions": allowed,
        "recommended_next_action": recommended,
        "rework_targets": rework,
        "last_failure": state.get("last_failure"),
        "no_progress_streak": state.get("no_progress_streak"),
        "retry_budget": state.get("retry_budget") or meta.get("retry_budget") or 3,
        "message_zh": _status_message_zh(status, state),
    }
    if recommended and recommended.get("id"):
        payload["message_zh"] = (
            f"下一步必须执行 recommended_next_action=`{recommended['id']}`；"
            "禁止从 allowed_actions 任意跳步；完成后再次 `pilot_cli next`。"
        )
    elif recommended and recommended.get("reason") == "pipeline_complete":
        payload["message_zh"] = str(recommended.get("hint_zh") or payload["message_zh"])
    if human_required is not None:
        payload["human_required"] = human_required
        superseded = bool(state.get("human_decision_superseded"))
        if superseded:
            payload["needs_human_decision"] = False
            payload["ask_interrupted"] = True
            payload["message_zh"] = (
                "上一问确认已被用户打断，不要重问上一题。请按本轮新消息继续。"
                "未点选不等于批准删除/重开。"
            )
            payload["primary_instruction_zh"] = payload["message_zh"]
        elif human_required.get("ask_question"):
            payload["needs_human_decision"] = True
            payload["ask_question"] = human_required["ask_question"]
            payload["primary_instruction_zh"] = (
                "先对本命令的返回做 AskQuestion；选项必须原样使用 ask_question.options。"
                "若用户已在本轮对话里回复（打断确认框），改为 interpret-user-turn，不要重问上一题。"
                "未点选不等于批准删除/重开。"
            )
            from ascendc_pilot.human_interaction import (
                KIND_HUMAN_REQUIRED,
                attach_interaction_request,
            )

            payload = attach_interaction_request(
                payload,
                project_root,
                kind=KIND_HUMAN_REQUIRED,
            )
    if state.get("failure_card"):
        payload["failure_card"] = state.get("failure_card")
    from ascendc_pilot.todo import attach_todo

    return attach_todo(payload, project_root, state=state, allowed_actions=allowed)


def _apply_gate_failure(
    project_root: Path,
    *,
    wid: str,
    last_failure: dict[str, Any],
    preferred_status: str = "rework_required",
) -> dict[str, Any]:
    """Keep phase; set rework/human; preserve blocked if budget already exhausted."""
    from ascendc_pilot.obligations import collect_obligations, open_obligations

    state = load_state(project_root)
    already_blocked = state.get("status") == "blocked"
    all_obl = collect_obligations(project_root, wid)
    state["open_items"] = open_obligations(all_obl)
    state.pop("all_obligations", None)
    state["last_failure"] = last_failure
    if already_blocked:
        state["status"] = "blocked"
    else:
        state["status"] = preferred_status
        # If streak hit budget during record_gate, status may already be blocked
        disk = load_state(project_root)
        if disk.get("status") == "blocked" or int(state.get("no_progress_streak") or 0) >= int(
            state.get("retry_budget") or 3
        ):
            state["status"] = "blocked"
            lf = dict(last_failure)
            lf.setdefault("reason_code", "NO_PROGRESS_BUDGET_EXCEEDED")
            if "预算" not in str(lf.get("message_zh") or ""):
                lf["message_zh"] = (
                    str(lf.get("message_zh") or "")
                    + f"（连续无进展已达预算 {state.get('retry_budget') or 3}）"
                ).strip("（）")
            state["last_failure"] = lf
    state = _apply_progress(project_root, state)
    save_state(project_root, state)
    return load_state(project_root)


def advance_phase(
    project_root: Path,
    next_phase: str,
    *,
    required_gates: list[str] | None = None,
) -> dict[str, Any]:
    from ascendc_pilot.gates import run_named_gate
    from ascendc_pilot.runs import append_event
    from ascendc_pilot.workflows import allowed_transition, get_workflow, label_zh_for
    from ascendc_pilot.workflows.pipeline import missing_phase_actions, recommend_next_action
    from ascendc_pilot.workflows import actions_for_phase

    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    if state.get("status") in TERMINAL:
        raise RuntimeError(f"Workflow already terminal: {state.get('status')}")

    wid = str(state.get("workflow_id") or "")
    meta = get_workflow(wid, project_root=project_root)
    current = str(state.get("phase") or "")
    if not allowed_transition(wid, current, next_phase, kind="forward", project_root=project_root):
        raise RuntimeError(f"Illegal transition {current!r} → {next_phase!r} (no forward edge)")

    # Hard constraint: cannot advance while recommended (or any pipeline) actions remain.
    missing = missing_phase_actions(project_root, wid, current)
    if missing:
        recommended = recommend_next_action(
            project_root,
            workflow_id=wid,
            phase=current,
            allowed_actions=actions_for_phase(wid, current, project_root=project_root),
        )
        msgs = [
            f"阶段 `{current}` 流水线未完成：缺少 Action {missing}",
            f"当前 recommended_next_action=`{(recommended or {}).get('id')}`",
        ]
        from ascendc_pilot.observation import record_pilot_result

        recorded = record_pilot_result(
            project_root,
            ok=False,
            action_id="",
            step_id="advance",
            error_code="PIPELINE_INCOMPLETE",
            messages=msgs,
            source="advance",
            extra={"from": current, "to": next_phase, "missing_actions": missing},
        )
        state = load_state(project_root)
        if state.get("status") not in TERMINAL and state.get("status") != "blocked":
            state["status"] = "rework_required"
            state["last_failure"] = {
                "reason_code": "PIPELINE_INCOMPLETE",
                "error_code": "PIPELINE_INCOMPLETE",
                "message_zh": "；".join(msgs),
                "missing_actions": missing,
                "action_id": (recommended or {}).get("id") or missing[0],
            }
            save_state(project_root, state)
            state = load_state(project_root)
        append_event(
            project_root,
            {
                "type": "advance_failed",
                "from": current,
                "to": next_phase,
                "failed": ["phase_pipeline"],
                "missing_actions": missing,
                "observation_id": (recorded.get("observation") or {}).get("observation_id"),
            },
        )
        return {
            "ok": False,
            "advanced": False,
            "from": current,
            "to": next_phase,
            "error": "PIPELINE_INCOMPLETE",
            "missing_actions": missing,
            "recommended_next_action": recommended,
            "failed_gates": [
                {
                    "gate": "phase_pipeline",
                    "ok": False,
                    "missing_actions": missing,
                    "message": msgs[0],
                }
            ],
            "status": state.get("status"),
            "state": state,
            "observation": recorded.get("observation"),
            "message_zh": "；".join(msgs),
        }

    gate_ids = (
        list(required_gates)
        if required_gates is not None
        else list((meta.get("phase_gates") or {}).get(current) or [])
    )
    results = [run_named_gate(project_root, gid) for gid in gate_ids]
    failed = [r for r in results if not r.get("ok")]
    for r in results:
        record_gate(
            project_root,
            str(r.get("gate") or "gate"),
            ok=bool(r.get("ok")),
            detail=r,
            bump=False,
        )
    if failed:
        msgs = [str(f.get("message") or f.get("gate")) for f in failed]
        preferred = "rework_required"
        explicit = None
        error_code = "GATE_FAILED"
        if any(g.get("gate") == "scope_receipt" for g in failed):
            if any(
                str(g.get("error") or g.get("reason_code") or "") == "INCLUDE_HEAL_UNRESOLVED"
                for g in failed
            ):
                preferred = "rework_required"
                error_code = "INCLUDE_HEAL_UNRESOLVED"
                explicit = None
            else:
                preferred = "blocked"
                error_code = "SCOPE_VALIDATE_BLOCKED"
                explicit = "environment_invariant"
        from ascendc_pilot.observation import record_pilot_result

        recorded = record_pilot_result(
            project_root,
            ok=False,
            action_id="",
            step_id="advance",
            error_code=error_code,
            messages=msgs,
            source="advance",
            explicit_class=explicit,
            extra={"from": current, "to": next_phase, "failed_gates": [f.get("gate") for f in failed]},
        )
        # Prefer observation-driven status; scope_receipt failure is a blocker
        # (machine validate), not a human file-list confirmation.
        state = load_state(project_root)
        if preferred == "blocked" and state.get("status") != "blocked":
            state["status"] = "blocked"
            lf = dict(state.get("last_failure") or {})
            lf["reason_code"] = error_code
            lf["message_zh"] = "范围校验失败（blocker）：检查 operator/arch、Build Context 与 Clang 探针"
            state["last_failure"] = lf
            save_state(project_root, state)
            state = load_state(project_root)
        append_event(
            project_root,
            {
                "type": "advance_failed",
                "from": current,
                "to": next_phase,
                "failed": [f.get("gate") for f in failed],
                "observation_id": (recorded.get("observation") or {}).get("observation_id"),
            },
        )
        return {
            "ok": False,
            "advanced": False,
            "from": current,
            "to": next_phase,
            "failed_gates": failed,
            "status": state.get("status"),
            "state": state,
            "observation": recorded.get("observation"),
            "failure_card": state.get("failure_card"),
            "message_zh": (state.get("last_failure") or {}).get("message_zh") or "；".join(msgs[:4]),
        }

    state = load_state(project_root)
    from ascendc_pilot.obligations import collect_obligations, open_obligations

    state["open_items"] = open_obligations(collect_obligations(project_root, wid))
    state["phase"] = next_phase
    state["phase_label_zh"] = label_zh_for(wid, next_phase)
    state["status"] = "running"
    state["last_failure"] = None
    state = _apply_progress(project_root, state)
    state["no_progress_streak"] = 0
    save_state(project_root, state)
    append_event(project_root, {"type": "advance_ok", "from": current, "to": next_phase})
    fresh = load_state(project_root)
    payload = {
        "ok": True,
        "advanced": True,
        "from": current,
        "to": next_phase,
        "phase_label_zh": state["phase_label_zh"],
        "state": fresh,
    }
    from ascendc_pilot.todo import attach_todo

    return attach_todo(payload, project_root, state=fresh)


def rework_phase(
    project_root: Path,
    *,
    to: str | None = None,
    reason_code: str = "",
) -> dict[str, Any]:
    from ascendc_pilot.runs import append_event
    from ascendc_pilot.workflows import label_zh_for, rework_targets

    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    if state.get("status") in TERMINAL:
        raise RuntimeError(f"Workflow already terminal: {state.get('status')}")
    wid = str(state.get("workflow_id") or "")
    current = str(state.get("phase") or "")
    targets = rework_targets(wid, current, reason_code=reason_code)
    all_targets = rework_targets(wid, current, reason_code="")
    dest = to or (targets[0] if targets else (all_targets[0] if all_targets else ""))
    if not dest:
        raise RuntimeError(f"No rework edge from {current!r} reason={reason_code!r}")
    if dest not in all_targets:
        raise RuntimeError(f"Illegal rework {current!r} → {dest!r}")
    state["phase"] = dest
    state["phase_label_zh"] = label_zh_for(wid, dest)
    state["status"] = "running"
    state["meta"] = dict(state.get("meta") or {})
    state["meta"]["last_rework_reason"] = reason_code
    save_state(project_root, state)
    append_event(project_root, {"type": "rework", "from": current, "to": dest, "reason_code": reason_code})
    fresh = load_state(project_root)
    payload = {"ok": True, "from": current, "to": dest, "state": fresh}
    from ascendc_pilot.todo import attach_todo

    return attach_todo(payload, project_root, state=fresh)


def complete_workflow(project_root: Path, *, reason: str = "") -> dict[str, Any]:
    from ascendc_pilot.gates import run_named_gate
    from ascendc_pilot.obligations import all_obligations_closed, collect_obligations, open_obligations
    from ascendc_pilot.runs import append_event
    from ascendc_pilot.state import release_live_execution
    from ascendc_pilot.workflows import get_workflow, state_ids

    state = load_state(project_root)
    if not state:
        from ascendc_pilot.active_run import clear_active_run

        clear_active_run(project_root)
        return {
            "ok": True,
            "status": "idle",
            "message_zh": "没有活动工作流",
        }
    if state.get("status") in TERMINAL:
        if str(state.get("status") or "") == "passed":
            from ascendc_pilot.todo import attach_todo

            snap = dict(state)
            payload = attach_todo(
                {
                    "ok": True,
                    "status": "passed",
                    "already_complete": True,
                    "state": snap,
                    "message_zh": "工作流已完成；已释放本产物族锁。",
                },
                project_root,
                state=snap,
            )
            release_live_execution(
                project_root, reason="workflow_passed_idempotent", state=snap
            )
            return payload
        raise RuntimeError(f"Workflow already terminal: {state.get('status')}")

    wid = str(state.get("workflow_id") or "")
    meta = get_workflow(wid, project_root=project_root)
    ready = set(meta.get("terminal_ready_states") or state_ids(wid))
    phase = str(state.get("phase") or "")
    if ready and phase not in ready:
        state["status"] = "rework_required"
        state["last_failure"] = {
            "reason_code": "NOT_TERMINAL_READY",
            "message_zh": (
                f"当前阶段「{state.get('phase_label_zh') or phase}」尚不可 complete，请先推进到终态阶段"
            ),
        }
        save_state(project_root, state)
        return {"ok": False, "status": "rework_required", "state": load_state(project_root)}

    # Complete gates come only from Workflow Spec — no implicit prefix attachment.
    intent = str(state.get("intent") or "")
    if intent == "diff_only" and meta.get("complete_gates_diff_only") is not None:
        gate_ids = list(meta.get("complete_gates_diff_only") or [])
    else:
        gate_ids = list(meta.get("complete_gates") or meta.get("gates") or [])
    results = [run_named_gate(project_root, gid) for gid in gate_ids]
    failed = [r for r in results if not r.get("ok")]
    for r in results:
        record_gate(
            project_root,
            str(r.get("gate") or "gate"),
            ok=bool(r.get("ok")),
            detail=r,
            bump=False,
        )
    if failed:
        state = load_state(project_root)
        state = _bump_no_progress(state)
        save_state(project_root, state)
        state = _apply_gate_failure(
            project_root,
            wid=wid,
            last_failure={
                "reason_code": "COMPLETE_GATES_FAILED",
                "message_zh": "完成门禁未通过："
                + "；".join(str(f.get("message") or f.get("gate")) for f in failed[:4]),
                "failed_gates": [f.get("gate") for f in failed],
            },
        )
        return {
            "ok": False,
            "status": state.get("status"),
            "failed_gates": failed,
            "state": state,
        }

    # Obligations must all be in a closed terminal status before passed.
    items = collect_obligations(project_root, wid)
    state = load_state(project_root)
    state["open_items"] = open_obligations(items)
    state.pop("all_obligations", None)
    save_state(project_root, state)
    if not all_obligations_closed(items):
        open_ids = [str(it.get("id")) for it in open_obligations(items)]
        state = _apply_gate_failure(
            project_root,
            wid=wid,
            last_failure={
                "reason_code": "OPEN_OBLIGATIONS",
                "message_zh": "仍有未闭合义务，不能进入 passed："
                + "、".join(open_ids[:8]),
                "open_obligation_ids": open_ids,
            },
        )
        return {
            "ok": False,
            "status": state.get("status"),
            "open_obligations": open_obligations(items),
            "state": state,
        }

    state = load_state(project_root)
    state["status"] = "passed"
    state["terminal_reason"] = reason or "all_gates_passed"
    state["no_progress_streak"] = 0
    state["open_items"] = []
    save_state(project_root, state)
    append_event(project_root, {"type": "workflow_passed"})
    fresh = load_state(project_root)
    payload = {"ok": True, "status": "passed", "state": fresh}
    try:
        from ascendc_pilot.user_goal import mark_workflow_passed

        goal_adv = mark_workflow_passed(project_root, wid)
        if goal_adv:
            payload["user_goal"] = goal_adv.get("goal")
            payload["user_goal_next_workflow_id"] = goal_adv.get("next_workflow_id") or ""
            payload["user_goal_next_summary_zh"] = goal_adv.get("next_summary_zh") or ""
            payload["user_summary_zh"] = str(goal_adv.get("message_zh") or "")
            payload["message_zh"] = str(goal_adv.get("message_zh") or "")
            if goal_adv.get("next_workflow_id"):
                payload["recommended_next_workflow"] = goal_adv["next_workflow_id"]
                payload["primary_directive_zh"] = (
                    "本阶段工作流已完成。"
                    + str(goal_adv.get("message_zh") or "")
                    + " 向用户仅说明意图/刚完成/下一步；禁止粘贴内部字段名。"
                    + f" 下一步：Host `pilot_run` workflow={goal_adv['next_workflow_id']} "
                    f"--project <算子目录>（若需 architecture 则带上）。"
                )
    except Exception:  # noqa: BLE001
        pass
    from ascendc_pilot.todo import attach_todo

    payload = attach_todo(payload, project_root, state=fresh)
    if wid in {"uo-init", "uo-update"}:
        try:
            from ascendc_pilot.occupancy import publish_uo_digest

            published = publish_uo_digest(
                project_root,
                architecture=str((fresh or {}).get("architecture") or ""),
                op_name=str((fresh or {}).get("op_name") or ""),
            )
            payload["uo_digest"] = published.get("digest") or ""
            payload["stale_sessions"] = published.get("stale_sessions") or []
        except Exception:  # noqa: BLE001
            pass
    released = release_live_execution(
        project_root, reason="workflow_passed", state=fresh
    )
    payload["released_execution"] = released
    if not payload.get("message_zh"):
        payload["message_zh"] = "工作流已完成；已释放本产物族锁。"
    return payload
