"""Deterministic workflow drain for Host adapters.

The Host/LLM chooses a workflow once.  After that, Pilot owns action ordering.
This helper executes only deterministic actions returned by ``acp next`` and
advances only across unconditional forward edges.  It stops before any LLM
subagent or primary-interactive action so the Host never has to guess whether
an engine or an agent should run next.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

PrepareAction = Callable[[Path, str], dict[str, Any]]


def _execution_descriptor(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": str(action.get("id") or ""),
        "execution_kind": str(action.get("execution_mode") or ""),
        "actor_id": str(action.get("agent_id") or ""),
        "role_id": str(action.get("role_id") or ""),
        "task_prompt_id": str(action.get("task_prompt_id") or ""),
        "output_contract_id": str(action.get("output_contract_id") or ""),
    }


def _unconditional_forward_phase(meta: dict[str, Any], phase: str) -> str:
    targets: list[str] = []
    for edge in meta.get("transitions") or []:
        if not isinstance(edge, dict):
            continue
        if str(edge.get("from") or "") != phase:
            continue
        if str(edge.get("kind") or "forward") != "forward":
            continue
        # Reason-coded forward edges are alternate routes (e.g. DIFF_ONLY), not
        # the default path for an automatic drain.
        if edge.get("reason_codes"):
            continue
        target = str(edge.get("to") or "").strip()
        if target and target not in targets:
            targets.append(target)
    return targets[0] if len(targets) == 1 else ""


def _progress(msg: str) -> None:
    sys.stderr.write(f"[acp-auto] {msg}\n")
    sys.stderr.flush()


def _attach_todo(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Always attach fresh todo_sync so Host can todowrite after auto returns."""
    from ascendc_pilot.state import load_state
    from ascendc_pilot.todo import attach_todo

    st = load_state(root) or {}
    out = attach_todo(payload, root, state=st, sync_merge=True)
    todo = out.get("todo") or {}
    sync = dict(todo.get("todo_sync") or {})
    sync["force"] = True
    sync["after_auto"] = True
    sync["instruction_zh"] = (
        "run-action auto 返回后必须立刻 todowrite（merge=true）"
        "全量同步 todo.todo_sync.items（含全部 id/content/status/priority）；"
        "禁止等到下一轮再同步；禁止子集；禁止在回复里讨论要不要同步。"
    )
    todo["todo_sync"] = sync
    out["todo"] = todo
    return out


def drive_until_interaction(
    project_root: Path,
    *,
    prepare: PrepareAction,
    max_steps: int = 128,
) -> dict[str, Any]:
    """Drain deterministic work and stop at the next Host interaction boundary."""
    from ascendc_pilot.state import (
        advance_phase,
        complete_workflow,
        describe_next,
        load_state,
    )
    from ascendc_pilot.workflows import action_by_id, get_workflow

    root = Path(project_root)
    executed: list[dict[str, Any]] = []

    def _done(payload: dict[str, Any]) -> dict[str, Any]:
        return _attach_todo(root, payload)

    for _ in range(max_steps):
        state = load_state(root)
        if not state:
            return _done(
                {
                    "ok": False,
                    "error": "no_active_workflow",
                    "message_zh": "无活动 workflow；请先 acp start",
                    "executed": executed,
                }
            )
        workflow_id = str(state.get("workflow_id") or "")
        phase = str(state.get("phase") or "")
        status = str(state.get("status") or "")
        if status != "running":
            payload: dict[str, Any] = {
                "ok": status == "passed",
                "stopped": True,
                "stop_reason": "workflow_status",
                "workflow_id": workflow_id,
                "phase": phase,
                "status": status,
                "executed": executed,
                "last_failure": state.get("last_failure"),
            }
            # Surface AskQuestion so Host can prompt in the same turn.
            if status in {"human_required", "waiting_for_confirmation"}:
                nxt = describe_next(root)
                ask = None
                if isinstance(nxt, dict):
                    hr = nxt.get("human_required") if isinstance(nxt.get("human_required"), dict) else {}
                    ask = (hr or {}).get("ask_question") or nxt.get("ask_question")
                    if nxt.get("needs_human_decision") is not None:
                        payload["needs_human_decision"] = nxt.get("needs_human_decision")
                    if hr:
                        payload["human_required"] = hr
                    payload["next"] = nxt
                if ask:
                    payload["ask_question"] = ask
                    payload["stop_reason"] = "interaction_required"
                    payload["message_zh"] = (
                        f"workflow `{workflow_id}` 状态为 `{status}`；"
                        "请先对本返回做 AskQuestion（选项必须原样使用 ask_question.options），"
                        "再按所选合法恢复动作继续。"
                    )
            return _done(payload)

        nxt = describe_next(root)
        if not nxt.get("ok"):
            return _done({**nxt, "executed": executed})
        recommended = nxt.get("recommended_next_action") or {}
        action_id = str(recommended.get("id") or "").strip()

        if action_id:
            action = action_by_id(workflow_id, action_id, project_root=root)
            if not action:
                return _done(
                    {
                        "ok": False,
                        "error": "recommended_action_missing",
                        "workflow_id": workflow_id,
                        "phase": phase,
                        "action_id": action_id,
                        "executed": executed,
                    }
                )
            descriptor = _execution_descriptor(action)
            if descriptor["execution_kind"] != "deterministic":
                return _done(
                    {
                        "ok": True,
                        "stopped": True,
                        "stop_reason": "interaction_required",
                        "workflow_id": workflow_id,
                        "phase": phase,
                        "status": status,
                        "next": descriptor,
                        "recommended_command": f"acp run-action {action_id}",
                        "executed": executed,
                        "message_zh": (
                            f"确定性步骤已自动执行到交互边界；下一步 `{action_id}` "
                            f"由 `{descriptor['actor_id']}` 执行。"
                            "请先按 todo.todo_sync 同步 Todo，再派发交互 Action。"
                        ),
                    }
                )

            _progress(f"run {action_id} (phase={phase})")
            result = prepare(root, action_id)
            executed.append(
                {
                    "action_id": action_id,
                    "actor_id": descriptor["actor_id"],
                    "execution_kind": "deterministic",
                    "ok": bool(result.get("ok")),
                    "auto_finalize": bool(result.get("auto_finalize")),
                    "error": str(result.get("error") or ""),
                }
            )
            if not result.get("ok"):
                _progress(f"{action_id} FAIL")
                return _done(
                    {
                        "ok": False,
                        "stopped": True,
                        "stop_reason": "deterministic_action_failed",
                        "workflow_id": workflow_id,
                        "phase": phase,
                        "failed_action": action_id,
                        "executed": executed,
                        "failure": {
                            "error": result.get("error"),
                            "message_zh": result.get("message_zh"),
                            "finalize": result.get("finalize"),
                        },
                    }
                )
            _progress(f"{action_id} ok")
            continue

        if str(recommended.get("reason") or "") == "pipeline_complete":
            meta = get_workflow(workflow_id, project_root=root)
            if phase in set(meta.get("terminal_ready_states") or []):
                completed = complete_workflow(root)
                return _done(
                    {
                        "ok": bool(completed.get("ok")),
                        "stopped": True,
                        "stop_reason": "workflow_complete"
                        if completed.get("ok")
                        else "completion_gate_failed",
                        "workflow_id": workflow_id,
                        "phase": phase,
                        "status": (completed.get("state") or completed).get("status"),
                        "executed": executed,
                        "complete": completed,
                    }
                )

            target = _unconditional_forward_phase(meta, phase)
            if not target:
                return _done(
                    {
                        "ok": False,
                        "error": "AUTO_ADVANCE_AMBIGUOUS",
                        "workflow_id": workflow_id,
                        "phase": phase,
                        "executed": executed,
                        "message_zh": "当前阶段没有唯一的无条件 forward edge；拒绝自动猜测下一阶段。",
                    }
                )
            advanced = advance_phase(root, target)
            if not advanced.get("ok"):
                return _done(
                    {
                        "ok": False,
                        "stopped": True,
                        "stop_reason": "advance_failed",
                        "workflow_id": workflow_id,
                        "phase": phase,
                        "target_phase": target,
                        "executed": executed,
                        "advance": advanced,
                    }
                )
            _progress(f"advance {phase}→{target}")
            executed.append(
                {
                    "transition": f"{phase}->{target}",
                    "ok": True,
                }
            )
            continue

        return _done(
            {
                "ok": False,
                "error": "AUTO_DRIVE_NO_RECOMMENDATION",
                "workflow_id": workflow_id,
                "phase": phase,
                "recommended_next_action": recommended,
                "executed": executed,
            }
        )

    return _done(
        {
            "ok": False,
            "error": "AUTO_DRIVE_STEP_LIMIT",
            "max_steps": max_steps,
            "executed": executed,
            "message_zh": "自动执行达到安全步数上限；停止而不是继续猜测。",
        }
    )


__all__ = ["drive_until_interaction"]
