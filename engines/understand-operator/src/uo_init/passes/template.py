# -*- coding: utf-8 -*-
"""TemplatePass — generalise tpl_dsl / tpl_bind into CodeMap template model."""

from __future__ import annotations

from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


def run(codemap: CodeMap, *, context: dict[str, Any] | None = None) -> CodeMap:
    ctx = context or {}
    # Prefer structured bindings from tpl_bind when present.
    bindings = list(ctx.get("template_bindings") or [])
    if not bindings:
        bindings = _bindings_from_declared(ctx.get("declared") or {})

    for row in bindings:
        if not isinstance(row, dict):
            continue
        tpl_name = str(row.get("template") or row.get("name") or "KernelTemplate")
        tpl = codemap.upsert(EntityKind.TEMPLATE, tpl_name, attrs={"layer": "template"})
        inst_name = str(row.get("instance") or row.get("specialization") or "")
        args = row.get("args") or row.get("bindings") or {}
        if not inst_name:
            if isinstance(args, dict):
                inst_name = f"{tpl_name}<{', '.join(f'{k}={v}' for k, v in args.items())}>"
            else:
                inst_name = f"{tpl_name}<...>"
        inst = codemap.upsert(
            EntityKind.TEMPLATE_INSTANCE,
            inst_name,
            attrs={"layer": "template", "args": args},
        )
        codemap.link(RelationKind.INSTANTIATES, tpl.id, inst.id)
        if isinstance(args, dict):
            for k, v in args.items():
                arg_e = codemap.upsert(
                    EntityKind.TEMPLATE_ARG,
                    str(k),
                    attrs={"value": v, "layer": "template"},
                )
                codemap.link(RelationKind.BINDS, inst.id, arg_e.id)
                cv = codemap.upsert(
                    EntityKind.COMPILE_VAR,
                    str(k),
                    attrs={"value": v, "layer": "template"},
                )
                codemap.link(RelationKind.BINDS, inst.id, cv.id)
        key_name = str(row.get("tiling_key") or row.get("key") or "")
        if key_name:
            key = codemap.upsert(EntityKind.TILING_KEY, key_name, attrs={"layer": "tiling"})
            codemap.link(RelationKind.SELECTS, key.id, inst.id)
        for kernel in codemap.by_kind(EntityKind.KERNEL):
            codemap.link(RelationKind.INSTANTIATES, inst.id, kernel.id)
            if codemap.architecture:
                arch = codemap.upsert(EntityKind.ARCH, codemap.architecture)
                codemap.link(RelationKind.AVAILABLE_ON, inst.id, arch.id)

    # Fallback: reuse tpl_dsl parse if raw DSL text provided.
    dsl_text = str(ctx.get("tiling_key_dsl") or "")
    if dsl_text and not bindings:
        try:
            from uo_init import tpl_dsl

            parsed = tpl_dsl.parse(dsl_text) if hasattr(tpl_dsl, "parse") else None
            if isinstance(parsed, dict):
                ctx = {**ctx, "declared": parsed}
                return run(codemap, context=ctx)
        except Exception:
            pass

    codemap.meta["template_pass"] = "v1"
    return codemap


def _bindings_from_declared(declared: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dims = declared.get("dimensions") or declared.get("keys") or declared.get("fields") or []
    if isinstance(dims, dict):
        dims = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in dims.items()]
    for d in dims:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or d.get("id") or "")
        if not name:
            continue
        out.append(
            {
                "template": str(d.get("template") or "TilingKey"),
                "tiling_key": name,
                "args": d.get("args") or d.get("bindings") or {},
                "instance": str(d.get("instance") or ""),
            }
        )
    return out
