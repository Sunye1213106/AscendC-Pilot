"""Lightweight Context Pack builder."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_harness.memory import search_local
from ascendc_harness.paths import context_root, ensure_agent_layout, uo_root
from ascendc_harness.state import load_state


def build_context_pack(
    project_root: Path,
    *,
    intent: str,
    topic: str = "",
    include_memory: bool = True,
    max_memory: int = 5,
) -> dict[str, Any]:
    ensure_agent_layout(project_root)
    state = load_state(project_root)
    uo = uo_root(project_root)
    sources_used: list[str] = ["workflow_state"]
    omitted: list[str] = ["full_kb", "full_source_tree", "full_memory"]

    overview = ""
    overview_path = uo / "summary" / "human_overview.md"
    if overview_path.is_file():
        overview = overview_path.read_text(encoding="utf-8")[:2000]
        sources_used.append("summary/human_overview.md")

    open_items = list(state.get("open_items") or [])
    memories: list[dict[str, Any]] = []
    if include_memory and topic:
        memories = search_local(project_root, topic=topic, limit=max_memory)
        if memories:
            sources_used.append("memory/stable+candidate")

    pack = {
        "version": 1,
        "built_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "intent": intent,
        "topic": topic,
        "workflow": {
            "workflow_id": state.get("workflow_id"),
            "phase": state.get("phase"),
            "status": state.get("status"),
            "run_id": state.get("run_id"),
            "open_items": open_items,
        },
        "uo_snippet": {"human_overview_prefix": overview},
        "memory": memories,
        "sources_used": sources_used,
        "omitted": omitted,
        "note": "Lightweight pack — do not load full KB unless a gate requires a specific path.",
    }

    out = context_root(project_root) / "context_pack.yaml"
    if yaml is not None:
        out.write_text(yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8")
    pack["path"] = out.as_posix()
    return pack
