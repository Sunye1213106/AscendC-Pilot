# -*- coding: utf-8 -*-
"""HostIR / KernelIR extract for /uo-init (structural IR only)."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def extract_host_bundle(
    *,
    op_dir: str | Path,
    cann_root: str,
    ops_root: str | None = None,
    arch_dir: str | None = None,
    with_kernel: bool = True,
    kernel_max_variants: int | None = 1,
) -> dict[str, Any]:
    """Discover + Clang scope + host IR ∥ kernel IR.

    One product path: no controllability, API clang, var_model, or key bind.
    ``kernel_max_variants`` defaults to one dtype so cold extract stays bounded.
    """
    from concurrent.futures import ThreadPoolExecutor

    from uo_init.build_context import BuildContext
    from uo_init.host_ir import build_host_ir
    from uo_init.kernel_ir import build_kernel_ir
    from uo_init.op_spec import discover
    from uo_init.tpl_dsl import parse_file

    from uo_init.timing import PhaseTimer, log as _tlog

    timer = PhaseTimer()
    _tlog(
        f"extract_host_bundle start  with_kernel={with_kernel} "
        f"kernel_max_variants={kernel_max_variants}"
    )

    with timer.span("discover"):
        spec = discover(op_dir, arch_dir=arch_dir)
    _tlog(f"  discover host_targets={[p.name for p in spec.host_targets]}")

    with timer.span("BuildContext.load"):
        ctx = BuildContext.load(
            cann_root=cann_root,
            ops_root=ops_root,
            op_dir=str(spec.op_dir),
            arch_dir=spec.arch_dir,
        )
        from uo_init.kernel_tiling_view import install_kernel_tiling_view

        # Same force-include as prepare's scope_scan, otherwise kernel AST
        # cache keys diverge and extract re-parses the TU prepare already stored.
        install_kernel_tiling_view(spec, ctx)

    with timer.span("scope_clang_enrich"):
        import os

        from uo_init import scope_scan as sscan
        from uo_init.op_spec import _targets_from_scope

        reused = sscan.load_prepared_scope(spec.op_dir, spec.arch_dir)
        if reused is not None:
            spec.scope = reused
            arch = (spec.arch_dir or "").strip().lower()
            if arch:
                kept = []
                for item in spec.scope.files:
                    others = [
                        p
                        for p in (s.lower() for s in item.path.parts)
                        if sscan.ARCH_SEGMENT_RE.match(p) and p != arch
                    ]
                    if others:
                        continue
                    kept.append(item)
                spec.scope.files = kept
                spec.scope.__post_init__()
            _targets_from_scope(spec)
            if spec.kernel_targets:
                from uo_init.source_layout import pick_kernel_entry

                spec.kernel_entry = (
                    pick_kernel_entry(spec.kernel_targets, spec.arch_dir)
                    or spec.kernel_targets[0]
                )
            elif spec.kernel_entry is not None:
                owns = sscan.entry_architecture(spec.kernel_entry)
                arch = (spec.arch_dir or "").strip().lower()
                if owns and arch and owns != arch:
                    spec.kernel_entry = None
            _tlog(
                f"  clang_scope=reused_prepare "
                f"scope_files={len(spec.scope.files)} "
                f"shared={sum(1 for f in spec.scope.files if f.shared)}"
            )
        else:
            if spec.scope is None:
                spec.scope = sscan.scan(spec.op_dir, arch_dir=spec.arch_dir)
            layout_hosts = [p for p in spec.host_targets if p.exists()]
            kernel_tu = spec.kernel_entry
            if kernel_tu is not None:
                owns = sscan.entry_architecture(kernel_tu)
                arch = (spec.arch_dir or "").strip().lower()
                if owns and arch and owns != arch:
                    kernel_tu = None
                    spec.kernel_entry = None
            try:
                enrichment = sscan.enrich_with_clang(
                    spec.scope,
                    host_args=ctx.host_args(),
                    kernel_args=ctx.kernel_args(
                        dtype_variant="DT_FLOAT16", source_path=kernel_tu
                    ),
                    host_tus=layout_hosts,
                    kernel_tu=kernel_tu,
                    walk_ctx=ctx,
                )
                spec.scope = enrichment.scope
                _targets_from_scope(spec)
                if spec.kernel_targets:
                    from uo_init.source_layout import pick_kernel_entry

                    spec.kernel_entry = (
                        pick_kernel_entry(spec.kernel_targets, spec.arch_dir)
                        or spec.kernel_targets[0]
                    )
                allow_unverified = str(
                    os.environ.get("UO_TEST_ALLOW_UNVERIFIED_SCOPE") or ""
                ).strip().lower() in {"1", "true", "yes"}
                if not enrichment.complete and not allow_unverified:
                    raise RuntimeError(
                        "SCOPE_CLANG_CLOSURE_INCOMPLETE: "
                        f"parsed {enrichment.tus_parsed}/{enrichment.tus_expected}; "
                        + "; ".join(enrichment.errors[:3])
                    )
                _tlog(
                    f"  clang_scope={enrichment.status} "
                    f"tus={enrichment.tus_parsed}/{enrichment.tus_expected} "
                    f"scope_files={len(spec.scope.files)} "
                    f"shared={sum(1 for f in spec.scope.files if f.shared)}"
                )
            except RuntimeError:
                raise
            except Exception as exc:  # noqa: BLE001
                allow_unverified = str(
                    os.environ.get("UO_TEST_ALLOW_UNVERIFIED_SCOPE") or ""
                ).strip().lower() in {"1", "true", "yes"}
                if not allow_unverified:
                    raise RuntimeError(
                        f"SCOPE_CLANG_CLOSURE_INCOMPLETE: {str(exc)[:200]}"
                    ) from exc
                spec.scope.notes.append(f"clang_enrichment_failed: {str(exc)[:200]}")
                _tlog(f"  scope_clang_enrich failed (unverified override): {exc}")

    targets = [p for p in spec.host_targets if p.exists()]
    if not targets:
        raise RuntimeError(
            "SCOPE_CONFIRMED_HOST_TUS_MISSING: Clang scope has no host tiling TU; "
            "re-run prepare until clang_scope_status=complete"
        )
    _tlog(f"  extract targets={[p.name for p in targets]}")

    schema = parse_file(spec.tiling_key_header) if spec.tiling_key_header else None
    kernel_dims = [d.name for d in schema.dims] if schema else []

    import time as _time

    def _run_host():
        t0 = _time.perf_counter()
        out = build_host_ir(
            list(targets), ctx=ctx, op_needle=spec.op_needle, scope=spec.scope
        )
        dt = _time.perf_counter() - t0
        _tlog(
            f"{dt:7.3f}s  build_host_ir.done  controls={len(out.controls)} "
            f"writes={len(out.writes)} local_writes={len(out.local_writes)} "
            f"calls={len(out.call_sites)}"
        )
        return out

    def _run_kernel_early():
        if not with_kernel:
            return None
        t0 = _time.perf_counter()
        _tlog("kernel_ir.start")
        out = build_kernel_ir(
            spec,
            ctx,
            dimensions=kernel_dims,
            max_variants=kernel_max_variants,
        )
        dt = _time.perf_counter() - t0
        _tlog(
            f"{dt:7.3f}s{' SLOW' if dt > 180 else ''}  kernel_ir.done  "
            f"branches={len(getattr(out, 'branches', []) or [])}"
        )
        return out

    with timer.span("host||kernel", tus=len(targets)):
        if not with_kernel:
            ir = _run_host()
            kernel = None
        else:
            from uo_init.kernel_ir import (
                finish_kernel_ir_job,
                kernel_ir_isolate,
                kernel_ir_payload,
                start_kernel_ir_job,
            )

            kernel_job = None
            if kernel_ir_isolate():
                try:
                    payload = kernel_ir_payload(
                        spec,
                        ctx,
                        dimensions=kernel_dims,
                        max_variants=kernel_max_variants,
                    )
                    kernel_job = start_kernel_ir_job(payload)
                    _tlog("kernel_ir.isolate process")
                except Exception as exc:  # noqa: BLE001
                    _tlog(f"kernel_ir.isolate_fallback  reason={type(exc).__name__}")
                    kernel_job = None
            if kernel_job is not None:
                ir = _run_host()
                try:
                    t0 = _time.perf_counter()
                    kernel = finish_kernel_ir_job(*kernel_job)
                    dt = _time.perf_counter() - t0
                    _tlog(
                        f"{dt:7.3f}s  kernel_ir.done  isolate=process "
                        f"branches={len(getattr(kernel, 'branches', []) or [])}"
                    )
                except Exception as exc:  # noqa: BLE001
                    _tlog(
                        f"kernel_ir.isolate_failed  reason={type(exc).__name__}; "
                        "rebuilding in-process"
                    )
                    try:
                        kernel_job[0].kill()
                    except Exception:
                        pass
                    kernel = _run_kernel_early()
            else:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    fut_host = pool.submit(_run_host)
                    fut_kernel = pool.submit(_run_kernel_early)
                    ir = fut_host.result()
                    kernel = fut_kernel.result()
    _tlog(
        f"  host_ir controls={len(ir.controls)} writes={len(ir.writes)} "
        f"kernel_branches={len(getattr(kernel, 'branches', []) or [])}"
    )

    timing = timer.summary()
    _tlog(
        f"extract_host_bundle TOTAL {timing['total_seconds']:.1f}s  "
        f"slow={timing['slow_phases'] or 'none'}"
    )
    for row in timing["phases"]:
        _tlog(f"  summary  {row['seconds']:7.3f}s  {row['phase']}")

    return {
        "spec": spec,
        "ctx": ctx,
        "tpl_schema": schema,
        "kernel_ir": kernel,
        "host_ir": ir,
        "timing": timing,
    }
