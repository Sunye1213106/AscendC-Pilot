# -*- coding: utf-8 -*-
"""Assemble a KnowledgeBase from host analyses + optional folded kernel branches."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from uo_init.paths import require_architecture
from uo_init.controllability import BranchRecord, ClosureMetrics, NodeAnalysis
from uo_init.gaps import GapReport
from uo_init.harness import MintedKernelBranch
from uo_init.kb_export import export_kb
from uo_init.kb_model import (
    STATUS_EXTRACTED,
    STATUS_UNRESOLVED,
    Evidence,
    KnowledgeBase,
    Node,
)
from uo_init.tpl_bind import BindingResult


def _arch_scoped_uo_root(op_dir: str | Path, arch_dir: str | None) -> Path:
    """Return the durable architecture-scoped UO artifact directory."""

    try:
        from ascendc_pilot.paths import uo_root

        return uo_root(Path(op_dir), arch=arch_dir)
    except Exception:
        arch = require_architecture(arch_dir)
        return Path(op_dir) / ".ascendc-pilot" / arch / "uo"


def _as_minted(item: MintedKernelBranch | str | dict[str, Any]) -> MintedKernelBranch | None:
    if isinstance(item, MintedKernelBranch):
        return item
    if isinstance(item, dict) and item.get("id"):
        return MintedKernelBranch.from_dict(item)
    if isinstance(item, str) and item.startswith("KBR_"):
        # Legacy id-only callers: keep the node but mark partial until fold re-runs.
        return MintedKernelBranch(id=item, file="<fold>", line=0, snippet=item)
    return None


def _add_kernel_ir(
    kb: KnowledgeBase,
    ir,
    *,
    op_root: str = "",
    dimensions: list[str] | None = None,
) -> None:
    """Land the pre-instantiation `if constexpr` branches and what decides them.

    Must run after the key space is materialized: the dimension nodes these
    edges point at are created there, and a dangling edge fails
    `check_invariants`.
    """
    from uo_init.ids import named_id

    ir.mint_ids(op_root)
    for b in ir.branches:
        if not b.id:
            continue
        ev = Evidence.at(b.file, b.line, snippet=(b.condition or b.id)[:200])
        kb.add_node(
            Node(
                id=b.id,
                kind="KernelBranch",
                layer="kernel",
                status=STATUS_EXTRACTED,
                confidence=1.0,
                evidence=[ev],
                data={
                    "side": "kernel",
                    "ctrl_kind": "if_constexpr",
                    "stage": "constexpr",
                    "condition": b.condition,
                    "function": b.function,
                    "dimensions": list(b.dimensions),
                    "derived": list(b.derived),
                    "symbols": list(b.symbols),
                    # Not `variants`: the TG branch contract already uses that
                    # name for guard polarity. These are dtype macro values.
                    "dtype_variants": list(b.variants),
                },
            )
        )
        for dim in (*b.dimensions, *b.derived):
            kid = named_id("TilingKeyDim", dim)
            if kid not in kb.nodes:
                continue
            kb.link(
                "controls",
                kid,
                b.id,
                data={
                    "exactness": "exact" if dim in b.dimensions else "derived",
                },
            )
    kb.notes["kernel_ir"] = {
        "variants": list(ir.variants),
        "branch_count": len(ir.branches),
        "by_dimension": ir.by_dimension(),
        "variant_only": len(ir.variant_only()),
        # Reported, never guessed at: a dimension with no branch either decides
        # nothing at compile time or was renamed on the way into the inner
        # template. Matching on name similarity would attach branches to the
        # wrong dimension, which is worse than a missing one.
        "silent_dimensions": ir.silent_dimensions(list(dimensions or ())),
        "unmapped_symbols": [
            {"symbol": sym, "count": n} for sym, n in ir.unmapped_symbols(limit=50)
        ],
        "notes": list(ir.notes),
    }


def assemble_kb(
    *,
    op_name: str,
    architecture: str,
    analyses: list[NodeAnalysis],
    records: list[BranchRecord],
    metrics: ClosureMetrics,
    gap: GapReport,
    binding: BindingResult | None = None,
    kernel_branches: Iterable[MintedKernelBranch | str | dict[str, Any]] = (),
    kernel_branch_ids: Iterable[str] | None = None,
    kernel_ir=None,
    op_root: str = "",
    notes: dict[str, Any] | None = None,
    tpl_schema=None,
    var_model=None,
    derivation=None,
    tpl_header: str = "",
    tiling_data_ir=None,
    host_ir=None,
    op_spec=None,
) -> KnowledgeBase:
    """Build an in-memory KB ready for :func:`export_kb`."""
    kb = KnowledgeBase(op_name=op_name, architecture=architecture)
    for a in analyses:
        ev = a.evidence()
        kb.add_node(
            Node(
                id=a.branch_id,
                kind="HostBranch",
                status=STATUS_EXTRACTED if a.closed else STATUS_UNRESOLVED,
                confidence=1.0 if a.closed else 0.0,
                evidence=[ev],
                data={
                    "ctrl_kind": a.node.kind,
                    "condition": a.node.condition or "",
                    "function": a.node.function,
                    "roots": list(a.roots),
                    "closed": a.closed,
                },
            )
        )
    for rec in records:
        ev = Evidence.at(rec.file, rec.line, snippet=rec.condition[:200])
        kb.add_node(
            Node(
                id=rec.predicate_id,
                kind="Predicate",
                status=STATUS_EXTRACTED if rec.status == "extracted" else STATUS_UNRESOLVED,
                evidence=[ev],
                data={
                    "branch_id": rec.branch_id,
                    "target_value": rec.target_value,
                    "source_roots": list(rec.source_roots),
                    "input_controllable": rec.input_controllable,
                    "side": getattr(rec, "side", "host"),
                    # BranchRecord carries the normalized predicate in `guard`;
                    # there is no `expr` attribute.
                    "expr": rec.guard,
                    "path_condition": rec.path_condition,
                },
            )
        )
        kb.link("HAS_PREDICATE", rec.branch_id, rec.predicate_id)
    minted: list[MintedKernelBranch] = []
    for item in kernel_branches:
        row = _as_minted(item)
        if row is not None:
            minted.append(row)
    if kernel_branch_ids:
        for bid in kernel_branch_ids:
            if any(m.id == bid for m in minted):
                continue
            row = _as_minted(bid)
            if row is not None:
                minted.append(row)
    for item in minted:
        snippet = item.snippet or item.condition or item.id
        has_loc = bool(item.file and item.file != "<fold>" and item.line > 0)
        ev = Evidence.at(item.file or "<fold>", item.line or 0, snippet=snippet[:200])
        kb.add_node(
            Node(
                id=item.id,
                kind="KernelBranch",
                status=STATUS_EXTRACTED if has_loc else STATUS_UNRESOLVED,
                confidence=1.0 if has_loc else 0.0,
                evidence=[ev],
                data={
                    "side": "kernel",
                    "ctrl_kind": item.kind,
                    "stage": item.stage,
                    "condition": item.condition,
                    "function": item.function,
                    "dimensions": list(item.dimensions),
                    "derived": list(item.derived),
                    "symbols": list(item.symbols),
                    "dtype_variants": list(item.dtype_variants),
                },
            )
        )
    if binding is not None:
        kb.notes["tpl_bind"] = [
            {
                "index": b.index,
                "decl": b.decl.name,
                "host_expr": b.host_expr,
                "nttp": b.nttp_name,
            }
            for b in binding.bindings
        ]
    for b in gap.blockers:
        kb.add_blocker(b)
    kb.notes["quality"] = metrics.to_dict()
    kb.notes["gap"] = gap.to_dict()
    if notes:
        kb.notes.update(notes)
    if tpl_schema is not None:
        from uo_init.materialize_tiling import materialize_into_kb

        materialize_into_kb(
            kb,
            schema=tpl_schema,
            var_model=var_model,
            binding=binding,
            derivation=derivation,
            header_path=tpl_header,
        )
    if kernel_ir is None and minted:
        from uo_init.ids import named_id

        for item in minted:
            for dim in (*item.dimensions, *item.derived):
                kid = named_id("TilingKeyDim", dim)
                if kid not in kb.nodes:
                    continue
                kb.link(
                    "controls",
                    kid,
                    item.id,
                    data={
                        "exactness": (
                            "exact" if dim in item.dimensions else "derived"
                        ),
                    },
                )
    if kernel_ir is not None:
        _add_kernel_ir(
            kb,
            kernel_ir,
            op_root=op_root,
            dimensions=(
                [d.name for d in tpl_schema.dims] if tpl_schema is not None else None
            ),
        )
    # TilingData + call graph: join declared fields to host writers / kernel
    # readers so AI can answer "what does this field affect" from the KB.
    from uo_init.tiling_data_ir import (
        build_tiling_data_ir,
        materialize_call_graph,
        materialize_tiling_data,
    )

    td_ir = tiling_data_ir
    if td_ir is None and op_spec is not None:
        td_ir = build_tiling_data_ir(op_spec, host_ir, op_root=op_root)
    if td_ir is not None:
        materialize_tiling_data(kb, td_ir, op_root=op_root)
    if host_ir is not None:
        materialize_call_graph(kb, host_ir, op_root=op_root)
    # Named constants already mined into var_model — promote any that are not
    # yet nodes so constexpr / #define / platform locks are queryable.
    if var_model is not None:
        _add_named_constants(kb, var_model, op_root=op_root)
    return kb


def _add_named_constants(kb: KnowledgeBase, var_model, *, op_root: str = "") -> None:
    """Ensure ``var_model.named_constants`` appear as Variable nodes."""
    from uo_init.ids import named_id

    del op_root
    constants = getattr(var_model, "named_constants", None) or {}
    added = 0
    for name, value in sorted(constants.items(), key=lambda kv: str(kv[0])):
        # Skip scoped duplicates like ge::DT_FLOAT when DT_FLOAT already exists.
        short = str(name).split("::")[-1]
        vid = named_id("Variable", f"CONST_{short}")
        if vid in kb.nodes:
            # Keep the first value; still record alias in data if different name.
            continue
        ev = Evidence.at("<named_constant>", 0, snippet=f"{name}={value}"[:200])
        kb.add_node(
            Node(
                id=vid,
                kind="Variable",
                name=short,
                layer="tiling",
                status=STATUS_EXTRACTED,
                confidence=1.0,
                evidence=[ev],
                data={
                    "value_type": "named_constant",
                    "origin": "variable_model",
                    "value": value,
                    "symbol": name,
                },
            )
        )
        added += 1
    kb.notes.setdefault("named_constants", {})
    kb.notes["named_constants"] = {
        "count": added,
        "source_count": len(constants),
    }


def export_operator_kb(
    kb: KnowledgeBase,
    op_dir: str | Path,
    *,
    uo_root_override: str | Path | None = None,
    rebuild_index: bool = True,
    write_integrity: bool = True,
) -> dict[str, Any]:
    """Write UO KB artifacts and derived index.

    ``uo_root_override`` is the production path for architecture-scoped runs
    (``.ascendc-pilot/<arch>/uo``).  The historical default is preserved for
    older direct callers and unit tests that still expect ``.ascendc-pilot/uo``.
    """
    import yaml

    uo_root = (
        Path(uo_root_override)
        if uo_root_override is not None
        else Path(op_dir) / ".ascendc-pilot" / "uo"
    )
    receipt = export_kb(kb, uo_root)
    invariant_errors = kb.check_invariants()
    receipt["invariant_errors"] = invariant_errors
    if rebuild_index:
        from uo_init.kb_index import rebuild_index as _rebuild

        idx = _rebuild(uo_root)
        receipt["index"] = {
            "database": idx.get("database"),
            "graph_fingerprint": idx.get("graph_fingerprint"),
        }
    if write_integrity:
        integrity = {
            "version": 1,
            "status": "pass" if not invariant_errors else "fail",
            "ok": not invariant_errors,
            "blocker_count": len(kb.blockers),
            "source_closure": (kb.notes.get("quality") or {}).get("source_closure"),
            "errors": list(invariant_errors),
        }
        db = uo_root / "indexes" / "kb_graph.sqlite"
        if db.is_file():
            try:
                import json as _json
                import sqlite3

                from uo_init.kb_index import set_meta_values

                conn = sqlite3.connect(str(db))
                try:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS view_blob("
                        "name TEXT PRIMARY KEY, schema_id TEXT, data TEXT NOT NULL)"
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO view_blob(name, schema_id, data) "
                        "VALUES(?,?,?)",
                        (
                            "checks/integrity.yaml",
                            "",
                            _json.dumps(
                                integrity,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
                set_meta_values(
                    db,
                    {
                        "integrity_status": integrity["status"],
                        "integrity_ok": integrity["ok"],
                    },
                )
            except Exception:  # noqa: BLE001
                pass
        from uo_init.kb_export import yaml_export_enabled

        if yaml_export_enabled():
            path = uo_root / "checks" / "integrity.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                yaml.safe_dump(integrity, allow_unicode=True, sort_keys=True),
                encoding="utf-8",
            )
        receipt["integrity"] = integrity
        receipt["ok"] = bool(receipt.get("ok")) and not invariant_errors
    return receipt


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
                spec.kernel_entry = spec.kernel_targets[0]
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
                    spec.kernel_entry = spec.kernel_targets[0]
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


def export_operator_closure(
    *,
    op_dir: str | Path,
    cann_root: str,
    ops_root: str | None = None,
    arch_dir: str | None = None,
    fold_kernel: bool = True,
    harness_limit: int | None = None,
    harness_workers: int = 4,
    work_dir: str | Path | None = None,
    clang_exe: str | None = None,
) -> dict[str, Any]:
    """Host analyse (+ optional pairwise kernel fold) → `export_kb` under op dir.

    Returns a receipt with quality metrics and artifact paths. Kernel fold is
    skipped when ``fold_kernel=False`` or clang/kernel entry is unavailable.
    """
    import tempfile

    from uo_init.harness import (
        build_harness_jobs,
        collect_folded_kernel_branches,
        find_clang,
    )

    bundle = extract_host_bundle(
        op_dir=op_dir,
        cann_root=cann_root,
        ops_root=ops_root,
        arch_dir=arch_dir,
        with_closure=True,
    )
    spec = bundle["spec"]
    kbr: list[MintedKernelBranch] = []
    fold_note = ""
    if fold_kernel and spec.tiling_key_header and spec.kernel_entry:
        exe = find_clang(clang_exe)
        if exe is None:
            fold_note = "clang driver missing; skipped kernel fold"
        else:
            jobs = build_harness_jobs(
                spec.tiling_key_header,
                entry_source=spec.kernel_entry,
                entry_name=spec.op_snake,
                limit=harness_limit,
            )
            wd = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="uo_fold_"))
            kbr = collect_folded_kernel_branches(
                jobs,
                bundle["ctx"],
                entry=spec.op_snake,
                work_dir=wd,
                op_root=str(spec.op_dir),
                clang_exe=exe,
                workers=harness_workers,
                logical_file=str(spec.kernel_entry).replace("\\", "/"),
            )
            fold_note = f"folded {len(jobs)} harness jobs → {len(kbr)} KBR"
            uo_root = _arch_scoped_uo_root(spec.op_dir, spec.arch_dir or arch_dir)
            fold_path = uo_root / "kernel" / "fold_receipt.yaml"
            fold_path.parent.mkdir(parents=True, exist_ok=True)
            import yaml as _yaml

            fold_path.write_text(
                _yaml.safe_dump(
                    {
                        "ok": True,
                        "jobs": len(jobs),
                        "kernel_branch_count": len(kbr),
                        "kernel_branch_ids": [m.id for m in kbr],
                        "kernel_branches": [m.to_dict() for m in kbr],
                    },
                    allow_unicode=True,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
    elif fold_kernel:
        fold_note = "missing tiling_key_header or kernel_entry; skipped fold"

    notes: dict[str, Any] = {"kernel_fold": fold_note}
    if bundle["bind_error"]:
        notes["tpl_bind_error"] = bundle["bind_error"]
    kb = assemble_kb(
        op_name=spec.op_name,
        architecture=spec.arch_dir or "",
        analyses=bundle["analyses"],
        records=bundle["records"],
        metrics=bundle["metrics"],
        gap=bundle["gap"],
        binding=bundle["binding"],
        kernel_branches=kbr,
        kernel_ir=bundle.get("kernel_ir"),
        op_root=str(spec.op_dir or ""),
        notes=notes,
        tpl_schema=bundle.get("tpl_schema"),
        var_model=bundle.get("var_model"),
        derivation=bundle.get("host_derivation"),
        tpl_header=bundle.get("tpl_header") or "",
        host_ir=bundle.get("host_ir"),
        op_spec=spec,
    )
    receipt = export_operator_kb(
        kb,
        spec.op_dir,
        uo_root_override=_arch_scoped_uo_root(spec.op_dir, spec.arch_dir or arch_dir),
    )
    receipt["source_closure"] = bundle["metrics"].source_closure
    receipt["blocker_count"] = len(bundle["gap"].blockers)
    receipt["kernel_branch_count"] = len(kbr)
    receipt["kernel_branch_ids"] = [m.id for m in kbr]
    receipt["kernel_fold"] = fold_note
    return receipt
