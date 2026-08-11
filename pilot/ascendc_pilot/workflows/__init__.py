"""Read-only workflow registry accessors."""

from __future__ import annotations

from typing import Any

from ascendc_pilot.workflows.specs import WORKFLOWS


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
