#!/usr/bin/env python3
"""Cursor hook adapter: event name from argv[1], payload from stdin."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _ensure_pilot_on_path() -> None:
    """Locate AscendC-Pilot/pilot when hook runs from workspace root."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "pilot",  # AscendC-Pilot/.cursor/hooks → AscendC-Pilot/pilot
        here.parents[3] / "AscendC-Pilot" / "pilot",  # PR-review/.cursor/hooks
        Path.home() / "PR-review" / "AscendC-Pilot" / "pilot",
    ]
    for c in candidates:
        if (c / "ascendc_pilot").is_dir():
            p = str(c)
            if p not in sys.path:
                sys.path.insert(0, p)
            return


def main() -> int:
    _ensure_pilot_on_path()
    event = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    try:
        from ascendc_pilot.debug import hook_handle
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps({"ok": True, "skipped": True, "error": str(exc)}) + "\n")
        return 0
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        out = hook_handle(event, payload)
    except Exception as exc:  # noqa: BLE001
        out = {"ok": True, "skipped": True, "error": str(exc)}
    # Only emit fields Cursor understands for the event.
    emit: dict = {}
    for k in (
        "additional_context",
        "agent_message",
        "user_message",
        "followup_message",
    ):
        if out.get(k):
            emit[k] = out[k]
    if not emit:
        emit = {"ok": True}
    sys.stdout.write(json.dumps(emit, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
