"""Deterministic workflow drain for Host adapters.

The Host/LLM chooses a workflow once.  After that, Pilot owns action ordering.
This helper executes only deterministic actions returned by ``acp next`` and
advances only across unconditional forward edges.  It stops before any LLM
subagent or primary-interactive action so the Host never has to guess whether
an engine or an agent should run next.
"""

from __future__ import annotations

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

    for _ in range(max_steps):
        state = load_state(root)
        if not state:
            return {
                "ok": False,
                "error": "no_active_workflow",
                "message_zh": "无活动 workflow；请先 acp start",
                "executed": executed,
            }
        workflow_id = str(state.get("workflow_id") or "")
        phase = str(state.get("phase") or "")
        status = str(state.get("status") or "")
        if status != "running":
            return {
                "ok": status == "passed",
                "stopped": True,
                "stop_reason": "workflow_status",
                "workflow_id": workflow_id,
                "phase": phase,
                "status": status,
                "executed": executed,
                "last_failure": state.get("last_failure"),
            }

        nxt = describe_next(root)
        if not nxt.get("ok"):
            return {**nxt, "executed": executed}
        recommended = nxt.get("recommended_next_action") or {}
        action_id = str(recommended.get("id") or "").strip()

        if action_id:
            action = action_by_id(workflow_id, action_id, project_root=root)
            if not action:
                return {
                    "ok": False,
                    "error": "recommended_action_missing",
                    "workflow_id": workflow_id,
                    "phase": phase,
                    "action_id": action_id,
                    "executed": executed,
                }
            descriptor = _execution_descriptor(action)
            if descriptor["execution_kind"] != "deterministic":
                return {
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
                    ),
                }

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
                return {
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
            continue

        if str(recommended.get("reason") or "") == "pipeline_complete":
            meta = get_workflow(workflow_id, project_root=root)
            if phase in set(meta.get("terminal_ready_states") or []):
                completed = complete_workflow(root)
                return {
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

            target = _unconditional_forward_phase(meta, phase)
            if not target:
                return {
                    "ok": False,
                    "error": "AUTO_ADVANCE_AMBIGUOUS",
                    "workflow_id": workflow_id,
                    "phase": phase,
                    "executed": executed,
                    "message_zh": "当前阶段没有唯一的无条件 forward edge；拒绝自动猜测下一阶段。",
                }
            advanced = advance_phase(root, target)
            if not advanced.get("ok"):
                return {
                    "ok": False,
                    "stopped": True,
                    "stop_reason": "advance_failed",
                    "workflow_id": workflow_id,
                    "phase": phase,
                    "target_phase": target,
                    "executed": executed,
                    "advance": advanced,
                }
            executed.append(
                {
                    "transition": f"{phase}->{target}",
                    "ok": True,
                }
            )
            continue

        return {
            "ok": False,
            "error": "AUTO_DRIVE_NO_RECOMMENDATION",
            "workflow_id": workflow_id,
            "phase": phase,
            "recommended_next_action": recommended,
            "executed": executed,
        }

    return {
        "ok": False,
        "error": "AUTO_DRIVE_STEP_LIMIT",
        "max_steps": max_steps,
        "executed": executed,
        "message_zh": "自动执行达到安全步数上限；停止而不是继续猜测。",
    }


__all__ = ["drive_until_interaction"]
