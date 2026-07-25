"""Structured recovery routing for UO control plane.

Engine emits stable reason codes; this module resolves them to Workflow Spec
transitions and/or registered action_ids. Human-descriptive strings are never
valid recovery targets.
"""

from __future__ import annotations

from typing import Any

# Reason codes engines may emit.
SCOPE_REWORK = "SCOPE_REWORK"
ENTRYPOINT_REWORK = "ENTRYPOINT_REWORK"
KERNEL_DISPATCH_REWORK = "KERNEL_DISPATCH_REWORK"
BRIDGE_REWORK = "BRIDGE_REWORK"
SEMANTIC_PATCH_REWORK = "SEMANTIC_PATCH_REWORK"
LEDGER_REBUILD_REWORK = "LEDGER_REBUILD_REWORK"
NO_PROGRESS_RECHECK = "NO_PROGRESS_RECHECK"

KNOWN_REASON_CODES = frozenset(
    {
        SCOPE_REWORK,
        ENTRYPOINT_REWORK,
        KERNEL_DISPATCH_REWORK,
        BRIDGE_REWORK,
        SEMANTIC_PATCH_REWORK,
        LEDGER_REBUILD_REWORK,
        NO_PROGRESS_RECHECK,
    }
)

# Default recovery map: reason_code → structured route.
# type=action: same-phase runnable action_id
# type=transition: must change phase first, then next_action
_DEFAULT_ROUTES: dict[str, dict[str, Any]] = {
    SCOPE_REWORK: {
        "type": "transition",
        "target_phase": "scope",
        "reason_code": SCOPE_REWORK,
        "next_action": "scope_confirmation",
    },
    ENTRYPOINT_REWORK: {
        "type": "action",
        "action_id": "detect_score_pre",
        "reason_code": ENTRYPOINT_REWORK,
    },
    KERNEL_DISPATCH_REWORK: {
        "type": "action",
        "action_id": "adjudicate_llm_tasks",
        "reason_code": KERNEL_DISPATCH_REWORK,
    },
    BRIDGE_REWORK: {
        "type": "action",
        "action_id": "adjudicate_llm_tasks",
        "reason_code": BRIDGE_REWORK,
    },
    SEMANTIC_PATCH_REWORK: {
        "type": "action",
        "action_id": "adjudicate_llm_tasks",
        "reason_code": SEMANTIC_PATCH_REWORK,
    },
    LEDGER_REBUILD_REWORK: {
        "type": "action",
        "action_id": "rebuild_from_ledger",
        "reason_code": LEDGER_REBUILD_REWORK,
    },
    NO_PROGRESS_RECHECK: {
        "type": "action",
        "action_id": "adjudicate_llm_tasks",
        "reason_code": NO_PROGRESS_RECHECK,
    },
}


def _workflow_action_ids(workflow_id: str = "uo-init") -> set[str]:
    try:
        from ascendc_pilot.workflows import get_workflow

        meta = get_workflow(workflow_id) or {}
        return {str(a.get("id")) for a in (meta.get("actions") or []) if a.get("id")}
    except Exception:  # noqa: BLE001
        return set()


def _action_phases(workflow_id: str, action_id: str) -> list[str]:
    try:
        from ascendc_pilot.workflows import get_workflow

        meta = get_workflow(workflow_id) or {}
        for a in meta.get("actions") or []:
            if str(a.get("id")) == action_id:
                return [str(p) for p in (a.get("phases") or [])]
    except Exception:  # noqa: BLE001
        pass
    return []


def resolve_recovery(
    reason_code: str,
    *,
    workflow_id: str = "uo-init",
    current_phase: str = "",
    routes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve a stable reason code into an executable recovery route."""
    code = str(reason_code or "").strip()
    table = dict(_DEFAULT_ROUTES)
    try:
        from ascendc_pilot.workflows import get_workflow

        meta = (get_workflow(workflow_id) or {}).get("meta") or {}
        spec_routes = meta.get("recovery_by_reason") or {}
        if isinstance(spec_routes, dict):
            for k, v in spec_routes.items():
                if isinstance(v, dict):
                    row = dict(v)
                    row.setdefault("reason_code", str(k))
                    table[str(k)] = row
    except Exception:  # noqa: BLE001
        pass
    if routes:
        table.update(routes)
    route = dict(table.get(code) or {})
    if not route:
        return {
            "ok": False,
            "error": "UNKNOWN_RECOVERY_REASON",
            "reason_code": code,
        }
    route.setdefault("reason_code", code)
    rtype = str(route.get("type") or "")
    registered = _workflow_action_ids(workflow_id)

    if rtype == "action":
        aid = str(route.get("action_id") or "")
        if not aid or (registered and aid not in registered):
            return {
                "ok": False,
                "error": "UNREGISTERED_RECOVERY_ACTION",
                "reason_code": code,
                "action_id": aid,
            }
        phases = _action_phases(workflow_id, aid)
        if current_phase and phases and current_phase not in phases:
            # Cross-phase: convert to transition toward the first legal phase.
            return {
                "ok": True,
                "recovery": {
                    "type": "transition",
                    "target_phase": phases[0],
                    "reason_code": code,
                    "next_action": aid,
                },
            }
        return {"ok": True, "recovery": {"type": "action", "action_id": aid, "reason_code": code}}

    if rtype == "transition":
        next_action = str(route.get("next_action") or "")
        target_phase = str(route.get("target_phase") or "")
        if next_action and registered and next_action not in registered:
            return {
                "ok": False,
                "error": "UNREGISTERED_RECOVERY_ACTION",
                "reason_code": code,
                "action_id": next_action,
            }
        if current_phase and target_phase and current_phase == target_phase and next_action:
            return {
                "ok": True,
                "recovery": {
                    "type": "action",
                    "action_id": next_action,
                    "reason_code": code,
                },
            }
        return {
            "ok": True,
            "recovery": {
                "type": "transition",
                "target_phase": target_phase,
                "reason_code": code,
                "next_action": next_action,
            },
        }

    return {"ok": False, "error": "INVALID_RECOVERY_ROUTE", "reason_code": code, "route": route}


def recoveries_for_closure_gaps(
    *,
    host_closed: bool,
    kernel_closed: bool,
    blocking_gap_count: int,
    unconsumed_patch_count: int,
    no_progress: bool = False,
    workflow_id: str = "uo-init",
    current_phase: str = "extract",
) -> dict[str, Any]:
    """Build structured recovery list from recheck closure gaps."""
    reason_codes: list[str] = []
    if not host_closed:
        reason_codes.append(SCOPE_REWORK)
        reason_codes.append(ENTRYPOINT_REWORK)
    if not kernel_closed:
        reason_codes.append(KERNEL_DISPATCH_REWORK)
    if blocking_gap_count:
        reason_codes.append(BRIDGE_REWORK)
        reason_codes.append(SEMANTIC_PATCH_REWORK)
    if unconsumed_patch_count:
        reason_codes.append(LEDGER_REBUILD_REWORK)
    if no_progress:
        reason_codes.append(NO_PROGRESS_RECHECK)

    recoveries: list[dict[str, Any]] = []
    action_ids: list[str] = []
    seen: set[str] = set()
    for code in reason_codes:
        if code in seen:
            continue
        seen.add(code)
        resolved = resolve_recovery(code, workflow_id=workflow_id, current_phase=current_phase)
        if not resolved.get("ok"):
            continue
        rec = resolved["recovery"]
        recoveries.append(rec)
        if rec.get("type") == "action" and rec.get("action_id"):
            action_ids.append(str(rec["action_id"]))
        elif rec.get("type") == "transition" and rec.get("next_action"):
            # Expose next_action only after noting transition is required.
            # For authorize compatibility, also list next_action when already in target phase.
            if current_phase == rec.get("target_phase"):
                action_ids.append(str(rec["next_action"]))

    # Deduplicate while preserving order.
    uniq_actions: list[str] = []
    for a in action_ids:
        if a not in uniq_actions:
            uniq_actions.append(a)

    return {
        "reason_codes": list(seen),
        "recoveries": recoveries,
        # Legacy flat list: ONLY registered action_ids (never prose).
        "recovery_actions": uniq_actions,
    }


def is_registered_action_id(action_id: str, *, workflow_id: str = "uo-init") -> bool:
    aid = str(action_id or "").strip()
    if not aid or " " in aid or "/" in aid:
        return False
    registered = _workflow_action_ids(workflow_id)
    if not registered:
        return bool(aid) and " " not in aid
    return aid in registered


def filter_executable_recovery_actions(
    actions: list[str],
    *,
    workflow_id: str = "uo-init",
) -> list[str]:
    """Drop any descriptive / unregistered strings from a recovery_actions list."""
    out: list[str] = []
    for a in actions:
        s = str(a or "").strip()
        if is_registered_action_id(s, workflow_id=workflow_id) and s not in out:
            out.append(s)
    return out
