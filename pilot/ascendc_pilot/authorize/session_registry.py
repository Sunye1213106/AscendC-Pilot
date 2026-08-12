"""Map OpenCode child session IDs to Pilot actor/action/lease identity.

Used by Host Session Driver so authorize does not guess identity from env.
Persists to ~/.config/opencode/ascendc-sessions/ for cross-process lookup.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# session_id -> binding (process-local)
_REGISTRY: dict[str, dict[str, Any]] = {}
_MAX = 512


def _disk_dir() -> Path:
    return Path.home() / ".config" / "opencode" / "ascendc-sessions"


def _safe_name(session_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in session_id)


def register_child_session(
    *,
    project: str,
    session_id: str,
    actor_id: str,
    action_id: str,
    lease_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    sid = (session_id or "").strip()
    if not sid:
        return {"ok": False, "error": "SESSION_ID_REQUIRED"}
    if len(_REGISTRY) >= _MAX:
        oldest = sorted(_REGISTRY.items(), key=lambda kv: float(kv[1].get("ts") or 0))
        for k, _ in oldest[: max(1, _MAX // 4)]:
            _REGISTRY.pop(k, None)
    binding = {
        "project": (project or "").strip(),
        "session_id": sid,
        "actor_id": (actor_id or "").strip(),
        "action_id": (action_id or "").strip(),
        "lease_id": (lease_id or "").strip(),
        "run_id": (run_id or "").strip(),
        "ts": time.time(),
    }
    _REGISTRY[sid] = binding
    try:
        d = _disk_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{_safe_name(sid)}.json").write_text(
            json.dumps(binding, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "method": "register-session", "session": binding}


def lookup_child_session(session_id: str) -> dict[str, Any] | None:
    sid = (session_id or "").strip()
    if not sid:
        return None
    hit = _REGISTRY.get(sid)
    if hit:
        return dict(hit)
    # Cross-process: read disk sidecar written by Host plugin.
    try:
        path = _disk_dir() / f"{_safe_name(sid)}.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("session_id"):
                _REGISTRY[sid] = data
                return dict(data)
    except Exception:  # noqa: BLE001
        pass
    return None


def clear() -> None:
    _REGISTRY.clear()


__all__ = ["register_child_session", "lookup_child_session", "clear"]
