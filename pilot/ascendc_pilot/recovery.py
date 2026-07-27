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
        # Kernel dispatch is now deterministic inside entrypoint/macro materialization.
        # Re-run that stage instead of entering an LLM adjudication loop with no tasks.
        "action_id": "detect_score_pre",
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
        # Same fingerprint with no closure progress → stop LLM retry loops.
        "type": "human_required",
        "reason_code": NO_PROGRESS_RECHECK,
        "diagnosis": "deadlock_no_progress",
    },
    MACRO_MATERIALIZE_REWORK: {
        "type": "action",
        "action_id": "rebuild_from_ledger",
        "reason_code": MACRO_MATERIALIZE_REWORK,
    },
    KEY_DERIVATION_REWORK: {
        "type": "action",
        "action_id": "key_triage",
        "reason_code": KEY_DERIVATION_REWORK,
    },
    SCOPE_EXPANSION_REWORK: {
        "type": "action",
        "action_id": "apply_scope_expansion",
        "reason_code": SCOPE_EXPANSION_REWORK,
    },
}


_ROUTE_TO_REASON: dict[str, str] = {
    "macro_semantic_materializer": MACRO_MATERIALIZE_REWORK,
    "uo-key-resolve": KEY_DERIVATION_REWORK,
    "deterministic_accept": LEDGER_REBUILD_REWORK,
    "uo-semantic-resolve": SEMANTIC_PATCH_REWORK,
}


def recoveries_for_task_routes(
    tasks: list[dict[str, Any]],
    *,
    workflow_id: str = "uo-init",
    current_phase: str = "extract",
) -> dict[str, Any]:
    """Map blocking tasks to recovery actions by triage route / effective type."""
    reason_codes: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        route = str(task.get("route") or "").strip()
        category = str(task.get("triage_category") or "").strip()
        effective = str(task.get("effective_task_type") or task.get("type") or "").strip()
        if category == "incomplete_scope_candidate" or effective == "evidence_enrichment":
            # Sequencing: propose first; apply only after pending_scope_expansion.
            if task.get("pending_scope_expansion"):
                reason_codes.append(SCOPE_EXPANSION_REWORK)
            else:
                reason_codes.append(SEMANTIC_PATCH_REWORK)
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

    recoveries: list[dict[str, Any]] = []
    action_ids: list[str] = []
    seen: set[str] = set()
    ordered: list[str] = []
    for code in reason_codes:
        if code in seen:
            continue
        seen.add(code)
        ordered.append(code)
        resolved = resolve_recovery(code, workflow_id=workflow_id, current_phase=current_phase)
        if not resolved.get("ok"):
            continue
        rec = resolved["recovery"]
        recoveries.append(rec)
        if rec.get("type") == "action" and rec.get("action_id"):
            action_ids.append(str(rec["action_id"]))
        elif rec.get("type") == "transition" and current_phase == rec.get("target_phase") and rec.get("next_action"):
            action_ids.append(str(rec["next_action"]))

    uniq: list[str] = []
    for action in action_ids:
        if action not in uniq:
            uniq.append(action)
    return {
        "reason_codes": ordered,
        "recoveries": recoveries,
        "recovery_actions": uniq,
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
    # Kernel dispatch is a source-derived deterministic responsibility. Keep the
    # recovery fail-closed even when an older workflow spec still points at LLM
    # adjudication; this also makes mixed-version installations safe.
    if code == KERNEL_DISPATCH_REWORK:
        table[code] = dict(_DEFAULT_ROUTES[KERNEL_DISPATCH_REWORK])
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

    if rtype == "human_required":
        return {
            "ok": True,
            "recovery": {
                "type": "human_required",
                "reason_code": code,
                "diagnosis": route.get("diagnosis") or "deadlock_no_progress",
            },
        }

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
    blocking_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build structured recovery list from recheck closure gaps."""
    reason_codes: list[str] = []
    if not host_closed:
        reason_codes.append(SCOPE_REWORK)
        reason_codes.append(ENTRYPOINT_REWORK)
    if not kernel_closed:
        reason_codes.append(KERNEL_DISPATCH_REWORK)
    if blocking_gap_count:
        tasks = [t for t in (blocking_tasks or []) if isinstance(t, dict)]
        if tasks:
            routed = recoveries_for_task_routes(
                tasks,
                workflow_id=workflow_id,
                current_phase=current_phase,
            )
            reason_codes.extend(list(routed.get("reason_codes") or []))
        else:
            # Fallback when triage fields unavailable.
            reason_codes.append(BRIDGE_REWORK)
            reason_codes.append(SEMANTIC_PATCH_REWORK)
    if unconsumed_patch_count:
        reason_codes.append(LEDGER_REBUILD_REWORK)
    # Kernel-only no-progress is already handled by the deterministic entrypoint rerun.
    # Do not append a second LLM recovery that would immediately no-op and loop.
    kernel_only_stall = (
        no_progress
        and not kernel_closed
        and host_closed
        and blocking_gap_count == 0
        and unconsumed_patch_count == 0
    )
    if no_progress and not kernel_only_stall:
        reason_codes.append(NO_PROGRESS_RECHECK)

    recoveries: list[dict[str, Any]] = []
    action_ids: list[str] = []
    seen: set[str] = set()
    ordered_reason_codes: list[str] = []
    human_required = False
    diagnoses: list[str] = []
    for code in reason_codes:
        if code in seen:
            continue
        seen.add(code)
        ordered_reason_codes.append(code)
        resolved = resolve_recovery(code, workflow_id=workflow_id, current_phase=current_phase)
        if not resolved.get("ok"):
            continue
        rec = resolved["recovery"]
        recoveries.append(rec)
        if rec.get("type") == "human_required":
            human_required = True
            if rec.get("diagnosis"):
                diagnoses.append(str(rec["diagnosis"]))
            continue
        if rec.get("type") == "action" and rec.get("action_id"):
            action_ids.append(str(rec["action_id"]))
        elif rec.get("type") == "transition" and rec.get("next_action"):
            # Expose next_action only after noting transition is required.
            # For authorize compatibility, also list next_action when already in target phase.
            if current_phase == rec.get("target_phase"):
                action_ids.append(str(rec["next_action"]))

    # Deduplicate while preserving order.
    uniq_actions: list[str] = []
    for action in action_ids:
        if action not in uniq_actions:
            uniq_actions.append(action)

    out = {
        "reason_codes": ordered_reason_codes,
        "recoveries": recoveries,
        # Legacy flat list: ONLY registered action_ids (never prose).
        "recovery_actions": uniq_actions,
    }
    if human_required:
        out["human_required"] = True
        out["deadlock_diagnosis"] = diagnoses or ["deadlock_no_progress"]
    return out


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
    for action in actions:
        value = str(action or "").strip()
        if is_registered_action_id(value, workflow_id=workflow_id) and value not in out:
            out.append(value)
    return out
