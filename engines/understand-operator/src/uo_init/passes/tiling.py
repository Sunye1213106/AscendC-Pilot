# -*- coding: utf-8 -*-
"""TilingPass — TilingData / TilingKey entities on CodeMap."""

from __future__ import annotations

from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


def run(codemap: CodeMap, *, context: dict[str, Any] | None = None) -> CodeMap:
    ctx = context or {}
    tiling_ir = ctx.get("tiling_ir")
    if tiling_ir is not None:
        CodeMap.from_tiling_data_ir(
            tiling_ir,
            op_name=codemap.op_name,
            architecture=codemap.architecture,
            codemap=codemap,
        )

    declared = ctx.get("declared") or {}
    dims = declared.get("dimensions") or declared.get("keys") or []
    if isinstance(dims, dict):
        dims = [{"name": k} for k in dims]
    for d in dims:
        name = str(d.get("name") if isinstance(d, dict) else d)
        if name:
            codemap.upsert(EntityKind.TILING_KEY, name, attrs={"layer": "tiling"})

    # Host field → tiling field name match.
    tiling_fields = {e.name: e for e in codemap.by_kind(EntityKind.TILING_FIELD)}
    for field_e in codemap.by_kind(EntityKind.FIELD):
        tail = field_e.name.rsplit(".", 1)[-1]
        tf = tiling_fields.get(tail) or tiling_fields.get(field_e.name)
        if tf is not None:
            codemap.link(RelationKind.FLOWS_TO, field_e.id, tf.id)
            codemap.link(RelationKind.WRITES, field_e.id, tf.id)

    for key in codemap.by_kind(EntityKind.TILING_KEY):
        for tf in tiling_fields.values():
            if key.name and (key.name == tf.name or key.name in tf.name or tf.name in key.name):
                codemap.link(RelationKind.SELECTS, key.id, tf.id)

    codemap.meta["tiling_pass"] = "v1"
    return codemap
