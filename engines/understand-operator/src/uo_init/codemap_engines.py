# -*- coding: utf-8 -*-
"""Five public uo-init Actions for the source-backed CodeMap compiler.

UO extracts facts an Agent can query.  It does not solve the operator's full
19-dimensional TilingKey function.  In particular the public analyze path does
not run ``derive_key_fields`` or a global host-reachability SAT pass. Test construction
and local lemma reasoning belong to TG.

Canonical ``.uo`` is compiler truth + deterministic derivation only.  Semantic
residuals stay in ``unresolved.yaml``; LLM must not patch them into the product.
Optional investigation lives under ``/uo-investigate``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from uo_init.paths import require_architecture
from uo_init import pilot_engines as pe


def _chain(
    project_root: Path,
    payload: dict[str, Any] | None,
    steps: list[tuple[str, Callable[..., dict[str, Any]]]],
    *,
    engine: str,
) -> dict[str, Any]:
    from uo_init.progress import emit

    ctx = dict(payload or {})
    results: list[dict[str, Any]] = []
    total = len(steps)
    for idx, (name, fn) in enumerate(steps, start=1):
        emit(f"{engine} ({idx}/{total}) {name} …")
        import time

        t0 = time.perf_counter()
        out = fn(project_root, ctx)
        dt = time.perf_counter() - t0
        ok = bool(out.get("ok", False))
        mark = "ok" if ok else "FAIL"
        emit(f"{engine} ({idx}/{total}) {name} {mark} ({dt:.1f}s)")
        results.append({"step": name, **{k: out.get(k) for k in ("ok", "error", "engine")}})
        if not ok:
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
    """Resolve Source Scope from operator+arch; machine-validate; seed BuildVariant.

    User chooses the analysis target. Clang decides the authoritative source
    closure. There is no human file-list confirmation and no decision=yes bypass.
    """
    ctx = dict(payload or {})
    out = _chain(
        project_root,
        ctx,
        [
            ("prepare_layout", pe.prepare_layout),
            ("scope_scan", pe.scope_scan),
            ("scope_validate", pe.scope_validate),
        ],
        engine="prepare",
    )
    if out.get("ok"):
        try:
            root = Path(project_root).expanduser().resolve()
            uo = pe._uo_root(root, arch=ctx.get("arch_dir"))
            arch = require_architecture(ctx.get("arch_dir") or ctx.get("architecture"))
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
    arch = require_architecture(ctx.get("arch_dir") or ctx.get("architecture") or spec.arch_dir)
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
        # to fall back to removed symbolic host-reachability logic.
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

    Residuals are recorded in ``ir/unresolved.yaml`` and retained — they are not
    LLM-resolved into canonical ``.uo``.
    """
    from uo_init.build import compile_codemap, store_compile_cache
    from uo_init.progress import step

    ctx = dict(payload or {})
    root = Path(project_root).expanduser().resolve()
    try:
        with step("analyze.resolve_inputs"):
            op_name, arch, host_ir, kernel_ir, declared, uo = _compiler_inputs(root, ctx)
        with step("analyze.compile_codemap"):
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
        with step("analyze.store_cache"):
            store_compile_cache(root, op_name, arch, result)
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
        "policy": "retain_unresolved_no_llm_patch",
        "non_goals": [
            "global_tilingkey_value_derivation",
            "global_host_reachability_sat",
            "container_cardinality_proofs",
            "read_coverage_implication_proofs",
            "llm_semantic_gap_patching",
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
        "compile_cached": True,
        "semantic_completeness": "complete" if not gaps else "partial",
    }
    pe._dump(uo / "ir" / "unresolved.yaml", unresolved)
    pe._dump(uo / "ir" / "codemap_analyze_receipt.yaml", receipt)
    return receipt


def resolve(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Optional / debug: stage gap blockers. Not part of default ``/uo-init``.

    Prefer ``/uo-investigate``. When called, LLM auto-resolve remains off unless
    ``UO_RESOLVE_GAPS_LLM=1`` / ``enable_llm=true``.
    """
    return pe.resolve_gaps(project_root, payload)


def commit(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compile current structural facts/source into the single ``.uo`` product.

    Open semantic residuals are allowed: commit writes a valid but possibly
    incomplete CodeMap (``semantic_completeness=partial``). Hard extraction
    failures still fail this stage.
    """
    from uo_init.progress import step

    ctx = dict(payload or {})
    with step("commit.write_uo_product"):
        product = _commit_uo_product(Path(project_root), ctx)
    return {
        "ok": bool(product.get("ok")),
        "engine": "commit",
        "uo_product": product,
        "path": product.get("path"),
        "summary": product.get("summary"),
        "gaps": product.get("gaps"),
        "reused_analyze": bool(product.get("reused_analyze")),
        **({"error": product.get("error") or "uo_commit_failed"} if not product.get("ok") else {}),
    }


def verify(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate graph legality / integrity of the committed ``.uo`` product.

    This is not semantic completeness: open ``unresolved`` blockers do not fail
    verify by themselves. Failures are schema/invariant/dangling-edge issues.

    Also materializes a lightweight ``uo/checks/integrity.yaml`` so Pilot gates
    and readiness consumers still have a workspace receipt (without requiring
    the legacy YAML KB export_integrity path).
    """
    from uo_init.progress import step

    ctx = dict(payload or {})
    root = Path(project_root).expanduser().resolve()
    try:
        from uo_init.diagnostics.audit import audit_uo
        from uo_init.store.reader import find_uo_product

        with step("verify.find_uo_product"):
            arch = require_architecture(ctx.get("arch_dir") or ctx.get("architecture"))
            op_name = str(ctx.get("op_name") or "")
            product = find_uo_product(root, op_name=op_name, architecture=arch)
        if product is None or product.suffix != ".uo":
            return {
                "ok": False,
                "engine": "verify",
                "error": "missing_uo_product",
                "message": "commit must write .ascendc-pilot/uo/<op>.<arch>.uo",
            }
        with step("verify.audit_uo"):
            report = audit_uo(product)
        ok = bool(report.get("ok"))
        with step("verify.write_integrity_receipt"):
            uo = pe._uo_root(root)
            integrity = {
                "version": 1,
                "schema": "uo-product-integrity/v1",
                "status": "pass" if ok else "fail",
                "ok": ok,
                "uo_product": str(product),
                "architecture": arch,
                "op_name": op_name or product.stem.split(".")[0],
                "audit_ok": ok,
                "source": "uo-init/verify",
            }
            pe._dump(uo / "checks" / "integrity.yaml", integrity)
        return {
            "ok": ok,
            "engine": "verify",
            "path": str(product),
            "audit": report,
            "verdict": "pass" if ok else "fail",
            "integrity": str(uo / "checks" / "integrity.yaml"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "verify", "error": str(exc)[:400], "verdict": "fail"}


def review(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Backward-compatible alias for :func:`verify`."""
    out = verify(project_root, payload)
    if isinstance(out, dict) and out.get("engine") == "verify":
        out = dict(out)
        out["engine"] = "review"
        out["alias_of"] = "verify"
    return out


def _commit_uo_product(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from uo_init.build import compile_codemap, load_compile_cache
    from uo_init.store.writer import uo_product_path, write_codemap
    from uo_init.tg_projection import require_commit_views

    root = project_root.expanduser().resolve()
    try:
        op_name, arch, host_ir, kernel_ir, declared, _uo = _compiler_inputs(root, ctx)
        cached = load_compile_cache(root, op_name, arch)
        if cached is not None and cached.get("codemap") is not None:
            views = cached.get("views") or {}
            missing = require_commit_views(views)
            if missing:
                return {
                    "ok": False,
                    "error": "TG_VIEW_INCOMPLETE",
                    "missing": missing,
                    "reused_analyze": True,
                }
            path = uo_product_path(root, op_name, arch)
            written = write_codemap(
                cached["codemap"],
                path,
                views=views,
                summary=cached.get("summary"),
            )
            return {
                "ok": bool(written.get("ok")),
                "path": written.get("path"),
                "summary": cached.get("summary"),
                "audit": cached.get("audit"),
                "gaps": cached.get("gaps"),
                "uo": written,
                "reused_analyze": True,
                "analysis_policy": "structure_and_provenance_only",
            }
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
        "error": result.get("error"),
        "missing": result.get("missing"),
        "reused_analyze": False,
        "analysis_policy": "structure_and_provenance_only",
    }
