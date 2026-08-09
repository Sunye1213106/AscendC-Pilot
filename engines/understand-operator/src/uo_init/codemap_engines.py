# -*- coding: utf-8 -*-
"""Six public uo-init Actions for the CodeMap compiler.

Fine-grained extract_*/normalize_*/export_* engines remain available as
internal steps; Pilot pipelines should call these composites only.
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
        # Propagate useful context forward.
        for key in ("op_name", "architecture", "arch_dir", "run_id"):
            if out.get(key) and not ctx.get(key):
                ctx[key] = out[key]
    return {"ok": True, "engine": engine, "steps": results}


def prepare(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """prepare = layout + scope scan + scope confirm (BuildVariant seeded)."""
    ctx = dict(payload or {})
    # Cold automation: probe-clean scopes auto-accept unless human must decide.
    ctx.setdefault("auto_accept_clean", True)
    steps: list[tuple[str, Callable[..., dict[str, Any]]]] = [
        ("prepare_layout", pe.prepare_layout),
        ("scope_scan", pe.scope_scan),
        ("scope_confirm", pe.scope_confirm),
    ]
    out = _chain(project_root, ctx, steps, engine="prepare")
    if out.get("ok"):
        # Seed BuildVariant marker under uo root.
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
    """extract = clang host/key/registry/kernel facts."""
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


def analyze(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """analyze = deterministic normalize / derive / predicate passes."""
    return _chain(
        project_root,
        payload,
        [
            ("normalize_variables", pe.normalize_variables),
            ("derive_key_fields", pe.derive_key_fields),
            ("normalize_predicates", pe.normalize_predicates),
        ],
        engine="analyze",
    )


def resolve(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """resolve = semantic gaps (staging producer). Merge via apply_gap_patch."""
    # Keep the same contract as resolve_gaps for subagent staging.
    return pe.resolve_gaps(project_root, payload)


def commit(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """commit = assemble KB + write single ``.uo`` CodeMap product."""
    ctx = dict(payload or {})
    # Optional merge of gap patch before commit.
    if ctx.get("apply_gap_patch", True):
        patch_out = pe.apply_gap_patch(project_root, ctx)
        if not patch_out.get("ok", False) and not ctx.get("allow_empty_gap_patch"):
            # Empty patch is fine.
            if patch_out.get("error") not in {None, "", "no_patch", "missing_patch"}:
                # Continue if there was simply nothing to apply.
                if "no" not in str(patch_out.get("error") or "").lower() and "missing" not in str(
                    patch_out.get("error") or ""
                ).lower():
                    pass

    chained = _chain(
        project_root,
        ctx,
        [
            ("export_kb", pe.export_kb_action),
            ("build_index", pe.build_index),
            ("export_tg_host_view", pe.export_tg_host_view),
            ("export_adapter_pack", pe.export_adapter_pack),
            ("export_integrity", pe.export_integrity),
        ],
        engine="commit",
    )
    if not chained.get("ok"):
        return chained

    # Compile unified CodeMap → ``.ascendc-pilot/uo/<op>.<arch>.uo``
    uo_write = _commit_uo_product(Path(project_root), ctx)
    chained["uo_product"] = uo_write
    if not uo_write.get("ok"):
        chained["ok"] = False
        chained["error"] = uo_write.get("error") or "uo_commit_failed"
    return chained


def review(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """review = structural CodeMap consistency + legacy kb_review."""
    ctx = dict(payload or {})
    root = Path(project_root).expanduser().resolve()
    structural = _structural_review(root, ctx)
    kb = pe.kb_review(project_root, ctx)
    ok = bool(structural.get("ok")) and bool(kb.get("ok"))
    return {
        "ok": ok,
        "engine": "review",
        "structural": structural,
        "kb_review": kb,
        "skipped": kb.get("skipped"),
        "need_subagent": kb.get("need_subagent"),
        "verdict": "pass" if ok and kb.get("verdict") == "pass" else kb.get("verdict") or "open",
    }


def _commit_uo_product(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        from uo_init.build import compile_codemap
        from uo_init.host_codemap import load_tg_host_view
        from uo_init.op_spec import discover
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"import_failed:{exc}"[:200]}

    root = project_root.expanduser().resolve()
    try:
        spec = discover(root, arch_dir=ctx.get("arch_dir"))
        op_name = str(ctx.get("op_name") or spec.op_name)
        arch = str(ctx.get("arch_dir") or spec.arch_dir or "arch35")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"discover_failed:{exc}"[:200]}

    uo = pe._uo_root(root, arch=arch)
    host_ir = None
    kernel_ir = None
    key_fields: list[dict[str, Any]] = []
    declared: dict[str, Any] = {}
    try:
        bundle = pe._ensure_bundle(root, ctx)
        host_ir = bundle.get("host_ir")
        kernel_ir = bundle.get("kernel_ir")
    except Exception:
        bundle = {}

    der = pe._load(uo / "ir" / "host_derivation.yaml")
    if isinstance(der, dict):
        key_fields = list(der.get("fields") or der.get("dimensions") or [])
    declared = pe._load(uo / "tiling" / "key_space.yaml") or pe._load(
        uo / "ir" / "tiling_key_bindings.yaml"
    ) or {}

    views: dict[str, Any] = {}
    try:
        view = load_tg_host_view(uo)
        if view:
            views["ir/tg_host_view.yaml"] = view
            views["tg_host_view"] = view
    except Exception:
        pass

    try:
        result = compile_codemap(
            op_name=op_name,
            architecture=arch,
            op_root=root,
            host_ir=host_ir,
            kernel_ir=kernel_ir,
            key_fields=key_fields,
            declared=declared if isinstance(declared, dict) else {},
            views=views,
            commit=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:400]}

    # Also stamp product path into legacy manifest when present.
    try:
        manifest = pe._load(uo / "manifest.yaml")
        if isinstance(manifest, dict):
            manifest["authority"] = "uo"
            manifest["product"] = result.get("path") or ""
            manifest["schema"] = "codemap-uo/v1"
            pe._dump(uo / "manifest.yaml", manifest)
    except Exception:
        pass
    return {
        "ok": bool(result.get("ok")),
        "path": result.get("path"),
        "summary": result.get("summary"),
        "gaps": result.get("gaps"),
        "uo": result.get("uo"),
    }


def _structural_review(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from uo_init.query.engine import open_codemap_query
    from uo_init.resolve.semantic_gap import list_gaps
    from uo_init.store.reader import find_uo_product

    arch = str(ctx.get("arch_dir") or ctx.get("architecture") or "arch35")
    op_name = str(ctx.get("op_name") or "")
    path = find_uo_product(project_root, op_name=op_name, architecture=arch)
    if path is None or path.suffix != ".uo":
        return {
            "ok": False,
            "error": "missing_uo_product",
            "message": "commit must write .ascendc-pilot/uo/<op>.<arch>.uo",
        }
    try:
        q = open_codemap_query(path)
        summary = q.summary()
        gaps = list_gaps(q.codemap)
        hard = [g for g in gaps if g.get("code") in {"missing_kernel", "missing_host_kernel_path"}]
        return {
            "ok": summary.get("has_host") and summary.get("has_kernel") and not hard,
            "path": str(path),
            "summary": summary,
            "gaps": gaps,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:400]}
