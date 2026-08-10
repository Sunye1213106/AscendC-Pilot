# -*- coding: utf-8 -*-
"""UO CodeMap compiler entry — assemble semantic passes and commit one ``.uo``."""

from __future__ import annotations

import pickle
import time
from pathlib import Path
from typing import Any

from uo_init.frontend.build_variant import build_variant_from_context
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.frontier_resolution import resolve_class_frontiers
from uo_init.passes.host_defuse import trace_host_key_roots
from uo_init.passes.host_defuse_validate import validate_host_defuse
from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions
from uo_init.passes.kernel_call_boundaries import classify_kernel_call_boundaries
from uo_init.passes.kernel_call_read_refine import refine_kernel_calls_and_tiling_reads
from uo_init.passes.kernel_call_resolution import resolve_kernel_call_frontiers
from uo_init.passes.kernel_identity import preserve_verified_kernel_identity
from uo_init.passes.kernel_tiling_closure import finalize_kernel_tiling_closure
from uo_init.passes.kernel_tiling_metrics import finalize_kernel_tiling_metrics
from uo_init.passes.kernel_tiling_truth import finalize_kernel_tiling_truth
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
from uo_init.timing import log as _tlog, timing_enabled

# Same-process reuse between analyze (commit=False) and commit. Avoids paying
# the full source-enrichment stack twice in one uo-init run.
_COMPILE_MEM: dict[str, dict[str, Any]] = {}


def _cache_key(op_root: Path, op_name: str, architecture: str) -> str:
    return f"{op_root.resolve()}|{op_name}|{architecture}"


def _cache_path(op_root: Path, architecture: str) -> Path:
    return (
        Path(op_root).expanduser().resolve()
        / ".ascendc-pilot"
        / architecture
        / "uo"
        / "ir"
        / "_codemap_compile_cache.pkl"
    )


def store_compile_cache(
    op_root: Path,
    op_name: str,
    architecture: str,
    result: dict[str, Any],
) -> None:
    """Keep analyze's compile result for a later commit in this (or next) process."""
    key = _cache_key(op_root, op_name, architecture)
    payload = {
        "op_name": op_name,
        "architecture": architecture,
        "codemap": result.get("codemap"),
        "views": result.get("_merged_views") or {},
        "summary": result.get("summary") or {},
        "gaps": result.get("gaps") or [],
        "audit": result.get("audit"),
        "tg_views": result.get("tg_views") or {},
    }
    _COMPILE_MEM[key] = payload
    try:
        path = _cache_path(op_root, architecture)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    except Exception:  # noqa: BLE001
        pass


def load_compile_cache(
    op_root: Path,
    op_name: str,
    architecture: str,
) -> dict[str, Any] | None:
    key = _cache_key(op_root, op_name, architecture)
    hit = _COMPILE_MEM.get(key)
    if hit is not None and hit.get("codemap") is not None:
        return hit
    try:
        path = _cache_path(op_root, architecture)
        if not path.is_file():
            return None
        data = pickle.loads(path.read_bytes())
        if not isinstance(data, dict) or data.get("codemap") is None:
            return None
        if data.get("op_name") != op_name or data.get("architecture") != architecture:
            return None
        _COMPILE_MEM[key] = data
        return data
    except Exception:  # noqa: BLE001
        return None


def clear_compile_cache(op_root: Path | None = None, architecture: str | None = None) -> None:
    if op_root is None:
        _COMPILE_MEM.clear()
        return
    arch = architecture or "arch35"
    key_prefix = f"{Path(op_root).expanduser().resolve()}|"
    for k in list(_COMPILE_MEM):
        if k.startswith(key_prefix):
            _COMPILE_MEM.pop(k, None)
    try:
        path = _cache_path(Path(op_root), arch)
        if path.is_file():
            path.unlink()
    except Exception:  # noqa: BLE001
        pass


def _span(name: str, t0: float) -> None:
    if timing_enabled():
        _tlog(f"{time.perf_counter() - t0:7.3f}s  compile.{name}")


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
    bind Host packed-key arguments, trace and lexically revalidate their def-use
    roots, complete scalar and array TilingData ABI fields, and finally rebuild
    an architecture-pure Kernel call/read/write closure from qualified current-
    source symbols before the strict completeness audit runs. Dependent/external
    calls that cannot be uniquely bound remain explicit call boundaries rather
    than guessed edges.
    """
    t_all = time.perf_counter()
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
    t0 = time.perf_counter()
    cm = run_analyze_passes(cm, context=context)
    _span("analyze_passes", t0)

    source_root = Path(op_root).expanduser().resolve() if op_root is not None else None
    if source_root is not None and _looks_like_operator_source(source_root):
        from uo_init.passes.source_text_cache import clear as clear_source_text

        clear_source_text()
        for name, fn, kwargs in (
            ("inventory", inventory_source_files, {}),
            ("source_contract", enrich_codemap_from_operator_source, {}),
            ("tiling_fields", complete_tiling_fields, {}),
            ("host_tiling_key", bind_host_tiling_key_expressions, {}),
            ("host_defuse", trace_host_key_roots, {}),
            ("host_defuse_validate", validate_host_defuse, {}),
            ("tiling_registration", enrich_tiling_registrations, {}),
            ("source_gaps", resolve_source_gaps, {}),
            ("class_frontiers", resolve_class_frontiers, {}),
            ("kernel_tiling_closure", finalize_kernel_tiling_closure, {}),
            ("kernel_identity", preserve_verified_kernel_identity, {"skip_arch": True}),
            ("kernel_call_refine", refine_kernel_calls_and_tiling_reads, {}),
            ("kernel_call_frontiers", resolve_kernel_call_frontiers, {}),
            ("kernel_call_boundaries", classify_kernel_call_boundaries, {"skip_arch": True}),
            ("tiling_reads", rebuild_verified_tiling_reads, {}),
            ("tiling_host_writes", enrich_tiling_host_writes, {}),
            ("kernel_tiling_truth", finalize_kernel_tiling_truth, {"skip_arch": True}),
            ("kernel_tiling_metrics", finalize_kernel_tiling_metrics, {"skip_arch": True}),
        ):
            t0 = time.perf_counter()
            if kwargs.get("skip_arch"):
                fn(cm)  # type: ignore[misc]
            else:
                fn(cm, source_root, architecture=arch)  # type: ignore[misc]
            _span(name, t0)
        cm.meta["production_source_enrichment"] = True
    else:
        cm.meta["production_source_enrichment"] = False

    from uo_init.diagnostics.audit import audit_codemap
    from uo_init.passes import tpl_schema as tpl_schema_pass
    from uo_init.tg_views import finalize_tg_views

    # Ensure TPL/D blobs exist even when header was only discoverable after
    # source inventory; then stamp host/graph projections with packing facts.
    t0 = time.perf_counter()
    if "tiling/exhaustive_key_space.yaml" not in (context.get("tg_views") or {}):
        if source_root is not None:
            context["op_root"] = str(source_root)
            context["architecture"] = arch
        cm = tpl_schema_pass.run(cm, context=context)
    _span("tpl_schema", t0)
    t0 = time.perf_counter()
    merged_views = dict(views or {})
    merged_views.update(context.get("tg_views") or {})
    merged_views = finalize_tg_views(cm, existing=merged_views)
    _span("finalize_views", t0)

    t0 = time.perf_counter()
    audit = audit_codemap(cm)
    _span("audit", t0)
    result: dict[str, Any] = {
        "ok": True,
        "summary": dict(audit["summary"]),
        "audit": audit,
        "gaps": list_gaps(cm),
        "codemap": cm,
        "_merged_views": merged_views,
        "tg_views": {
            "legal_key_count": int(cm.meta.get("legal_key_count") or 0),
            "view_names": sorted(merged_views),
        },
    }
    if commit and source_root is not None:
        t0 = time.perf_counter()
        path = uo_product_path(source_root, op_name, arch)
        written = write_codemap(
            cm, path, views=merged_views, summary=dict(audit["summary"])
        )
        result["uo"] = written
        result["path"] = written.get("path")
        _span("write_uo", t0)
    _span("total", t_all)
    return result


def _looks_like_operator_source(root: Path) -> bool:
    return root.is_dir() and any((root / name).is_dir() for name in ("op_graph", "op_host", "op_kernel"))
