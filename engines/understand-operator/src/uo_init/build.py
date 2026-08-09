# -*- coding: utf-8 -*-
"""UO CodeMap compiler entry — assemble passes and commit ``.uo``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from uo_init.frontend.build_variant import build_variant_from_context
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.manager import run_analyze_passes
from uo_init.resolve.semantic_gap import list_gaps
from uo_init.store.writer import uo_product_path, write_codemap


def compile_codemap(
    *,
    op_name: str,
    architecture: str = "arch35",
    op_root: str | Path | None = None,
    host_ir: Any = None,
    kernel_ir: Any = None,
    tiling_ir: Any = None,
    kb: Any = None,
    key_fields: list[dict[str, Any]] | None = None,
    declared: dict[str, Any] | None = None,
    inputs: list[str] | None = None,
    build_context: Any = None,
    template_bindings: list[dict[str, Any]] | None = None,
    views: dict[str, Any] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Run BuildVariant + analyze passes and optionally write ``.uo``."""
    arch = (architecture or "arch35").strip() or "arch35"
    variant = build_variant_from_context(
        architecture=arch,
        build_context=build_context,
        name=arch,
    )
    cm = CodeMap(op_name=op_name, architecture=arch)
    bv = cm.upsert(EntityKind.BUILD_VARIANT, variant.name, attrs=variant.to_dict())
    arch_e = cm.upsert(EntityKind.ARCH, arch)
    cm.link(RelationKind.ACTIVE_UNDER, arch_e.id, bv.id)

    context: dict[str, Any] = {
        "host_ir": host_ir,
        "kernel_ir": kernel_ir,
        "tiling_ir": tiling_ir,
        "key_fields": key_fields or [],
        "declared": declared or {},
        "inputs": inputs or [],
        "build_variant": variant.to_dict(),
        "template_bindings": template_bindings or [],
        "op_name": op_name,
        "op_root": str(op_root or ""),
    }
    if kb is not None:
        CodeMap.from_kb(kb, codemap=cm)
    cm = run_analyze_passes(cm, context=context)

    result: dict[str, Any] = {
        "ok": True,
        "summary": cm.summary(),
        "gaps": list_gaps(cm),
        "codemap": cm,
    }
    if commit and op_root is not None:
        path = uo_product_path(op_root, op_name, arch)
        written = write_codemap(cm, path, views=views)
        result["uo"] = written
        result["path"] = written.get("path")
    return result
