"""Deterministic workflow drain for Host adapters.

The Host/LLM chooses a workflow once.  After that, Pilot owns action ordering.
This helper executes only deterministic actions returned by ``acp next`` and
advances only across unconditional forward edges.  It stops before any LLM
subagent or primary-interactive action so the Host never has to guess whether
an engine or an agent should run next.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ascendc_pilot.actions.failure_text import preferred_failure_text

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


def _progress(msg: str, *, event: str = "stage", extra: dict[str, Any] | None = None) -> None:
    """Emit a compact stage line on stderr and append host_stage.jsonl.

    Live UX for long runs belongs to Host ``pilot_run`` (OpenCode tool metadata
    progress bar). These lines are a machine protocol for that bar to parse,
    not a 15s "still running" heartbeat for bash.
    """
    sys.stderr.write(f"[acp-auto] {msg}\n")
    sys.stderr.flush()
    try:
        from ascendc_pilot.paths import agent_root
        from ascendc_pilot.state import load_state

        # Best-effort: resolve project from env when drive is running under Host.
        import os

        root_s = (os.environ.get("ASCENDC_PROJECT_ROOT") or "").strip()
        if not root_s:
            return
        root = Path(root_s)
        st = load_state(root) or {}
        run_id = str(st.get("run_id") or "").strip()
        if not run_id:
            return
        events = agent_root(root) / "runs" / run_id / "host_stage.jsonl"
        events.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": time.time(),
            "event": event,
            "message": msg,
            **(extra or {}),
        }
        with events.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _attach_todo(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Always attach fresh todo_sync so Host can todowrite after auto returns."""
    from ascendc_pilot.state import load_state
    from ascendc_pilot.todo import attach_todo

    st = load_state(root) or {}
    if not st:
        # complete/abort already released the live slot; keep the snapshot so
        # Host still todowrites the finished board instead of wiping Todo.
        complete = payload.get("complete") if isinstance(payload.get("complete"), dict) else {}
        snap = complete.get("state") if isinstance(complete.get("state"), dict) else {}
        if not snap and isinstance(payload.get("state"), dict):
            snap = payload["state"]
        if snap:
            st = snap
    if not st:
        return payload
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


def _action_failure_detail(result: dict[str, Any]) -> str:
    """Prefer engine/finalize human text over the generic stop_reason token."""
    return preferred_failure_text(result, fallback="deterministic_action_failed")


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
    _progress("drain start")

    def _done(payload: dict[str, Any]) -> dict[str, Any]:
        _progress(
            f"drain stop reason={payload.get('stop_reason') or payload.get('error') or 'done'} "
            f"executed={len(executed)}"
        )
        attached = _attach_todo(root, payload)
        try:
            from ascendc_pilot.actions.dispatch import attach_host_step

            return attach_host_step(root, attached, reenter_drive=False)
        except Exception as exc:  # noqa: BLE001
            if not (
                isinstance(attached.get("host_step"), dict)
                and str(attached["host_step"].get("kind") or "").strip()
            ):
                attached["host_step"] = {
                    "kind": "failed",
                    "message_zh": f"host_step 装配失败：{type(exc).__name__}",
                    "error_detail": str(exc)[:400],
                }
            attached.setdefault("error", "HOST_STEP_ATTACH_FAILED")
            return attached

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
        phase_label = str(state.get("phase_label_zh") or phase)
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
                        "请先对本返回做 AskQuestion（选项必须原样使用 ask_question.options）。"
                        "若用户已打断并在对话里回复，改为 interpret-user-turn，不要重问上一题。"
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
                if descriptor["execution_kind"] == "primary_interactive":
                    result = prepare(root, action_id)
                    executed.append(
                        {
                            "action_id": action_id,
                            "actor_id": descriptor["actor_id"],
                            "execution_kind": "primary_interactive",
                            "ok": bool(result.get("ok")),
                            "auto_finalize": bool(result.get("auto_finalize")),
                            "error": str(result.get("error") or ""),
                        }
                    )
                    if result.get("ok") and (
                        result.get("auto_finalize") or result.get("auto_skip_human_gate")
                    ):
                        continue
                    ask = result.get("ask_question")
                    if not isinstance(ask, dict):
                        eng = result.get("engine") if isinstance(result.get("engine"), dict) else {}
                        ask = eng.get("ask_question") if isinstance(eng.get("ask_question"), dict) else None
                    return _done(
                        {
                            "ok": True,
                            "stopped": True,
                            "stop_reason": "interaction_required",
                            "needs_human_decision": True,
                            "ask_question": ask,
                            "prepare": result,
                            "workflow_id": workflow_id,
                            "phase": phase,
                            "status": status,
                            "next": descriptor,
                            "recommended_command": "pilot_run",
                            "executed": executed,
                            "message_zh": str(
                                result.get("message_zh")
                                or (ask or {}).get("question")
                                or (
                                    f"确定性步骤已自动执行到交互边界；下一步 `{action_id}` "
                                    f"由 `{descriptor['actor_id']}` 执行。"
                                    "请先按 todo.todo_sync 同步 Todo，再派发交互 Action。"
                                )
                            ),
                        }
                    )
                return _done(
                    {
                        "ok": True,
                        "stopped": True,
                        "stop_reason": "interaction_required",
                        "workflow_id": workflow_id,
                        "phase": phase,
                        "status": status,
                        "next": descriptor,
                        "recommended_command": "pilot_run",
                        "executed": executed,
                        "message_zh": (
                            f"确定性步骤已自动执行到交互边界；下一步 `{action_id}` "
                            f"由 `{descriptor['actor_id']}` 执行。"
                            "请先按 todo.todo_sync 同步 Todo，再派发交互 Action。"
                        ),
                    }
                )

            _progress(f"run {action_id} (phase={phase} {phase_label})")
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
            eng = result.get("engine") if isinstance(result.get("engine"), dict) else {}
            ask = result.get("ask_question")
            if not isinstance(ask, dict):
                ask = eng.get("ask_question") if isinstance(eng.get("ask_question"), dict) else None
            if result.get("needs_human_decision") or eng.get("needs_human_decision") or ask:
                return _done(
                    {
                        "ok": True,
                        "stopped": True,
                        "stop_reason": "interaction_required",
                        "needs_human_decision": True,
                        "ask_question": ask,
                        "workflow_id": workflow_id,
                        "phase": phase,
                        "status": status,
                        "executed": executed,
                        "next": descriptor,
                        "message_zh": str(
                            result.get("message_zh")
                            or (ask or {}).get("question")
                            or f"确定性 Action `{action_id}` 需要人工选择后再继续。"
                        ),
                    }
                )
            if not result.get("ok"):
                _progress(f"{action_id} FAIL")
                detail = _action_failure_detail(result)
                eng = result.get("engine") if isinstance(result.get("engine"), dict) else {}
                from ascendc_pilot.actions.failure_text import with_failure_hint

                message_zh = with_failure_hint(
                    str(result.get("message_zh") or "").strip()
                    or f"确定性 Action `{action_id}` 失败：{detail}",
                    result,
                )
                return _done(
                    {
                        "ok": False,
                        "stopped": True,
                        "stop_reason": "deterministic_action_failed",
                        "workflow_id": workflow_id,
                        "phase": phase,
                        "failed_action": action_id,
                        "executed": executed,
                        "error": str(eng.get("error") or result.get("error") or detail),
                        "message_zh": message_zh,
                        "hint_zh": str(result.get("hint_zh") or ""),
                        "failure": {
                            "error": eng.get("error") or result.get("error"),
                            "message_zh": result.get("message_zh") or eng.get("message_zh"),
                            "issues": eng.get("issues") or result.get("issues"),
                            "finalize": result.get("finalize"),
                            "engine": eng,
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
