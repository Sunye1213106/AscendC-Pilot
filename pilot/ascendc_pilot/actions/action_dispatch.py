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
    try:
        from ascendc_pilot.debug import _load_children_registry

        reg = _load_children_registry(Path(project_root))
    except Exception:  # noqa: BLE001
        return {}
    matches: list[dict[str, Any]] = []
    for row in reg.get("children") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("run_id") or "") and str(row.get("run_id") or "") != run_id:
            continue
        if str(row.get("action_id") or "") != action_id:
            continue
        if not str(row.get("child_session_id") or "").strip():
            continue
        matches.append(row)
    if not matches:
        # Fall back to dispatch.yaml
        doc = load_dispatch(project_root, run_id, action_id)
        sid = str(doc.get("external_task_session_id") or "").strip()
        if sid:
            return {
                "external_task_session_id": sid,
                "parent_session_id": doc.get("parent_session_id"),
                "resumed_from": doc.get("resumed_from"),
                "continuation_mode": doc.get("continuation_mode"),
                "lineage_verified": bool(doc.get("lineage_verified")),
            }
        return {}
    row = matches[-1]
    return {
        "external_task_session_id": str(row.get("child_session_id") or ""),
        "parent_session_id": str(row.get("parent_session_id") or ""),
        "registration_id": row.get("registration_id"),
        "actor_id": row.get("actor_id"),
    }


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
            "continuation_mode": "resume",
            "lineage_verified": False,  # verified only after host returns parent linkage
        },
    )
    return {"resume_required": True, "resume_session_id": sid}


def record_continuation(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
    external_task_session_id: str,
    resumed_from: str = "",
    parent_session_id: str = "",
    actor_id: str = "",
) -> dict[str, Any]:
    """Persist host continuation observation. Never claim resume without parent linkage."""
    prev = str(resumed_from or parent_session_id or "").strip()
    current = str(external_task_session_id or "").strip()
    if prev and current and (prev == current or parent_session_id or resumed_from):
        mode = "resume"
        verified = bool(parent_session_id or resumed_from)
    elif prev and current and prev != current and not (parent_session_id or resumed_from):
        mode = "fork_with_context"
        verified = False
    else:
        mode = "new"
        verified = False
    payload = {
        "external_task_session_id": current,
        "resumed_from": resumed_from or prev,
        "parent_session_id": parent_session_id,
        "continuation_mode": mode,
        "lineage_verified": verified,
        "actor_id": actor_id,
        "fork_reason": "" if verified or mode != "fork_with_context" else "host_resume_lineage_not_observable",
    }
    write_dispatch(project_root, run_id, action_id, payload)
    if mode == "fork_with_context":
        handoff_extra: dict[str, Any] = {
            "source_session_id": prev,
            "pending_items": [],
            "notes": "Host returned a new session without parent linkage; continue from handoff only. "
            "Do not unconditionally re-scan candidates.",
        }
        try:
            from ascendc_pilot.paths import uo_root
            from uo.scripts._ir_io import read_yaml

            tasks = read_yaml(uo_root(project_root) / "ir" / "llm_tasks.yaml") or {}
            open_ids = [
                str(t.get("task_id") or "")
                for t in (tasks.get("tasks") or [])
                if isinstance(t, dict) and str(t.get("task_status") or t.get("status") or "") in {"open", "rework_required"}
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
