# -*- coding: utf-8 -*-
"""Pilot Action engines for the clang-based uo-init workflow.

Each entrypoint has signature ``fn(project_root, payload) -> dict`` with an
``ok`` field.  Engines write under ``.ascendc-pilot/uo/`` only.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Default CANN tree used by local regression; override via payload / env.
_DEFAULT_CANN = r"d:\PR-review\_cann\pkg"


def _uo_root(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / ".ascendc-pilot" / "uo"


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )


def _quote_unquoted_snippets(text: str) -> str:
    """LLM proposals often leave ``snippet: !foo && bar`` unquoted; quote them."""
    import re

    def _fix(m: re.Match[str]) -> str:
        indent, val = m.group(1), m.group(2)
        if not val or val[:1] in "\"'|[{":
            return m.group(0)
        if not any(ch in val for ch in "!&*:{}[],"):
            return m.group(0)
        esc = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'{indent}snippet: "{esc}"'

    return re.sub(r"^([ \t]*)snippet: (.+)$", _fix, text, flags=re.M)


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        data = yaml.safe_load(_quote_unquoted_snippets(text)) or {}
    return data if isinstance(data, dict) else {}


def _ctx(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})


def _cann_root(ctx: dict[str, Any]) -> str:
    return str(
        ctx.get("cann_root")
        or os.environ.get("ASCEND_CANN_PACKAGE_PATH")
        or os.environ.get("CANN_ROOT")
        or _DEFAULT_CANN
    )


def _ops_root(ctx: dict[str, Any], project_root: Path) -> str | None:
    raw = ctx.get("ops_root")
    if raw:
        return str(raw)
    # Typical layout: …/ops-transformer/attention/<op>
    parent = project_root.parent.parent
    return str(parent) if parent.is_dir() else None


def _run_dir(uo: Path, ctx: dict[str, Any]) -> Path:
    run_id = str(ctx.get("run_id") or "default").strip() or "default"
    d = uo / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def prepare_layout(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Discover operator layout and seed the contract KB skeleton.

    Resets ``.ascendc-pilot/uo/`` to the allowed prepare layout, seeds OPTIONAL
    layers as ``status: not_extracted``, and writes manifest / operator /
    layout_receipt.
    """
    from uo_init.op_spec import discover

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    run_id = str(ctx.get("run_id") or "").strip()
    if not run_id:
        return {
            "ok": False,
            "engine": "prepare_layout",
            "error": "run_id_required",
            "message_zh": "prepare_layout 需要 Pilot state.run_id",
        }
    try:
        spec = discover(root, arch_dir=ctx.get("arch_dir"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "prepare_layout", "error": str(exc)[:400]}

    uo = _uo_root(root)
    scrub = _reset_uo_skeleton(uo, run_id=run_id, keep_other_runs=bool(ctx.get("keep_other_runs")))

    manifest = {
        "version": 1,
        "status": "prepared",
        "authority": "yaml",
        "derived_index": "indexes/kb_graph.sqlite",
        "op_name": spec.op_name,
        "architecture": spec.arch_dir,
        "schema": "kb_schema-v1",
        "run_id": run_id,
        "source": "uo_init.pilot_engines.prepare_layout",
        "workflow": "uo-init",
        "contract": "clang-layered-kb",
    }
    operator = {
        "version": 1,
        "status": "prepared",
        "op_name": spec.op_name,
        "op_snake": spec.op_snake,
        "architecture": spec.arch_dir,
        "op_spec": spec.to_dict(),
        "ambiguities": list(spec.ambiguities),
    }
    _dump(uo / "manifest.yaml", manifest)
    _dump(uo / "operator.yaml", operator)
    scope = uo / "runs" / run_id / "scope"
    _dump(
        scope / "layout_receipt.yaml",
        {
            "ok": True,
            "op_name": spec.op_name,
            "run_id": run_id,
            "schema": "kb_schema-v1",
            "scrubbed": scrub,
        },
    )
    return {
        "ok": True,
        "engine": "prepare_layout",
        "op_name": spec.op_name,
        "run_id": run_id,
        "manifest": (uo / "manifest.yaml").as_posix(),
        "ambiguous": bool(spec.ambiguities),
        "scrubbed_paths": scrub.get("removed") or [],
        "layout_reset": bool(scrub.get("removed")),
    }


# New-contract product roots under uo/.
# Empty product dirs (ir/checks/…) are created on demand by export — prepare
# only seeds meta + declared-optional stubs + the current run scope.
_UO_SEED_DIRS = (
    "tiling",
    "kernel",
    "flow",
    "summary",
    "runs",
)

_DISALLOWED_TOP_DIRS = (
    "analysis",
    "cbm",
    "diff",
    "docs_cache",
    "test",
    "generated",
    "ledger",
)

# Optional layers seeded as declared-missing so TG intake does not treat them
# as "file absent by accident".
_NOT_EXTRACTED_SEEDS = (
    "tiling/data_model.yaml",
    "kernel/pipeline.yaml",
    "kernel/resources.yaml",
    "flow/golden_model.yaml",
    "flow/numerical_model.yaml",
)

# Created by extract/export; prepare must not leave them around.
_DEFER_UNTIL_EXPORT = (
    "ir",
    "checks",
    "cross_layer",
    "indexes",
    "review",
)


def _reset_uo_skeleton(uo: Path, *, run_id: str, keep_other_runs: bool = False) -> dict[str, Any]:
    """Reset uo/ to the prepare-allowed skeleton and seed OPTIONAL stubs."""
    import shutil

    removed: list[str] = []
    uo.mkdir(parents=True, exist_ok=True)

    for name in _DISALLOWED_TOP_DIRS:
        path = uo / name
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(name)

    # Product dirs created by extract/export — remove at prepare so the tree
    # only contains what this Action is allowed to seed.
    for name in _DEFER_UNTIL_EXPORT:
        path = uo / name
        if path.exists():
            shutil.rmtree(path)
            removed.append(name)

    for name in _UO_SEED_DIRS:
        path = uo / name
        if name == "runs":
            path.mkdir(parents=True, exist_ok=True)
            if not keep_other_runs:
                for child in list(path.iterdir()):
                    if child.name == run_id:
                        continue
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    removed.append(f"runs/{child.name}")
            (path / run_id / "scope").mkdir(parents=True, exist_ok=True)
            continue
        path.mkdir(parents=True, exist_ok=True)

    keep_top = set(_UO_SEED_DIRS) | {"manifest.yaml", "operator.yaml", "quality.yaml"}
    for child in list(uo.iterdir()):
        if child.name in keep_top:
            if child.name == "quality.yaml" and child.is_file():
                child.unlink()
                removed.append("quality.yaml")
            continue
        if child.name in _DISALLOWED_TOP_DIRS or child.name in _DEFER_UNTIL_EXPORT:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed.append(child.name)

    stub = {
        "version": 1,
        "status": "not_extracted",
        "nodes": [],
        "edges": [],
        "note": "declared missing by prepare_layout (clang uo-init contract)",
    }
    for rel in _NOT_EXTRACTED_SEEDS:
        _dump(uo / rel, stub)

    return {"removed": sorted(set(removed)), "seeded_not_extracted": list(_NOT_EXTRACTED_SEEDS)}


def scope_scan(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """List host/kernel candidates and probe libclang diagnostics."""
    from uo_init.build_context import BuildContext
    from uo_init.clang_tu import parse_path
    from uo_init.op_spec import discover

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    uo = _uo_root(root)
    run = _run_dir(uo, ctx)
    try:
        spec = discover(root, arch_dir=ctx.get("arch_dir"))
        cann = _cann_root(ctx)
        bctx = BuildContext.load(
            cann_root=cann,
            ops_root=_ops_root(ctx, root),
            op_dir=str(spec.op_dir),
            arch_dir=spec.arch_dir,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "scope_scan", "error": str(exc)[:400]}

    hosts = [p for p in spec.host_targets if p.exists()]
    kernel = spec.kernel_entry if spec.kernel_entry and spec.kernel_entry.exists() else None
    probes: list[dict[str, Any]] = []
    host_errors = 0
    kernel_errors = 0
    for path in hosts[:3]:  # bound: probe cost; full parse happens in extract
        try:
            res = parse_path(str(path), bctx.host_args())
            errs = res.errors_in_paths([spec.op_needle]) if spec.op_needle else res.error_count
        except Exception as exc:  # noqa: BLE001
            probes.append({"file": path.as_posix(), "error": str(exc)[:200]})
            continue
        host_errors += max(errs, 0)
        probes.append({"file": path.as_posix(), "errors": errs, "side": "host"})
    if kernel is not None:
        try:
            res = parse_path(str(kernel), bctx.kernel_args(dtype_variant="DT_FLOAT16"))
            # Kernel preamble noise is expected; only count op-owned paths.
            kernel_errors = res.errors_in_paths([spec.op_needle]) if spec.op_needle else 0
            probes.append(
                {
                    "file": kernel.as_posix(),
                    "errors": kernel_errors,
                    "side": "kernel",
                    "raw_error_count": res.error_count,
                }
            )
        except Exception as exc:  # noqa: BLE001
            probes.append({"file": kernel.as_posix(), "error": str(exc)[:200], "side": "kernel"})
            kernel_errors = -1

    candidate = {
        "version": 1,
        "status": "extracted",
        "op_name": spec.op_name,
        "arch_dir": spec.arch_dir,
        "available_archs": list(spec.available_archs),
        "host_targets": [p.as_posix() for p in hosts],
        "kernel_entry": kernel.as_posix() if kernel else "",
        "tiling_key_header": (
            spec.tiling_key_header.as_posix() if spec.tiling_key_header else ""
        ),
        "ambiguities": list(spec.ambiguities),
        "probes": probes,
        "host_probe_errors": host_errors,
        "kernel_probe_errors": kernel_errors,
        "probe_clean": host_errors == 0 and kernel_errors == 0,
    }
    out = run / "scope" / "candidates.yaml"
    _dump(out, candidate)
    _dump(uo / "summary" / "scope_candidates.yaml", candidate)
    return {
        "ok": True,
        "engine": "scope_scan",
        "probe_clean": candidate["probe_clean"],
        "ambiguous": bool(spec.ambiguities),
        "candidates": out.as_posix(),
        "host_probe_errors": host_errors,
        "kernel_probe_errors": kernel_errors,
    }


def scope_confirm(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Auto-confirm when unambiguous and probe-clean; else request human."""
    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    uo = _uo_root(root)
    run = _run_dir(uo, ctx)
    scope = run / "scope"
    cand = _load(scope / "candidates.yaml") or _load(uo / "summary" / "scope_candidates.yaml")
    force = bool(ctx.get("force_confirm") or ctx.get("confirmed"))
    ambiguous = bool(cand.get("ambiguities"))
    probe_clean = bool(cand.get("probe_clean", False))
    need_human = (ambiguous or not probe_clean) and not force
    if need_human:
        return {
            "ok": False,
            "engine": "scope_confirm",
            "need_human": True,
            "ambiguous": ambiguous,
            "probe_clean": probe_clean,
            "message_zh": "范围有歧义或探针有错，需要人工确认",
        }
    receipt = {
        "version": 1,
        "status": "confirmed",
        "op_name": cand.get("op_name") or root.name,
        "arch_dir": cand.get("arch_dir") or "",
        "host_targets": cand.get("host_targets") or [],
        "kernel_entry": cand.get("kernel_entry") or "",
        "auto": not force,
        "probe_clean": probe_clean,
    }
    _dump(scope / "scope_confirmed.yaml", receipt)
    _dump(scope / "receipt.yaml", {"ok": True, "gate": "scope_receipt", **receipt})
    _dump(uo / "summary" / "scope_confirmed.yaml", receipt)
    return {"ok": True, "engine": "scope_confirm", "auto": not force, "receipt": receipt}


def _bundle_cache(uo: Path) -> Path:
    return uo / "ir" / "_host_bundle_meta.yaml"


def extract_host(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build host IR + PRODUCTION inventory analysis; cache metrics for later actions."""
    from uo_init.assemble_kb import extract_host_bundle

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    uo = _uo_root(root)
    try:
        bundle = extract_host_bundle(
            op_dir=root,
            cann_root=_cann_root(ctx),
            ops_root=_ops_root(ctx, root),
            arch_dir=ctx.get("arch_dir"),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "extract_host", "error": str(exc)[:400]}

    metrics = bundle["metrics"].to_dict()
    gap = bundle["gap"].to_dict()
    meta = {
        "version": 1,
        "status": "extracted",
        "op_name": bundle["spec"].op_name,
        "architecture": bundle["spec"].arch_dir,
        "quality": metrics,
        "gap": gap,
        "node_count": metrics.get("total_nodes", 0),
        "blocker_count": len(bundle["gap"].blockers),
        "bind_error": bundle.get("bind_error") or "",
    }
    _dump(_bundle_cache(uo), meta)
    _dump(
        uo / "ir" / "host_extract_receipt.yaml",
        {"ok": True, "engine": "extract_host", **meta},
    )
    # Keep analyses alive across process? Pilot engines are in-process; stash on module.
    _STORE["bundle"] = bundle
    return {
        "ok": True,
        "engine": "extract_host",
        "source_closure": metrics.get("source_closure"),
        "blocker_count": meta["blocker_count"],
        "node_count": meta["node_count"],
    }


_STORE: dict[str, Any] = {}


def _ensure_bundle(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    if "bundle" in _STORE:
        return _STORE["bundle"]
    from uo_init.assemble_kb import extract_host_bundle

    root = Path(project_root).expanduser().resolve()
    bundle = extract_host_bundle(
        op_dir=root,
        cann_root=_cann_root(ctx),
        ops_root=_ops_root(ctx, root),
        arch_dir=ctx.get("arch_dir"),
    )
    _STORE["bundle"] = bundle
    return bundle


def extract_tiling_key(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = _ctx(payload)
    try:
        bundle = _ensure_bundle(project_root, ctx)
        binding = bundle.get("binding")
        n = len(binding.bindings) if binding is not None else 0
        _dump(
            _uo_root(project_root) / "tiling" / "key_bind_receipt.yaml",
            {
                "ok": True,
                "binding_count": n,
                "bind_error": bundle.get("bind_error") or "",
                "status": "extracted" if binding is not None else "partial",
            },
        )
        return {"ok": True, "engine": "extract_tiling_key", "binding_count": n}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "extract_tiling_key", "error": str(exc)[:400]}


def extract_registry(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from uo_init.op_spec import discover
    from uo_init.registry_capable import build_arch35_competition

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    try:
        spec = discover(root, arch_dir=ctx.get("arch_dir"))
        comp = build_arch35_competition(spec.host_root, op_name=spec.op_name)
        payload_out = {
            "version": 1,
            "status": "extracted",
            "ordered": list(comp.ordered),
            "pred_count": len(comp.preds),
        }
        _dump(_uo_root(root) / "tiling" / "families.yaml", payload_out)
        return {"ok": True, "engine": "extract_registry", "pred_count": len(comp.preds)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "extract_registry", "error": str(exc)[:400]}


def extract_kernel(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    import tempfile

    from uo_init.harness import (
        build_harness_jobs,
        collect_folded_kernel_branches,
        find_clang,
    )
    from uo_init.op_spec import discover
    from uo_init.build_context import BuildContext

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    fold = bool(ctx.get("fold_kernel", True))
    limit = ctx.get("harness_limit")
    try:
        spec = discover(root, arch_dir=ctx.get("arch_dir"))
        if not fold or not spec.tiling_key_header or not spec.kernel_entry:
            _STORE["kbr"] = []
            _STORE["kbr_ids"] = []
            _dump(
                _uo_root(root) / "kernel" / "fold_receipt.yaml",
                {"ok": True, "skipped": True, "kernel_branch_count": 0, "kernel_branches": []},
            )
            return {"ok": True, "engine": "extract_kernel", "skipped": True, "kernel_branch_count": 0}
        exe = find_clang(ctx.get("clang_exe"))
        if exe is None:
            return {"ok": False, "engine": "extract_kernel", "error": "clang driver missing"}
        bctx = BuildContext.load(
            cann_root=_cann_root(ctx),
            ops_root=_ops_root(ctx, root),
            op_dir=str(spec.op_dir),
            arch_dir=spec.arch_dir,
        )
        jobs = build_harness_jobs(
            spec.tiling_key_header,
            entry_source=spec.kernel_entry,
            entry_name=spec.op_snake,
            limit=int(limit) if limit is not None else None,
        )
        wd = Path(ctx["work_dir"]) if ctx.get("work_dir") else Path(tempfile.mkdtemp(prefix="uo_fold_"))
        minted = collect_folded_kernel_branches(
            jobs,
            bctx,
            entry=spec.op_snake,
            work_dir=wd,
            op_root=str(spec.op_dir),
            clang_exe=exe,
            workers=int(ctx.get("harness_workers") or 4),
            logical_file=str(spec.kernel_entry).replace("\\", "/"),
        )
        _STORE["kbr"] = minted
        _STORE["kbr_ids"] = [m.id for m in minted]
        _dump(
            _uo_root(root) / "kernel" / "fold_receipt.yaml",
            {
                "ok": True,
                "jobs": len(jobs),
                "kernel_branch_count": len(minted),
                "kernel_branch_ids": [m.id for m in minted],
                "kernel_branches": [m.to_dict() for m in minted],
            },
        )
        return {
            "ok": True,
            "engine": "extract_kernel",
            "jobs": len(jobs),
            "kernel_branch_count": len(minted),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "extract_kernel", "error": str(exc)[:400]}


def normalize_variables(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Variable layer is produced inside export; this action records a receipt."""
    meta = _load(_bundle_cache(_uo_root(project_root)))
    _dump(
        _uo_root(project_root) / "tiling" / "normalize_variables_receipt.yaml",
        {"ok": True, "status": "pending_export", "from_host": bool(meta)},
    )
    return {"ok": True, "engine": "normalize_variables", "deferred_to": "export_kb"}


def derive_key_fields(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Expand every TilingKey dimension to input roots; write host_derivation.yaml.

    This is the step that used to live only in ``scripts/_probe_derive.py``.
    Downstream K6 and TG consume the artifact; undecided guards that survive
    the soft-scheduling pre-sort feed the gap loop.
    """
    from uo_init.host_derivation import derive_host_fields, to_key_derivations

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    uo = _uo_root(root)
    try:
        bundle = _ensure_bundle(root, ctx)
        timeout = int(ctx.get("derive_timeout") or 180)
        helper = int(ctx.get("max_helper_guards") or 4)
        isolate = ctx.get("derive_isolate", True)
        if isinstance(isolate, str):
            isolate = isolate.strip().lower() not in {"0", "false", "no"}
        doc = derive_host_fields(
            bundle,
            timeout=timeout,
            max_helper_guards=helper,
            isolate=bool(isolate),
            only=ctx.get("derive_only"),
        )
        bundle["host_derivation"] = doc
        _dump(uo / "ir" / "host_derivation.yaml", doc.to_dict())
        # TG-facing view is written early so export_kb can attach it without
        # re-deriving; still a contract stub until TG consumes it.
        _dump(uo / "tiling" / "key_derivations.yaml", to_key_derivations(doc))
        totals = doc.totals()
        receipt = {
            "ok": True,
            "engine": "derive_key_fields",
            "status": doc.status,
            "totals": totals,
            "encode_function": doc.encode_function,
            "note": doc.note,
        }
        _dump(uo / "ir" / "derive_key_fields_receipt.yaml", receipt)
        return receipt
    except Exception as exc:  # noqa: BLE001
        err = {"ok": False, "engine": "derive_key_fields", "error": str(exc)[:400]}
        _dump(uo / "ir" / "derive_key_fields_receipt.yaml", err)
        return err


def normalize_predicates(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from uo_init.gaps import (
        build_derivation_gap_report,
        merge_gap_reports,
    )
    from uo_init.host_derivation import HostDerivation, derive_host_fields

    ctx = _ctx(payload)
    try:
        bundle = _ensure_bundle(project_root, ctx)
        gap = bundle["gap"]
        # Prefer an in-memory derivation from derive_key_fields; otherwise load
        # the artifact or run a quick in-process derive so key-field undecided
        # guards become blockers in the same unresolved.yaml.
        derivation = bundle.get("host_derivation")
        uo = _uo_root(project_root)
        if not isinstance(derivation, HostDerivation):
            raw = _load(uo / "ir" / "host_derivation.yaml")
            if raw.get("fields"):
                # Re-derive cheaply so UndecidedGuard objects exist for clustering.
                derivation = derive_host_fields(
                    bundle,
                    isolate=bool(ctx.get("derive_isolate", False)),
                    timeout=int(ctx.get("derive_timeout") or 180),
                )
                bundle["host_derivation"] = derivation
                _dump(uo / "ir" / "host_derivation.yaml", derivation.to_dict())
        reports = [gap]
        der_count = 0
        if isinstance(derivation, HostDerivation) and derivation.fields:
            der_report = build_derivation_gap_report(derivation)
            der_count = der_report.blocker_count
            reports.append(der_report)
        merged = merge_gap_reports(*reports)
        unresolved = {
            "version": 1,
            "status": "unresolved" if merged.blockers else "closed",
            "blocker_count": merged.blocker_count,
            "predicate_blocker_count": len(gap.blockers),
            "derivation_blocker_count": der_count,
            "blockers": [b.to_dict() for b in merged.blockers],
            "closed_vocabulary": {
                "classification": [
                    "scheduling",
                    "input_derived",
                    "validation_assumption",
                    "genuinely_unknown",
                ],
                "binding_ops": ["eq", "ne", "lt", "le", "gt", "ge", "in"],
            },
        }
        _dump(uo / "ir" / "unresolved.yaml", unresolved)
        return {
            "ok": True,
            "engine": "normalize_predicates",
            "blocker_count": merged.blocker_count,
            "derivation_blocker_count": der_count,
            "source_closure": bundle["metrics"].source_closure,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "normalize_predicates", "error": str(exc)[:400]}


def resolve_gaps(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Subagent trigger point: skip when unresolved is empty/closed."""
    from uo_init.gap_patch import SCHEMA_HINT

    ctx = _ctx(payload)
    uo = _uo_root(project_root)
    run = _run_dir(uo, ctx)
    unresolved = _load(uo / "ir" / "unresolved.yaml") or {}
    count = int(unresolved.get("blocker_count") or len(unresolved.get("blockers") or []))
    der_count = int(unresolved.get("derivation_blocker_count") or 0)
    if count == 0 or unresolved.get("status") == "closed":
        _dump(
            uo / "ir" / "resolve_gaps_receipt.yaml",
            {"ok": True, "skipped": True, "blocker_count": 0},
        )
        return {
            "ok": True,
            "engine": "resolve_gaps",
            "skipped": True,
            "blocker_count": 0,
            "message_zh": "无残余 blocker，auto-skip",
        }
    # Key-field derivation residuals always need the closed-vocabulary subagent,
    # even when the absolute count is small (FAG's leftover is typically <20).
    need_subagent = der_count > 0 or count >= 20
    staging = {
        "version": 1,
        "contract": "resolve-gaps-staging-v1",
        "schema": SCHEMA_HINT,
        "blocker_count": count,
        "derivation_blocker_count": der_count,
        "blockers": unresolved.get("blockers") or [],
        "instruction_zh": (
            "对每个 blocker 只从封闭词汇表选 classification；"
            "input_derived 时 binding.var_id 必须已在 VariableModel 中，禁止发明符号或写自由表达式。"
        ),
    }
    staging_rel = f"runs/{run.name}/actions/resolve_gaps/staging.yaml"
    _dump(run / "actions" / "resolve_gaps" / "staging.yaml", staging)
    # Mirror under ir for humans / older readers (Host-only).
    _dump(uo / "ir" / "resolve_gaps_staging.yaml", staging)
    _dump(
        uo / "ir" / "resolve_gaps_receipt.yaml",
        {
            "ok": True,
            "skipped": False,
            "blocker_count": count,
            "derivation_blocker_count": der_count,
            "need_subagent": need_subagent,
            "deferred": not need_subagent,
            "staging": staging_rel,
        },
    )
    return {
        "ok": True,
        "engine": "resolve_gaps",
        "skipped": False,
        "blocker_count": count,
        "need_subagent": need_subagent,
        "deferred": not need_subagent,
        "message_zh": (
            f"有 {count} 个 blocker（派生 {der_count}）"
            + ("，交 resolve_gaps subagent" if need_subagent else "（确定性记录后继续）")
        ),
    }


def apply_gap_patch(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from uo_init.gap_patch import (
        apply_bindings_to_derivation,
        dump_bindings,
        load_bindings,
        load_unresolved,
        merge_accepted,
        validate_patches,
    )
    from uo_init.host_derivation import HostDerivation, derive_host_fields, to_key_derivations

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    uo = _uo_root(root)
    run = _run_dir(uo, ctx)
    parts = run / "actions" / "resolve_gaps" / "parts"
    patch_files = list(parts.glob("**/*.yaml")) if parts.is_dir() else []
    # Also accept a single consolidated proposal for local / subagent handoff.
    consolidated = uo / "ir" / "gap_patch_proposal.yaml"
    if consolidated.is_file():
        patch_files.append(consolidated)
    if not patch_files:
        dump_bindings(uo / "ir" / "gap_bindings.yaml", [])
        _dump(
            uo / "ir" / "gap_patch_receipt.yaml",
            {"ok": True, "applied": 0, "skipped": True},
        )
        return {"ok": True, "engine": "apply_gap_patch", "applied": 0, "skipped": True}

    patches: list[dict[str, Any]] = []
    for path in patch_files:
        data = _load(path)
        if isinstance(data.get("patches"), list):
            patches.extend(p for p in data["patches"] if isinstance(p, dict))
        elif data.get("blocker_id"):
            patches.append(data)

    blockers = load_unresolved(uo / "ir" / "unresolved.yaml")
    bundle = _ensure_bundle(root, ctx)
    var_model = bundle.get("var_model")
    ops_root = Path(_ops_root(ctx, root)) if _ops_root(ctx, root) else None
    verdicts = validate_patches(
        patches, blockers=blockers, var_model=var_model, ops_root=ops_root
    )
    existing = load_bindings(uo / "ir" / "gap_bindings.yaml")
    # Snapshot derivation metrics before applying.
    before_doc = bundle.get("host_derivation")
    if not isinstance(before_doc, HostDerivation):
        before_doc = derive_host_fields(
            bundle, isolate=bool(ctx.get("derive_isolate", False))
        )
        bundle["host_derivation"] = before_doc
    before_derived = sum(1 for f in before_doc.fields if f.status == "derived")
    before_escalating = sum(len(f.escalating) for f in before_doc.fields)
    before_free = len({v for f in before_doc.fields for v in f.free_vars})

    merged, accepted, rejected = merge_accepted(
        existing, verdicts, blockers=blockers
    )
    # Tentatively apply; roll back accepted rows that fail the loop gate.
    dump_bindings(uo / "ir" / "gap_bindings.yaml", merged)
    after_doc = derive_host_fields(
        bundle, isolate=bool(ctx.get("derive_isolate", False))
    )
    metrics = apply_bindings_to_derivation(after_doc, merged)
    after_derived = sum(1 for f in after_doc.fields if f.status == "derived")
    after_free = len({v for f in after_doc.fields for v in f.free_vars})
    # A round has to shrink the questions without growing what is unexplained.
    # Counting only `derived` and `escalating` let a patch trade one for the
    # other: strike guards off the record, leave their variables in the
    # expressions, and both tracked numbers still improve.
    loop_ok = (
        after_derived >= before_derived
        and metrics["escalating_after"] < before_escalating
        and after_free <= before_free
    )
    if accepted and not loop_ok:
        # Roll back: keep only previously existing bindings.
        dump_bindings(uo / "ir" / "gap_bindings.yaml", existing)
        for row in accepted:
            row["status"] = "rejected"
            row["issues"] = [
                {
                    "code": "loop_regression",
                    "message": (
                        f"derived {before_derived}->{after_derived}, "
                        f"escalating {before_escalating}->{metrics['escalating_after']}, "
                        f"free_vars {before_free}->{after_free}"
                    ),
                }
            ]
            rejected.append(row)
        accepted = []
        after_doc = before_doc
        metrics = {
            "escalating_before": before_escalating,
            "escalating_after": before_escalating,
            "resolved": 0,
            "softened": 0,
            "reverted": 0,
        }
    else:
        bundle["host_derivation"] = after_doc
        _dump(uo / "ir" / "host_derivation.yaml", after_doc.to_dict())
        _dump(uo / "tiling" / "key_derivations.yaml", to_key_derivations(after_doc))

    receipt = {
        "ok": True,
        "engine": "apply_gap_patch",
        "applied": len(accepted),
        "rejected": len(rejected),
        "skipped": False,
        "loop": {
            "derived_before": before_derived,
            "derived_after": after_derived,
            "free_vars_before": before_free,
            "free_vars_after": after_free,
            **metrics,
            "ok": loop_ok if accepted else True,
        },
        "accepted": accepted,
        "rejected": rejected,
    }
    _dump(uo / "ir" / "gap_patch_receipt.yaml", receipt)
    return receipt


def export_kb_action(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from uo_init.assemble_kb import assemble_kb, export_operator_kb

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    try:
        from uo_init.harness import MintedKernelBranch

        bundle = _ensure_bundle(root, ctx)
        uo = _uo_root(root)
        fold = _load(uo / "kernel" / "fold_receipt.yaml")
        kbr = list(_STORE.get("kbr") or [])
        if not kbr:
            rows = fold.get("kernel_branches") or []
            kbr = [MintedKernelBranch.from_dict(r) for r in rows if isinstance(r, dict)]
        if not kbr:
            # Recover evidence-bearing KBR nodes from a previous export.
            existing = _load(uo / "kernel" / "branches.yaml")
            graph = _load(uo / "ir" / "operator_graph.yaml")
            ev_by_id = {
                str(e.get("id")): e
                for e in (graph.get("evidence") or [])
                if isinstance(e, dict) and e.get("id")
            }
            for node in existing.get("nodes") or []:
                if not str(node.get("id") or "").startswith("KBR_"):
                    continue
                refs = node.get("evidence_refs") or []
                ev = ev_by_id.get(str(refs[0])) if refs else None
                kbr.append(
                    MintedKernelBranch(
                        id=str(node["id"]),
                        file=str((ev or {}).get("file") or node.get("file") or ""),
                        line=int((ev or {}).get("line_start") or node.get("line") or 0),
                        snippet=str((ev or {}).get("snippet") or ""),
                        condition=str(node.get("condition") or ""),
                        function=str(node.get("function") or ""),
                        kind=str(node.get("ctrl_kind") or "if"),
                    )
                )
        if not kbr:
            kbr = list(fold.get("kernel_branch_ids") or [])
        from uo_init.host_derivation import HostDerivation, to_key_derivations

        derivation = bundle.get("host_derivation")
        kb = assemble_kb(
            op_name=bundle["spec"].op_name,
            architecture=bundle["spec"].arch_dir or "",
            analyses=bundle["analyses"],
            records=bundle["records"],
            metrics=bundle["metrics"],
            gap=bundle["gap"],
            binding=bundle.get("binding"),
            kernel_branches=kbr,
            notes={"kernel_fold": fold},
            # Without these the key space is never materialized at all, and
            # `legal_key_index.jsonl` keeps whatever a previous run left. The
            # derivation is what turns the template product into a reachability
            # answer; absent it every key is reported `underivable`.
            tpl_schema=bundle.get("tpl_schema"),
            var_model=bundle.get("var_model"),
            derivation=derivation,
            tpl_header=bundle.get("tpl_header") or "",
        )
        receipt = export_operator_kb(kb, root)
        receipt["engine"] = "export_kb"
        receipt["source_closure"] = bundle["metrics"].source_closure
        receipt["blocker_count"] = len(bundle["gap"].blockers)
        receipt["kernel_branch_count"] = len(kbr)
        materialized = kb.notes.get("tiling_materialize")
        if isinstance(materialized, dict) and materialized.get("ok"):
            receipt["key_status_counts"] = dict(materialized["key_status_counts"])
            receipt["reachability"] = dict(materialized["reachability"])
        # Re-emit the TG contract if derive_key_fields already ran in this process.
        # export_kb does not wipe tiling/key_derivations.yaml, but a fresh
        # in-memory derivation is the authoritative view.
        if isinstance(derivation, HostDerivation):
            _dump(uo / "tiling" / "key_derivations.yaml", to_key_derivations(derivation))
            receipt["key_derivations"] = derivation.status
        elif (uo / "tiling" / "key_derivations.yaml").is_file():
            receipt["key_derivations"] = "preserved"
        return receipt
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "export_kb", "error": str(exc)[:400]}


def build_index(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from uo_init.kb_index import rebuild_index

    del payload
    uo = _uo_root(project_root)
    try:
        out = rebuild_index(uo)
        out["engine"] = "build_index"
        out["ok"] = True
        return out
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "build_index", "error": str(exc)[:400]}


def export_integrity(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    del payload
    from uo_init.kb_export import knowledge_base_from_payload, load_graph

    uo = _uo_root(project_root)
    graph = uo / "ir" / "operator_graph.yaml"
    quality = uo / "quality.yaml"
    unresolved = uo / "ir" / "unresolved.yaml"
    hashes = uo / "checks" / "artifact_hashes.yaml"
    sqlite = uo / "indexes" / "kb_graph.sqlite"
    errors: list[str] = []
    if not graph.is_file():
        errors.append("missing ir/operator_graph.yaml")
    if not quality.is_file():
        errors.append("missing quality.yaml")
    if not hashes.is_file():
        errors.append("missing checks/artifact_hashes.yaml")
    if not sqlite.is_file():
        errors.append("missing indexes/kb_graph.sqlite")
    if graph.is_file():
        try:
            kb = knowledge_base_from_payload(load_graph(uo))
            errors.extend(kb.check_invariants())
        except Exception as exc:  # noqa: BLE001
            errors.append(f"graph_load_failed: {exc}")
    ur = _load(unresolved)
    q = _load(quality)
    blocker_count = int(ur.get("blocker_count") or len(ur.get("blockers") or []))
    doc = {
        "version": 1,
        "status": "pass" if not errors else "fail",
        "ok": not errors,
        "blocker_count": blocker_count,
        "source_closure": q.get("source_closure"),
        "errors": errors,
    }
    _dump(uo / "checks" / "integrity.yaml", doc)
    return {"ok": not errors, "engine": "export_integrity", **doc}


def kb_review(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Referee trigger: auto-skip when quality gate already green."""
    del payload
    uo = _uo_root(project_root)
    q = _load(uo / "quality.yaml")
    ur = _load(uo / "ir" / "unresolved.yaml")
    closure = float(q.get("source_closure") or 0.0)
    blockers = int(ur.get("blocker_count") or len(ur.get("blockers") or []))
    auto_ok = closure >= 0.95 and blockers < 20
    review = {
        "version": 1,
        "status": "skipped" if auto_ok else "needs_review",
        "verdict": "pass" if auto_ok else "open",
        "source_closure": closure,
        "blocker_count": blockers,
        "auto": auto_ok,
    }
    _dump(uo / "review" / "kb_product_review.yaml", review)
    return {
        "ok": True,
        "engine": "kb_review",
        "skipped": auto_ok,
        "need_subagent": not auto_ok,
        **review,
    }


# Stable names for ENGINE_REGISTRY adapters.
ENGINES: dict[str, Any] = {
    "prepare_layout": prepare_layout,
    "scope_scan": scope_scan,
    "scope_confirm": scope_confirm,
    "extract_host": extract_host,
    "extract_tiling_key": extract_tiling_key,
    "extract_registry": extract_registry,
    "extract_kernel": extract_kernel,
    "normalize_variables": normalize_variables,
    "derive_key_fields": derive_key_fields,
    "normalize_predicates": normalize_predicates,
    "resolve_gaps": resolve_gaps,
    "apply_gap_patch": apply_gap_patch,
    "export_kb": export_kb_action,
    "build_index": build_index,
    "export_integrity": export_integrity,
    "kb_review": kb_review,
}
