# -*- coding: utf-8 -*-
"""CompileTimePass — syntax-backed constexpr / enum / NTTP / arch facts.

A branch token is not a compile-time root merely because it is uppercase.  This
pass only creates compile entities from deterministic compiler/IR facts and may
link an existing compile entity into a branch when the names match.
"""
from __future__ import annotations

from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


def run(codemap: CodeMap, *, context: dict[str, Any] | None = None) -> CodeMap:
    ctx = context or {}
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
            attrs={
                "value": value,
                "origin": "constexpr_or_define",
                "compile_root": True,
                "layer": "compile",
            },
        )
        if codemap.architecture:
            arch = codemap.upsert(EntityKind.ARCH, codemap.architecture)
            codemap.link(RelationKind.ACTIVE_UNDER, ent.id, arch.id)

    known: dict[str, list[str]] = {}
    for kind in (EntityKind.COMPILE_VAR, EntityKind.MACRO):
        for ent in codemap.by_kind(kind):
            for name in {ent.name, ent.name.split("::")[-1]}:
                if name:
                    known.setdefault(name, []).append(ent.id)

    linked = 0
    for br in codemap.by_kind(EntityKind.BRANCH):
        cond = str(br.attrs.get("condition") or br.attrs.get("predicate") or br.name or "")
        for token in _ident_tokens(cond):
            for entity_id in known.get(token, ()):  # never upsert from spelling alone
                codemap.link(
                    RelationKind.CONTROLS,
                    entity_id,
                    br.id,
                    attrs={"provenance": "compile_symbol_reference"},
                    status="confirmed",
                )
                linked += 1

    codemap.meta["compile_time_pass"] = "v2-syntax-backed"
    codemap.meta["compile_time_branch_links"] = linked
    return codemap


def _ident_tokens(text: str) -> list[str]:
    import re

    return re.findall(r"\b[A-Za-z_]\w*\b", text or "")
