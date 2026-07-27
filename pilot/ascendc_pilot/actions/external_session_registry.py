"""Always-on external Task session registry (control plane; SQLite-backed)."""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_SESSION_ID_RE = re.compile(r"ses_[A-Za-z0-9_]+")
_DB_LOCK = threading.RLock()


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
    """Legacy YAML path (kept for migration / debug export)."""
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


def db_path(project_root: Path) -> Path:
    return Path(project_root) / ".ascendc-pilot" / "external_sessions.sqlite3"


def _new_registration_id() -> str:
    return f"ext_{uuid.uuid4().hex[:12]}"


def _connect(project_root: Path) -> sqlite3.Connection:
    path = db_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS registrations (
            registration_id TEXT PRIMARY KEY,
            dispatch_nonce TEXT UNIQUE NOT NULL,
            run_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            task_id TEXT,
            primary_session_id TEXT,
            previous_external_task_session_id TEXT,
            external_task_session_id TEXT,
            status TEXT NOT NULL,
            actor_id TEXT,
            host_reported_resumed_from TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {k: row[k] for k in row.keys()}


def _migrate_yaml_once(project_root: Path, conn: sqlite3.Connection) -> None:
    """Import legacy per-action YAML registries once into SQLite."""
    root = Path(project_root)
    marker = root / ".ascendc-pilot" / ".external_sessions_migrated"
    if marker.is_file():
        return
    runs = root / ".ascendc-pilot" / "runs"
    if not runs.is_dir():
        marker.write_text("1\n", encoding="utf-8")
        return
    for yaml_path in runs.glob("*/actions/*/external_sessions.yaml"):
        data = _load_yaml(yaml_path)
        run_id = str(data.get("run_id") or yaml_path.parts[-4])
        action_id = str(data.get("action_id") or yaml_path.parts[-2])
        for sess in data.get("sessions") or []:
            if not isinstance(sess, dict):
                continue
            rid = str(sess.get("registration_id") or _new_registration_id())
            nonce = str(sess.get("dispatch_nonce") or f"nonce_{uuid.uuid4().hex[:10]}")
            now = _now()
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO registrations (
                        registration_id, dispatch_nonce, run_id, action_id, task_id,
                        primary_session_id, previous_external_task_session_id,
                        external_task_session_id, status, actor_id, host_reported_resumed_from,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rid,
                        nonce,
                        run_id,
                        action_id,
                        str(sess.get("task_id") or ""),
                        normalize_session_id(str(sess.get("primary_session_id") or "")),
                        normalize_session_id(str(sess.get("previous_external_task_session_id") or "")),
                        normalize_session_id(str(sess.get("external_task_session_id") or "")),
                        "bound" if sess.get("external_task_session_id") else "pending",
                        str(sess.get("actor_id") or ""),
                        normalize_session_id(str(sess.get("host_reported_resumed_from") or "")),
                        str(sess.get("started_at") or now),
                        str(sess.get("patched_at") or sess.get("started_at") or now),
                    ),
                )
            except sqlite3.IntegrityError:
                continue
    marker.write_text("1\n", encoding="utf-8")


def _export_yaml_mirror(project_root: Path, run_id: str, action_id: str, sessions: list[dict[str, Any]]) -> None:
    """Best-effort YAML mirror for human inspection (not the control-plane authority)."""
    try:
        save_registry(project_root, run_id, action_id, {"sessions": sessions})
    except Exception:  # noqa: BLE001
        pass


def load_registry(project_root: Path, run_id: str, action_id: str) -> dict[str, Any]:
    root = Path(project_root)
    with _DB_LOCK:
        conn = _connect(root)
        try:
            _migrate_yaml_once(root, conn)
            rows = conn.execute(
                "SELECT * FROM registrations WHERE run_id=? AND action_id=? ORDER BY created_at ASC",
                (run_id, action_id),
            ).fetchall()
        finally:
            conn.close()
    sessions = [_row_to_dict(r) for r in rows]
    return {"version": 1, "run_id": run_id, "action_id": action_id, "sessions": sessions}


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
    dispatch_nonce: str = "",
) -> None:
    idx = _load_yaml(global_index_path(project_root))
    rows = list(idx.get("entries") or [])
    rows.append(
        {
            "run_id": run_id,
            "action_id": action_id,
            "registration_id": registration_id,
            "dispatch_nonce": dispatch_nonce,
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
    task_id: str = "",
) -> dict[str, Any]:
    """Always-on registration. Never gated on debug.is_enabled."""
    root = Path(project_root)
    rid = str(run_id or "").strip()
    aid = str(action_id or "").strip()
    if not rid or not aid:
        return {"ok": False, "error": "run_id_and_action_id_required"}
    registration_id = _new_registration_id()
    nonce = str(dispatch_nonce or "").strip() or f"nonce_{uuid.uuid4().hex[:10]}"
    child = normalize_session_id(external_task_session_id)
    primary = normalize_session_id(primary_session_id)
    previous = latest_external_session(root, run_id=rid, action_id=aid)
    prev_child = str(previous.get("external_task_session_id") or "").strip()
    now = _now()
    status = "bound" if child else "pending"
    row = {
        "registration_id": registration_id,
        "dispatch_nonce": nonce,
        "run_id": rid,
        "action_id": aid,
        "task_id": task_id,
        "primary_session_id": primary,
        "external_task_session_id": child,
        "previous_external_task_session_id": prev_child,
        "host_reported_resumed_from": normalize_session_id(host_reported_resumed_from),
        "actor_id": actor_id,
        "status": status,
        "started_at": now,
        "created_at": now,
        "updated_at": now,
        "patched_at": now if child else "",
    }
    with _DB_LOCK:
        conn = _connect(root)
        try:
            _migrate_yaml_once(root, conn)
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO registrations (
                        registration_id, dispatch_nonce, run_id, action_id, task_id,
                        primary_session_id, previous_external_task_session_id,
                        external_task_session_id, status, actor_id, host_reported_resumed_from,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        registration_id,
                        nonce,
                        rid,
                        aid,
                        task_id,
                        primary,
                        prev_child,
                        child,
                        status,
                        actor_id,
                        normalize_session_id(host_reported_resumed_from),
                        now,
                        now,
                    ),
                )
                conn.execute("COMMIT")
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK")
                return {"ok": False, "error": "dispatch_nonce_conflict", "dispatch_nonce": nonce}
        finally:
            conn.close()
    sessions = load_registry(root, rid, aid).get("sessions") or []
    _export_yaml_mirror(root, rid, aid, sessions)
    _touch_index(
        root,
        run_id=rid,
        action_id=aid,
        registration_id=registration_id,
        external_task_session_id=child,
        dispatch_nonce=nonce,
    )
    return {"ok": True, "registration": row, "registration_id": registration_id, "dispatch_nonce": nonce}


def lookup_registration(
    project_root: Path,
    *,
    registration_id: str = "",
    dispatch_nonce: str = "",
) -> dict[str, Any] | None:
    """Resolve run_id/action_id from SQLite (control plane). YAML index is not authoritative."""
    root = Path(project_root)
    rid = str(registration_id or "").strip()
    nonce = str(dispatch_nonce or "").strip()
    if not rid and not nonce:
        return None
    with _DB_LOCK:
        conn = _connect(root)
        try:
            _migrate_yaml_once(root, conn)
            row = None
            if rid:
                row = conn.execute(
                    "SELECT * FROM registrations WHERE registration_id=?",
                    (rid,),
                ).fetchone()
            if row is None and nonce:
                row = conn.execute(
                    "SELECT * FROM registrations WHERE dispatch_nonce=?",
                    (nonce,),
                ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()


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
    allow_orphan_recovery: bool = False,
) -> dict[str, Any]:
    """Bind child session id with compare-and-set on registration identity."""
    root = Path(project_root)
    rid = str(run_id or "").strip()
    aid = str(action_id or "").strip()
    child = normalize_session_id(external_task_session_id)
    if not child:
        return {"ok": False, "error": "missing_external_task_session_id"}
    if not rid or not aid:
        return {"ok": False, "error": "run_id_and_action_id_required"}

    target_dict: dict[str, Any] | None = None
    with _DB_LOCK:
        conn = _connect(root)
        try:
            _migrate_yaml_once(root, conn)
            conn.execute("BEGIN IMMEDIATE")
            target = None
            if registration_id:
                target = conn.execute(
                    "SELECT * FROM registrations WHERE registration_id=? AND run_id=? AND action_id=?",
                    (registration_id, rid, aid),
                ).fetchone()
            if target is None and dispatch_nonce:
                target = conn.execute(
                    "SELECT * FROM registrations WHERE dispatch_nonce=? AND run_id=? AND action_id=?",
                    (dispatch_nonce, rid, aid),
                ).fetchone()
            if target is None and (registration_id or dispatch_nonce):
                conn.execute("ROLLBACK")
                return {
                    "ok": False,
                    "error": "registration_not_found",
                    "registration_id": registration_id,
                    "dispatch_nonce": dispatch_nonce,
                }
            if target is None:
                pending = conn.execute(
                    """
                    SELECT * FROM registrations
                    WHERE run_id=? AND action_id=? AND (external_task_session_id IS NULL OR external_task_session_id='')
                    ORDER BY created_at ASC
                    """,
                    (rid, aid),
                ).fetchall()
                if len(pending) == 1:
                    target = pending[0]
                elif len(pending) > 1:
                    conn.execute("ROLLBACK")
                    return {"ok": False, "error": "ambiguous_pending_registration", "pending_count": len(pending)}
            if target is None:
                conn.execute("ROLLBACK")
            else:
                existing_child = normalize_session_id(str(target["external_task_session_id"] or ""))
                if existing_child and existing_child == child:
                    conn.execute("COMMIT")
                    return {
                        "ok": True,
                        "registration": _row_to_dict(target),
                        "duplicate": True,
                        "status": "already_patched",
                    }
                if existing_child and existing_child != child:
                    conn.execute("ROLLBACK")
                    return {
                        "ok": False,
                        "error": "registration_already_bound",
                        "existing_external_task_session_id": existing_child,
                    }

                prev = normalize_session_id(str(target["previous_external_task_session_id"] or ""))
                if not prev:
                    prior = conn.execute(
                        """
                        SELECT external_task_session_id FROM registrations
                        WHERE run_id=? AND action_id=? AND registration_id!=?
                          AND external_task_session_id IS NOT NULL AND external_task_session_id!=''
                        ORDER BY updated_at DESC LIMIT 1
                        """,
                        (rid, aid, target["registration_id"]),
                    ).fetchone()
                    if prior:
                        prev = normalize_session_id(str(prior["external_task_session_id"] or ""))
                primary = normalize_session_id(primary_session_id) or normalize_session_id(
                    str(target["primary_session_id"] or "")
                )
                host_resume = normalize_session_id(host_reported_resumed_from) or normalize_session_id(
                    str(target["host_reported_resumed_from"] or "")
                )
                now = _now()
                cur = conn.execute(
                    """
                    UPDATE registrations SET
                        external_task_session_id=?,
                        primary_session_id=?,
                        previous_external_task_session_id=?,
                        host_reported_resumed_from=?,
                        actor_id=COALESCE(NULLIF(?, ''), actor_id),
                        status='bound',
                        updated_at=?
                    WHERE registration_id=? AND (external_task_session_id IS NULL OR external_task_session_id='')
                    """,
                    (child, primary, prev, host_resume, actor_id, now, target["registration_id"]),
                )
                if cur.rowcount == 0:
                    again = conn.execute(
                        "SELECT * FROM registrations WHERE registration_id=?",
                        (target["registration_id"],),
                    ).fetchone()
                    conn.execute("COMMIT")
                    again_child = normalize_session_id(str((again["external_task_session_id"] if again else "") or ""))
                    if again_child == child:
                        return {
                            "ok": True,
                            "registration": _row_to_dict(again),
                            "duplicate": True,
                            "status": "already_patched",
                        }
                    return {"ok": False, "error": "cas_conflict", "registration": _row_to_dict(again)}
                updated = conn.execute(
                    "SELECT * FROM registrations WHERE registration_id=?",
                    (target["registration_id"],),
                ).fetchone()
                conn.execute("COMMIT")
                target_dict = _row_to_dict(updated)
        finally:
            conn.close()

    if target_dict is None:
        if not allow_orphan_recovery:
            return {
                "ok": False,
                "error": "no_pending_registration",
                "run_id": rid,
                "action_id": aid,
                "registration_id": registration_id,
                "dispatch_nonce": dispatch_nonce,
            }
        return register_external_session(
            root,
            run_id=rid,
            action_id=aid,
            primary_session_id=primary_session_id,
            external_task_session_id=child,
            actor_id=actor_id,
            dispatch_nonce=dispatch_nonce,
            host_reported_resumed_from=host_reported_resumed_from,
        )

    sessions = load_registry(root, rid, aid).get("sessions") or []
    _export_yaml_mirror(root, rid, aid, sessions)
    _touch_index(
        root,
        run_id=rid,
        action_id=aid,
        registration_id=str(target_dict.get("registration_id") or ""),
        external_task_session_id=child,
        dispatch_nonce=str(target_dict.get("dispatch_nonce") or ""),
    )

    from ascendc_pilot.actions.action_dispatch import record_continuation

    continuation = record_continuation(
        root,
        run_id=rid,
        action_id=aid,
        external_task_session_id=child,
        primary_session_id=str(target_dict.get("primary_session_id") or ""),
        previous_external_task_session_id=str(target_dict.get("previous_external_task_session_id") or ""),
        host_reported_resumed_from=str(target_dict.get("host_reported_resumed_from") or ""),
        actor_id=str(target_dict.get("actor_id") or actor_id or ""),
    )
    return {"ok": True, "registration": target_dict, "continuation": continuation}


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
    with _DB_LOCK:
        conn = _connect(root)
        try:
            _migrate_yaml_once(root, conn)
            row = conn.execute(
                """
                SELECT * FROM registrations
                WHERE run_id=? AND action_id=?
                  AND external_task_session_id IS NOT NULL AND external_task_session_id!=''
                ORDER BY updated_at DESC LIMIT 1
                """,
                (rid, aid),
            ).fetchone()
        finally:
            conn.close()
    if row is None:
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
    d = _row_to_dict(row)
    return {
        "external_task_session_id": normalize_session_id(str(d.get("external_task_session_id") or "")),
        "primary_session_id": normalize_session_id(str(d.get("primary_session_id") or "")),
        "previous_external_task_session_id": normalize_session_id(
            str(d.get("previous_external_task_session_id") or "")
        ),
        "host_reported_resumed_from": normalize_session_id(str(d.get("host_reported_resumed_from") or "")),
        "registration_id": d.get("registration_id"),
        "actor_id": d.get("actor_id"),
    }
