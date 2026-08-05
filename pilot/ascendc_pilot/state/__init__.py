"""Workflow state machine — sole authority for status transitions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.paths import ensure_control_layout, runs_root, state_root

RUNNING_LIKE = frozenset({"running", "rework_required", "human_required"})
TERMINAL = frozenset({"blocked", "failed", "passed"})
ALL_STATUSES = RUNNING_LIKE | TERMINAL

_STATUS_ALIASES = {
    "pass": "passed",
    "human": "human_required",
}

# Hot workflow.yaml must stay small: verify_receipt / pipeline call load_state many times.
_OPEN_ITEM_PERSIST_KEYS = ("id", "status", "kind", "settled_by_gate")
_STATE_LOAD_CACHE: dict[str, tuple[int, int, dict[str, Any]]] = {}


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
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def _compact_state_for_persist(state: dict[str, Any]) -> dict[str, Any]:
    """Drop bulky obligation snapshots from the hot workflow pointer file.

    Full obligation lists belong in describe_next / collect_obligations responses,
    not in workflow.yaml (embedding them made every verify_receipt ~1s).
    """
    out = dict(state)
    out.pop("all_obligations", None)
    oi = out.get("open_items")
    if isinstance(oi, list):
        compact: list[dict[str, Any]] = []
        for it in oi:
            if not isinstance(it, dict):
                continue
            row = {
                k: it.get(k)
                for k in _OPEN_ITEM_PERSIST_KEYS
                if it.get(k) not in (None, "")
            }
            if row.get("id"):
                compact.append(row)
        out["open_items"] = compact
        out["open_items_count"] = len(compact)
    return out


def workflow_state_path(project_root: Path) -> Path:
    return state_root(project_root) / "workflow.yaml"


def resume_path(project_root: Path) -> Path:
    return state_root(project_root) / "resume.yaml"


def new_run_id(prefix: str = "RUN") -> str:
    return f"{prefix}_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def load_state(project_root: Path) -> dict[str, Any]:
    path = workflow_state_path(project_root)
    if not path.is_file():
        return {}
    try:
        st = path.stat()
        key = str(path.resolve())
        hit = _STATE_LOAD_CACHE.get(key)
        if hit and hit[0] == int(st.st_mtime_ns) and hit[1] == int(st.st_size):
            return dict(hit[2])
        data = _load(path)
        _STATE_LOAD_CACHE[key] = (int(st.st_mtime_ns), int(st.st_size), data)
        return dict(data)
    except OSError:
        return _load(path)


def save_state(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    state = _compact_state_for_persist(dict(state))
    state["updated_at"] = _now()
    path = workflow_state_path(project_root)
    _dump(path, state)
    try:
        st = path.stat()
        _STATE_LOAD_CACHE[str(path.resolve())] = (
            int(st.st_mtime_ns),
            int(st.st_size),
            dict(state),
        )
    except OSError:
        pass
    return state


def _normalize_status(status: str) -> str:
    s = str(status or "").strip().lower()
    return _STATUS_ALIASES.get(s, s)


def _status_message_zh(status: str, state: dict[str, Any]) -> str:
    st = _normalize_status(status)
    lf = state.get("last_failure") or {}
    msg = str(lf.get("message_zh") or "") if isinstance(lf, dict) else ""
    labels = {
        "running": "工作流运行中",
        "rework_required": "门禁未通过，需要返工",
        "human_required": "需要人工确认或补充",
        "blocked": "自动流程无法继续",
        "failed": "不可恢复的执行错误",
        "passed": "工作流已通过全部完成门禁",
    }
    base = labels.get(st, st)
    return f"{base}：{msg}" if msg else base


def _retry_budget(state: dict[str, Any]) -> int:
    budget = state.get("retry_budget")
    if isinstance(budget, int) and budget >= 0:
        return budget
    return 3


def _apply_progress(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.runs import semantic_progress_fingerprint

    fp = semantic_progress_fingerprint(state)
    state["progress_fingerprint"] = fp
    return state


def _bump_no_progress(state: dict[str, Any]) -> dict[str, Any]:
    streak = int(state.get("no_progress_streak") or 0) + 1
    state["no_progress_streak"] = streak
    budget = _retry_budget(state)
    if streak >= budget and state.get("status") in {"rework_required", "running"}:
        state["status"] = "blocked"
        lf = dict(state.get("last_failure") or {})
        lf.setdefault("reason_code", "NO_PROGRESS_BUDGET_EXCEEDED")
        lf.setdefault(
            "message_zh",
            f"连续 {streak} 次无有效进展，重试预算（{budget}）已耗尽",
        )
        state["last_failure"] = lf
    return state


def no_progress_exceeded(project_root: Path, *, limit: int = 3) -> bool:
    state = load_state(project_root)
    return int(state.get("no_progress_streak") or 0) >= limit


def record_gate(
    project_root: Path,
    gate_id: str,
    *,
    ok: bool,
    detail: dict[str, Any] | None = None,
    bump: bool = True,
) -> dict[str, Any]:
    """Record a gate result; failed gates optionally bump no-progress streak."""
    from ascendc_pilot.runs import append_event

    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    failed = list(state.get("failed_gates") or [])
    passed = list(state.get("passed_gates") or [])
    entry = {"id": gate_id, "gate": gate_id, "ok": ok, "at": _now()}
    if detail:
        entry["detail"] = {k: detail[k] for k in ("message", "gate", "ok", "reason") if k in detail}
    # Keep latest per gate id
    failed = [g for g in failed if str(g.get("id") or g.get("gate") or "") != gate_id]
    passed = [g for g in passed if str(g) != gate_id]
    if not ok:
        failed.append(entry)
        state["failed_gates"] = failed
        state["passed_gates"] = passed
        if bump:
            state = _bump_no_progress(state)
    else:
        passed.append(gate_id)
        state["failed_gates"] = failed
        state["passed_gates"] = passed
        before = dict(state.get("progress_fingerprint") or {})
        state = _apply_progress(project_root, state)
        from ascendc_pilot.runs import fingerprint_improved

        if fingerprint_improved(before, state.get("progress_fingerprint") or {}):
            state["no_progress_streak"] = 0
    save_state(project_root, state)
    append_event(
        project_root,
        {"type": "gate_recorded", "gate": gate_id, "ok": ok},
    )
    return load_state(project_root)


def start_workflow(
    project_root: Path,
    workflow_id: str,
    *,
    phase: str | None = None,
    force_phase: bool = False,
    intent: str = "",
    op_name: str = "",
    architecture: str = "",
    test_script_root: str = "",
    csv_consumer_root: str = "",
    level: str = "",
    focus: str = "",
) -> dict[str, Any]:
    """Start at entry_state. Arbitrary phase only when force_phase=True (tests)."""
    from ascendc_pilot.obligations import collect_obligations, open_obligations
    from ascendc_pilot.runs import append_event
    from ascendc_pilot.paths import (
        ensure_ce_layout,
        ensure_closure_layout,
        ensure_control_layout,
        ensure_tg_layout,
        ensure_uo_layout,
    )
    from ascendc_pilot.workflows import entry_state, get_workflow, label_zh_for, state_ids

    meta = get_workflow(workflow_id, project_root=project_root)
    ensure_control_layout(project_root)
    engine = str(meta.get("engine") or "")
    if engine == "uo" or workflow_id.startswith("uo-"):
        ensure_uo_layout(project_root)
    elif engine == "tg" or workflow_id.startswith("tg-"):
        ensure_tg_layout(project_root)
        if workflow_id == "tg-solve":
            ensure_closure_layout(project_root)
    elif engine == "ce" or workflow_id.startswith("ce-"):
        ensure_ce_layout(project_root)
    entry = entry_state(workflow_id)
    if phase and phase != entry and not force_phase:
        raise RuntimeError(
            f"Production start must use entry_state={entry!r}; "
            f"got phase={phase!r} (pass force_phase=True in tests only)"
        )
    start_phase = phase if (force_phase and phase) else entry
    if intent == "diff_only" and workflow_id == "uo-update" and not force_phase:
        # Jump to diff terminal-ready path without full update chain
        start_phase = "diff" if "diff" in state_ids(workflow_id) else entry
    if start_phase not in state_ids(workflow_id):
        raise RuntimeError(f"Unknown phase {start_phase!r} for {workflow_id}")

    run_id = new_run_id("RUN")
    try:
        from ascendc_pilot.spec_hashes import all_spec_hashes

        hashes = all_spec_hashes(workflow_id=workflow_id)
    except Exception:  # noqa: BLE001
        hashes = {}
    all_obl = collect_obligations(project_root, workflow_id)
    consumer = (csv_consumer_root or test_script_root or "").strip()
    state: dict[str, Any] = {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "phase": start_phase,
        "phase_label_zh": label_zh_for(workflow_id, start_phase),
        "status": "running",
        "intent": intent or "",
        "op_name": (op_name or "").strip(),
        "architecture": (architecture or "").strip() or "arch35",
        "test_script_root": consumer,
        "csv_consumer_root": consumer,
        "level": (level or "").strip() or "L0",
        "focus": (focus or "").strip(),
        "retry_budget": int(meta.get("retry_budget") or 3),
        "no_progress_streak": 0,
        "failed_gates": [],
        "passed_gates": [],
        "open_items": open_obligations(all_obl),
        "last_failure": None,
        "created_at": _now(),
        "meta": {},
        **{k: v for k, v in hashes.items()},
    }
    state = _apply_progress(project_root, state)
    save_state(project_root, state)
    (runs_root(project_root) / run_id).mkdir(parents=True, exist_ok=True)
    try:
        from ascendc_pilot.authorize.lease import clear_lease

        clear_lease(project_root)
    except Exception:  # noqa: BLE001
        pass
    append_event(
        project_root,
        {"type": "workflow_started", "workflow_id": workflow_id, "phase": start_phase, "intent": intent},
        run_id=run_id,
    )
    # If debug was enabled before start, mint a fresh debug session for this run.
    try:
        from ascendc_pilot import debug as _dbg

        if _dbg.is_enabled(project_root):
            rotated = _dbg.rotate_debug_session_for_new_run(project_root)
            if not rotated.get("ok") and rotated.get("error") == "debug_run_already_bound":
                # Never silently ignore a bound mismatch when starting a new workflow.
                raise RuntimeError(
                    f"debug_run_already_bound: {rotated.get('bound_run_id')} vs {run_id}"
                )
            _dbg.bind_debug_session_run(project_root)
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001
        pass
    fresh = load_state(project_root)
    from ascendc_pilot.todo import attach_todo

    return attach_todo(
        {**(fresh or {}), "fresh_start": True},
        project_root,
        state=fresh,
        sync_merge=False,
    )


def mark_terminal(
    project_root: Path,
    status: str,
    *,
    reason: str = "",
) -> dict[str, Any]:
    """Mark human_required / blocked / failed. Refuse passed — use complete_workflow."""
    from ascendc_pilot.runs import append_event

    state = load_state(project_root)
    if not state:
        raise RuntimeError("No active workflow state")
    normalized = _normalize_status(status)
    if normalized == "passed":
        raise RuntimeError("Refuse mark_terminal(passed/pass); use complete_workflow")
    if normalized not in {"blocked", "failed", "human_required"}:
        raise RuntimeError(f"Unsupported terminal status: {status!r}")
    if state.get("status") == "passed":
        raise RuntimeError("Workflow already passed")
    state["status"] = normalized
    state["terminal_reason"] = reason
    if reason:
        state["last_failure"] = {
            "reason_code": "MARK_TERMINAL",
            "message_zh": reason,
        }
    save_state(project_root, state)
    try:
        from ascendc_pilot.authorize.lease import issue_lease_for_status

        issue_lease_for_status(project_root, state=state)
    except Exception:  # noqa: BLE001
        pass
    append_event(project_root, {"type": "mark_terminal", "status": normalized, "reason": reason})
    return load_state(project_root)


# Advance / rework / complete / next
from ascendc_pilot.state.machine import (  # noqa: E402
    advance_phase,
    complete_workflow,
    describe_next,
    rework_phase,
)

__all__ = [
    "ALL_STATUSES",
    "RUNNING_LIKE",
    "TERMINAL",
    "advance_phase",
    "complete_workflow",
    "describe_next",
    "load_state",
    "mark_terminal",
    "new_run_id",
    "no_progress_exceeded",
    "record_gate",
    "resume_path",
    "rework_phase",
    "save_state",
    "start_workflow",
    "workflow_state_path",
]
