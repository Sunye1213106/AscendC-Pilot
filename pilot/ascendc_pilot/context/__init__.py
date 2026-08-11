"""Lightweight Context Pack builder + optional Context Compiler slices."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.memory import search_local
from ascendc_pilot.paths import context_root, ensure_agent_layout, tg_root, uo_root
from ascendc_pilot.state import load_state

# Re-export compiler entry points for callers / tests.
from ascendc_pilot.context.compiler import (  # noqa: E402
    compile_context_slice,
    maybe_compile_slice,
)
from ascendc_pilot.context.profiles import get_profile  # noqa: E402


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _resolve_pilot_params(project_root: Path, state: dict[str, Any]) -> dict[str, str]:
    params = _load_yaml(context_root(project_root) / "pilot_params.yaml")
    man = _load_yaml(uo_root(project_root) / "manifest.yaml")
    run_ctx = _load_yaml(tg_root(project_root) / "init" / "run_context.yaml")

    def pick(*vals: Any, default: str = "") -> str:
        for v in vals:
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        return default

    test_script_root = pick(
        state.get("test_script_root"),
        state.get("csv_consumer_root"),
        params.get("test_script_root"),
        params.get("csv_consumer_root"),
        run_ctx.get("test_script_root"),
        os.environ.get("ASCENDC_TEST_SCRIPT_ROOT"),
        os.environ.get("ASCENDC_CSV_CONSUMER_ROOT"),
    )
    return {
        "op_name": pick(state.get("op_name"), params.get("op_name"), man.get("op_name"), run_ctx.get("op_name"), project_root.name),
        "architecture": pick(state.get("architecture"), params.get("architecture"), man.get("architecture"), default="arch35"),
        "test_script_root": test_script_root,
        "level": pick(state.get("level"), params.get("level"), default="L0"),
        "focus": pick(state.get("focus"), params.get("focus")),
    }


def build_context_pack(
    project_root: Path,
    *,
    intent: str,
    topic: str = "",
    include_memory: bool = True,
    max_memory: int = 5,
) -> dict[str, Any]:
    """Build the legacy lightweight context pack (byte-stable when no slice).

    This function deliberately ignores context profiles so callers that only
    need the pack keep identical output. Use ``maybe_compile_slice`` separately
    when a profile is registered.
    """
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

    params = _resolve_pilot_params(project_root, state if isinstance(state, dict) else {})
    if params.get("op_name"):
        sources_used.append("pilot_params")

    pack = {
        "version": 1,
        "built_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "intent": intent,
        "topic": topic,
        "op_name": params["op_name"],
        "architecture": params["architecture"],
        "test_script_root": params["test_script_root"],
        "level": params["level"],
        "focus": params["focus"],
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


__all__ = [
    "build_context_pack",
    "compile_context_slice",
    "maybe_compile_slice",
    "get_profile",
]
