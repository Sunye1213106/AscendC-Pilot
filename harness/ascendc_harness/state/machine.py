"""Advance / rework / complete / next — state machine operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ascendc_harness.state import (
    TERMINAL,
    _apply_progress,
    _bump_no_progress,
    _status_message_zh,
    load_state,
    record_gate,
    save_state,
)


def describe_next(project_root: Path) -> dict[str, Any]:
    from ascendc_harness.obligations import collect_obligations, open_obligations
    from ascendc_harness.workflows import actions_for_phase, get_workflow, label_zh_for, rework_targets

    state = load_state(project_root)
    if not state:
        return {"ok": False, "error": "no_active_workflow", "message_zh": "无活动工作流"}
    wid = str(state.get("workflow_id") or "")
    phase = str(state.get("phase") or "")
    meta = get_workflow(wid)
    fresh = collect_obligations(project_root, wid)
    state["open_items"] = open_obligations(fresh)
    state["all_obligations"] = fresh
    save_state(project_root, state)

    status = str(state.get("status") or "running")
    actions = actions_for_phase(wid, phase)
    rework: list[str] = []
    if status == "rework_required":
        reason = str((state.get("last_failure") or {}).get("reason_code") or "")
        rework = rework_targets(wid, phase, reason_code=reason)

    return {
        "ok": True,
        "workflow_id": wid,
        "run_id": state.get("run_id"),
        "phase": phase,
        "phase_label_zh": label_zh_for(wid, phase),
        "status": status,
        "open_items": state["open_items"],
        "allowed_actions": actions,
        "rework_targets": rework,
        "last_failure": state.get("last_failure"),
        "no_progress_streak": state.get("no_progress_streak"),
        "retry_budget": state.get("retry_budget") or meta.get("retry_budget") or 3,
        "message_zh": _status_message_zh(status, state),
    }


def _apply_gate_failure(
    project_root: Path,
    *,
    wid: str,
    last_failure: dict[str, Any],
    preferred_status: str = "rework_required",
) -> dict[str, Any]:
    """Keep phase; set rework/human; preserve blocked if budget already exhausted."""
    from ascendc_harness.obligations import collect_obligations, open_obligations

    state = load_state(project_root)
    already_blocked = state.get("status") == "blocked"
    all_obl = collect_obligations(project_root, wid)
    state["open_items"] = open_obligations(all_obl)
    state["all_obligations"] = all_obl
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
    from ascendc_harness.gates import run_named_gate
    from ascendc_harness.runs import append_event
    from ascendc_harness.workflows import allowed_transition, get_workflow, label_zh_for

    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    if state.get("status") in TERMINAL:
        raise RuntimeError(f"Workflow already terminal: {state.get('status')}")

    wid = str(state.get("workflow_id") or "")
    meta = get_workflow(wid)
    current = str(state.get("phase") or "")
    if not allowed_transition(wid, current, next_phase, kind="forward"):
        raise RuntimeError(f"Illegal transition {current!r} → {next_phase!r} (no forward edge)")

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
        state = load_state(project_root)
        state = _bump_no_progress(state)
        save_state(project_root, state)
        msgs = [str(f.get("message") or f.get("gate")) for f in failed]
        preferred = "rework_required"
        lf: dict[str, Any] = {
            "reason_code": "GATE_FAILED",
            "message_zh": "门禁未通过：" + "；".join(msgs[:4]),
            "failed_gates": [f.get("gate") for f in failed],
            "from": current,
            "to": next_phase,
        }
        if any(g.get("gate") == "scope_receipt" for g in failed):
            preferred = "human_required"
            lf["reason_code"] = "SCOPE_CONFIRMATION_REQUIRED"
            lf["message_zh"] = "请确认本次算子源码范围"
        state = _apply_gate_failure(project_root, wid=wid, last_failure=lf, preferred_status=preferred)
        append_event(
            project_root,
            {
                "type": "advance_failed",
                "from": current,
                "to": next_phase,
                "failed": [f.get("gate") for f in failed],
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
            "message_zh": (state.get("last_failure") or {}).get("message_zh") or lf["message_zh"],
        }

    state = load_state(project_root)
    from ascendc_harness.obligations import collect_obligations

    state["open_items"] = collect_obligations(project_root, wid)
    state["phase"] = next_phase
    state["phase_label_zh"] = label_zh_for(wid, next_phase)
    state["status"] = "running"
    state["last_failure"] = None
    state = _apply_progress(project_root, state)
    state["no_progress_streak"] = 0
    save_state(project_root, state)
    append_event(project_root, {"type": "advance_ok", "from": current, "to": next_phase})
    return {
        "ok": True,
        "advanced": True,
        "from": current,
        "to": next_phase,
        "phase_label_zh": state["phase_label_zh"],
        "state": load_state(project_root),
    }


def rework_phase(
    project_root: Path,
    *,
    to: str | None = None,
    reason_code: str = "",
) -> dict[str, Any]:
    from ascendc_harness.runs import append_event
    from ascendc_harness.workflows import label_zh_for, rework_targets

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
    return {"ok": True, "from": current, "to": dest, "state": load_state(project_root)}


def complete_workflow(project_root: Path, *, reason: str = "") -> dict[str, Any]:
    from ascendc_harness.gates import run_named_gate
    from ascendc_harness.obligations import all_obligations_closed, collect_obligations, open_obligations
    from ascendc_harness.runs import append_event
    from ascendc_harness.workflows import get_workflow, state_ids

    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    if state.get("status") in TERMINAL:
        raise RuntimeError(f"Workflow already terminal: {state.get('status')}")

    wid = str(state.get("workflow_id") or "")
    meta = get_workflow(wid)
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
    state["all_obligations"] = items
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
    return {"ok": True, "status": "passed", "state": load_state(project_root)}
