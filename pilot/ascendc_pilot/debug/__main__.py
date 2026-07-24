"""CLI entry: python -m ascendc_pilot.debug <event>  (stdin JSON → stdout JSON)."""

from __future__ import annotations

import json
import sys

from ascendc_pilot.debug import hook_handle


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    event = args[0] if args else "unknown"
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    # Cursor often nests under different keys — flatten common aliases.
    if "cwd" not in payload and isinstance(payload.get("workspace_roots"), list):
        roots = payload["workspace_roots"]
        if roots:
            payload["cwd"] = roots[0]
    try:
        out = hook_handle(event, payload)
    except Exception as exc:  # noqa: BLE001 — fail open
        out = {"ok": True, "skipped": True, "error": str(exc)}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
