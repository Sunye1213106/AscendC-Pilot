# -*- coding: utf-8 -*-
"""Pilot Action engines for the clang-based uo-init workflow.

Each entrypoint has signature ``fn(project_root, payload) -> dict`` with an
``ok`` field.  Engines write under ``.ascendc-pilot/uo/`` only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from uo_init import paths


def _uo_root(project_root: Path, *, arch: str | None = None) -> Path:
    root = Path(project_root).expanduser().resolve()
    try:
        from ascendc_pilot.paths import uo_root

        return uo_root(root, arch=arch)
    except Exception:
        arch_name = (arch or "").strip() or "arch35"
        return root / ".ascendc-pilot" / arch_name / "uo"


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


def _load_yaml_scalar(path: Path, key: str) -> str:
    """Read one top-level YAML scalar without parsing a large graph file."""
    if not path.is_file():
        return ""
    prefix = f"{key}:"
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                text = line.strip()
                if not text.startswith(prefix):
                    continue
                value = text[len(prefix):].strip()
                if not value:
                    return ""
                if " #" in value:
                    value = value.split(" #", 1)[0].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                    value = value[1:-1]
                return value
    except OSError:
        return ""
    return ""


def _ctx(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})


def _flag(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return bool(value)


def _cann_root(ctx: dict[str, Any]) -> str:
    found = paths.cann_root(ctx.get("cann_root"))
    if found is None:
        # Returning a path that does not exist gives clang a clearer failure
        # than returning None does three frames further down.
        raise FileNotFoundError(f"CANN packages not found.\n{paths.explain()}")
    return str(found)


def _ops_root(ctx: dict[str, Any], project_root: Path) -> str | None:
    raw = ctx.get("ops_root")
    if raw:
        return str(raw)
    # Typical layout: …/ops-transformer/attention/<op>. Confirm by shape rather
    # than by existence, or an operator two levels below anything at all would
    # silently hand clang an include root with no headers in it.
    parent = project_root.parent.parent
    if (parent / "common" / "include").is_dir():
        return str(parent)
    found = paths.ops_root()
    return str(found) if found is not None else None


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
    prior = _load(scope / "scope_confirmed.yaml") or _load(uo / "summary" / "scope_confirmed.yaml")
    if str((prior or {}).get("status") or "") == "confirmed":
        return {
            "ok": True,
            "engine": "scope_confirm",
            "auto": bool((prior or {}).get("auto")),
            "already_confirmed": True,
            "receipt": prior,
        }
    decision = str(ctx.get("decision") or "").strip().lower()
    force = bool(
        ctx.get("force_confirm")
        or ctx.get("confirmed")
        or decision in {"continue", "accept", "confirm", "yes", "y"}
    )
    ambiguous = bool(cand.get("ambiguities"))
    probe_clean = bool(cand.get("probe_clean", False))
    # Automation / cold-start drivers: probe-clean + explicit continue accepts
    # mild discover ambiguities (extra headers) without a human prompt.
    if (
        not force
        and probe_clean
        and str(ctx.get("step") or "").strip().lower() in {"finalize", "confirm", "scope_confirm", ""}
        and bool(ctx.get("auto_accept_clean"))
    ):
        force = True
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
        # Run-scoped identity is required by the Pilot output contract.  The
        # compatibility ``uo-scope`` wrapper supplies these fields from the
        # active workflow state; keeping them in the producer artifact also
        # makes direct static execution auditable.
        "run_id": str(ctx.get("run_id") or ""),
        "workflow_id": str(ctx.get("workflow_id") or "uo-init"),
        "action_id": str(ctx.get("action_id") or "scope_confirmation"),
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
    """Build host IR + controllability + kernel/API facts.

    Default profile is ``UO_INIT_PROFILE=fast``: ``closure_mode=keypath``,
    one dtype kernel walk (overlapped with host IR), no API clang contract,
    so cold uo-init stays within ``UO_COLD_BUDGET_S``.  Set
    ``UO_INIT_PROFILE=full`` (or ``closure_mode=full``) for every PRODUCTION
    control.  Per-TU walks hit ``UO_TU_CACHE`` on warm runs.
    """
    from uo_init.assemble_kb import extract_host_bundle
    from uo_init.controllability import ClosureMetrics
    from uo_init.extract_cache import (
        compute_extract_fingerprint,
        skip_reextract_for_unchanged_tus,
        store_extract_fingerprint,
    )
    from uo_init.gaps import GapReport
    from uo_init.init_profile import (
        default_closure_max_nodes,
        default_closure_mode,
        default_kernel_max_variants,
        default_with_api,
        default_with_kernel,
        profile_name,
    )

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    uo = _uo_root(root, arch=ctx.get("arch_dir"))
    mode = default_closure_mode(ctx)
    max_nodes = default_closure_max_nodes(ctx)
    with_kernel = default_with_kernel(ctx)
    with_api = default_with_api(ctx)
    kernel_max_variants = default_kernel_max_variants(ctx)
    skip_plan = skip_reextract_for_unchanged_tus(
        root, uo_root=uo, arch=ctx.get("arch_dir") or "arch35"
    )
    try:
        bundle = extract_host_bundle(
            op_dir=root,
            cann_root=_cann_root(ctx),
            ops_root=_ops_root(ctx, root),
            arch_dir=ctx.get("arch_dir"),
            closure_mode=str(mode),
            closure_max_nodes=int(max_nodes),
            with_kernel=with_kernel,
            with_api=with_api,
            kernel_max_variants=kernel_max_variants,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "extract_host", "error": str(exc)[:400]}

    metrics_obj = bundle.get("metrics") or ClosureMetrics()
    gap_obj = bundle.get("gap") or GapReport()
    metrics = metrics_obj.to_dict()
    gap = gap_obj.to_dict()
    fp_meta = compute_extract_fingerprint(
        root, uo_root=uo, arch=getattr(bundle["spec"], "arch_dir", None)
    )
    store_extract_fingerprint(uo, fp_meta)
    kir = bundle.get("kernel_ir")
    kernel_branches = len(getattr(kir, "branches", []) or [])
    if kir is not None and hasattr(kir, "to_persist_dict"):
        # Cross-process export_kb must not lose uninstantiated branches.
        _dump(uo / "ir" / "kernel_ir.yaml", kir.to_persist_dict())
    meta = {
        "version": 1,
        "status": "extracted",
        "op_name": bundle["spec"].op_name,
        "architecture": bundle["spec"].arch_dir,
        "quality": metrics,
        "gap": gap,
        "node_count": metrics.get("total_nodes", 0),
        "blocker_count": len(gap_obj.blockers),
        "bind_error": bundle.get("bind_error") or "",
        "closure_mode": bundle.get("closure_mode") or mode,
        "closure_selected": bundle.get("closure_selected") or 0,
        "closure_max_nodes": int(max_nodes),
        "init_profile": profile_name(ctx),
        "with_kernel": bool(with_kernel),
        "with_api": bool(with_api),
        "kernel_max_variants": int(kernel_max_variants or 0),
        "kernel_branches": kernel_branches,
        "extract_fingerprint": fp_meta.get("extract_fingerprint"),
        "sources_unchanged_at_start": bool(skip_plan.get("skip_reextract")),
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
        "closure_mode": meta["closure_mode"],
        "closure_selected": meta["closure_selected"],
        "kernel_branches": meta["kernel_branches"],
        "extract_fingerprint": meta["extract_fingerprint"],
        "sources_unchanged_at_start": meta["sources_unchanged_at_start"],
    }


_STORE: dict[str, Any] = {}


def _ensure_bundle(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    if "bundle" in _STORE:
        return _STORE["bundle"]
    from uo_init.assemble_kb import extract_host_bundle
    from uo_init.kernel_ir import kernel_ir_from_dict

    root = Path(project_root).expanduser().resolve()
    # ``acp run-action`` launches each deterministic action in a fresh
    # process, so the in-memory bundle from extract_host is not available to
    # the next action. Downstream only needs the structural bundle — rebuild
    # with closure off when meta exists (TU cache makes this cheap).
    from uo_init.init_profile import (
        default_closure_mode,
        default_kernel_max_variants,
        default_with_api,
        default_with_kernel,
    )

    uo = _uo_root(root, arch=ctx.get("arch_dir"))
    cached_meta = _load(_bundle_cache(uo))
    mode = ctx.get("closure_mode") or ("off" if cached_meta else default_closure_mode(ctx))
    persisted_kir = _load(uo / "ir" / "kernel_ir.yaml")
    has_persist = isinstance(persisted_kir, dict) and bool(persisted_kir.get("branches"))
    # Prefer the persisted uninstantiated kernel IR from extract_host so
    # export_kb does not drop branches (and does not re-pay a cold walk).
    with_kernel = False if (cached_meta and has_persist) else default_with_kernel(ctx)
    with_api = False if cached_meta else default_with_api(ctx)
    kernel_max_variants = default_kernel_max_variants(ctx)
    if "with_kernel" in ctx:
        with_kernel = bool(ctx.get("with_kernel"))
    if "with_api" in ctx:
        with_api = bool(ctx.get("with_api"))
    if "kernel_max_variants" in ctx:
        try:
            kernel_max_variants = int(ctx.get("kernel_max_variants"))
        except (TypeError, ValueError):
            pass
    bundle = extract_host_bundle(
        op_dir=root,
        cann_root=_cann_root(ctx),
        ops_root=_ops_root(ctx, root),
        arch_dir=ctx.get("arch_dir"),
        closure_mode=str(mode),
        with_kernel=with_kernel,
        with_api=with_api,
        kernel_max_variants=kernel_max_variants,
    )
    if not getattr(bundle.get("kernel_ir"), "branches", None) and has_persist:
        restored = kernel_ir_from_dict(persisted_kir)
        if restored is not None:
            bundle["kernel_ir"] = restored
    elif bundle.get("kernel_ir") is not None and hasattr(
        bundle["kernel_ir"], "to_persist_dict"
    ):
        _dump(uo / "ir" / "kernel_ir.yaml", bundle["kernel_ir"].to_persist_dict())
    _STORE["bundle"] = bundle
    return bundle


def extract_tiling_key(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = _ctx(payload)
    try:
        local_ctx = dict(ctx)
        local_ctx.setdefault("with_kernel", False)
        bundle = _ensure_bundle(project_root, local_ctx)
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

    from uo_init.init_profile import default_fold_kernel

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    # Pairwise fold is expensive.  ``UO_INIT_PROFILE=fast`` (default) skips it
    # and relies on uninstantiated kernel_ir from extract_host.
    fold = default_fold_kernel(ctx)
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
            # libclang has already produced the uninstantiated kernel IR in
            # extract_host.  A folded harness additionally needs the clang
            # executable; keep that limitation explicit while emitting a
            # valid receipt so the static pipeline can continue to TG/replay.
            meta = _load(_bundle_cache(_uo_root(root)))
            branch_count = int(meta.get("kernel_branches") or 0)
            _dump(
                _uo_root(root) / "kernel" / "fold_receipt.yaml",
                {
                    "ok": True,
                    "skipped": True,
                    "reason": "clang_driver_missing",
                    "kernel_branch_count": branch_count,
                    "kernel_branches": [],
                },
            )
            return {
                "ok": True,
                "engine": "extract_kernel",
                "skipped": True,
                "reason": "clang_driver_missing",
                "kernel_branch_count": branch_count,
            }
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
        local_ctx = dict(ctx)
        local_ctx.setdefault("with_kernel", False)
        bundle = _ensure_bundle(root, local_ctx)
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
        try:
            from uo_init.materialize_tiling import write_expr_shards, write_key_index

            field_dicts = [f.to_dict() for f in doc.fields]
            write_key_index(uo, field_dicts)
            # No-op unless UO_DEEP_SOLVE=1 (to_dict then carries value_expr).
            write_expr_shards(uo, field_dicts)
        except Exception:
            pass
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
        # Fast cross-process path: extract_host persists the complete gap
        # ledger in its receipt, while the Python object graph is process
        # local.  Rehydrate the facts directly instead of reparsing all clang
        # translation units for this normalization-only action.
        uo = _uo_root(project_root)
        host_receipt = _load(uo / "ir" / "host_extract_receipt.yaml")
        cached_gap = host_receipt.get("gap") if isinstance(host_receipt, dict) else None
        if isinstance(cached_gap, dict) and isinstance(cached_gap.get("blockers"), list):
            blockers = list(cached_gap.get("blockers") or [])
            unresolved = {
                "version": 1,
                "status": "unresolved" if blockers else "closed",
                "blocker_count": len(blockers),
                "predicate_blocker_count": len(blockers),
                "derivation_blocker_count": 0,
                "blockers": blockers,
                "closed_vocabulary": {
                    "classification": [
                        "scheduling",
                        "input_derived",
                        "validation_assumption",
                        "genuinely_unknown",
                    ],
                    "binding_ops": ["eq", "ne", "lt", "le", "gt", "ge", "in"],
                },
                "source": "host_extract_receipt",
            }
            _dump(uo / "ir" / "unresolved.yaml", unresolved)
            return {
                "ok": True,
                "engine": "normalize_predicates",
                "blocker_count": len(blockers),
                "derivation_blocker_count": 0,
                "source_closure": host_receipt.get("quality", {}).get("source_closure"),
                "rehydrated": True,
            }
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
    """Subagent trigger point: skip when unresolved is empty/closed.

    Auto LLM / subagent gap resolve is **off by default**. Set
    ``UO_RESOLVE_GAPS_LLM=1`` (or payload ``enable_llm=true``) to allow the
    closed-vocabulary producer path. LLM patches are graded ``llm``, never sound.
    """
    import os

    from uo_init.gap_patch import SCHEMA_HINT

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
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
    llm_env = str(os.environ.get("UO_RESOLVE_GAPS_LLM") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    llm_enabled = llm_env or _flag(ctx.get("enable_llm"), default=False)
    # Key-field derivation residuals need the closed-vocabulary subagent only
    # when LLM resolve is explicitly enabled.
    need_subagent = llm_enabled and (der_count > 0 or count >= 20)
    staging = {
        "version": 1,
        "contract": "resolve-gaps-staging-v1",
        "schema": SCHEMA_HINT,
        "blocker_count": count,
        "derivation_blocker_count": der_count,
        "llm_enabled": llm_enabled,
        "patch_grade": "llm",
        "blockers": unresolved.get("blockers") or [],
        "instruction_zh": (
            "对每个 blocker 只从封闭词汇表选 classification；"
            "input_derived 时 binding.var_id 必须已在 VariableModel 中，禁止发明符号或写自由表达式。"
            "每条 patch 必须带 grade: llm（不得标 sound）。"
        ),
    }
    staging_rel = f"runs/{run.name}/actions/resolve_gaps/staging.yaml"
    _dump(run / "actions" / "resolve_gaps" / "staging.yaml", staging)
    # Mirror under ir for humans / older readers (Host-only).
    _dump(uo / "ir" / "resolve_gaps_staging.yaml", staging)
    try:
        from uo_init.blocker_review import write_review

        static_review = write_review(
            uo,
            ops_root=_ops_root(ctx, root),
            project_root=root,
        )
    except Exception as exc:  # noqa: BLE001
        static_review = {"ok": False, "error": str(exc)[:200]}
    _dump(
        uo / "ir" / "resolve_gaps_receipt.yaml",
        {
            "ok": True,
            "skipped": False,
            "blocker_count": count,
            "derivation_blocker_count": der_count,
            "need_subagent": need_subagent,
            "deferred": not need_subagent,
            "llm_enabled": llm_enabled,
            "staging": staging_rel,
            "static_review": static_review,
        },
    )
    return {
        "ok": True,
        "engine": "resolve_gaps",
        "skipped": False,
        "blocker_count": count,
        "need_subagent": need_subagent,
        "deferred": not need_subagent,
        "llm_enabled": llm_enabled,
        "static_review": static_review,
        "message_zh": (
            f"有 {count} 个 blocker（派生 {der_count}）"
            + (
                "，交 resolve_gaps subagent"
                if need_subagent
                else (
                    "（LLM 默认关闭，设 UO_RESOLVE_GAPS_LLM=1 启用；确定性记录后继续）"
                    if not llm_enabled
                    else "（确定性记录后继续）"
                )
            )
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
    local_ctx = dict(ctx)
    local_ctx.setdefault("with_kernel", False)
    bundle = _ensure_bundle(root, local_ctx)
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
    # LLM / subagent patches are never sound — force grade llm.
    for row in merged:
        if isinstance(row, dict):
            src = str(row.get("source") or row.get("origin") or "llm")
            if src in {"llm", "subagent", "producer", ""} or "grade" not in row:
                row["grade"] = "llm"
            elif str(row.get("grade") or "") in {"sound", "source_lemma", "solver_derived"}:
                row["grade"] = "llm"
    for row in accepted:
        if isinstance(row, dict):
            row["grade"] = "llm"
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
        host_receipt = _load(uo / "ir" / "host_extract_receipt.yaml")
        cached_quality = (
            host_receipt.get("quality") if isinstance(host_receipt, dict) else None
        )
        if isinstance(cached_quality, dict) and cached_quality.get("total_nodes"):
            from uo_init.controllability import ClosureMetrics

            bundle["metrics"] = ClosureMetrics(
                total_nodes=int(cached_quality.get("total_nodes") or 0),
                closed_nodes=int(cached_quality.get("closed_nodes") or 0),
                partial_nodes=int(cached_quality.get("partial_nodes") or 0),
                open_nodes=int(cached_quality.get("open_nodes") or 0),
                controllable_nodes=int(cached_quality.get("controllable_nodes") or 0),
                normalized_predicates=int(
                    cached_quality.get("normalized_predicates") or 0
                ),
                total_predicates=int(cached_quality.get("total_predicates") or 0),
                root_histogram={
                    str(k): int(v)
                    for k, v in (cached_quality.get("root_histogram") or {}).items()
                },
                reason_histogram={
                    str(k): int(v)
                    for k, v in (cached_quality.get("reason_histogram") or {}).items()
                },
            )
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
                        dimensions=tuple(
                            str(x) for x in (node.get("dimensions") or [])
                        ),
                        derived=tuple(str(x) for x in (node.get("derived") or [])),
                        symbols=tuple(str(x) for x in (node.get("symbols") or [])),
                        dtype_variants=tuple(
                            str(x) for x in (node.get("dtype_variants") or [])
                        ),
                        stage=str(node.get("stage") or ""),
                    )
                )
        if not kbr:
            kbr = list(fold.get("kernel_branch_ids") or [])
        from uo_init.host_derivation import (
            HostDerivation,
            host_derivation_from_dict,
            to_key_derivations,
        )

        derivation = bundle.get("host_derivation")
        if not isinstance(derivation, HostDerivation):
            raw_derivation = _load(uo / "ir" / "host_derivation.yaml")
            if isinstance(raw_derivation, dict) and raw_derivation.get("fields"):
                derivation = host_derivation_from_dict(raw_derivation)
                bundle["host_derivation"] = derivation
        kernel_ir_count = len(getattr(bundle.get("kernel_ir"), "branches", []) or [])
        kb = assemble_kb(
            op_name=bundle["spec"].op_name,
            architecture=bundle["spec"].arch_dir or "",
            analyses=bundle["analyses"],
            records=bundle["records"],
            metrics=bundle["metrics"],
            gap=bundle["gap"],
            binding=bundle.get("binding"),
            kernel_branches=kbr,
            # Uninstantiated kernel branches: the only pass where the guard
            # still names the dimension that decides it.
            kernel_ir=bundle.get("kernel_ir"),
            op_root=str(bundle["spec"].op_dir or ""),
            notes={"kernel_fold": fold},
            # Without these the key space is never materialized at all, and
            # `legal_key_index.jsonl` keeps whatever a previous run left. The
            # derivation is what turns the template product into a reachability
            # answer; absent it every key is reported `underivable`.
            tpl_schema=bundle.get("tpl_schema"),
            var_model=bundle.get("var_model"),
            derivation=derivation,
            tpl_header=bundle.get("tpl_header") or "",
            host_ir=bundle.get("host_ir"),
            op_spec=bundle.get("spec"),
        )
        receipt = export_operator_kb(kb, root, uo_root_override=uo)
        receipt["engine"] = "export_kb"
        receipt["source_closure"] = bundle["metrics"].source_closure
        receipt["blocker_count"] = len(bundle["gap"].blockers)
        receipt["kernel_branch_count"] = len(kbr) or kernel_ir_count
        receipt["folded_kernel_branch_count"] = len(kbr)
        receipt["kernel_ir_branch_count"] = kernel_ir_count
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


def export_tg_host_view(
    project_root: Path, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Project live HostIR into tg_host_view.yaml stamped with the KB fingerprint.

    Must run after ``export_kb`` + ``build_index``. Does not read
    ``.probe_cache/fag_bundle.pkl`` — HostIR comes from the in-process extract
    bundle (same source that fed the KB).
    """
    from uo_init.host_codemap import (
        TG_HOST_VIEW_YAML,
        export_tg_host_view as _export_view,
        rebuild_codemap_index,
    )
    from uo_init.host_derivation import HostDerivation

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    uo = _uo_root(root)
    graph_path = uo / "ir" / "operator_graph.yaml"
    sqlite = uo / "indexes" / "kb_graph.sqlite"
    if not sqlite.is_file() and not graph_path.is_file():
        return {
            "ok": False,
            "engine": "export_tg_host_view",
            "error": "missing KB product (indexes/kb_graph.sqlite); run export_kb first",
        }
    if not sqlite.is_file():
        return {
            "ok": False,
            "engine": "export_tg_host_view",
            "error": "missing indexes/kb_graph.sqlite; run build_index / export_kb first",
        }
    try:
        fingerprint = ""
        if graph_path.is_file():
            fingerprint = _load_yaml_scalar(graph_path, "fingerprint")
        if not fingerprint:
            from uo_init.kb_export import load_graph

            graph = load_graph(uo)
            fingerprint = str(graph.get("fingerprint") or "")
        manifest = _load(uo / "manifest.yaml")
        if not isinstance(manifest, dict):
            manifest = {}
        manifest_hash = str(manifest.get("content_hash") or manifest.get("hash") or "")
        manifest_source = manifest.get("source")
        if not isinstance(manifest_source, dict):
            manifest_source = {}
        source_revision = str(
            manifest.get("source_revision")
            or manifest_source.get("revision")
            or ""
        )
        existing_view = _load(uo / TG_HOST_VIEW_YAML)
        if isinstance(existing_view, dict):
            source = existing_view.get("source")
            if not isinstance(source, dict):
                source = {}
            view_fp = str(source.get("graph_fingerprint") or "")
            view_manifest_hash = str(source.get("manifest_hash") or "")
            view_source_revision = str(source.get("source_revision") or "")
            same_manifest = (
                not manifest_hash
                or not view_manifest_hash
                or view_manifest_hash == manifest_hash
            )
            same_revision = (
                not source_revision
                or not view_source_revision
                or view_source_revision == source_revision
            )
            if (
                fingerprint
                and view_fp == fingerprint
                and same_manifest
                and same_revision
                and (existing_view.get("fields") or existing_view.get("predicates"))
            ):
                summary = rebuild_codemap_index(uo)
                receipt = {
                    "ok": bool(summary.get("ok", True)),
                    "engine": "export_tg_host_view",
                    "cached": True,
                    "graph_fingerprint": fingerprint,
                    "schema": existing_view.get("schema"),
                    "yaml": str(uo / TG_HOST_VIEW_YAML),
                    "alias_yaml": "",
                    "fields": len(existing_view.get("fields") or []),
                    "writers": sum(
                        len(f.get("writers") or [])
                        for f in existing_view.get("fields") or []
                        if isinstance(f, dict)
                    ),
                    "predicates": len(existing_view.get("predicates") or []),
                    **summary,
                }
                _dump(uo / "checks" / "tg_host_view_receipt.yaml", receipt)
                return receipt

        local_ctx = dict(ctx)
        local_ctx.setdefault("with_kernel", False)
        bundle = _ensure_bundle(root, local_ctx)
        host_ir = bundle.get("host_ir")
        if host_ir is None:
            return {
                "ok": False,
                "engine": "export_tg_host_view",
                "error": "bundle has no host_ir; re-run extract_host",
            }
        derive_fields: list[dict[str, Any]] | None = None
        derivation = bundle.get("host_derivation")
        if isinstance(derivation, HostDerivation):
            derive_fields = [f.to_dict() for f in derivation.fields]
        elif isinstance(derivation, dict):
            derive_fields = list(derivation.get("fields") or [])
        else:
            kd = _load(uo / "tiling" / "key_derivations.yaml")
            derive_fields = list(kd.get("fields") or []) or None

        declared: dict[str, Any] | None = None
        try:
            from testcase_agent.closure import workspace as WS

            sch = WS.schema()
            declared = {
                "count": len(WS.declared()),
                "dims": [
                    {
                        "name": d.name,
                        "bw": getattr(d, "bw", 0),
                        "domain": list(getattr(d, "value_domain", []) or []),
                    }
                    for d in sch.dims
                ],
            }
        except Exception:
            declared = None

        result = _export_view(
            host_ir,
            uo,
            derive_fields=derive_fields,
            declared=declared,
            graph_fingerprint=fingerprint,
            source_revision=source_revision,
            manifest_hash=manifest_hash,
        )
        receipt = {
            "ok": bool(result.get("ok")),
            "engine": "export_tg_host_view",
            "graph_fingerprint": fingerprint,
            **{k: v for k, v in result.items() if k != "ok"},
        }
        _dump(uo / "checks" / "tg_host_view_receipt.yaml", receipt)
        return receipt
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "export_tg_host_view", "error": str(exc)[:400]}


def export_adapter_pack(
    project_root: Path, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Export TG adapter YAML from host_derivation into ``tg/adapter/``."""
    from uo_init.adapter_pack import export_adapter_pack as _export

    ctx = _ctx(payload)
    root = Path(project_root).expanduser().resolve()
    arch = str(ctx.get("architecture") or ctx.get("arch") or "").strip() or None
    write_package = _flag(ctx.get("write_package"), default=False)
    sampling_grid = ctx.get("sampling_grid")
    if sampling_grid is not None and not isinstance(sampling_grid, dict):
        return {
            "ok": False,
            "engine": "export_adapter_pack",
            "error": "sampling_grid must be a mapping",
        }
    return _export(
        root,
        arch=arch,
        write_package=write_package,
        sampling_grid=sampling_grid,
    )


def export_integrity(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    del payload
    from uo_init.kb_export import knowledge_base_from_payload, load_graph
    from uo_init.host_codemap import TG_HOST_VIEW_YAML, CODEMAP_YAML, load_tg_host_view
    from uo_init.kb_index import (
        db_authority_ok,
        index_summary,
        load_view_blob,
        set_meta_values,
    )

    uo = _uo_root(project_root)
    graph = uo / "ir" / "operator_graph.yaml"
    quality = uo / "quality.yaml"
    unresolved = uo / "ir" / "unresolved.yaml"
    hashes = uo / "checks" / "artifact_hashes.yaml"
    sqlite = uo / "indexes" / "kb_graph.sqlite"
    view_path = uo / TG_HOST_VIEW_YAML
    alias_path = uo / CODEMAP_YAML
    errors: list[str] = []
    db_ready = sqlite.is_file() and db_authority_ok(sqlite)
    if not graph.is_file() and not db_ready:
        errors.append("missing ir/operator_graph.yaml (and no DB authority product)")
    if not quality.is_file() and not (
        db_ready and load_view_blob(sqlite, "quality.yaml") is not None
    ):
        errors.append("missing quality.yaml")
    if not hashes.is_file() and not (
        db_ready and load_view_blob(sqlite, "checks/artifact_hashes.yaml") is not None
    ):
        errors.append("missing checks/artifact_hashes.yaml")
    if not sqlite.is_file():
        errors.append("missing indexes/kb_graph.sqlite")
    graph_fp = ""
    try:
        payload_graph = load_graph(uo)
        graph_fp = str(payload_graph.get("fingerprint") or "")
        kb = knowledge_base_from_payload(payload_graph)
        errors.extend(kb.check_invariants())
    except Exception as exc:  # noqa: BLE001
        if graph.is_file() or db_ready:
            errors.append(f"graph_load_failed: {exc}")
    if sqlite.is_file() and graph_fp:
        try:
            summary = index_summary(sqlite)
            idx_fp = str(summary.get("graph_fingerprint") or "")
            if idx_fp != graph_fp:
                errors.append(
                    f"kb_graph fingerprint drift: index={idx_fp!r} graph={graph_fp!r}"
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"kb_index_summary_failed: {exc}")
    host_view_in_db = bool(
        db_ready and load_view_blob(sqlite, "ir/tg_host_view.yaml") is not None
    )
    if not view_path.is_file() and not alias_path.is_file() and not host_view_in_db:
        errors.append(f"missing {TG_HOST_VIEW_YAML} (run export_tg_host_view)")
    else:
        view = load_tg_host_view(uo)
        if not view and host_view_in_db:
            view = load_view_blob(sqlite, "ir/tg_host_view.yaml") or {}
        if not isinstance(view, dict):
            view = {}
        view_source = view.get("source")
        if not isinstance(view_source, dict):
            view_source = {}
        view_fp = str(view_source.get("graph_fingerprint") or "")
        if not view_fp:
            errors.append("tg_host_view missing source.graph_fingerprint")
        elif graph_fp and view_fp != graph_fp:
            errors.append(
                f"tg_host_view fingerprint drift: view={view_fp!r} graph={graph_fp!r}"
            )
        if sqlite.is_file() and view_fp:
            try:
                import sqlite3

                with sqlite3.connect(str(sqlite)) as conn:
                    row = conn.execute(
                        "SELECT value FROM meta WHERE key='host_view_fingerprint'"
                    ).fetchone()
                    hv_fp = row[0] if row else ""
                    if hv_fp and hv_fp != view_fp:
                        errors.append(
                            "kb_graph host_view_fingerprint drift: "
                            f"meta={hv_fp!r} view={view_fp!r}"
                        )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"host_view_meta_failed: {exc}")
    ur = _load(unresolved)
    if not ur and db_ready:
        ur = load_view_blob(sqlite, "ir/unresolved.yaml") or {}
    q = _load(quality)
    if not q and db_ready:
        q = load_view_blob(sqlite, "quality.yaml") or {}
    blocker_count = int(ur.get("blocker_count") or len(ur.get("blockers") or []))
    doc = {
        "version": 1,
        "status": "pass" if not errors else "fail",
        "ok": not errors,
        "blocker_count": blocker_count,
        "source_closure": q.get("source_closure"),
        "graph_fingerprint": graph_fp,
        "errors": errors,
    }
    if sqlite.is_file():
        try:
            import json as _json
            import sqlite3

            conn = sqlite3.connect(str(sqlite))
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS view_blob("
                    "name TEXT PRIMARY KEY, schema_id TEXT, data TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES(?,?,?)",
                    (
                        "checks/integrity.yaml",
                        "",
                        _json.dumps(
                            doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                        ),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            set_meta_values(
                sqlite,
                {
                    "integrity_status": doc["status"],
                    "integrity_ok": doc["ok"],
                    "authority": "db",
                },
            )
        except Exception:  # noqa: BLE001
            pass
    # Always materialize the gate receipt on disk — the pilot integrity gate
    # and integrity-v1 contract read this path. The heavy YAML layers stay
    # opt-in via UO_KB_YAML; this file is a few hundred bytes.
    _dump(uo / "checks" / "integrity.yaml", doc)
    return {"ok": not errors, "engine": "export_integrity", **doc}


def kb_review(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Referee trigger: auto-skip when quality gate already green."""
    del payload
    from uo_init.kb_index import db_authority_ok, load_view_blob

    uo = _uo_root(project_root)
    q = _load(uo / "quality.yaml")
    ur = _load(uo / "ir" / "unresolved.yaml")
    host_meta = _load(uo / "ir" / "host_extract_receipt.yaml")
    sqlite = uo / "indexes" / "kb_graph.sqlite"
    if sqlite.is_file() and db_authority_ok(sqlite):
        if not q:
            blob = load_view_blob(sqlite, "quality.yaml")
            if isinstance(blob, dict):
                q = blob
        if not ur:
            blob = load_view_blob(sqlite, "ir/unresolved.yaml")
            if isinstance(blob, dict):
                ur = blob
    from uo_init.init_profile import review_skips_closure_gate

    closure = float(q.get("source_closure") or 0.0)
    blockers = int(ur.get("blocker_count") or len(ur.get("blockers") or []))
    closure_mode = str(host_meta.get("closure_mode") or "")
    # keypath/off never measured full source_closure — do not demand ≥0.95.
    if review_skips_closure_gate(closure_mode):
        auto_ok = blockers < 20
    else:
        auto_ok = closure >= 0.95 and blockers < 20
    review = {
        "version": 1,
        "status": "skipped" if auto_ok else "needs_review",
        "verdict": "pass" if auto_ok else "open",
        "source_closure": closure,
        "blocker_count": blockers,
        "closure_mode": closure_mode or "unknown",
        "init_profile": host_meta.get("init_profile") or "",
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
    "export_tg_host_view": export_tg_host_view,
    "export_adapter_pack": export_adapter_pack,
    "export_integrity": export_integrity,
    "kb_review": kb_review,
}
