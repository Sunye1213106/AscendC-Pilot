"""Action dispatch lineage: Pilot action_session vs external Task session."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


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


def dispatch_path(project_root: Path, run_id: str, action_id: str) -> Path:
    return (
        Path(project_root)
        / ".ascendc-pilot"
        / "runs"
        / run_id
        / "actions"
        / action_id
        / "dispatch.yaml"
    )


def handoff_path(project_root: Path, run_id: str, action_id: str) -> Path:
    return (
        Path(project_root)
        / ".ascendc-pilot"
        / "runs"
        / run_id
        / "actions"
        / action_id
        / "handoff.yaml"
    )


def load_dispatch(project_root: Path, run_id: str, action_id: str) -> dict[str, Any]:
    return _load_yaml(dispatch_path(project_root, run_id, action_id))


def write_dispatch(project_root: Path, run_id: str, action_id: str, payload: dict[str, Any]) -> Path:
    path = dispatch_path(project_root, run_id, action_id)
    prev = _load_yaml(path)
    doc = {
        "version": 1,
        "run_id": run_id,
        "action_id": action_id,
        "updated_at": _now(),
        **prev,
        **payload,
    }
    if "created_at" not in doc:
        doc["created_at"] = _now()
    _dump_yaml(path, doc)
    return path


def latest_external_session(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
) -> dict[str, Any]:
    """Look up the most recent registered child session for this action."""
    from ascendc_pilot.actions.external_session_registry import (
        latest_external_session as _latest,
    )

    return _latest(Path(project_root), run_id=run_id, action_id=action_id)


def prepare_resume_fields(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
    workflow_status: str,
) -> dict[str, Any]:
    """Return resume_required / resume_session_id for rework prepares."""
    if str(workflow_status or "") not in {"rework_required", "human_required"}:
        return {"resume_required": False, "resume_session_id": ""}
    latest = latest_external_session(project_root, run_id=run_id, action_id=action_id)
    sid = str(latest.get("external_task_session_id") or "").strip()
    if not sid:
        return {"resume_required": False, "resume_session_id": ""}
    write_dispatch(
        project_root,
        run_id,
        action_id,
        {
            "workflow_id": "uo-init",
            "resume_required": True,
            "resume_session_id": sid,
            "external_task_session_id": sid,
            "current_external_task_session_id": sid,
            "previous_external_task_session_id": sid,
            "continuation_mode": "resume",
            # Verified only after host reports resumed_from == previous child.
            "lineage_verified": False,
        },
    )
    return {"resume_required": True, "resume_session_id": sid}


def record_continuation(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
    external_task_session_id: str,
    primary_session_id: str = "",
    previous_external_task_session_id: str = "",
    host_reported_resumed_from: str = "",
    resumed_from: str = "",  # legacy alias for host_reported_resumed_from
    parent_session_id: str = "",  # legacy alias for primary_session_id
    actor_id: str = "",
) -> dict[str, Any]:
    """Persist host continuation. Resume verified ONLY via previous child match.

    Primary parent equality must never set continuation_mode=resume or lineage_verified.
    """
    primary = str(primary_session_id or parent_session_id or "").strip()
    host_resume = str(host_reported_resumed_from or resumed_from or "").strip()
    previous_child = str(previous_external_task_session_id or "").strip()
    if not previous_child:
        prev_doc = load_dispatch(project_root, run_id, action_id)
        previous_child = str(
            prev_doc.get("current_external_task_session_id")
            or prev_doc.get("external_task_session_id")
            or ""
        ).strip()
    current = str(external_task_session_id or "").strip()

    verified = bool(host_resume and previous_child and host_resume == previous_child)
    if verified:
        mode = "resume"
    elif previous_child and current and previous_child != current:
        mode = "fork_with_context"
    elif current and not previous_child:
        mode = "new"
    else:
        mode = "fork_with_context" if current else "new"

    payload = {
        "primary_session_id": primary,
        "previous_external_task_session_id": previous_child,
        "current_external_task_session_id": current,
        "external_task_session_id": current,  # legacy alias
        "host_reported_resumed_from": host_resume,
        "resumed_from": host_resume,  # legacy alias — never Primary parent
        "parent_session_id": primary,  # legacy alias for Primary
        "continuation_mode": mode,
        "lineage_verified": verified,
        "actor_id": actor_id,
        "fork_reason": ""
        if verified or mode != "fork_with_context"
        else "host_resume_lineage_not_observable",
    }
    write_dispatch(project_root, run_id, action_id, payload)
    if mode == "fork_with_context":
        handoff_extra: dict[str, Any] = {
            "source_session_id": previous_child,
            "pending_items": [],
            "notes": "Host returned a new session without resumed_from==previous child; "
            "continue from handoff only. Do not unconditionally re-scan candidates.",
        }
        try:
            from ascendc_pilot.paths import uo_root
            from ascendc_pilot.uo_artifacts import read_yaml

            tasks = read_yaml(uo_root(project_root) / "ir" / "llm_tasks.yaml") or {}
            open_ids = [
                str(t.get("task_id") or "")
                for t in (tasks.get("tasks") or [])
                if isinstance(t, dict)
                and str(t.get("task_status") or t.get("status") or "") in {"open", "rework_required"}
            ]
            csets = sorted(
                {
                    str(t.get("candidate_set_hash") or "")
                    for t in (tasks.get("tasks") or [])
                    if isinstance(t, dict) and t.get("candidate_set_hash")
                }
            )
            snaps = sorted(
                {
                    str(t.get("source_snapshot_hash") or "")
                    for t in (tasks.get("tasks") or [])
                    if isinstance(t, dict) and t.get("source_snapshot_hash")
                }
            )
            handoff_extra["pending_items"] = open_ids[:64]
            handoff_extra["candidate_set_hash"] = csets[0] if len(csets) == 1 else ""
            handoff_extra["candidate_set_hashes"] = csets
            handoff_extra["source_snapshot_hash"] = snaps[0] if len(snaps) == 1 else ""
            handoff_extra["source_snapshot_hashes"] = snaps
        except Exception:  # noqa: BLE001
            pass
        write_handoff(project_root, run_id, action_id, handoff_extra)
    return payload


def write_handoff(
    project_root: Path,
    run_id: str,
    action_id: str,
    payload: dict[str, Any],
) -> Path:
    path = handoff_path(project_root, run_id, action_id)
    doc = {
        "version": 1,
        "action_id": action_id,
        "run_id": run_id,
        "updated_at": _now(),
        "completed_reads": [],
        "accepted_decisions": [],
        "rejected_decisions": [],
        "pending_items": [],
        "last_validation_errors": [],
        "artifact_paths": [],
        "candidate_set_hash": "",
        "source_snapshot_hash": "",
        "notes": "",
        **payload,
    }
    _dump_yaml(path, doc)
    return path
