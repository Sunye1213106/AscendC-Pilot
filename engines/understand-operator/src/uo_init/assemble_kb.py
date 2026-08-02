# -*- coding: utf-8 -*-
"""Assemble a KnowledgeBase from host analyses + optional folded kernel branches."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

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


def _as_minted(item: MintedKernelBranch | str | dict[str, Any]) -> MintedKernelBranch | None:
    if isinstance(item, MintedKernelBranch):
        return item
    if isinstance(item, dict) and item.get("id"):
        return MintedKernelBranch.from_dict(item)
    if isinstance(item, str) and item.startswith("KBR_"):
        # Legacy id-only callers: keep the node but mark partial until fold re-runs.
        return MintedKernelBranch(id=item, file="<fold>", line=0, snippet=item)
    return None


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
    notes: dict[str, Any] | None = None,
    tpl_schema=None,
    var_model=None,
    derivation=None,
    tpl_header: str = "",
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
                    # there is no `smt` attribute.
                    "smt": rec.guard,
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
                    "condition": item.condition,
                    "function": item.function,
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
    return kb


def export_operator_kb(
    kb: KnowledgeBase,
    op_dir: str | Path,
    *,
    rebuild_index: bool = True,
    write_integrity: bool = True,
) -> dict[str, Any]:
    """Write `.ascendc-pilot/uo/` under the operator tree and derived index."""
    import yaml

    uo_root = Path(op_dir) / ".ascendc-pilot" / "uo"
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
        path = uo_root / "checks" / "integrity.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(integrity, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )
        receipt["integrity"] = integrity
        receipt["ok"] = bool(receipt.get("ok")) and not invariant_errors
    return receipt


def extract_host_bundle(
    *,
    op_dir: str | Path,
    cann_root: str,
    ops_root: str | None = None,
    arch_dir: str | None = None,
    with_closure: bool = True,
) -> dict[str, Any]:
    """Host-only analyse → metrics/gap/binding (no FAG defaults).

    `with_closure=False` stops once the facts are in — the IR, the resolver,
    the variable model and the key binding — and skips the controllability
    closure over every branch in the operator. That closure is five sixths of
    the run: a second libclang parse of every translation unit, then several
    hundred branches analysed one at a time. Key-field derivation reads none
    of it, so a caller after the facts alone was waiting four and a half
    minutes for a result it then dropped.
    """
    from uo_init.branch_inventory import inventory_clang
    from uo_init.build_context import BuildContext
    from uo_init.controllability import ControllabilityBuilder, measure
    from uo_init.gaps import build_gap_report
    from uo_init.host_ir import build_host_ir
    from uo_init.op_spec import discover
    from uo_init.registry_capable import parse_enums
    from uo_init.source_resolver import SourceResolver
    from uo_init.tpl_bind import bind_from_spec, merge_literal_encode_alts
    from uo_init.tpl_dsl import parse_file
    from uo_init.variable_model import apply_platform_profile, build_variable_model
    from uo_init.platform_ini import load_platform_profile

    spec = discover(op_dir, arch_dir=arch_dir)
    ctx = BuildContext.load(
        cann_root=cann_root,
        ops_root=ops_root,
        op_dir=str(spec.op_dir),
        arch_dir=spec.arch_dir,
    )
    targets = [p for p in spec.host_targets if p.exists()]
    ir = build_host_ir(list(targets), ctx=ctx, op_needle=spec.op_needle)
    resolver = SourceResolver(host_ir=ir)
    schema = parse_file(spec.tiling_key_header) if spec.tiling_key_header else None
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
    for h in header_paths:
        key = h.resolve()
        if key in seen_headers or not h.is_file():
            continue
        seen_headers.add(key)
        text = h.read_text(encoding="utf-8", errors="replace")
        header_texts.append(text)
        enums.update(parse_enums(text))
    model = build_variable_model(
        opdef_path=spec.opdef,
        tpl_schema=schema,
        tpl_header=str(spec.tiling_key_header or ""),
        enums=enums,
        header_texts=list(header_texts) + cpp_texts,
    )
    resolver.adopt(model)
    platform_error = ""
    try:
        profile = load_platform_profile(
            cann_root,
            arch_dir=spec.arch_dir or "arch35",
            platform_sku=None,
        )
        apply_platform_profile(model, profile)
    except FileNotFoundError as exc:
        platform_error = str(exc)
    analyses: list = []
    records: list = []
    metrics = None
    gap = None
    if with_closure:
        builder = ControllabilityBuilder(
            resolver, model, side="host", op_root=str(spec.op_dir)
        )
        # Parallel TU inventory: each file is an independent libclang parse.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _inv(path: Path):
            return inventory_clang(path, ctx, op_needle=spec.op_needle).production()

        nodes: list = []
        if len(targets) <= 1:
            for t in targets:
                nodes.extend(_inv(t))
        else:
            with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
                futs = [pool.submit(_inv, t) for t in targets]
                for fut in as_completed(futs):
                    nodes.extend(fut.result())
        analyses, records = builder.build(nodes)
        metrics = measure(analyses, records)
        gap = build_gap_report(analyses)
    binding = None
    if targets and spec.tiling_key_header and spec.kernel_entry:
        try:
            # All host targets: the encode site is chosen by DECL arity and by
            # being host-derived, not by filename.
            binding = bind_from_spec(spec, targets)
            binding = merge_literal_encode_alts(binding, ir)
        except Exception as exc:  # noqa: BLE001 — surface in notes, don't abort export
            binding = None
            bind_error = str(exc)
        else:
            bind_error = ""
    else:
        bind_error = "missing host tiling / key header / kernel entry"
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
        "var_model": model,
        "tpl_header": str(spec.tiling_key_header or ""),
        # The guarded write set is what key-field derivation runs on; without
        # it every run recomputes the IR and throws it away.
        "host_ir": ir,
        "resolver": resolver,
        "platform_error": platform_error,
        "platform_profile": getattr(model, "platform_profile", None),
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
            fold_path = Path(spec.op_dir) / ".ascendc-pilot" / "uo" / "kernel" / "fold_receipt.yaml"
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
        notes=notes,
        tpl_schema=bundle.get("tpl_schema"),
        var_model=bundle.get("var_model"),
        derivation=bundle.get("host_derivation"),
        tpl_header=bundle.get("tpl_header") or "",
    )
    receipt = export_operator_kb(kb, spec.op_dir)
    receipt["source_closure"] = bundle["metrics"].source_closure
    receipt["blocker_count"] = len(bundle["gap"].blockers)
    receipt["kernel_branch_count"] = len(kbr)
    receipt["kernel_branch_ids"] = [m.id for m in kbr]
    receipt["kernel_fold"] = fold_note
    return receipt
