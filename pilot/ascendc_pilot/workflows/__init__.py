"""Workflow registry — sole authority for phases, transitions, actions, gates."""

from __future__ import annotations

from typing import Any

from ascendc_pilot.workflows.specs import WORKFLOWS


_TG_PIPELINES: dict[str, dict[str, list[str]]] = {
    "tg-init": {
        "kb_ready": ["kb_check"],
        "contract": ["contract_build"],
        "bind": ["semantic_bind"],
        "merge": ["bind_merge"],
        "nest": ["mid_nest"],
        "gate": ["integrity_gate", "init_audit"],
        "confirm": ["human_confirm"],
    },
    "tg-plan": {
        "scope": ["plan_scope"],
        "gate": ["plan_precheck"],
        # plan_build performs generation, filtering, and review materialization
        # in one deterministic engine invocation. Reusing the same receipt in
        # the following two states prevents skipping the build while avoiding
        # duplicate planner execution.
        "build": ["plan_build"],
        "filter": ["plan_build"],
        "review": ["plan_build"],
        "approve": ["plan_approve"],
    },
    "tg-solve": {
        "gate": ["solve_precheck"],
        # z3_solve performs encoding, solving, and CSV projection atomically.
        "encode": ["z3_solve"],
        "solve": ["z3_solve"],
        "project": ["z3_solve"],
        "cover": ["cover_confirm"],
    },
}

_TG_ACTION_IO: dict[str, dict[str, dict[str, list[str]]]] = {
    "tg-init": {
        "kb_check": {
            "read": ["uo/manifest.yaml", "uo/checks/integrity.yaml"],
            "write": [],
        },
        "contract_build": {
            "read": ["uo/**", "context/**"],
            "write": ["tg/snapshot/**", "tg/consumer_evidence/**", "tg/realization/**", "tg/init/run_context.yaml"],
        },
        "semantic_bind": {
            "read": [
                "tg/realization/llm_bind_prompt_bundle.yaml",
                "tg/realization/binding_inventory.yaml",
                "tg/realization/binding_gaps.yaml",
                "tg/realization/unresolved.yaml",
            ],
            "write": ["tg/realization/semantic_bind_patch.yaml"],
        },
        "bind_merge": {
            "read": ["tg/snapshot/**", "tg/realization/**"],
            "write": ["tg/realization/**"],
        },
        "mid_nest": {
            "read": ["tg/realization/**"],
            "write": ["tg/realization/mid_symbol_queue.yaml"],
        },
        "integrity_gate": {
            "read": ["tg/snapshot/**", "tg/realization/**"],
            "write": [],
        },
        "init_audit": {
            "read": ["tg/snapshot/**", "tg/consumer_evidence/**", "tg/realization/**", "tg/init/**"],
            "write": ["tg/init/audit_report.yaml"],
        },
        "human_confirm": {
            "read": ["tg/init/audit_report.yaml", "tg/realization/**", "tg/snapshot/**"],
            "write": ["tg/init/status.yaml"],
        },
    },
    "tg-plan": {
        "plan_scope": {
            "read": ["tg/init/**", "tg/snapshot/**", "tg/realization/**", "context/**"],
            "write": ["tg/plan/levels/*/plan_scope.yaml"],
        },
        "plan_precheck": {
            "read": ["tg/init/status.yaml", "tg/snapshot/**", "uo/manifest.yaml"],
            "write": [],
        },
        "plan_build": {
            "read": ["tg/init/**", "tg/snapshot/**", "tg/realization/**", "context/**"],
            "write": ["tg/plan/**"],
        },
        "plan_approve": {
            "read": ["tg/plan/levels/*/**"],
            "write": ["tg/plan/levels/*/human_supplement.yaml"],
        },
    },
    "tg-solve": {
        "solve_precheck": {
            "read": ["tg/init/**", "tg/plan/**", "tg/snapshot/**", "uo/manifest.yaml"],
            "write": [],
        },
        "z3_solve": {
            "read": ["tg/init/**", "tg/plan/**", "tg/snapshot/**", "tg/realization/**", "context/**"],
            "write": ["tg/solve/**"],
        },
        "cover_confirm": {
            "read": ["tg/solve/**", "tg/plan/**"],
            "write": [],
        },
    },
}


def _action(meta: dict[str, Any], action_id: str) -> dict[str, Any] | None:
    for row in meta.get("actions") or []:
        if isinstance(row, dict) and str(row.get("id") or "") == action_id:
            return row
    return None


def _apply_tg_control_plane_contracts() -> None:
    """Close TG ordering, ownership, and reset-policy gaps at registry load."""

    for workflow_id, pipelines in _TG_PIPELINES.items():
        meta = WORKFLOWS.get(workflow_id)
        if not isinstance(meta, dict):
            continue
        meta["pipelines"] = {phase: list(actions) for phase, actions in pipelines.items()}

        for action_id, io in _TG_ACTION_IO.get(workflow_id, {}).items():
            row = _action(meta, action_id)
            if row is None:
                continue
            row["allowed_read_paths"] = list(io.get("read") or [])
            row["allowed_write_paths"] = list(io.get("write") or [])

    # Human decisions execute in the current primary session; they are never
    # anonymous actors and must not inherit the UO scope-confirmation recipe.
    for workflow_id, action_id in (("tg-init", "human_confirm"), ("tg-plan", "plan_approve")):
        meta = WORKFLOWS.get(workflow_id) or {}
        row = _action(meta, action_id)
        if row is None:
            continue
        row["agent_id"] = "ascendc-pilot"
        row["role_id"] = "controller"
        row["execution_mode"] = "primary_interactive"
        row["actors"] = ["ascendc-pilot"]

    # Reinitializing a downstream TG workflow must preserve its upstream
    # contracts. Only products owned by that workflow and its descendants are
    # invalidated.
    plan = WORKFLOWS.get("tg-plan") or {}
    plan["reset_policy"] = {
        "reinit_delete": ["tg/plan", "tg/solve"],
        "reinit_preserve": ["uo", "tg/snapshot", "tg/consumer_evidence", "tg/realization", "tg/init"],
        "reinit_wipe_runs": "current",
        "continue_scrub": "from_contracts",
    }
    solve = WORKFLOWS.get("tg-solve") or {}
    solve["reset_policy"] = {
        "reinit_delete": ["tg/solve"],
        "reinit_preserve": ["uo", "tg/snapshot", "tg/consumer_evidence", "tg/realization", "tg/init", "tg/plan"],
        "reinit_wipe_runs": "current",
        "continue_scrub": "from_contracts",
    }


_apply_tg_control_plane_contracts()


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
    """Return actions explicitly bound to ``phase`` via action.phases."""
    meta = get_workflow(workflow_id)
    actions = [a for a in (meta.get("actions") or []) if isinstance(a, dict)]
    return [a for a in actions if phase in set(a.get("phases") or [])]


def phase_pipeline(workflow_id: str, phase: str) -> list[str]:
    """Ordered mandatory actions for a phase (Spec ``pipelines`` is the sole authority)."""
    meta = get_workflow(workflow_id)
    pipes = meta.get("pipelines") or {}
    raw = pipes.get(phase) if isinstance(pipes, dict) else None
    if isinstance(raw, list):
        return [str(a) for a in raw if str(a).strip()]
    return []


def action_by_id(workflow_id: str, action_id: str) -> dict[str, Any] | None:
    meta = get_workflow(workflow_id)
    for a in meta.get("actions") or []:
        if isinstance(a, dict) and str(a.get("id") or "") == action_id:
            return dict(a)
    return None
