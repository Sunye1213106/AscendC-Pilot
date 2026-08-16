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

from ascendc_pilot.paths import (
    discover_arch,
    ensure_control_layout,
    require_architecture,
    runs_root,
    state_root,
)

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


def workflow_state_path(project_root: Path, *, arch: str | None = None) -> Path:
    arch_name = arch if arch is not None else discover_arch(project_root)
    return state_root(project_root, arch=arch_name) / "workflow.yaml"


def resume_path(project_root: Path, *, arch: str | None = None) -> Path:
    arch_name = arch if arch is not None else discover_arch(project_root)
    return state_root(project_root, arch=arch_name) / "resume.yaml"


def new_run_id(prefix: str = "RUN") -> str:
    return f"{prefix}_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _read_state_file(path: Path) -> dict[str, Any]:
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


def _write_state_file(path: Path, state: dict[str, Any]) -> None:
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


def load_state(
    project_root: Path,
    *,
    arch: str | None = None,
    workflow_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    from ascendc_pilot.occupancy import resolve_load_state_path

    path = resolve_load_state_path(
        project_root,
        arch=arch,
        workflow_id=workflow_id,
        session_id=session_id,
    )
    if path is None:
        try:
            path = workflow_state_path(project_root, arch=arch)
        except ValueError:
            return {}
    return _read_state_file(path)


def save_state(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.occupancy import (
        is_shared,
        live_exclusive_lock,
        occupancy_group_of,
        persist_path_for_state,
    )

    state = _compact_state_for_persist(dict(state))
    state["updated_at"] = _now()
    arch = str(state.get("architecture") or "").strip() or None
    try:
        path = persist_path_for_state(project_root, state)
    except ValueError as exc:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE") from exc
    _write_state_file(path, state)
    wid = str(state.get("workflow_id") or "").strip()
    # Keep a legacy pointer for discover_arch / older helpers: last exclusive,
    # or a shared run only when no exclusive family is live.
    mirror_legacy = False
    if wid and not is_shared(wid):
        mirror_legacy = True
    elif wid and is_shared(wid):
        group_locks = False
        for group in ("uo", "tg", "ce-impact", "ce-intent", "ce-verify"):
            if live_exclusive_lock(project_root, group):
                group_locks = True
                break
        mirror_legacy = not group_locks
    if mirror_legacy:
        try:
            _write_state_file(workflow_state_path(project_root, arch=arch), state)
        except ValueError:
            pass
    if wid and not is_shared(wid):
        occupancy_group_of(wid)  # validate spec; slot already written
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
    level: str = "",
    focus: str = "",
) -> dict[str, Any]:
    """Start at entry_state. Arbitrary phase only when force_phase=True (tests)."""
    from ascendc_pilot.human_interaction import clear_pending
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

    import os

    from ascendc_pilot.occupancy import (
        SESSION_ENV,
        WORKFLOW_ENV,
        acquire_exclusive_lock,
        bind_session,
        current_session_id,
        is_shared,
        live_exclusive_lock,
        migrate_legacy_slot,
        occupancy_group_of,
        pin_digest_from_product,
        register_shared_run,
    )

    clear_pending(project_root)
    arch = require_architecture(architecture)
    # Pin process env so path helpers (uo_root/agent_root) resolve without
    # inventing a default architecture for the rest of this process.
    os.environ["UO_ARCH"] = arch
    os.environ[WORKFLOW_ENV] = str(workflow_id or "")
    meta = get_workflow(workflow_id, project_root=project_root)
    try:
        migrate_legacy_slot(project_root, arch=arch)
    except Exception:  # noqa: BLE001
        pass
    ensure_control_layout(project_root, arch=arch)
    engine = str(meta.get("engine") or "")
    if engine == "uo" or workflow_id.startswith("uo-"):
        ensure_uo_layout(project_root, arch=arch)
    elif engine == "tg" or workflow_id.startswith("tg-"):
        ensure_tg_layout(project_root, arch=arch)
        if workflow_id == "tg-solve":
            ensure_closure_layout(project_root, arch=arch)
    elif engine == "ce" or workflow_id.startswith("ce-"):
        ensure_ce_layout(project_root, arch=arch)
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
    consumer = (test_script_root or "").strip()
    session_id = current_session_id()
    pin = pin_digest_from_product(
        project_root, architecture=arch, op_name=(op_name or "").strip()
    )
    occ_group = occupancy_group_of(workflow_id)
    shared = is_shared(workflow_id)
    state: dict[str, Any] = {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "phase": start_phase,
        "phase_label_zh": label_zh_for(workflow_id, start_phase),
        "status": "running",
        "intent": intent or "",
        "op_name": (op_name or "").strip(),
        "architecture": arch,
        "test_script_root": consumer,
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
        "occupancy": "shared" if shared else "exclusive",
        "occupancy_group": occ_group,
        "session_id": session_id,
        "pinned_digest": str(pin.get("digest") or ""),
        "uo_path": str(pin.get("path") or ""),
        "uo_stale": False,
        **{k: v for k, v in hashes.items()},
    }
    state = _apply_progress(project_root, state)
    save_state(project_root, state)
    from ascendc_pilot.active_run import write_active_run

    if shared:
        register_shared_run(
            project_root,
            workflow_id=workflow_id,
            run_id=run_id,
            architecture=arch,
            session_id=session_id,
            pinned_digest=str(pin.get("digest") or ""),
        )
        exclusive_live = any(
            live_exclusive_lock(project_root, group)
            for group in ("uo", "tg", "ce-impact", "ce-intent", "ce-verify")
        )
        if not exclusive_live:
            write_active_run(
                project_root,
                architecture=arch,
                run_id=run_id,
                workflow_id=workflow_id,
                status=str(state.get("status") or "running"),
            )
    else:
        acquire_exclusive_lock(
            project_root,
            occupancy_group=occ_group,
            workflow_id=workflow_id,
            run_id=run_id,
            architecture=arch,
            session_id=session_id,
            pinned_digest=str(pin.get("digest") or ""),
        )
        write_active_run(
            project_root,
            architecture=arch,
            run_id=run_id,
            workflow_id=workflow_id,
            status=str(state.get("status") or "running"),
        )
    if session_id:
        bind_session(
            project_root,
            session_id=session_id,
            architecture=arch,
            uo_path=str(pin.get("path") or ""),
            digest=str(pin.get("digest") or ""),
            workflow_id=workflow_id,
            occupancy_group=occ_group,
            run_id=run_id,
            stale=False,
        )
    if session_id:
        os.environ[SESSION_ENV] = session_id
    (runs_root(project_root, arch=arch) / run_id).mkdir(parents=True, exist_ok=True)
    # Run-level source scope: resolve once; subsequent action leases inherit.
    try:
        from ascendc_pilot.environment_capabilities import source_scope_for_lease
        import yaml as _yaml

        run_scope = source_scope_for_lease(project_root, run_id=run_id)
        scope_path = runs_root(project_root, arch=arch) / run_id / "source_scope.yaml"
        scope_path.parent.mkdir(parents=True, exist_ok=True)
        scope_path.write_text(
            _yaml.safe_dump(
                {
                    "version": 1,
                    "run_id": run_id,
                    **run_scope,
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        state["run_source_scope_path"] = scope_path.as_posix()
        state["allowed_source_roots"] = list(run_scope.get("allowed_source_roots") or [])
        save_state(project_root, state)
    except Exception:  # noqa: BLE001
        pass
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
    fresh = load_state(project_root, workflow_id=workflow_id, session_id=session_id)
    from ascendc_pilot.todo import attach_todo

    return attach_todo(
        {**(fresh or {}), "fresh_start": True, "ok": True},
        project_root,
        state=fresh,
        sync_merge=False,
    )


_LIVE_STATE_FILES = (
    "workflow.yaml",
    "active_action.yaml",
    "action_lease.yaml",
    "resume.yaml",
)


def release_live_execution(
    project_root: Path,
    *,
    reason: str = "",
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Archive this run and free its product-family lock (not other families).

    Formal products (``.uo`` / tg / ce) stay. Shared query runs never hold an
    exclusive lock. After ``passed``, this family must not still occupy.
    """
    from ascendc_pilot.active_run import clear_active_run, read_active_run, write_active_run
    from ascendc_pilot.occupancy import (
        is_shared,
        occupancy_group_of,
        persist_path_for_state,
        read_product_locks,
        release_exclusive_lock,
        release_session_occupancy,
        slot_state_path,
        unregister_shared_run,
    )

    root = Path(project_root).expanduser().resolve()
    st = dict(state) if isinstance(state, dict) and state else (load_state(root) or {})
    arch = str(st.get("architecture") or "").strip()
    run_id = str(st.get("run_id") or "").strip()
    wid = str(st.get("workflow_id") or "").strip()
    archived_to = ""
    if st and run_id:
        try:
            dest = runs_root(root, arch=arch or None) / run_id / "final_state.yaml"
            dest.parent.mkdir(parents=True, exist_ok=True)
            payload = dict(st)
            if reason:
                payload["release_reason"] = reason
            payload["released_at"] = _now()
            _dump(dest, payload)
            archived_to = dest.as_posix()
        except Exception:  # noqa: BLE001
            archived_to = ""
    if st:
        try:
            live_path = persist_path_for_state(root, st)
            if live_path.is_file():
                live_path.unlink()
                _STATE_LOAD_CACHE.pop(str(live_path.resolve()), None)
        except Exception:  # noqa: BLE001
            pass
    if wid and is_shared(wid):
        unregister_shared_run(root, run_id)
    elif wid:
        group = occupancy_group_of(wid)
        if group:
            release_exclusive_lock(root, group, run_id=run_id)
            try:
                slot = slot_state_path(root, group, arch=arch or None)
                if slot.is_file():
                    slot.unlink()
                    _STATE_LOAD_CACHE.pop(str(slot.resolve()), None)
            except Exception:  # noqa: BLE001
                pass
    # Drop legacy pointer only when it still names this run.
    try:
        legacy = workflow_state_path(root, arch=arch or None)
        if legacy.is_file():
            legacy_st = _load(legacy)
            if str(legacy_st.get("run_id") or "") in {"", run_id}:
                leftover = None
                locks = read_product_locks(root)
                for lock in (locks.get("locks") or {}).values():
                    if not isinstance(lock, dict):
                        continue
                    if str(lock.get("run_id") or "") in {"", run_id}:
                        continue
                    leftover = lock
                    break
                if leftover:
                    try:
                        other_group = occupancy_group_of(
                            str(leftover.get("workflow_id") or "")
                        )
                        other_path = slot_state_path(
                            root,
                            other_group,
                            arch=str(leftover.get("architecture") or arch or "") or None,
                        )
                        if other_group and other_path.is_file():
                            _write_state_file(legacy, _load(other_path))
                        else:
                            legacy.unlink()
                            _STATE_LOAD_CACHE.pop(str(legacy.resolve()), None)
                    except Exception:  # noqa: BLE001
                        try:
                            legacy.unlink()
                        except OSError:
                            pass
                else:
                    legacy.unlink()
                    _STATE_LOAD_CACHE.pop(str(legacy.resolve()), None)
    except Exception:  # noqa: BLE001
        pass
    try:
        st_dir = state_root(root, arch=arch or None)
    except ValueError:
        st_dir = None
    if st_dir and st_dir.is_dir():
        for name in ("active_action.yaml", "action_lease.yaml", "resume.yaml"):
            path = st_dir / name
            if not path.is_file():
                continue
            body = _load(path)
            if body and str(body.get("run_id") or "") not in {"", run_id}:
                continue
            try:
                path.unlink()
            except OSError:
                pass
            _STATE_LOAD_CACHE.pop(str(path.resolve()), None)
    pointer = read_active_run(root)
    if pointer and str(pointer.get("run_id") or "") in {"", run_id}:
        leftover_lock = None
        for lock in (read_product_locks(root).get("locks") or {}).values():
            if isinstance(lock, dict) and str(lock.get("run_id") or "") not in {"", run_id}:
                leftover_lock = lock
                break
        if leftover_lock:
            try:
                write_active_run(
                    root,
                    architecture=str(leftover_lock.get("architecture") or arch or ""),
                    run_id=str(leftover_lock.get("run_id") or ""),
                    workflow_id=str(leftover_lock.get("workflow_id") or ""),
                    status=str(leftover_lock.get("status") or ""),
                )
            except ValueError:
                clear_active_run(root)
        else:
            clear_active_run(root)
    try:
        from ascendc_pilot.human_interaction import clear_pending

        clear_pending(root)
    except Exception:  # noqa: BLE001
        pass
    try:
        release_session_occupancy(
            root,
            run_id=run_id,
            session_id=str(st.get("session_id") or ""),
        )
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "released": bool(st),
        "run_id": run_id,
        "workflow_id": wid,
        "archived_to": archived_to,
        "reason": reason,
    }


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
    "release_live_execution",
    "resume_path",
    "rework_phase",
    "save_state",
    "start_workflow",
    "workflow_state_path",
]
