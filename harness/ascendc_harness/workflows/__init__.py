"""Workflow registry — sole authority for phases, transitions, actions, gates."""

from __future__ import annotations

from typing import Any

from ascendc_harness.workflows.specs import WORKFLOWS


def get_workflow(workflow_id: str) -> dict[str, Any]:
    if workflow_id not in WORKFLOWS:
        raise KeyError(f"Unknown workflow: {workflow_id}")
    return dict(WORKFLOWS[workflow_id])


def list_user_workflows() -> list[str]:
    return [wid for wid, meta in WORKFLOWS.items() if meta.get("slash") and not meta.get("reserved")]


def state_ids(workflow_id: str) -> list[str]:
    meta = get_workflow(workflow_id)
    states = meta.get("states") or []
    if states:
        return [str(s["id"]) for s in states if isinstance(s, dict) and s.get("id")]
    return list(meta.get("phases") or [])


def label_zh_for(workflow_id: str, phase: str) -> str:
    meta = get_workflow(workflow_id)
    for s in meta.get("states") or []:
        if isinstance(s, dict) and s.get("id") == phase:
            return str(s.get("label_zh") or phase)
    return phase


def entry_state(workflow_id: str) -> str:
    meta = get_workflow(workflow_id)
    if meta.get("entry_state"):
        return str(meta["entry_state"])
    ids = state_ids(workflow_id)
    if not ids:
        raise ValueError(f"workflow {workflow_id} has no entry_state")
    return ids[0]


def allowed_transition(workflow_id: str, frm: str, to: str, *, kind: str = "forward") -> bool:
    meta = get_workflow(workflow_id)
    for edge in meta.get("transitions") or []:
        if not isinstance(edge, dict):
            continue
        if edge.get("from") == frm and edge.get("to") == to and str(edge.get("kind") or "forward") == kind:
            return True
    return False


def rework_targets(workflow_id: str, frm: str, *, reason_code: str = "") -> list[str]:
    meta = get_workflow(workflow_id)
    out: list[str] = []
    for edge in meta.get("transitions") or []:
        if not isinstance(edge, dict):
            continue
        if edge.get("from") != frm or str(edge.get("kind") or "") != "rework":
            continue
        codes = edge.get("reason_codes") or []
        if reason_code and codes and reason_code not in codes:
            continue
        to = str(edge.get("to") or "")
        if to and to not in out:
            out.append(to)
    return out


def actions_for_phase(workflow_id: str, phase: str) -> list[dict[str, Any]]:
    meta = get_workflow(workflow_id)
    phase_gates = set((meta.get("phase_gates") or {}).get(phase) or [])
    actions = [a for a in (meta.get("actions") or []) if isinstance(a, dict)]
    if not phase_gates:
        return actions
    matched = [a for a in actions if phase_gates.intersection(set(a.get("gates") or []))]
    return matched or actions
