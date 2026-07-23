"""Workflow state machine and open_items tracking."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_harness.paths import ensure_agent_layout, runs_root, state_root


TERMINAL = frozenset({"pass", "blocked", "human", "failed"})


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _dump(path: Path, data: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML required")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def workflow_state_path(project_root: Path) -> Path:
    return state_root(project_root) / "workflow.yaml"


def resume_path(project_root: Path) -> Path:
    return state_root(project_root) / "resume.yaml"


def new_run_id(prefix: str = "RUN") -> str:
    return f"{prefix}_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def start_workflow(
    project_root: Path,
    workflow_id: str,
    *,
    phase: str,
    open_items: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_agent_layout(project_root)
    run_id = new_run_id(workflow_id.replace("-", "_").upper())
    state = {
        "version": 1,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "phase": phase,
        "status": "running",
        "open_items": list(open_items or []),
        "completed_gates": [],
        "failed_gates": [],
        "no_progress_streak": 0,
        "updated_at": _now(),
        "meta": dict(meta or {}),
    }
    _dump(workflow_state_path(project_root), state)
    run_dir = runs_root(project_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _dump(run_dir / "receipt.yaml", {"run_id": run_id, "workflow_id": workflow_id, "started_at": _now()})
    return state


def load_state(project_root: Path) -> dict[str, Any]:
    return _load(workflow_state_path(project_root))


def save_state(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    state = dict(state)
    state["updated_at"] = _now()
    _dump(workflow_state_path(project_root), state)
    return state


def set_phase(project_root: Path, phase: str) -> dict[str, Any]:
    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    if state.get("status") in TERMINAL:
        raise RuntimeError(f"Workflow already terminal: {state.get('status')}")
    state["phase"] = phase
    return save_state(project_root, state)


def record_gate(
    project_root: Path,
    gate_id: str,
    *,
    ok: bool,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    entry = {"id": gate_id, "ok": ok, "at": _now(), "detail": detail or {}}
    if ok:
        completed = list(state.get("completed_gates") or [])
        completed.append(entry)
        state["completed_gates"] = completed
        state["no_progress_streak"] = 0
    else:
        failed = list(state.get("failed_gates") or [])
        failed.append(entry)
        state["failed_gates"] = failed
        state["no_progress_streak"] = int(state.get("no_progress_streak") or 0) + 1
    return save_state(project_root, state)


def reduce_open_items(project_root: Path, item_ids: list[str]) -> dict[str, Any]:
    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    drop = set(item_ids)
    before = list(state.get("open_items") or [])
    after = [it for it in before if str(it.get("id") or "") not in drop]
    if len(after) < len(before):
        state["no_progress_streak"] = 0
    state["open_items"] = after
    return save_state(project_root, state)


def mark_terminal(project_root: Path, status: str, *, reason: str = "", force: bool = False) -> dict[str, Any]:
    if status not in TERMINAL:
        raise ValueError(f"status must be one of {sorted(TERMINAL)}")
    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    if status == "pass" and not force:
        raise RuntimeError(
            "Refuse mark_terminal(pass) without harness.complete_workflow — "
            "state authority lives in harness (use force=True only for tests)"
        )
    state["status"] = status
    state["terminal_reason"] = reason
    return save_state(project_root, state)


def advance_phase(
    project_root: Path,
    next_phase: str,
    *,
    required_gates: list[str] | None = None,
) -> dict[str, Any]:
    """Advance phase only when required gates pass (Harness authority)."""
    from ascendc_harness.gates import run_named_gate
    from ascendc_harness.workflows import get_workflow

    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    if state.get("status") in TERMINAL:
        raise RuntimeError(f"Workflow already terminal: {state.get('status')}")

    wid = str(state.get("workflow_id") or "")
    meta = get_workflow(wid) if wid else {}
    phases = list(meta.get("phases") or [])
    current = str(state.get("phase") or "")
    if phases and next_phase in phases and current in phases:
        if phases.index(next_phase) > phases.index(current) + 1:
            raise RuntimeError(f"Illegal phase jump {current!r} → {next_phase!r}")

    gate_ids = list(required_gates or [])
    if not gate_ids:
        # Default: all gates listed before the target phase index (resolve+)
        # For simplicity, require key-related gates when entering export/review
        phase_gates = dict(meta.get("phase_gates") or {})
        gate_ids = list(phase_gates.get(current) or [])

    results = [run_named_gate(project_root, gid) for gid in gate_ids]
    failed = [r for r in results if not r.get("ok")]
    for r in results:
        record_gate(project_root, str(r.get("gate") or "gate"), ok=bool(r.get("ok")), detail=r)
    if failed:
        state = load_state(project_root)
        state["status"] = "blocked" if no_progress_exceeded(project_root) else state.get("status") or "running"
        state["last_advance_failure"] = {
            "from": current,
            "to": next_phase,
            "failed_gates": [f.get("gate") for f in failed],
            "messages": [f.get("message") for f in failed],
        }
        save_state(project_root, state)
        return {
            "ok": False,
            "advanced": False,
            "from": current,
            "to": next_phase,
            "failed_gates": failed,
            "state": load_state(project_root),
        }
    state = set_phase(project_root, next_phase)
    return {"ok": True, "advanced": True, "from": current, "to": next_phase, "state": state}


def complete_workflow(project_root: Path, *, reason: str = "") -> dict[str, Any]:
    """Only path to status=pass: all workflow gates must succeed."""
    from ascendc_harness.gates import run_key_gates, run_workflow_gates

    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    if state.get("status") in TERMINAL:
        raise RuntimeError(f"Workflow already terminal: {state.get('status')}")

    wid = str(state.get("workflow_id") or "")
    # Always run KEY hard gates for UO workflows
    key_payload = None
    if wid.startswith("uo-") or wid in {"uo-init", "uo-update"}:
        key_payload = run_key_gates(project_root)
        if not key_payload.get("ok"):
            record_gate(project_root, "key_gates", ok=False, detail=key_payload)
            state = load_state(project_root)
            state["status"] = "blocked"
            state["terminal_reason"] = "key_gates_failed"
            save_state(project_root, state)
            return {"ok": False, "status": "blocked", "key_gates": key_payload, "state": load_state(project_root)}

    wf = run_workflow_gates(project_root)
    for r in wf.get("gates") or []:
        record_gate(project_root, str(r.get("gate") or "gate"), ok=bool(r.get("ok")), detail=r)
    if not wf.get("ok"):
        state = load_state(project_root)
        state["status"] = "blocked"
        state["terminal_reason"] = "workflow_gates_failed"
        save_state(project_root, state)
        return {"ok": False, "status": "blocked", "workflow_gates": wf, "key_gates": key_payload, "state": load_state(project_root)}

    state = load_state(project_root)
    state["status"] = "pass"
    state["terminal_reason"] = reason or "all_gates_passed"
    save_state(project_root, state)
    return {"ok": True, "status": "pass", "workflow_gates": wf, "key_gates": key_payload, "state": load_state(project_root)}


def no_progress_exceeded(project_root: Path, *, limit: int = 3) -> bool:
    state = load_state(project_root)
    return int(state.get("no_progress_streak") or 0) >= limit


def write_subagent_receipt(
    project_root: Path,
    *,
    identity: str,
    agent: str,
    artifact: str,
) -> Path:
    state = load_state(project_root)
    run_id = str(state.get("run_id") or "NO_RUN")
    path = runs_root(project_root) / run_id / "subagents" / f"{identity.replace(':', '_')}.yaml"
    _dump(
        path,
        {
            "identity": identity,
            "agent": agent,
            "artifact": artifact,
            "recorded_at": _now(),
            "run_id": run_id,
        },
    )
    return path


def has_subagent_receipt(project_root: Path, *, agent: str | None = None, identity_prefix: str = "") -> bool:
    state = load_state(project_root)
    run_id = str(state.get("run_id") or "")
    if not run_id:
        return False
    base = runs_root(project_root) / run_id / "subagents"
    if not base.is_dir():
        return False
    for path in base.glob("*.yaml"):
        data = _load(path)
        if agent and str(data.get("agent") or "") != agent:
            continue
        if identity_prefix and not str(data.get("identity") or "").startswith(identity_prefix):
            continue
        return True
    return False
