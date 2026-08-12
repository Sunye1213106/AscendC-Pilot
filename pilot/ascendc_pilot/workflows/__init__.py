"""Read-only workflow registry accessors.

Workflow Spec stays the source of truth. This module derives the runtime
execution binding that Host adapters consume so deterministic actions always
have an explicit engine identity and never carry a Host Task prompt.
"""

from __future__ import annotations

from typing import Any

from ascendc_pilot.workflows.specs import WORKFLOWS as _SPEC_WORKFLOWS


_DETERMINISTIC_ENGINE_BY_DOMAIN = {
    "uo": "deterministic-uo-engine",
    "tg": "deterministic-tg-engine",
}


def _normalize_execution_registry(
    specs: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Derive explicit Action execution ownership for Host/runtime consumption.

    ``agent_id=None`` historically meant "internal deterministic engine" for
    UO while TG already named ``deterministic-tg-engine`` explicitly. Some
    legacy deterministic Actions also retained a model-facing ``task_prompt_id``
    even though their implementation is an ``ENGINE_REGISTRY`` function. Those
    two asymmetries leaked into generated Skills, OpenCode Task routing, leases,
    and prompt pruning. Normalize them once at the registry boundary instead of
    teaching every Host adapter another heuristic.
    """
    registry: dict[str, dict[str, Any]] = {}
    for workflow_id, source in specs.items():
        if not isinstance(source, dict):
            continue
        meta = dict(source)
        domain = str(meta.get("engine") or "").strip().lower()
        deterministic_actor = _DETERMINISTIC_ENGINE_BY_DOMAIN.get(domain, "")
        actions: list[dict[str, Any]] = []
        used_agents: dict[str, str] = {}

        # UO runtime state lives under the arch-scoped agent root, while the
        # canonical CodeMap product is deliberately arch-neutral one directory
        # above it (`../uo/*.uo`). Keep that canonical root explicit in the
        # workflow ceiling for the two deterministic UO writers.
        if workflow_id in {"uo-init", "uo-update"}:
            write_roots = list(meta.get("write_roots") or [])
            if "../uo" not in write_roots:
                write_roots.append("../uo")
            meta["write_roots"] = write_roots

        for raw in source.get("actions") or []:
            if not isinstance(raw, dict):
                continue
            action = dict(raw)
            role = str(action.get("role_id") or "").strip()
            mode = str(action.get("execution_mode") or "").strip()
            actor = str(action.get("agent_id") or "").strip()
            deterministic = mode == "deterministic" or role == "deterministic_engine"
            if deterministic:
                if not actor:
                    if not deterministic_actor:
                        raise RuntimeError(
                            f"{workflow_id}/{action.get('id')}: deterministic Action has no engine actor"
                        )
                    actor = deterministic_actor
                    action["agent_id"] = actor
                # Deterministic Actions consume structured Action context through
                # the engine function. A Host Task prompt is both unreachable and
                # dangerous: prune_runtime_context intentionally removes it, while
                # prepare_action renders prompts before invoking the engine.
                action["task_prompt_id"] = None
            action["actors"] = [actor] if actor else []
            if actor:
                used_agents[actor] = role or (
                    "deterministic_engine" if deterministic else ""
                )
            actions.append(action)

        meta["actions"] = actions
        agents: list[dict[str, Any]] = [
            dict(row) for row in (source.get("agents") or []) if isinstance(row, dict)
        ]
        present = {str(row.get("id") or "") for row in agents}
        for actor, role in used_agents.items():
            if actor and actor not in present:
                agents.append({"id": actor, "role": role})
                present.add(actor)
        meta["agents"] = agents
        registry[workflow_id] = meta
    return registry


# Runtime/Host-facing registry. Raw editable authority remains specs.WORKFLOWS.
WORKFLOWS = _normalize_execution_registry(_SPEC_WORKFLOWS)


def resolve_workflow_id(workflow_id: str) -> str:
    seen: set[str] = set()
    wid = str(workflow_id or "").strip()
    while wid and wid not in seen:
        seen.add(wid)
        meta = WORKFLOWS.get(wid)
        if not isinstance(meta, dict):
            break
        alias = str(meta.get("alias_of") or "").strip()
        if not alias:
            break
        wid = alias
    return wid


def resolve_tg_mode(project_root: Any | None = None, *, default: str = "tilingkey_full_coverage") -> str:
    if project_root is None:
        return default
    try:
        from pathlib import Path
        from ascendc_pilot.paths import tg_root
        tg = tg_root(Path(project_root))
        for rel in ("plan/plan_intent.yaml", "init/init_intent.yaml"):
            path = tg / rel
            if not path.is_file():
                continue
            try:
                import yaml
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            mode = str((doc or {}).get("mode") or "").strip()
            if mode:
                return mode
    except Exception:
        return default
    return default


def _rederive_actor_fields(merged: dict[str, Any], patch: dict[str, Any]) -> None:
    if "agent_id" not in patch and "role_id" not in patch:
        return
    agent_id = str(merged.get("agent_id") or "")
    merged["actors"] = [agent_id] if agent_id else []
    try:
        from ascendc_pilot.ownership import infer_execution_mode
        merged["execution_mode"] = infer_execution_mode(
            agent_id=agent_id or None,
            role_id=str(merged.get("role_id") or "") or None,
            execution_mode=None,
        )
    except Exception:
        pass
    if (
        str(merged.get("execution_mode") or "") == "deterministic"
        or str(merged.get("role_id") or "") == "deterministic_engine"
    ):
        merged["task_prompt_id"] = None


def _apply_mode_overlay(meta: dict[str, Any], mode: str | None) -> dict[str, Any]:
    overlays = meta.get("mode_overlays") if isinstance(meta.get("mode_overlays"), dict) else {}
    if not overlays:
        return meta
    default = str((meta.get("meta") or {}).get("default_mode") or "tilingkey_full_coverage")
    chosen = mode or default
    overlay = overlays.get(chosen) or overlays.get(default) or {}
    if not isinstance(overlay, dict):
        return meta
    out = dict(meta)
    for key in ("pipelines", "transitions", "phase_gates", "complete_gates", "terminal_ready_states", "phases", "states", "gates"):
        if key in overlay:
            out[key] = overlay[key]
    overrides = overlay.get("action_overrides")
    if isinstance(overrides, dict) and overrides:
        actions: list[dict[str, Any]] = []
        for row in out.get("actions") or []:
            if not isinstance(row, dict):
                continue
            aid = str(row.get("id") or "")
            patch = overrides.get(aid)
            if isinstance(patch, dict) and patch:
                merged = dict(row)
                for key, value in patch.items():
                    if value is None:
                        merged.pop(key, None)
                    else:
                        merged[key] = value
                _rederive_actor_fields(merged, patch)
                actions.append(merged)
            else:
                actions.append(dict(row))
        out["actions"] = actions
    out["_active_mode"] = chosen
    return out


def get_workflow(workflow_id: str, *, project_root: Any | None = None, mode: str | None = None) -> dict[str, Any]:
    wid = resolve_workflow_id(workflow_id)
    if wid not in WORKFLOWS:
        raise KeyError(f"Unknown workflow: {workflow_id}")
    meta = dict(WORKFLOWS[wid])
    if meta.get("mode_overlays"):
        meta = _apply_mode_overlay(meta, mode or resolve_tg_mode(project_root))
    return meta


def list_user_workflows() -> list[str]:
    return [wid for wid, meta in WORKFLOWS.items() if meta.get("slash") and not meta.get("reserved") and not meta.get("alias_of")]


def state_ids(workflow_id: str) -> list[str]:
    meta = get_workflow(workflow_id)
    states = meta.get("states") or []
    if states:
        return [str(state["id"]) for state in states if isinstance(state, dict) and state.get("id")]
    return list(meta.get("phases") or [])


def label_zh_for(workflow_id: str, phase: str) -> str:
    meta = get_workflow(workflow_id)
    for state in meta.get("states") or []:
        if isinstance(state, dict) and state.get("id") == phase:
            return str(state.get("label_zh") or phase)
    return phase


def entry_state(workflow_id: str) -> str:
    meta = get_workflow(workflow_id)
    if meta.get("entry_state"):
        return str(meta["entry_state"])
    ids = state_ids(workflow_id)
    if not ids:
        raise ValueError(f"workflow {workflow_id} has no entry_state")
    return ids[0]


def allowed_transition(workflow_id: str, frm: str, to: str, *, kind: str = "forward", project_root: Any | None = None, mode: str | None = None) -> bool:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    return any(
        isinstance(edge, dict)
        and edge.get("from") == frm
        and edge.get("to") == to
        and str(edge.get("kind") or "forward") == kind
        for edge in meta.get("transitions") or []
    )


def rework_targets(workflow_id: str, frm: str, *, reason_code: str = "", project_root: Any | None = None, mode: str | None = None) -> list[str]:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    out: list[str] = []
    for edge in meta.get("transitions") or []:
        if not isinstance(edge, dict) or edge.get("from") != frm or str(edge.get("kind") or "") != "rework":
            continue
        codes = edge.get("reason_codes") or []
        if reason_code and codes and reason_code not in codes:
            continue
        target = str(edge.get("to") or "")
        if target and target not in out:
            out.append(target)
    return out


def actions_for_phase(workflow_id: str, phase: str, *, project_root: Any | None = None, mode: str | None = None) -> list[dict[str, Any]]:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    return [action for action in (meta.get("actions") or []) if isinstance(action, dict) and phase in set(action.get("phases") or [])]


def phase_pipeline(workflow_id: str, phase: str, *, project_root: Any | None = None, mode: str | None = None) -> list[str]:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    pipes = meta.get("pipelines") or {}
    raw = pipes.get(phase) if isinstance(pipes, dict) else None
    return [str(action) for action in raw if str(action).strip()] if isinstance(raw, list) else []


def action_by_id(workflow_id: str, action_id: str, *, project_root: Any | None = None, mode: str | None = None) -> dict[str, Any] | None:
    meta = get_workflow(workflow_id, project_root=project_root, mode=mode)
    for action in meta.get("actions") or []:
        if isinstance(action, dict) and str(action.get("id") or "") == action_id:
            return dict(action)
    return None


def workflow_requires_project(workflow_id: str) -> bool:
    """True when Spec declares ``requires_project`` for this workflow."""
    wid = resolve_workflow_id(workflow_id)
    meta = WORKFLOWS.get(wid) or {}
    if "requires_project" in meta:
        return bool(meta.get("requires_project"))
    # Reserved / alias stubs without the flag are not operator workflows.
    return False


def workflow_requires_architecture(workflow_id: str) -> bool:
    """True when Spec declares ``requires_architecture`` for this workflow."""
    wid = resolve_workflow_id(workflow_id)
    meta = WORKFLOWS.get(wid) or {}
    if "requires_architecture" in meta:
        return bool(meta.get("requires_architecture"))
    return False


def workflows_needing_project() -> frozenset[str]:
    return frozenset(
        wid for wid in list_user_workflows() if workflow_requires_project(wid)
    )


def workflows_needing_architecture() -> frozenset[str]:
    return frozenset(
        wid for wid in list_user_workflows() if workflow_requires_architecture(wid)
    )


def cognitive_skill_id(workflow_id: str) -> str:
    wid = resolve_workflow_id(workflow_id)
    meta = WORKFLOWS.get(wid) or {}
    return str(meta.get("cognitive_skill_id") or "").strip()


def architecture_required_labels() -> str:
    """Human-readable list of workflows that require --architecture (for CLI/docs)."""
    ids = sorted(workflows_needing_architecture())
    return "/".join(ids) if ids else "(none)"


def project_required_labels() -> str:
    ids = sorted(workflows_needing_project())
    return "/".join(ids) if ids else "(none)"
