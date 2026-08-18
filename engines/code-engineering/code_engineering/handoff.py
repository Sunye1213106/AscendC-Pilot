# -*- coding: utf-8 -*-
"""Portable session handoff markdown. Pointers only; no yaml; no copied bodies."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def write_session_handoff(
    project_root: Path | str,
    *,
    architecture: str,
    next_slash: str,
    artifact_paths: list[str] | None = None,
    open_items: list[str] | None = None,
    suggested_next: list[str] | None = None,
    why: str = "",
) -> dict[str, Any]:
    """Write `.ascendc-pilot/<arch>/session_handoff.md`."""
    arch = str(architecture or "").strip()
    if not arch:
        return {"ok": False, "engine": "session_handoff", "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    root = Path(project_root).expanduser().resolve()
    out = root / ".ascendc-pilot" / arch / "session_handoff.md"
    artifacts = [str(p).strip() for p in (artifact_paths or []) if str(p).strip()]
    opens = [str(p).strip() for p in (open_items or []) if str(p).strip()]
    suggestions = [str(p).strip() for p in (suggested_next or []) if str(p).strip()]
    lines = [
        "# Session handoff",
        "",
        f"- next: `{next_slash}`",
    ]
    if why.strip():
        lines.append(f"- why: {why.strip()}")
    lines.append("- artifacts:")
    if artifacts:
        lines.extend(f"  - `{path}`" for path in artifacts)
    else:
        lines.append("  - (none)")
    lines.append("- open:")
    if opens:
        lines.extend(f"  - {item}" for item in opens)
    else:
        lines.append("  - (none)")
    if suggestions:
        lines.append("- suggested:")
        lines.extend(f"  - {item}" for item in suggestions)
    lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return {"ok": True, "engine": "session_handoff", "artifact": out.as_posix(), "next_slash": next_slash}
