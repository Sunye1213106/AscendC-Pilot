# -*- coding: utf-8 -*-
"""Six public uo-init Actions for the source-backed CodeMap compiler.

UO extracts facts an Agent can query.  It does not solve the operator's full
19-dimensional TilingKey function.  In particular the public analyze path does
not run ``derive_key_fields`` / KeyReachability / global SAT.  Test construction
and local lemma reasoning belong to TG.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from uo_init import pilot_engines as pe


def _chain(
    project_root: Path,
    payload: dict[str, Any] | None,
    steps: list[tuple[str, Callable[..., dict[str, Any]]]],
    *,
    engine: str,
) -> dict[str, Any]:
    ctx = dict(payload or {})
    results: list[dict[str, Any]] = []
    for name, fn in steps:
        out = fn(project_root, ctx)
        results.append({"step": name, **{k: out.get(k) for k in ("ok", "error", "engine")}})
        if not out.get("ok", False):
            return {
                "ok": False,
                "engine": engine,
                "failed_step": name,
                "error": out.get("error") or out.get("message_zh") or f"{name} failed",
                "steps": results,
                "detail": out,
            }
        for key in ("op_name", "architecture", "arch_dir", "run_id"):
            if out.get(key) and not ctx.get(key):
                ctx[key] = out[key]
    return {"ok": True, "engine": engine, "steps": results}


def prepare(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Discover source scope and seed the selected BuildVariant."""
    ctx = dict(payload or {})
    ctx.setdefault("auto_accept_clean", True)
    out = _chain(
        project_root,
        ctx,
        [
            ("prepare_layout", pe.prepare_layout),
            ("scope_scan", pe.scope_scan),
            ("scope_confirm", pe.scope_confirm),
        ],
        engine="prepare",
    )
    if out.get("ok"):
        try:
            root = Path(project_root).expanduser().resolve()
            uo = pe._uo_root(root, arch=ctx.get("arch_dir"))
            arch = str(ctx.get("arch_dir") or ctx.get("architecture") or "arch35")
            pe._dump(
                uo / "ir" / "build_variant.yaml",
                {
                    "schema": "build-variant/v1",
                    "architecture": arch,
                    "name": arch,
                    "source": "uo_init.codemap_engines.prepare",
                },
            )
        except Exception as exc:  # noqa: BLE001
            out["build_variant_warning"] = str(exc)[:200]
    return out


def extract(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run deterministic Clang/frontend extraction."""
    return _chain(
        project_root,
        payload,
        [
            ("extract_host", pe.extract_host),
            ("extract_tiling_key", pe.extract_tiling_key),
            ("extract_registry", pe.extract_registry),
            ("extract_kernel", pe.extract_kernel),
        ],
        engine="extract",
    )


def _compiler_inputs(
    project_root: Path, ctx: dict[str, Any]
) -> tuple[str, str, Any, Any, dict[str, Any], Path]:
    """Resolve only structural inputs for CodeMap compilation.

    ``tiling/key_space.yaml`` is a deterministic declaration/schema artefact and
    is allowed.  ``host_derivation.yaml`` and per-key value expressions are
    intentionally not loaded here.
    """
    from uo_init.op_spec import discover

    root = project_root.expanduser().resolve()
    spec = discover(root, arch_dir=ctx.get("arch_dir"))
    op_name = str(ctx.get("op_name") or spec.op_name)
    arch = str(ctx.get("arch_dir") or ctx.get("architecture") or spec.arch_dir or "arch35")
    uo = pe._uo_root(root, arch=arch)

    host_ir = None
    kernel_ir = None
    try:
        bundle = pe._ensure_bundle(root, ctx)
        host_ir = bundle.get("host_ir")
        kernel_ir = bundle.get("kernel_ir")
    except Exception:
        # Current-source enrichment in compile_codemap remains authoritative;
        # missing compiler IR becomes an explicit structural gap, not a reason
        # to fall back to symbolic Key derivation.
        pass

    declared = pe._load(uo / "tiling" / "key_space.yaml") or pe._load(
        uo / "ir" / "tiling_key_bindings.yaml"
    ) or {}
    if not isinstance(declared, dict):
        declared = {}
    return op_name, arch, host_ir, kernel_ir, declared, uo


def analyze(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a structural CodeMap dry-run and emit only extraction gaps.

    This stage answers: did UO recover API, Host provenance, TilingKey packing,
    TilingData transport, template/kernel structure and evidence-backed paths?
    It explicitly does *not* answer whether every declared packed key is
    reachable or derive a closed-form formula for every key dimension.
    """
    from uo_init.build import compile_codemap

    ctx = dict(payload or {})
    root = Path(project_root).expanduser().resolve()
    try:
        op_name, arch, host_ir, kernel_ir, declared, uo = _compiler_inputs(root, ctx)
        result = compile_codemap(
            op_name=op_name,
            architecture=arch,
            op_root=root,
            host_ir=host_ir,
            kernel_ir=kernel_ir,
            declared=declared,
            key_fields=[],
            commit=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "analyze", "error": str(exc)[:400]}

    gaps = [g for g in (result.get("gaps") or []) if isinstance(g, dict)]
    unresolved = {
        "schema": "codemap-structural-gaps/v1",
        "status": "unresolved" if gaps else "closed",
        "blocker_count": len(gaps),
        "derivation_blocker_count": 0,
        "blockers": gaps,
        "scope": "structural_source_extraction",
        "non_goals": [
            "global_tilingkey_value_derivation",
            "global_key_reachability_sat",
            "container_cardinality_proofs",
            "read_coverage_implication_proofs",
        ],
    }
    receipt = {
        "ok": True,
        "engine": "analyze",
        "schema": "uo-codemap-analyze/v1",
        "op_name": op_name,
        "architecture": arch,
        "summary": dict(result.get("summary") or {}),
        "gap_count": len(gaps),
        "analysis_policy": "structure_and_provenance_only",
        "deep_key_derivation": False,
        "global_sat": False,
    }
    pe._dump(uo / "ir" / "unresolved.yaml", unresolved)
    pe._dump(uo / "ir" / "codemap_analyze_receipt.yaml", receipt)
    return receipt


def resolve(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Escalate only structural gaps that deterministic extraction left open."""
    return pe.resolve_gaps(project_root, payload)


def commit(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compile current structural facts/source into the single ``.uo`` product."""
    ctx = dict(payload or {})
    product = _commit_uo_product(Path(project_root), ctx)
    return {
        "ok": bool(product.get("ok")),
        "engine": "commit",
        "uo_product": product,
        "path": product.get("path"),
        "summary": product.get("summary"),
        "gaps": product.get("gaps"),
        **({"error": product.get("error") or "uo_commit_failed"} if not product.get("ok") else {}),
    }


def review(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the strict binary CodeMap audit; no legacy KB review layer."""
    ctx = dict(payload or {})
    root = Path(project_root).expanduser().resolve()
    try:
        from uo_init.diagnostics.audit import audit_uo
        from uo_init.store.reader import find_uo_product

        arch = str(ctx.get("arch_dir") or ctx.get("architecture") or "arch35")
        op_name = str(ctx.get("op_name") or "")
        product = find_uo_product(root, op_name=op_name, architecture=arch)
        if product is None or product.suffix != ".uo":
            return {
                "ok": False,
                "engine": "review",
                "error": "missing_uo_product",
                "message": "commit must write .ascendc-pilot/uo/<op>.<arch>.uo",
            }
        report = audit_uo(product)
        return {
            "ok": bool(report.get("ok")),
            "engine": "review",
            "path": str(product),
            "audit": report,
            "verdict": "pass" if report.get("ok") else "fail",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "review", "error": str(exc)[:400], "verdict": "fail"}


def _commit_uo_product(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from uo_init.build import compile_codemap

    root = project_root.expanduser().resolve()
    try:
        op_name, arch, host_ir, kernel_ir, declared, _uo = _compiler_inputs(root, ctx)
        result = compile_codemap(
            op_name=op_name,
            architecture=arch,
            op_root=root,
            host_ir=host_ir,
            kernel_ir=kernel_ir,
            declared=declared,
            key_fields=[],
            commit=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:400]}

    return {
        "ok": bool(result.get("ok")),
        "path": result.get("path"),
        "summary": result.get("summary"),
        "audit": result.get("audit"),
        "gaps": result.get("gaps"),
        "uo": result.get("uo"),
        "analysis_policy": "structure_and_provenance_only",
    }
