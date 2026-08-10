# -*- coding: utf-8 -*-
"""Clang frontend wrapper — emits CompilerFacts only."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CompilerFacts:
    """Raw compiler-visible facts (no AscendC interpretation)."""

    path: str = ""
    functions: dict[str, Any] = field(default_factory=dict)
    call_sites: list[Any] = field(default_factory=list)
    writes: list[Any] = field(default_factory=list)
    controls: list[Any] = field(default_factory=list)
    field_decls: list[Any] = field(default_factory=list)
    local_decls: list[Any] = field(default_factory=list)
    macros: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "function_count": len(self.functions),
            "call_sites": len(self.call_sites),
            "writes": len(self.writes),
            "controls": len(self.controls),
            "macros": list(self.macros),
            "notes": list(self.notes),
        }


def extract_compiler_facts(
    path: str | Path,
    build_context: Any,
    *,
    side: str = "host",
    dtype_variant: str = "",
    deep: bool = True,
) -> CompilerFacts:
    """Walk one TU via existing ``clang_walk.walk_file``; return facts only."""
    from uo_init.clang_walk import walk_file

    result = walk_file(
        Path(path),
        build_context,
        side=side,
        dtype_variant=dtype_variant or None,
    )
    facts = CompilerFacts(path=str(path))
    if result is None:
        facts.notes.append("walk_file returned None")
        return facts
    facts.functions = dict(getattr(result, "functions", None) or {})
    facts.call_sites = list(getattr(result, "call_sites", None) or [])
    facts.writes = list(getattr(result, "writes", None) or [])
    facts.controls = list(getattr(result, "controls", None) or [])
    facts.field_decls = list(getattr(result, "field_decls", None) or [])
    facts.local_decls = list(getattr(result, "local_decls", None) or [])
    # Opaque macro-expanded guards surface as control notes.
    for ctrl in facts.controls:
        pretty = ""
        if hasattr(ctrl, "pretty"):
            pretty = str(ctrl.pretty())
        elif hasattr(ctrl, "condition"):
            pretty = str(ctrl.condition)
        if "macro-expanded" in pretty or getattr(ctrl, "is_opaque", False):
            facts.macros.append(
                {
                    "kind": "opaque_guard",
                    "text": pretty[:200],
                    "file": str(getattr(ctrl, "file", "") or ""),
                    "line": int(getattr(ctrl, "line", 0) or 0),
                }
            )
    del deep  # deep walk is controlled inside clang_walk reachable closure
    return facts
