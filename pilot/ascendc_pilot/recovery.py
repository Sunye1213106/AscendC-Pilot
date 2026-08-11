"""Structured recovery routing for the public UO CodeMap workflow.

Engines emit stable reason codes.  Recovery may only target the five public
uo-init Actions; internal compiler helpers are implementation details and must
never be surfaced to OpenCode/Cursor as runnable recovery actions.
LLM gap-patching is not part of the default `/uo-init` path — use
`/uo-investigate` for residual analysis without mutating canonical `.uo`.
"""

from __future__ import annotations

from typing import Any

SCOPE_REWORK = "SCOPE_REWORK"
ENTRYPOINT_REWORK = "ENTRYPOINT_REWORK"
KERNEL_DISPATCH_REWORK = "KERNEL_DISPATCH_REWORK"
BRIDGE_REWORK = "BRIDGE_REWORK"
SEMANTIC_PATCH_REWORK = "SEMANTIC_PATCH_REWORK"
LEDGER_REBUILD_REWORK = "LEDGER_REBUILD_REWORK"
NO_PROGRESS_RECHECK = "NO_PROGRESS_RECHECK"
MACRO_MATERIALIZE_REWORK = "MACRO_MATERIALIZE_REWORK"
KEY_DERIVATION_REWORK = "KEY_DERIVATION_REWORK"
SCOPE_EXPANSION_REWORK = "SCOPE_EXPANSION_REWORK"

KNOWN_REASON_CODES = frozenset(
    {
        SCOPE_REWORK,
        ENTRYPOINT_REWORK,
        KERNEL_DISPATCH_REWORK,
        BRIDGE_REWORK,
        SEMANTIC_PATCH_REWORK,
        LEDGER_REBUILD_REWORK,
        NO_PROGRESS_RECHECK,
        MACRO_MATERIALIZE_REWORK,
        KEY_DERIVATION_REWORK,
        SCOPE_EXPANSION_REWORK,
    }
)

# Public five-stage recovery map.  Internal helpers such as scope_scan,
# extract_kernel, normalize_predicates, resolve_gaps and key_triage are never
# executable recovery targets. Semantic residuals re-enter analyze (retain
# unresolved) rather than an LLM resolve stage.
_DEFAULT_ROUTES: dict[str, dict[str, Any]] = {
    SCOPE_REWORK: {
        "type": "transition",
        "target_phase": "prepare",
        "next_action": "prepare",
        "reason_code": SCOPE_REWORK,
    },
    SCOPE_EXPANSION_REWORK: {
        "type": "transition",
        "target_phase": "prepare",
        "next_action": "prepare",
        "reason_code": SCOPE_EXPANSION_REWORK,
    },
    ENTRYPOINT_REWORK: {
        "type": "transition",
        "target_phase": "extract",
        "next_action": "extract",
        "reason_code": ENTRYPOINT_REWORK,
    },
    KERNEL_DISPATCH_REWORK: {
        "type": "transition",
        "target_phase": "extract",
        "next_action": "extract",
        "reason_code": KERNEL_DISPATCH_REWORK,
    },
    MACRO_MATERIALIZE_REWORK: {
        "type": "transition",
        "target_phase": "analyze",
        "next_action": "analyze",
        "reason_code": MACRO_MATERIALIZE_REWORK,
    },
    KEY_DERIVATION_REWORK: {
        "type": "transition",
        "target_phase": "analyze",
        "next_action": "analyze",
        "reason_code": KEY_DERIVATION_REWORK,
    },
    LEDGER_REBUILD_REWORK: {
        "type": "transition",
        "target_phase": "analyze",
        "next_action": "analyze",
        "reason_code": LEDGER_REBUILD_REWORK,
    },
    BRIDGE_REWORK: {
        "type": "transition",
        "target_phase": "analyze",
        "next_action": "analyze",
        "reason_code": BRIDGE_REWORK,
    },
    SEMANTIC_PATCH_REWORK: {
        "type": "transition",
        "target_phase": "analyze",
        "next_action": "analyze",
        "reason_code": SEMANTIC_PATCH_REWORK,
    },
    NO_PROGRESS_RECHECK: {
        "type": "human_required",
        "reason_code": NO_PROGRESS_RECHECK,
        "diagnosis": "deadlock_no_progress",
    },
}

# Historical triage labels can still occur in old intermediate evidence.  They
# are interpreted only as reason categories; execution always resolves through
# the public routes above.
_ROUTE_TO_REASON: dict[str, str] = {
    "macro_semantic_materializer": MACRO_MATERIALIZE_REWORK,
    "uo-key-resolve": KEY_DERIVATION_REWORK,
    "deterministic_accept": LEDGER_REBUILD_REWORK,
    "uo-semantic-resolve": SEMANTIC_PATCH_REWORK,
    "uo-semantic-resolver": SEMANTIC_PATCH_REWORK,
    "uo-gap-investigator": SEMANTIC_PATCH_REWORK,
}


def recoveries_for_task_routes(
    tasks: list[dict[str, Any]],
    *,
    workflow_id: str = "uo-init",
    current_phase: str = "extract",
) -> dict[str, Any]:
    """Map blocking task categories to public recovery actions."""
    reason_codes: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        route = str(task.get("route") or "").strip()
        category = str(task.get("triage_category") or "").strip()
        effective = str(task.get("effective_task_type") or task.get("type") or "").strip()
        if category == "incomplete_scope_candidate" or effective == "evidence_enrichment":
            reason_codes.append(
                SCOPE_EXPANSION_REWORK if task.get("pending_scope_expansion") else SEMANTIC_PATCH_REWORK
            )
        elif effective == "candidate_generation" or category == "candidate_generation_required":
            reason_codes.append(SEMANTIC_PATCH_REWORK)
        elif effective == "macro_semantics" or route == "macro_semantic_materializer":
            reason_codes.append(MACRO_MATERIALIZE_REWORK)
        elif effective == "key_derivation" or route == "uo-key-resolve" or category == "key_derivation_gap":
            reason_codes.append(KEY_DERIVATION_REWORK)
        elif route in _ROUTE_TO_REASON:
            reason_codes.append(_ROUTE_TO_REASON[route])
        else:
            reason_codes.append(SEMANTIC_PATCH_REWORK)

    return _resolve_many(
        reason_codes,
        workflow_id=workflow_id,
        current_phase=current_phase,
    )


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
        for action in meta.get("actions") or []:
            if str(action.get("id")) == action_id:
                return [str(phase) for phase in (action.get("phases") or [])]
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
    """Resolve one stable reason code into an executable public route."""
    code = str(reason_code or "").strip()
    table = dict(_DEFAULT_ROUTES)

    # Workflow metadata may refine a public route, but cannot introduce an
    # unregistered internal action because validation below is fail-closed.
    try:
        from ascendc_pilot.workflows import get_workflow

        meta = (get_workflow(workflow_id) or {}).get("meta") or {}
        spec_routes = meta.get("recovery_by_reason") or {}
        if isinstance(spec_routes, dict):
            for key, value in spec_routes.items():
                if isinstance(value, dict):
                    row = dict(value)
                    row.setdefault("reason_code", str(key))
                    table[str(key)] = row
    except Exception:  # noqa: BLE001
        pass
    if routes:
        table.update(routes)

    # UO public-route safety wins over stale spec metadata.
    if workflow_id == "uo-init" and code in _DEFAULT_ROUTES:
        table[code] = dict(_DEFAULT_ROUTES[code])

    route = dict(table.get(code) or {})
    if not route:
        return {"ok": False, "error": "UNKNOWN_RECOVERY_REASON", "reason_code": code}
    route.setdefault("reason_code", code)
    route_type = str(route.get("type") or "")
    registered = _workflow_action_ids(workflow_id)

    if route_type == "human_required":
        return {
            "ok": True,
            "recovery": {
                "type": "human_required",
                "reason_code": code,
                "diagnosis": route.get("diagnosis") or "deadlock_no_progress",
            },
        }

    if route_type == "action":
        action_id = str(route.get("action_id") or "")
        if not action_id or (registered and action_id not in registered):
            return {
                "ok": False,
                "error": "UNREGISTERED_RECOVERY_ACTION",
                "reason_code": code,
                "action_id": action_id,
            }
        phases = _action_phases(workflow_id, action_id)
        if current_phase and phases and current_phase not in phases:
            return {
                "ok": True,
                "recovery": {
                    "type": "transition",
                    "target_phase": phases[0],
                    "reason_code": code,
                    "next_action": action_id,
                },
            }
        return {
            "ok": True,
            "recovery": {"type": "action", "action_id": action_id, "reason_code": code},
        }

    if route_type == "transition":
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


def _resolve_many(
    reason_codes: list[str],
    *,
    workflow_id: str,
    current_phase: str,
) -> dict[str, Any]:
    recoveries: list[dict[str, Any]] = []
    action_ids: list[str] = []
    ordered: list[str] = []
    seen: set[str] = set()
    human_required = False
    diagnoses: list[str] = []

    for code in reason_codes:
        if code in seen:
            continue
        seen.add(code)
        ordered.append(code)
        resolved = resolve_recovery(code, workflow_id=workflow_id, current_phase=current_phase)
        if not resolved.get("ok"):
            continue
        recovery = resolved["recovery"]
        recoveries.append(recovery)
        if recovery.get("type") == "human_required":
            human_required = True
            if recovery.get("diagnosis"):
                diagnoses.append(str(recovery["diagnosis"]))
        elif recovery.get("type") == "action" and recovery.get("action_id"):
            action_ids.append(str(recovery["action_id"]))
        elif recovery.get("type") == "transition" and current_phase == recovery.get("target_phase") and recovery.get("next_action"):
            action_ids.append(str(recovery["next_action"]))

    unique_actions: list[str] = []
    for action in action_ids:
        if action not in unique_actions:
            unique_actions.append(action)
    result: dict[str, Any] = {
        "reason_codes": ordered,
        "recoveries": recoveries,
        "recovery_actions": unique_actions,
    }
    if human_required:
        result["human_required"] = True
        result["deadlock_diagnosis"] = diagnoses or ["deadlock_no_progress"]
    return result


def recoveries_for_closure_gaps(
    *,
    host_closed: bool,
    kernel_closed: bool,
    blocking_gap_count: int,
    unconsumed_patch_count: int,
    no_progress: bool = False,
    workflow_id: str = "uo-init",
    current_phase: str = "extract",
    blocking_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build public recovery routes from closure gaps."""
    reason_codes: list[str] = []
    if not host_closed:
        reason_codes.extend([SCOPE_REWORK, ENTRYPOINT_REWORK])
    if not kernel_closed:
        reason_codes.append(KERNEL_DISPATCH_REWORK)
    if blocking_gap_count:
        tasks = [task for task in (blocking_tasks or []) if isinstance(task, dict)]
        if tasks:
            routed = recoveries_for_task_routes(
                tasks,
                workflow_id=workflow_id,
                current_phase=current_phase,
            )
            reason_codes.extend(list(routed.get("reason_codes") or []))
        else:
            reason_codes.extend([BRIDGE_REWORK, SEMANTIC_PATCH_REWORK])
    if unconsumed_patch_count:
        reason_codes.append(LEDGER_REBUILD_REWORK)

    kernel_only_stall = (
        no_progress
        and not kernel_closed
        and host_closed
        and blocking_gap_count == 0
        and unconsumed_patch_count == 0
    )
    if no_progress and not kernel_only_stall:
        reason_codes.append(NO_PROGRESS_RECHECK)

    return _resolve_many(
        reason_codes,
        workflow_id=workflow_id,
        current_phase=current_phase,
    )


def is_registered_action_id(action_id: str, *, workflow_id: str = "uo-init") -> bool:
    value = str(action_id or "").strip()
    if not value or " " in value or "/" in value:
        return False
    registered = _workflow_action_ids(workflow_id)
    return value in registered if registered else bool(value)


def filter_executable_recovery_actions(
    actions: list[str],
    *,
    workflow_id: str = "uo-init",
) -> list[str]:
    """Drop descriptive/internal strings from an executable recovery list."""
    out: list[str] = []
    for action in actions:
        value = str(action or "").strip()
        if is_registered_action_id(value, workflow_id=workflow_id) and value not in out:
            out.append(value)
    return out
