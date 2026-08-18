"""UO-bound product locks, session bindings, and family-scoped live state.

The control plane hub is a ``.uo`` product (operator + architecture + digest),
not a global exclusive execution slot. Exclusive writers take a product-family
lock; shared (read) workflows never do.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ascendc_pilot.paths import AGENT_DIR, STATE_SUBDIR, runs_root, state_root

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

OCCUPANCY_EXCLUSIVE = "exclusive"
OCCUPANCY_SHARED = "shared"
OCCUPANCY_VALUES = frozenset({OCCUPANCY_EXCLUSIVE, OCCUPANCY_SHARED})
_RUNNING_LIKE = frozenset({"running", "rework_required", "human_required"})

PRODUCT_LOCKS_SCHEMA = "pilot-product-locks/v1"
SESSION_BINDINGS_SCHEMA = "pilot-session-bindings/v1"

SESSION_ENV = "ASCENDC_SESSION_ID"
WORKFLOW_ENV = "ASCENDC_WORKFLOW_ID"

_SESSION_KEY_RE = re.compile(r"[^\w.-]+")


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _dump(path: Path, data: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML required")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    tmp.replace(path)


def current_session_id(explicit: str = "") -> str:
    return str(explicit or os.environ.get(SESSION_ENV) or "").strip()


def current_workflow_id(explicit: str = "") -> str:
    return str(explicit or os.environ.get(WORKFLOW_ENV) or "").strip()


def occupancy_of(workflow_id: str) -> str:
    from ascendc_pilot.workflows.specs import WORKFLOWS

    wid = str(workflow_id or "").strip()
    meta = WORKFLOWS.get(wid) or {}
    occ = str(meta.get("occupancy") or "").strip().lower()
    return occ if occ in OCCUPANCY_VALUES else OCCUPANCY_EXCLUSIVE


def occupancy_group_of(workflow_id: str) -> str:
    from ascendc_pilot.workflows.specs import WORKFLOWS

    wid = str(workflow_id or "").strip()
    meta = WORKFLOWS.get(wid) or {}
    if occupancy_of(wid) != OCCUPANCY_EXCLUSIVE:
        return ""
    return str(meta.get("occupancy_group") or "").strip()


def is_shared(workflow_id: str) -> bool:
    return occupancy_of(workflow_id) == OCCUPANCY_SHARED


def product_locks_path(project_root: Path | str) -> Path:
    root = Path(project_root).expanduser().resolve()
    return root / AGENT_DIR / "control" / "product_locks.yaml"


def session_bindings_path(project_root: Path | str) -> Path:
    root = Path(project_root).expanduser().resolve()
    return root / AGENT_DIR / "control" / "session_bindings.yaml"


def slot_state_path(
    project_root: Path | str,
    occupancy_group: str,
    *,
    arch: str | None = None,
) -> Path:
    group = str(occupancy_group or "").strip()
    if not group:
        raise ValueError("occupancy_group required for exclusive slot path")
    return state_root(project_root, arch=arch) / "slots" / group / "workflow.yaml"


def shared_live_state_path(
    project_root: Path | str,
    run_id: str,
    *,
    arch: str | None = None,
) -> Path:
    rid = str(run_id or "").strip()
    if not rid:
        raise ValueError("run_id required for shared live state")
    return runs_root(project_root, arch=arch) / rid / "live_state.yaml"


def read_product_locks(project_root: Path | str) -> dict[str, Any]:
    path = product_locks_path(project_root)
    doc = _load(path)
    if not doc:
        return {
            "schema": PRODUCT_LOCKS_SCHEMA,
            "locks": {},
            "shared": [],
        }
    if not isinstance(doc.get("locks"), dict):
        doc["locks"] = {}
    if not isinstance(doc.get("shared"), list):
        doc["shared"] = []
    doc.setdefault("schema", PRODUCT_LOCKS_SCHEMA)
    return doc


def write_product_locks(project_root: Path | str, doc: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema": PRODUCT_LOCKS_SCHEMA,
        "locks": dict(doc.get("locks") or {}),
        "shared": list(doc.get("shared") or []),
        "updated_at": _now(),
    }
    _dump(product_locks_path(project_root), payload)
    return payload


def read_session_bindings(project_root: Path | str) -> dict[str, Any]:
    path = session_bindings_path(project_root)
    doc = _load(path)
    if not doc:
        return {"schema": SESSION_BINDINGS_SCHEMA, "bindings": {}}
    if not isinstance(doc.get("bindings"), dict):
        doc["bindings"] = {}
    doc.setdefault("schema", SESSION_BINDINGS_SCHEMA)
    return doc


def write_session_bindings(project_root: Path | str, doc: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema": SESSION_BINDINGS_SCHEMA,
        "bindings": dict(doc.get("bindings") or {}),
        "updated_at": _now(),
    }
    _dump(session_bindings_path(project_root), payload)
    return payload


def _session_key(session_id: str) -> str:
    raw = str(session_id or "").strip()
    if not raw:
        return ""
    return _SESSION_KEY_RE.sub("_", raw)[:120]


def live_exclusive_lock(
    project_root: Path | str,
    occupancy_group: str,
) -> dict[str, Any] | None:
    group = str(occupancy_group or "").strip()
    if not group:
        return None
    doc = read_product_locks(project_root)
    lock = (doc.get("locks") or {}).get(group)
    if not isinstance(lock, dict):
        return None
    status = str(lock.get("status") or "").strip()
    if status and status not in _RUNNING_LIKE:
        return None
    if not str(lock.get("run_id") or "").strip():
        return None
    return dict(lock)


def live_resource_conflict(
    project_root: Path | str,
    workflow_id: str,
    *,
    ignore_run_id: str = "",
) -> dict[str, Any] | None:
    """RW/WR/WW intersection against live exclusive locks (not occupancy_group)."""
    from ascendc_pilot.workflows.specs import resource_sets_conflict, workflow_resource_sets

    if is_shared(workflow_id):
        return None
    _read, write_set = workflow_resource_sets(workflow_id)
    if not write_set and not _read:
        return None
    doc = read_product_locks(project_root)
    skip = str(ignore_run_id or "").strip()
    for group, lock in (doc.get("locks") or {}).items():
        if not isinstance(lock, dict):
            continue
        other = str(lock.get("workflow_id") or "").strip()
        other_run = str(lock.get("run_id") or "").strip()
        if not other or not other_run:
            continue
        if skip and other_run == skip:
            continue
        status = str(lock.get("status") or "").strip()
        if status and status not in _RUNNING_LIKE:
            continue
        if not resource_sets_conflict(workflow_id, other):
            continue
        return {
            "error": "resource_lock_conflict",
            "active_workflow_id": other,
            "requested_workflow_id": workflow_id,
            "occupancy_group": group,
            "active_run_id": other_run,
            "message_zh": (
                f"{other} 正在写相交资源，暂时不能并行启动 {workflow_id}。"
                f"推荐：等 {other} 结束，或换一个不冲突的问题。"
            ),
        }
    return None


def acquire_exclusive_lock(
    project_root: Path | str,
    *,
    occupancy_group: str,
    workflow_id: str,
    run_id: str,
    architecture: str,
    session_id: str = "",
    pinned_digest: str = "",
    status: str = "running",
) -> dict[str, Any]:
    group = str(occupancy_group or "").strip()
    if not group:
        raise ValueError("occupancy_group required to acquire exclusive lock")
    arch = str(architecture or "").strip()
    rel = f"{arch}/{STATE_SUBDIR}/slots/{group}/workflow.yaml" if arch else ""
    doc = read_product_locks(project_root)
    locks = dict(doc.get("locks") or {})
    locks[group] = {
        "architecture": arch,
        "run_id": str(run_id or "").strip(),
        "workflow_id": str(workflow_id or "").strip(),
        "session_id": str(session_id or "").strip(),
        "status": str(status or "running").strip(),
        "state_path": rel,
        "pinned_digest": str(pinned_digest or "").strip(),
        "updated_at": _now(),
    }
    doc["locks"] = locks
    write_product_locks(project_root, doc)
    return locks[group]


def release_exclusive_lock(
    project_root: Path | str,
    occupancy_group: str,
    *,
    run_id: str = "",
) -> dict[str, Any]:
    group = str(occupancy_group or "").strip()
    doc = read_product_locks(project_root)
    locks = dict(doc.get("locks") or {})
    current = locks.get(group) if isinstance(locks.get(group), dict) else {}
    if run_id and str((current or {}).get("run_id") or "") not in {"", run_id}:
        return doc
    if group in locks:
        locks.pop(group, None)
        doc["locks"] = locks
        write_product_locks(project_root, doc)
    return doc


def register_shared_run(
    project_root: Path | str,
    *,
    workflow_id: str,
    run_id: str,
    architecture: str,
    session_id: str = "",
    pinned_digest: str = "",
    status: str = "running",
) -> dict[str, Any]:
    doc = read_product_locks(project_root)
    shared = [
        row
        for row in (doc.get("shared") or [])
        if isinstance(row, dict) and str(row.get("run_id") or "") != run_id
    ]
    row = {
        "workflow_id": str(workflow_id or "").strip(),
        "run_id": str(run_id or "").strip(),
        "architecture": str(architecture or "").strip(),
        "session_id": str(session_id or "").strip(),
        "pinned_digest": str(pinned_digest or "").strip(),
        "status": str(status or "running").strip(),
        "updated_at": _now(),
    }
    shared.append(row)
    doc["shared"] = shared
    write_product_locks(project_root, doc)
    return row


def unregister_shared_run(project_root: Path | str, run_id: str) -> dict[str, Any]:
    rid = str(run_id or "").strip()
    doc = read_product_locks(project_root)
    doc["shared"] = [
        row
        for row in (doc.get("shared") or [])
        if not (isinstance(row, dict) and str(row.get("run_id") or "") == rid)
    ]
    write_product_locks(project_root, doc)
    return doc


def list_shared_runs(project_root: Path | str) -> list[dict[str, Any]]:
    doc = read_product_locks(project_root)
    return [dict(row) for row in (doc.get("shared") or []) if isinstance(row, dict)]


def bind_session(
    project_root: Path | str,
    *,
    session_id: str,
    architecture: str = "",
    uo_path: str = "",
    digest: str = "",
    workflow_id: str = "",
    occupancy_group: str = "",
    run_id: str = "",
    stale: bool = False,
) -> dict[str, Any] | None:
    key = _session_key(session_id)
    if not key:
        return None
    doc = read_session_bindings(project_root)
    bindings = dict(doc.get("bindings") or {})
    prev = bindings.get(key) if isinstance(bindings.get(key), dict) else {}
    row = {
        "session_id": str(session_id).strip(),
        "architecture": str(architecture or prev.get("architecture") or "").strip(),
        "uo_path": str(uo_path or prev.get("uo_path") or "").strip(),
        "digest": str(digest or prev.get("digest") or "").strip(),
        "workflow_id": str(workflow_id or prev.get("workflow_id") or "").strip(),
        "occupancy_group": str(occupancy_group or prev.get("occupancy_group") or "").strip(),
        "run_id": str(run_id or prev.get("run_id") or "").strip(),
        "stale": bool(stale),
        "bound_at": str(prev.get("bound_at") or _now()),
        "updated_at": _now(),
    }
    if digest and prev.get("digest") and str(prev.get("digest")) != str(digest):
        row["stale"] = True
        row["previous_digest"] = str(prev.get("digest"))
    if uo_path:
        row["stale"] = bool(stale)
    bindings[key] = row
    doc["bindings"] = bindings
    write_session_bindings(project_root, doc)
    return row


def release_session_occupancy(
    project_root: Path | str,
    *,
    run_id: str = "",
    session_id: str = "",
) -> list[str]:
    """Clear exclusive occupancy on bindings for a finished run.

    Digest pin stays (STALE detection). ``bind_session`` cannot clear
    ``occupancy_group`` because empty string is treated as "keep previous".
    """
    rid = str(run_id or "").strip()
    sid = _session_key(session_id)
    if not rid and not sid:
        return []
    doc = read_session_bindings(project_root)
    bindings = dict(doc.get("bindings") or {})
    changed_ids: list[str] = []
    changed = False
    for key, row in list(bindings.items()):
        if not isinstance(row, dict):
            continue
        match_run = bool(rid) and str(row.get("run_id") or "") == rid
        match_sid = bool(sid) and key == sid
        if not match_run and not match_sid:
            continue
        row = dict(row)
        row["occupancy_group"] = ""
        row["released"] = True
        row["updated_at"] = _now()
        bindings[key] = row
        changed_ids.append(str(row.get("session_id") or key))
        changed = True
    if changed:
        doc["bindings"] = bindings
        write_session_bindings(project_root, doc)
    return changed_ids


def get_session_binding(
    project_root: Path | str,
    session_id: str = "",
) -> dict[str, Any] | None:
    key = _session_key(session_id or current_session_id())
    if not key:
        return None
    doc = read_session_bindings(project_root)
    row = (doc.get("bindings") or {}).get(key)
    return dict(row) if isinstance(row, dict) else None


def mark_sessions_stale(
    project_root: Path | str,
    *,
    live_digest: str,
    architecture: str = "",
) -> list[str]:
    """Mark bindings / other-family runs whose pinned digest no longer matches."""
    digest = str(live_digest or "").strip()
    arch = str(architecture or "").strip()
    stale_ids: list[str] = []
    doc = read_session_bindings(project_root)
    bindings = dict(doc.get("bindings") or {})
    changed = False
    for key, row in list(bindings.items()):
        if not isinstance(row, dict):
            continue
        if arch and str(row.get("architecture") or "") not in {"", arch}:
            continue
        pinned = str(row.get("digest") or "").strip()
        if digest and pinned and pinned != digest:
            row = dict(row)
            row["stale"] = True
            row["previous_digest"] = pinned
            row["updated_at"] = _now()
            bindings[key] = row
            stale_ids.append(str(row.get("session_id") or key))
            changed = True
        elif digest and not pinned:
            row = dict(row)
            row["digest"] = digest
            row["stale"] = False
            row["updated_at"] = _now()
            bindings[key] = row
            changed = True
    if changed:
        doc["bindings"] = bindings
        write_session_bindings(project_root, doc)

    locks_doc = read_product_locks(project_root)
    lock_changed = False
    locks = dict(locks_doc.get("locks") or {})
    for group, lock in list(locks.items()):
        if not isinstance(lock, dict):
            continue
        if arch and str(lock.get("architecture") or "") not in {"", arch}:
            continue
        pinned = str(lock.get("pinned_digest") or "").strip()
        if digest and pinned and pinned != digest:
            lock = dict(lock)
            lock["uo_stale"] = True
            lock["updated_at"] = _now()
            locks[group] = lock
            lock_changed = True
    shared = []
    for row in locks_doc.get("shared") or []:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        if arch and str(row.get("architecture") or "") not in {"", arch}:
            shared.append(row)
            continue
        pinned = str(row.get("pinned_digest") or "").strip()
        if digest and pinned and pinned != digest:
            row["uo_stale"] = True
            row["updated_at"] = _now()
            lock_changed = True
        shared.append(row)
    if lock_changed:
        locks_doc["locks"] = locks
        locks_doc["shared"] = shared
        write_product_locks(project_root, locks_doc)
    return stale_ids


def live_digest_for(
    project_root: Path | str,
    *,
    architecture: str = "",
    op_name: str = "",
) -> str:
    try:
        from ascendc_pilot.uo_product_handle import build_uo_product_handle

        handle = build_uo_product_handle(
            project_root,
            op_name=op_name,
            architecture=architecture,
        )
    except Exception:  # noqa: BLE001
        return ""
    if not handle.get("ok"):
        return ""
    return str(handle.get("canonical_graph_digest") or "").strip()


def pin_digest_from_product(
    project_root: Path | str,
    *,
    architecture: str = "",
    op_name: str = "",
) -> dict[str, Any]:
    try:
        from ascendc_pilot.uo_product_handle import build_uo_product_handle

        handle = build_uo_product_handle(
            project_root,
            op_name=op_name,
            architecture=architecture,
        )
    except Exception:  # noqa: BLE001
        return {"ok": False, "digest": "", "path": ""}
    if not handle.get("ok"):
        return {
            "ok": False,
            "digest": "",
            "path": str(handle.get("path") or ""),
            "error": str(handle.get("error") or "UO_PRODUCT_REQUIRED"),
        }
    return {
        "ok": True,
        "digest": str(handle.get("canonical_graph_digest") or "").strip(),
        "path": str(handle.get("path") or ""),
        "op_name": str(handle.get("op_name") or ""),
        "architecture": str(handle.get("architecture") or architecture or ""),
        "handle": handle,
    }


def publish_uo_digest(
    project_root: Path | str,
    *,
    architecture: str,
    digest: str = "",
    op_name: str = "",
) -> dict[str, Any]:
    live = str(digest or "").strip() or live_digest_for(
        project_root, architecture=architecture, op_name=op_name
    )
    stale = mark_sessions_stale(
        project_root, live_digest=live, architecture=architecture
    )
    return {"ok": True, "digest": live, "stale_sessions": stale}


def binding_is_stale(
    project_root: Path | str,
    *,
    session_id: str = "",
    pinned_digest: str = "",
    architecture: str = "",
) -> dict[str, Any]:
    live = live_digest_for(project_root, architecture=architecture)
    pinned = str(pinned_digest or "").strip()
    binding = get_session_binding(project_root, session_id)
    if not pinned and binding:
        pinned = str(binding.get("digest") or "").strip()
        if binding.get("stale"):
            return {
                "stale": True,
                "reason_code": "UO_DIGEST_CHANGED",
                "pinned_digest": pinned,
                "live_digest": live,
            }
    if live and pinned and live != pinned:
        return {
            "stale": True,
            "reason_code": "UO_DIGEST_CHANGED",
            "pinned_digest": pinned,
            "live_digest": live,
        }
    return {
        "stale": False,
        "reason_code": "",
        "pinned_digest": pinned,
        "live_digest": live,
    }


def legacy_workflow_state_path(
    project_root: Path | str,
    *,
    arch: str | None = None,
) -> Path:
    from ascendc_pilot.paths import discover_arch

    arch_name = arch if arch is not None else discover_arch(project_root)
    return state_root(project_root, arch=arch_name) / "workflow.yaml"


def migrate_legacy_slot(
    project_root: Path | str,
    *,
    arch: str | None = None,
) -> dict[str, Any]:
    """Copy legacy ``state/workflow.yaml`` into ``slots/{family}/`` if needed."""
    try:
        legacy = legacy_workflow_state_path(project_root, arch=arch)
    except ValueError:
        return {"migrated": False, "reason": "no_arch"}
    if not legacy.is_file():
        return {"migrated": False, "reason": "no_legacy"}
    st = _load(legacy)
    wid = str(st.get("workflow_id") or "").strip()
    if not wid or is_shared(wid):
        return {"migrated": False, "reason": "not_exclusive", "workflow_id": wid}
    group = occupancy_group_of(wid)
    if not group:
        return {"migrated": False, "reason": "no_group", "workflow_id": wid}
    status = str(st.get("status") or "").strip()
    dest = slot_state_path(project_root, group, arch=str(st.get("architecture") or arch or "") or None)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file():
        dest.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
    if status in _RUNNING_LIKE or not status:
        acquire_exclusive_lock(
            project_root,
            occupancy_group=group,
            workflow_id=wid,
            run_id=str(st.get("run_id") or ""),
            architecture=str(st.get("architecture") or arch or ""),
            session_id=str(st.get("session_id") or ""),
            pinned_digest=str(st.get("pinned_digest") or ""),
            status=status or "running",
        )
    return {
        "migrated": True,
        "workflow_id": wid,
        "occupancy_group": group,
        "slot": dest.as_posix(),
    }


def persist_path_for_state(
    project_root: Path | str,
    state: dict[str, Any],
) -> Path:
    """Where this live state document should be written."""
    wid = str(state.get("workflow_id") or "").strip()
    arch = str(state.get("architecture") or "").strip() or None
    run_id = str(state.get("run_id") or "").strip()
    if is_shared(wid) and run_id:
        return shared_live_state_path(project_root, run_id, arch=arch)
    group = occupancy_group_of(wid) if wid else ""
    if group:
        return slot_state_path(project_root, group, arch=arch)
    return legacy_workflow_state_path(project_root, arch=arch)


def resolve_load_state_path(
    project_root: Path | str,
    *,
    arch: str | None = None,
    workflow_id: str = "",
    session_id: str = "",
) -> Path | None:
    """Pick the live state file for this process (session / workflow / fallback)."""
    root = Path(project_root).expanduser().resolve()
    sid = current_session_id(session_id)
    wid = current_workflow_id(workflow_id)
    arch_name = str(arch or "").strip() or None

    binding = get_session_binding(root, sid) if sid else None
    if binding and not wid:
        wid = str(binding.get("workflow_id") or "").strip()
        if not arch_name:
            arch_name = str(binding.get("architecture") or "").strip() or None
        run_id = str(binding.get("run_id") or "").strip()
        if run_id and is_shared(str(binding.get("workflow_id") or "")):
            path = shared_live_state_path(root, run_id, arch=arch_name)
            if path.is_file():
                return path
        group = str(binding.get("occupancy_group") or "").strip()
        if group:
            path = slot_state_path(root, group, arch=arch_name)
            if path.is_file():
                return path

    if wid:
        if is_shared(wid):
            shared = list_shared_runs(root)
            if sid:
                for row in reversed(shared):
                    if str(row.get("session_id") or "") != sid:
                        continue
                    if str(row.get("workflow_id") or "") != wid:
                        continue
                    row_arch = str(row.get("architecture") or "").strip()
                    if arch_name and row_arch and row_arch != arch_name:
                        continue
                    path = shared_live_state_path(
                        root,
                        str(row.get("run_id") or ""),
                        arch=row_arch or arch_name,
                    )
                    if path.is_file():
                        return path
            for row in reversed(shared):
                if str(row.get("workflow_id") or "") != wid:
                    continue
                row_arch = str(row.get("architecture") or "").strip()
                if arch_name and row_arch and row_arch != arch_name:
                    continue
                path = shared_live_state_path(
                    root,
                    str(row.get("run_id") or ""),
                    arch=row_arch or arch_name,
                )
                if path.is_file():
                    return path
        else:
            group = occupancy_group_of(wid)
            if group:
                try:
                    path = slot_state_path(root, group, arch=arch_name)
                    if path.is_file():
                        return path
                except ValueError:
                    pass

    lock_doc = read_product_locks(root)
    if wid:
        group = occupancy_group_of(wid)
        lock = (lock_doc.get("locks") or {}).get(group) if group else None
        if isinstance(lock, dict) and str(lock.get("architecture") or "").strip():
            try:
                path = slot_state_path(
                    root,
                    group,
                    arch=str(lock.get("architecture") or arch_name or "") or None,
                )
                if path.is_file():
                    return path
            except ValueError:
                pass

    try:
        legacy = legacy_workflow_state_path(root, arch=arch_name)
        if legacy.is_file():
            return legacy
    except ValueError:
        pass
    return None


def apply_stale_confidence(
    payload: dict[str, Any],
    project_root: Path | str,
    *,
    architecture: str = "",
    pinned_digest: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Cap answer confidence when the session is bound to an older ``.uo`` digest."""
    check = binding_is_stale(
        project_root,
        session_id=session_id,
        pinned_digest=pinned_digest,
        architecture=architecture,
    )
    out = dict(payload or {})
    out["uo_freshness"] = check
    if not check.get("stale"):
        return out
    out["reason_code"] = "UO_DIGEST_CHANGED"
    out["message_zh"] = (
        str(out.get("message_zh") or "")
        + ("；" if out.get("message_zh") else "")
        + "CodeMap 已更新，上一轮结论置信度下降；请重新查询或重新绑定。"
    ).strip("；")
    _cap_confidence_fields(out)
    return out


def cap_confidence_fields(obj: Any) -> None:
    """Public alias for capping confidence fields on stale UO bindings."""
    _cap_confidence_fields(obj)


def _cap_confidence_fields(obj: Any) -> None:
    if isinstance(obj, dict):
        if "confidence" in obj:
            val = obj.get("confidence")
            if isinstance(val, str) and val.strip().lower() in {"high", "source_verified"}:
                obj["confidence"] = "medium"
            elif isinstance(val, (int, float)) and float(val) > 0.6:
                obj["confidence"] = 0.6
        for value in obj.values():
            _cap_confidence_fields(value)
    elif isinstance(obj, list):
        for item in obj:
            _cap_confidence_fields(item)


def occupancy_status_payload(project_root: Path | str) -> dict[str, Any]:
    """Compact occupancy view for ``acp status`` / Host (not pasted to the user)."""
    locks = read_product_locks(project_root)
    binding = get_session_binding(project_root)
    families = {}
    for group, lock in (locks.get("locks") or {}).items():
        if isinstance(lock, dict):
            families[str(group)] = {
                "workflow_id": lock.get("workflow_id"),
                "run_id": lock.get("run_id"),
                "status": lock.get("status"),
                "architecture": lock.get("architecture"),
                "uo_stale": bool(lock.get("uo_stale")),
            }
    handle_stale = binding_is_stale(project_root) if binding else {"stale": False}
    return {
        "product_locks": families,
        "shared_runs": [
            {
                "workflow_id": row.get("workflow_id"),
                "run_id": row.get("run_id"),
                "session_id": row.get("session_id"),
                "uo_stale": bool(row.get("uo_stale")),
            }
            for row in (locks.get("shared") or [])
            if isinstance(row, dict)
        ],
        "session_binding": {
            "session_id": (binding or {}).get("session_id") or "",
            "uo_path": (binding or {}).get("uo_path") or "",
            "digest": str((binding or {}).get("digest") or "")[:16],
            "stale": bool((binding or {}).get("stale") or handle_stale.get("stale")),
            "architecture": (binding or {}).get("architecture") or "",
        }
        if binding
        else {},
        "uo_stale": bool(handle_stale.get("stale")),
        "reason_code": str(handle_stale.get("reason_code") or ""),
    }
