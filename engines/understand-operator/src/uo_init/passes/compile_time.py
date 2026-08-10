# -*- coding: utf-8 -*-
"""CompileTimePass — constexpr / enum / NTTP / arch macros as CompileTimeEntity."""

from __future__ import annotations

from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


def run(codemap: CodeMap, *, context: dict[str, Any] | None = None) -> CodeMap:
    ctx = context or {}
    # Named constants from tiling IR.
    tiling_ir = ctx.get("tiling_ir")
    constants = list(getattr(tiling_ir, "constants", None) or []) if tiling_ir else []
    for c in constants:
        if isinstance(c, dict):
            name = str(c.get("name") or "")
            value = c.get("value")
        else:
            name = str(getattr(c, "name", "") or "")
            value = getattr(c, "value", None)
        if not name:
            continue
        ent = codemap.upsert(
            EntityKind.COMPILE_VAR,
            name,
            attrs={"value": value, "origin": "constexpr_or_define", "layer": "compile"},
        )
        if codemap.architecture:
            arch = codemap.upsert(EntityKind.ARCH, codemap.architecture)
            codemap.link(RelationKind.ACTIVE_UNDER, ent.id, arch.id)

    # Kernel branch conditions that mention compile-time symbols.
    for br in codemap.by_kind(EntityKind.BRANCH):
        cond = str(br.attrs.get("condition") or br.name or "")
        for token in _ident_tokens(cond):
            if token.isupper() or token.startswith("IS_") or token.startswith("__"):
                cv = codemap.upsert(
                    EntityKind.COMPILE_VAR,
                    token,
                    attrs={"layer": "compile", "from_branch": br.id},
                )
                codemap.link(RelationKind.CONTROLS, cv.id, br.id)

    codemap.meta["compile_time_pass"] = "v1"
    return codemap


def _ident_tokens(text: str) -> list[str]:
    import re

    return re.findall(r"\b[A-Za-z_]\w*\b", text or "")
