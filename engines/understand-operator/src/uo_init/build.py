# -*- coding: utf-8 -*-
"""UO CodeMap compiler entry — assemble semantic passes and commit one ``.uo``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from uo_init.frontend.build_variant import build_variant_from_context
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.frontier_resolution import resolve_class_frontiers
from uo_init.passes.host_defuse import trace_host_key_roots
from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions
from uo_init.passes.kernel_call_read_refine import refine_kernel_calls_and_tiling_reads
from uo_init.passes.kernel_call_resolution import resolve_kernel_call_frontiers
from uo_init.passes.kernel_tiling_closure import finalize_kernel_tiling_closure
from uo_init.passes.manager import run_analyze_passes
from uo_init.passes.source_contract import enrich_codemap_from_operator_source
from uo_init.passes.source_inventory import inventory_source_files
from uo_init.passes.source_resolution import resolve_source_gaps
from uo_init.passes.tiling_field_complete import complete_tiling_fields
from uo_init.passes.tiling_host_writes import enrich_tiling_host_writes
from uo_init.passes.tiling_kernel_reads import rebuild_verified_tiling_reads
from uo_init.passes.tiling_registration import enrich_tiling_registrations
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
    """Compile deterministic facts + current source into the unified CodeMap.

    Compiler-derived Host/Kernel IR remains authoritative where available. When
    an operator source root exists, deterministic source passes additionally
    inventory the selected architecture, recover API/Key/TilingData contracts,
    bind Host packed-key arguments, trace their def-use roots, complete scalar
    and array TilingData ABI fields, and finally rebuild an architecture-pure
    Kernel call/read/write closure from qualified current-source symbols before
    the strict completeness audit runs.
    """
    arch = (architecture or "arch35").strip() or "arch35"
    variant = build_variant_from_context(architecture=arch, build_context=build_context, name=arch)
    cm = CodeMap(op_name=op_name, architecture=arch)
    bv = cm.upsert(EntityKind.BUILD_VARIANT, variant.name, attrs=variant.to_dict())
    arch_e = cm.upsert(EntityKind.ARCH, arch)
    cm.link(RelationKind.ACTIVE_UNDER, arch_e.id, bv.id, attrs={"provenance": "build_variant"}, status="confirmed")

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

    source_root = Path(op_root).expanduser().resolve() if op_root is not None else None
    if source_root is not None and _looks_like_operator_source(source_root):
        inventory_source_files(cm, source_root, architecture=arch)
        enrich_codemap_from_operator_source(cm, source_root, architecture=arch)
        complete_tiling_fields(cm, source_root, architecture=arch)
        bind_host_tiling_key_expressions(cm, source_root, architecture=arch)
        trace_host_key_roots(cm, source_root, architecture=arch)
        enrich_tiling_registrations(cm, source_root, architecture=arch)
        resolve_source_gaps(cm, source_root, architecture=arch)
        resolve_class_frontiers(cm, source_root, architecture=arch)
        finalize_kernel_tiling_closure(cm, source_root, architecture=arch)
        refine_kernel_calls_and_tiling_reads(cm, source_root, architecture=arch)
        resolve_kernel_call_frontiers(cm, source_root, architecture=arch)
        rebuild_verified_tiling_reads(cm, source_root, architecture=arch)
        enrich_tiling_host_writes(cm, source_root, architecture=arch)
        cm.meta["production_source_enrichment"] = True
    else:
        cm.meta["production_source_enrichment"] = False

    from uo_init.diagnostics.audit import audit_codemap

    audit = audit_codemap(cm)
    result: dict[str, Any] = {
        "ok": True,
        "summary": dict(audit["summary"]),
        "audit": audit,
        "gaps": list_gaps(cm),
        "codemap": cm,
    }
    if commit and source_root is not None:
        path = uo_product_path(source_root, op_name, arch)
        written = write_codemap(cm, path, views=views)
        result["uo"] = written
        result["path"] = written.get("path")
    return result


def _looks_like_operator_source(root: Path) -> bool:
    return root.is_dir() and any((root / name).is_dir() for name in ("op_graph", "op_host", "op_kernel"))
