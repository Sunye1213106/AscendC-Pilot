# -*- coding: utf-8 -*-
"""CE session handoff: pointer-only next-slash note."""

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
) -> dict[str, Any]:
    """Write ce/session_handoff.md. References paths; does not copy artifact bodies."""
    arch = str(architecture or "").strip()
    if not arch:
        return {"ok": False, "engine": "session_handoff", "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    root = Path(project_root).expanduser().resolve()
    out = root / ".ascendc-pilot" / arch / "ce" / "session_handoff.md"
    artifacts = [str(p).strip() for p in (artifact_paths or []) if str(p).strip()]
    opens = [str(p).strip() for p in (open_items or []) if str(p).strip()]
    lines = [
        "# CE session handoff",
        "",
        f"- next: `{next_slash}`",
        "- artifacts:",
    ]
    if artifacts:
        lines.extend(f"  - `{path}`" for path in artifacts)
    else:
        lines.append("  - (none)")
    lines.append("- open:")
    if opens:
        lines.extend(f"  - {item}" for item in opens)
    else:
        lines.append("  - (none)")
    lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return {"ok": True, "engine": "session_handoff", "artifact": out.as_posix(), "next_slash": next_slash}
