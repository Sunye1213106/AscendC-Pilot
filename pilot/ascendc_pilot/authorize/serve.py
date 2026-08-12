"""Long-lived authorize daemon (stdio JSON-lines + optional IPC directory).

Host adapters (OpenCode plugin) spawn once. Sync hooks use a request/response
file protocol under ``--ipc-dir`` so authorize stays hot without per-call Python
cold start.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _read_line() -> str | None:
    line = sys.stdin.readline()
    if line == "":
        return None
    return line.strip()


def _write(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_request(req: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one daemon request. Methods: authorize, ping, register-session, clear-cache."""
    method = str(req.get("method") or req.get("cmd") or "authorize").strip().lower()
    if method in {"ping", "health"}:
        return {"ok": True, "method": "ping", "alive": True}

    if method in {"clear-cache", "cache-clear"}:
        from ascendc_pilot.authorize import cache as auth_cache

        auth_cache.clear()
        auth_cache.bump_generation()
        return {"ok": True, "method": "clear-cache"}

    if method in {"register-session", "register_session"}:
        from ascendc_pilot.authorize.session_registry import register_child_session

        return register_child_session(
            project=str(req.get("project") or ""),
            session_id=str(req.get("session_id") or ""),
            actor_id=str(req.get("actor_id") or req.get("agent") or ""),
            action_id=str(req.get("action_id") or req.get("action") or ""),
            lease_id=str(req.get("lease_id") or ""),
            run_id=str(req.get("run_id") or ""),
        )

    if method in {"lookup-session", "lookup_session"}:
        from ascendc_pilot.authorize.session_registry import lookup_child_session

        hit = lookup_child_session(str(req.get("session_id") or ""))
        return {"ok": bool(hit), "method": "lookup-session", "session": hit}

    # default: authorize
    from ascendc_pilot.authorize import authorize

    project = req.get("project")
    project_path = Path(project).expanduser() if project else None
    return authorize(
        project_path,
        tool=str(req.get("tool") or ""),
        command=str(req.get("command") or ""),
        path=str(req.get("path") or ""),
        agent=str(req.get("agent") or ""),
        action=str(req.get("action") or ""),
        lease_id=str(req.get("lease_id") or ""),
        session_id=str(req.get("session_id") or ""),
    )


def _process_ipc_dir(ipc_dir: Path) -> int:
    """Process *.req.json files; write matching *.resp.json. Returns count handled."""
    handled = 0
    if not ipc_dir.is_dir():
        return 0
    for req_path in sorted(ipc_dir.glob("*.req.json")):
        try:
            raw = req_path.read_text(encoding="utf-8")
            req = json.loads(raw)
        except Exception:  # noqa: BLE001
            try:
                req_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            continue
        if not isinstance(req, dict):
            continue
        req_id = str(req.get("id") or req_path.stem.replace(".req", ""))
        try:
            out = handle_request(req)
        except Exception as exc:  # noqa: BLE001
            out = {"ok": False, "error": "SERVE_EXCEPTION", "message": str(exc)[:400]}
        if not isinstance(out, dict):
            out = {"ok": False, "error": "BAD_RESPONSE"}
        if req_id:
            out = {**out, "id": req_id}
        resp_path = ipc_dir / f"{req_id}.resp.json"
        try:
            resp_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            req_path.unlink(missing_ok=True)
            handled += 1
        except Exception:  # noqa: BLE001
            pass
    return handled


def serve_forever(*, ipc_dir: str | Path | None = None) -> int:
    """Block serving authorize. If ipc_dir set, also poll request files."""
    ipc = Path(ipc_dir).expanduser() if ipc_dir else None
    if ipc is not None:
        ipc.mkdir(parents=True, exist_ok=True)
    _write({"ok": True, "event": "ready", "protocol": "acp-authorize-v1", "ipc_dir": str(ipc or "")})

    if ipc is not None:
        # IPC poll loop (OpenCode sync hooks). Optional stdin for quit.
        try:
            import select
        except ImportError:
            select = None  # type: ignore[assignment]

        while True:
            _process_ipc_dir(ipc)
            line: str | None = None
            if select is not None:
                try:
                    ready, _, _ = select.select([sys.stdin], [], [], 0.05)
                except Exception:  # noqa: BLE001
                    ready = []
                if ready:
                    line = _read_line()
            else:
                time.sleep(0.05)
            if line is None:
                if select is None:
                    continue
                # empty ready set → continue polling
                continue
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                _write({"ok": False, "error": "JSON_DECODE", "message": str(exc)[:200]})
                continue
            if not isinstance(req, dict):
                _write({"ok": False, "error": "BAD_REQUEST"})
                continue
            if req.get("method") in {"quit", "exit", "shutdown"} or req.get("cmd") in {
                "quit",
                "exit",
                "shutdown",
            }:
                _write({"ok": True, "event": "shutdown"})
                return 0
            out = handle_request(req)
            if "id" in req and isinstance(out, dict):
                out = {**out, "id": req["id"]}
            _write(out if isinstance(out, dict) else {"ok": False})
        return 0

    # Stdio-only mode
    while True:
        line = _read_line()
        if line is None:
            break
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            _write({"ok": False, "error": "JSON_DECODE", "message": str(exc)[:200]})
            continue
        if not isinstance(req, dict):
            _write({"ok": False, "error": "BAD_REQUEST", "message": "request must be object"})
            continue
        if req.get("method") in {"quit", "exit", "shutdown"} or req.get("cmd") in {
            "quit",
            "exit",
            "shutdown",
        }:
            _write({"ok": True, "event": "shutdown"})
            return 0
        try:
            out = handle_request(req)
        except Exception as exc:  # noqa: BLE001
            out = {"ok": False, "error": "SERVE_EXCEPTION", "message": str(exc)[:400]}
        if not isinstance(out, dict):
            out = {"ok": False, "error": "BAD_RESPONSE", "message": "handler returned non-dict"}
        if "id" in req:
            out = {**out, "id": req["id"]}
        _write(out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acp serve-authorize")
    parser.add_argument("--ipc-dir", default="", help="Directory for *.req.json / *.resp.json IPC")
    args = parser.parse_args(argv)
    return serve_forever(ipc_dir=args.ipc_dir or None)


__all__ = ["serve_forever", "handle_request", "main"]
