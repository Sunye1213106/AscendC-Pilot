# -*- coding: utf-8 -*-
"""InputRootPass — promote derive_key_fields / host_derivation into CodeMap edges."""

from __future__ import annotations

from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


def run(codemap: CodeMap, *, context: dict[str, Any] | None = None) -> CodeMap:
    ctx = context or {}
    rows = list(ctx.get("key_fields") or ctx.get("derive_fields") or [])
    derivation = ctx.get("host_derivation") or {}
    if not rows and isinstance(derivation, dict):
        rows = list(derivation.get("fields") or derivation.get("dimensions") or [])

    for row in rows:
        if not isinstance(row, dict):
            continue
        key_name = str(row.get("name") or row.get("field") or row.get("dim") or "")
        if not key_name:
            continue
        key_e = codemap.upsert(
            EntityKind.TILING_KEY,
            key_name,
            attrs={
                "layer": "tiling",
                "exactness": row.get("exactness"),
                "status": row.get("status"),
            },
        )
        roots = row.get("input_roots") or row.get("roots") or []
        for root in roots:
            root_name = str(root)
            if not root_name:
                continue
            known_inputs = {e.name for e in codemap.by_kind(EntityKind.INPUT)}
            root_e = codemap.upsert(
                EntityKind.INPUT if _looks_like_input(root_name, known_inputs) else EntityKind.VARIABLE,
                root_name,
                attrs={"layer": "api", "role": "input_root"},
            )
            codemap.link(RelationKind.DERIVES, root_e.id, key_e.id)
            codemap.link(RelationKind.FLOWS_TO, root_e.id, key_e.id)

        # Intermediate host variables from leaves / value_leaves.
        for leaf in row.get("value_leaves") or row.get("leaves") or []:
            leaf_name = str(leaf)
            if not leaf_name:
                continue
            var = codemap.upsert(
                EntityKind.VARIABLE,
                leaf_name,
                attrs={"layer": "host", "role": "leaf"},
            )
            codemap.link(RelationKind.DERIVES, var.id, key_e.id)

    codemap.meta["input_root_pass"] = "v1"
    return codemap


def _looks_like_input(name: str, known_inputs: set[str] | None = None) -> bool:
    n = name.strip()
    if not n:
        return False
    if known_inputs and n in known_inputs:
        return True
    if n.isupper() and "_" in n:
        return True
    if n.startswith("INPUT_") or n.startswith("ATTR_"):
        return True
    return False
