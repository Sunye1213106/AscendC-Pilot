# -*- coding: utf-8 -*-
"""HostIR / KernelIR extract for /uo-init (not KnowledgeBase assembly)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo_init.paths import require_architecture


def _proto_of(spec) -> Path | None:
    """The `REG_OP` prototype, which sits in `op_graph` and is a header."""
    scope = getattr(spec, "scope", None)
    if scope is None:
        return None
    from uo_init import scope_scan as sscan

    found = [p for p in scope.paths(role=sscan.ROLE_GRAPH) if p.suffix.lower() != ".cpp"]
    return found[0] if found else None


def _production_controls_from_host_ir(host_ir, targets: list[Path]) -> list:
    """PRODUCTION control nodes already walked into HostIR, plus invoke macros.

    Replaces a second ``inventory_clang`` pass over the same translation units.
    HostIR deduplicates cross-TU header controls; the old inventory summed per
    TU and double-counted shared headers.
    """
    from uo_init.branch_inventory import _invoke_nodes

    nodes = [
        n
        for n in (getattr(host_ir, "controls", None) or [])
        if getattr(n, "universe", "PRODUCTION") == "PRODUCTION"
    ]
    # Stable order for ordinal assignment downstream.
    nodes.sort(key=lambda n: (n.file, n.line, getattr(n, "column", 0), n.kind, n.id))
    # Macro dispatch sites clang expands away — same recovery as inventory_clang.
    seen_ids = {n.id for n in nodes}
    for path in targets:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n in _invoke_nodes(text, str(path).replace("\\", "/"), {}):
            if n.id not in seen_ids:
                seen_ids.add(n.id)
                nodes.append(n)
    return nodes


def _select_closure_nodes(
    host_ir,
    targets: list[Path],
    *,
    mode: str,
    max_nodes: int = 96,
) -> list:
    """Pick which control nodes pay for deep resolve under a wall-time budget.

    ``full`` — every PRODUCTION control (minutes on FAG; opt-in only).
    ``keypath`` — controls in functions that write tiling / call setters, capped.
    ``off`` — nothing.
    """
    nodes = _production_controls_from_host_ir(host_ir, targets)
    mode = (mode or "off").strip().lower()
    if mode in {"off", "none", "0", "false"}:
        return []
    if mode in {"full", "all", "true", "1"}:
        return nodes
    # keypath (default when closure is requested without "full")
    writer_fns = {
        str(getattr(w, "function", "") or "")
        for w in (getattr(host_ir, "writes", None) or [])
        if getattr(w, "function", None)
    }
    for site in getattr(host_ir, "call_sites", None) or []:
        cal = str(getattr(site, "callee", "") or "")
        if cal.startswith("set_") or "Tiling" in cal or "TilingKey" in cal:
            writer_fns.add(str(getattr(site, "caller", "") or ""))
    # Prefer branchy controls; loops are numerous and rarely TG knobs.
    ranked = [
        n
        for n in nodes
        if (n.function in writer_fns)
        and n.kind in {"if", "if_constexpr", "switch", "ternary", "guard_clause"}
    ]
    if not ranked:
        ranked = [n for n in nodes if n.function in writer_fns]
    return ranked[: max(0, int(max_nodes))]


def extract_host_bundle(
    *,
    op_dir: str | Path,
    cann_root: str,
    ops_root: str | None = None,
    arch_dir: str | None = None,
    with_closure: bool | str = False,
    with_kernel: bool = True,
    with_api: bool = True,
    closure_mode: str | None = None,
    closure_max_nodes: int = 10**9,
    kernel_max_variants: int | None = None,
) -> dict[str, Any]:
    """Host-only analyse → metrics/gap/binding (no FAG defaults).

    Library default is ``closure_mode=off`` so callers that only need HostIR /
    binding (e.g. key derivation) do not pay.  Product ``extract_host`` defaults
    to ``keypath`` under ``UO_INIT_PROFILE=fast``; use ``UO_INIT_PROFILE=full``
    / ``closure_mode=full`` for every PRODUCTION control.

    Closure modes (``closure_mode`` overrides ``with_closure``):
    - ``full``: every PRODUCTION control (opt-in complete path).
    - ``keypath``: tiling-writer functions only (capped by ``closure_max_nodes``).
    - ``off``: skip controllability.

    Kernel IR walks in parallel with ``build_host_ir`` (both release the GIL in
    libclang).  ``kernel_max_variants`` caps dtype walks on the fast path.
    """
    from concurrent.futures import ThreadPoolExecutor

    from uo_init.api_contract import extract_api_contract
    from uo_init.build_context import BuildContext
    from uo_init.controllability import ControllabilityBuilder, ClosureMetrics, measure
    from uo_init.decl_facts import extract_decl_facts
    from uo_init.gaps import GapReport, build_gap_report
    from uo_init.host_ir import build_host_ir
    from uo_init.kernel_ir import build_kernel_ir
    from uo_init.op_spec import discover
    from uo_init.registry_capable import parse_enums
    from uo_init.source_resolver import SourceResolver
    from uo_init.tpl_bind import bind_from_spec, merge_literal_encode_alts
    from uo_init.tpl_dsl import parse_file
    from uo_init.variable_model import apply_platform_profile, build_variable_model
    from uo_init.platform_ini import load_platform_profile

    if closure_mode is not None:
        mode = str(closure_mode).strip().lower()
    elif isinstance(with_closure, str):
        mode = with_closure.strip().lower() or "off"
    elif with_closure:
        mode = "full"
    else:
        mode = "off"
    if mode in {"true", "1", "yes"}:
        mode = "full"
    if mode in {"false", "0", "no", "none"}:
        mode = "off"

    from uo_init.timing import PhaseTimer, log as _tlog

    timer = PhaseTimer()
    _tlog(
        f"extract_host_bundle start  closure_mode={mode} "
        f"with_kernel={with_kernel} with_api={with_api} "
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

    # Authoritative Clang include closure replaces regex shared discovery.
    # Prepare already wrote clang-complete scope_set.yaml — reuse it on extract.
    # Do not re-discover / glob a second TU set once the Clang set exists.
    with timer.span("scope_clang_enrich"):
        import os

        from uo_init import scope_scan as sscan
        from uo_init.op_spec import _targets_from_scope

        reused = sscan.load_prepared_scope(spec.op_dir, spec.arch_dir)
        if reused is not None:
            spec.scope = reused
            _targets_from_scope(spec)
            # Prefer Clang-confirmed kernel entry; reject foreign-arch fallbacks.
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

    # Host extract walks only Clang-confirmed host tiling TUs (or layout TUs
    # that survived enrich as clang_tu / clang_include).
    targets = [p for p in spec.host_targets if p.exists()]
    if not targets:
        raise RuntimeError(
            "SCOPE_CONFIRMED_HOST_TUS_MISSING: Clang scope has no host tiling TU; "
            "re-run prepare until clang_scope_status=complete"
        )
    _tlog(f"  extract targets={[p.name for p in targets]}")

    # Schema is cheap text parse; needed for kernel dimension tags before host IR.
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

    # libclang releases the GIL — overlap host TU walks with kernel dtype walk.
    with timer.span("host||kernel", tus=len(targets)):
        if with_kernel:
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_host = pool.submit(_run_host)
                fut_kernel = pool.submit(_run_kernel_early)
                ir = fut_host.result()
                kernel = fut_kernel.result()
        else:
            ir = _run_host()
            kernel = None
    _tlog(
        f"  host_ir controls={len(ir.controls)} writes={len(ir.writes)} "
        f"kernel_branches={len(getattr(kernel, 'branches', []) or [])}"
    )

    with timer.span("var_model+platform"):
        resolver = SourceResolver(host_ir=ir)
        enums: dict = {}
        header_texts: list[str] = []
        header_paths: list[Path] = []
        for h in list((spec.host_root / (spec.arch_dir or ".")).glob("*.h")) + list(
            spec.host_root.glob("*.h")
        ):
            header_paths.append(h)
        tiling_host = spec.host_root / "op_tiling"
        if tiling_host.is_dir():
            header_paths.extend(tiling_host.glob("*.h"))
            header_paths.extend(tiling_host.glob("*.hpp"))
        # Kernel tiling-data headers often hold shared constexprs (e.g. prefix lengths)
        # referenced from host guards.
        kernel_arch = spec.op_dir / "op_kernel" / (spec.arch_dir or ".")
        if kernel_arch.is_dir():
            header_paths.extend(kernel_arch.glob("*.h"))
        # Shared tiling enums (DtypeEnum / OptionEnum / …) live under the ops
        # tree's common include, not the operator's own headers. Without them
        # named-constant fold cannot map ENABLE / FLOAT32 onto TPL domains.
        ops = Path(ctx.ops_root) if ctx.ops_root else None
        if ops and ops.is_dir():
            common_host = ops / "common" / "include" / "op_host"
            if common_host.is_dir():
                header_paths.extend(common_host.glob("*.h"))
        # Host .cpp also carries constexprs used as key literals (e.g. TILING_KEY_1
        # on the empty-tensor path). Enums are rare there; only the constexpr pass
        # needs the text.
        cpp_texts: list[str] = []
        for cpp in list((spec.host_root / (spec.arch_dir or ".")).glob("*.cpp")) + list(
            spec.host_root.glob("*.cpp")
        ):
            if cpp.is_file():
                cpp_texts.append(cpp.read_text(encoding="utf-8", errors="replace"))
        seen_headers: set[Path] = set()
        text_cache: dict[str, str] = {}
        for h in header_paths:
            key = h.resolve()
            if key in seen_headers or not h.is_file():
                continue
            seen_headers.add(key)
            text = h.read_text(encoding="utf-8", errors="replace")
            header_texts.append(text)
            text_cache[str(key).replace("\\", "/")] = text
            enums.update(parse_enums(text))
        if spec.opdef and spec.opdef.is_file():
            opdef_key = str(spec.opdef.resolve()).replace("\\", "/")
            if opdef_key not in text_cache:
                text_cache[opdef_key] = spec.opdef.read_text(
                    encoding="utf-8", errors="replace"
                )
        model = build_variable_model(
            opdef_path=spec.opdef,
            tpl_schema=schema,
            tpl_header=str(spec.tiling_key_header or ""),
            enums=enums,
            header_texts=list(header_texts) + cpp_texts,
            text_cache=text_cache,
        )
        resolver.adopt(model)
        platform_error = ""
        try:
            profile = load_platform_profile(
                cann_root,
                arch_dir=require_architecture(spec.arch_dir),
                platform_sku=None,
            )
            apply_platform_profile(model, profile)
        except FileNotFoundError as exc:
            platform_error = str(exc)

    # Remaining clang-light / text legs. Do NOT overlap full Python
    # controllability with clang — GIL contention made FAG slower before.
    def _run_api():
        t0 = _time.perf_counter()
        _tlog("api_contract.start")
        local_facts = extract_decl_facts(spec.opdef, _proto_of(spec))
        t_facts = _time.perf_counter() - t0
        if not with_api:
            # Fast cold path: keep opdef facts, skip the clang API TU walk.
            class _EmptyContract:
                ir = None
                premises: list = []

            dt = _time.perf_counter() - t0
            _tlog(
                f"{dt:7.3f}s  api_contract.done  facts={t_facts:.3f}s "
                f"contract=skipped premises=0"
            )
            return local_facts, _EmptyContract(), None
        t1 = _time.perf_counter()
        local_contract = extract_api_contract(spec, ctx, local_facts)
        t_contract = _time.perf_counter() - t1
        local_resolver = None
        if local_contract.ir is not None:
            local_resolver = SourceResolver(host_ir=local_contract.ir)
            local_resolver.adopt(model)
        dt = _time.perf_counter() - t0
        _tlog(
            f"{dt:7.3f}s{' SLOW' if dt > 180 else ''}  api_contract.done  "
            f"facts={t_facts:.3f}s contract={t_contract:.3f}s "
            f"premises={len(getattr(local_contract, 'premises', []) or [])}"
        )
        return local_facts, local_contract, local_resolver

    def _run_bind():
        if not (targets and spec.tiling_key_header and spec.kernel_entry):
            return None, "missing host tiling / key header / kernel entry"
        t0 = _time.perf_counter()
        try:
            local_binding = bind_from_spec(spec, targets)
            local_binding = merge_literal_encode_alts(local_binding, ir)
            dt = _time.perf_counter() - t0
            _tlog(f"{dt:7.3f}s  bind.done  bindings={len(local_binding.bindings)}")
            return local_binding, ""
        except Exception as exc:  # noqa: BLE001
            dt = _time.perf_counter() - t0
            _tlog(f"{dt:7.3f}s  bind.fail  err={exc}")
            return None, str(exc)

    with timer.span("api||bind"):
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_api = pool.submit(_run_api)
            fut_bind = pool.submit(_run_bind)
            facts, contract, api_resolver = fut_api.result()
            binding, bind_error = fut_bind.result()
    _tlog(
        f"  api_premises={len(getattr(contract, 'premises', []) or [])} "
        f"kernel_branches={len(getattr(kernel, 'branches', []) or [])} "
        f"bindings={len(binding.bindings) if binding else 0}"
    )

    analyses: list = []
    records: list = []
    metrics: ClosureMetrics | None = None
    gap: GapReport | None = None
    closure_selected = 0
    if mode != "off":
        with timer.span("controllability", mode=mode):
            builder = ControllabilityBuilder(
                resolver, model, side="host", op_root=str(spec.op_dir)
            )
            nodes = _select_closure_nodes(
                ir, targets, mode=mode, max_nodes=closure_max_nodes
            )
            closure_selected = len(nodes)
            _tlog(f"  closure_nodes={closure_selected} mode={mode}")
            analyses, records = builder.build(nodes)
            metrics = measure(analyses, records)
            gap = build_gap_report(analyses)
        _tlog(
            f"  closure={metrics.source_closure:.3f} blockers={len(gap.blockers)} "
            f"core_cache={len(builder._core_cache)}"
        )
    else:
        metrics = ClosureMetrics()
        gap = GapReport()
        _tlog("  controllability skipped (mode=off)")

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
        "analyses": analyses,
        "records": records,
        "metrics": metrics,
        "gap": gap,
        "binding": binding,
        "bind_error": bind_error,
        "tpl_schema": schema,
        "decl_facts": facts,
        "api_contract": contract,
        "api_resolver": api_resolver,
        "kernel_ir": kernel,
        "var_model": model,
        "tpl_header": str(spec.tiling_key_header or ""),
        # The guarded write set is what key-field derivation runs on; without
        # it every run recomputes the IR and throws it away.
        "host_ir": ir,
        "resolver": resolver,
        "platform_error": platform_error,
        "platform_profile": getattr(model, "platform_profile", None),
        "closure_mode": mode,
        "closure_selected": closure_selected,
        "timing": timing,
    }

