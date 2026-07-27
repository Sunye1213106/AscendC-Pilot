"""Always-on external Task session registry (control plane; not debug-gated)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_SESSION_ID_RE = re.compile(r"ses_[A-Za-z0-9_]+")


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def normalize_session_id(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    m = _SESSION_ID_RE.search(text)
    return m.group(0) if m else text


def registry_path(project_root: Path, run_id: str, action_id: str) -> Path:
    return (
        Path(project_root)
        / ".ascendc-pilot"
        / "runs"
        / run_id
        / "actions"
        / action_id
        / "external_sessions.yaml"
    )


def global_index_path(project_root: Path) -> Path:
    return Path(project_root) / ".ascendc-pilot" / "external_sessions_index.yaml"


def _new_registration_id() -> str:
    return f"ext_{uuid.uuid4().hex[:12]}"


def load_registry(project_root: Path, run_id: str, action_id: str) -> dict[str, Any]:
    data = _load_yaml(registry_path(project_root, run_id, action_id))
    if not isinstance(data.get("sessions"), list):
        data["sessions"] = []
    data.setdefault("version", 1)
    data.setdefault("run_id", run_id)
    data.setdefault("action_id", action_id)
    return data


def save_registry(project_root: Path, run_id: str, action_id: str, data: dict[str, Any]) -> Path:
    path = registry_path(project_root, run_id, action_id)
    data = dict(data)
    data["version"] = 1
    data["run_id"] = run_id
    data["action_id"] = action_id
    data["updated_at"] = _now()
    _dump_yaml(path, data)
    return path


def _touch_index(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
    registration_id: str,
    external_task_session_id: str = "",
) -> None:
    idx = _load_yaml(global_index_path(project_root))
    rows = list(idx.get("entries") or [])
    rows.append(
        {
            "run_id": run_id,
            "action_id": action_id,
            "registration_id": registration_id,
            "external_task_session_id": external_task_session_id,
            "updated_at": _now(),
        }
    )
    idx = {"version": 1, "entries": rows[-500:]}
    _dump_yaml(global_index_path(project_root), idx)


def register_external_session(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
    primary_session_id: str = "",
    external_task_session_id: str = "",
    actor_id: str = "",
    dispatch_nonce: str = "",
    host_reported_resumed_from: str = "",
) -> dict[str, Any]:
    """Always-on registration. Never gated on debug.is_enabled."""
    root = Path(project_root)
    rid = str(run_id or "").strip()
    aid = str(action_id or "").strip()
    if not rid or not aid:
        return {"ok": False, "error": "run_id_and_action_id_required"}
    reg = load_registry(root, rid, aid)
    registration_id = _new_registration_id()
    nonce = str(dispatch_nonce or "").strip() or f"nonce_{uuid.uuid4().hex[:10]}"
    child = normalize_session_id(external_task_session_id)
    primary = normalize_session_id(primary_session_id)
    previous = latest_external_session(root, run_id=rid, action_id=aid)
    prev_child = str(previous.get("external_task_session_id") or "").strip()
    row = {
        "registration_id": registration_id,
        "dispatch_nonce": nonce,
        "primary_session_id": primary,
        "external_task_session_id": child,
        "previous_external_task_session_id": prev_child,
        "host_reported_resumed_from": normalize_session_id(host_reported_resumed_from),
        "actor_id": actor_id,
        "started_at": _now(),
        "patched_at": "",
    }
    reg.setdefault("sessions", []).append(row)
    save_registry(root, rid, aid, reg)
    _touch_index(root, run_id=rid, action_id=aid, registration_id=registration_id, external_task_session_id=child)
    return {"ok": True, "registration": row, "registration_id": registration_id, "dispatch_nonce": nonce}


def patch_external_session_id(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
    external_task_session_id: str,
    primary_session_id: str = "",
    registration_id: str = "",
    dispatch_nonce: str = "",
    host_reported_resumed_from: str = "",
    actor_id: str = "",
) -> dict[str, Any]:
    """Bind child session id onto a pending registration and record continuation."""
    root = Path(project_root)
    rid = str(run_id or "").strip()
    aid = str(action_id or "").strip()
    child = normalize_session_id(external_task_session_id)
    if not child:
        return {"ok": False, "error": "missing_external_task_session_id"}
    if not rid or not aid:
        return {"ok": False, "error": "run_id_and_action_id_required"}

    reg = load_registry(root, rid, aid)
    sessions = list(reg.get("sessions") or [])
    target: dict[str, Any] | None = None
    if registration_id:
        for row in sessions:
            if isinstance(row, dict) and row.get("registration_id") == registration_id:
                target = row
                break
    if target is None and dispatch_nonce:
        for row in sessions:
            if isinstance(row, dict) and str(row.get("dispatch_nonce") or "") == dispatch_nonce:
                target = row
                break
    if target is None:
        candidates = [
            r
            for r in sessions
            if isinstance(r, dict) and not normalize_session_id(str(r.get("external_task_session_id") or ""))
        ]
        if len(candidates) == 1:
            target = candidates[0]
        elif len(candidates) > 1:
            return {
                "ok": False,
                "error": "ambiguous_pending_registration",
                "pending_count": len(candidates),
            }
    if target is None:
        created = register_external_session(
            root,
            run_id=rid,
            action_id=aid,
            primary_session_id=primary_session_id,
            external_task_session_id=child,
            actor_id=actor_id,
            dispatch_nonce=dispatch_nonce,
            host_reported_resumed_from=host_reported_resumed_from,
        )
        target = created.get("registration") if isinstance(created.get("registration"), dict) else None
        if target is None:
            return {"ok": False, "error": "no_pending_registration"}
        reg = load_registry(root, rid, aid)
        sessions = list(reg.get("sessions") or [])

    previous_child = str(target.get("previous_external_task_session_id") or "").strip()
    if not previous_child:
        for row in reversed(sessions):
            if not isinstance(row, dict):
                continue
            if row.get("registration_id") == target.get("registration_id"):
                continue
            sid = normalize_session_id(str(row.get("external_task_session_id") or ""))
            if sid:
                previous_child = sid
                break

    host_resume = normalize_session_id(host_reported_resumed_from) or normalize_session_id(
        str(target.get("host_reported_resumed_from") or "")
    )
    primary = normalize_session_id(primary_session_id) or normalize_session_id(
        str(target.get("primary_session_id") or "")
    )
    target["external_task_session_id"] = child
    target["primary_session_id"] = primary
    target["previous_external_task_session_id"] = previous_child
    target["host_reported_resumed_from"] = host_resume
    target["patched_at"] = _now()
    if actor_id:
        target["actor_id"] = actor_id
    save_registry(root, rid, aid, {"sessions": sessions})
    _touch_index(
        root,
        run_id=rid,
        action_id=aid,
        registration_id=str(target.get("registration_id") or ""),
        external_task_session_id=child,
    )

    from ascendc_pilot.actions.action_dispatch import record_continuation

    continuation = record_continuation(
        root,
        run_id=rid,
        action_id=aid,
        external_task_session_id=child,
        primary_session_id=primary,
        previous_external_task_session_id=previous_child,
        host_reported_resumed_from=host_resume,
        actor_id=str(target.get("actor_id") or actor_id or ""),
    )
    return {"ok": True, "registration": target, "continuation": continuation}


def latest_external_session(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
) -> dict[str, Any]:
    """Most recent bound external session for this action (control plane)."""
    root = Path(project_root)
    rid = str(run_id or "").strip()
    aid = str(action_id or "").strip()
    if not rid or not aid:
        return {}
    reg = load_registry(root, rid, aid)
    matches: list[dict[str, Any]] = []
    for row in reg.get("sessions") or []:
        if not isinstance(row, dict):
            continue
        sid = normalize_session_id(str(row.get("external_task_session_id") or ""))
        if sid:
            matches.append(row)
    if not matches:
        try:
            from ascendc_pilot.actions.action_dispatch import load_dispatch

            doc = load_dispatch(root, rid, aid)
            sid = normalize_session_id(
                str(doc.get("current_external_task_session_id") or doc.get("external_task_session_id") or "")
            )
            if sid:
                return {
                    "external_task_session_id": sid,
                    "primary_session_id": doc.get("primary_session_id") or doc.get("parent_session_id") or "",
                    "previous_external_task_session_id": doc.get("previous_external_task_session_id") or "",
                    "host_reported_resumed_from": doc.get("host_reported_resumed_from") or "",
                    "continuation_mode": doc.get("continuation_mode"),
                    "lineage_verified": bool(doc.get("lineage_verified")),
                }
        except Exception:  # noqa: BLE001
            pass
        return {}
    row = matches[-1]
    return {
        "external_task_session_id": normalize_session_id(str(row.get("external_task_session_id") or "")),
        "primary_session_id": normalize_session_id(str(row.get("primary_session_id") or "")),
        "previous_external_task_session_id": normalize_session_id(
            str(row.get("previous_external_task_session_id") or "")
        ),
        "host_reported_resumed_from": normalize_session_id(str(row.get("host_reported_resumed_from") or "")),
        "registration_id": row.get("registration_id"),
        "actor_id": row.get("actor_id"),
    }
