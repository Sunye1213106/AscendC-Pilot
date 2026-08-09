# -*- coding: utf-8 -*-
"""Six public uo-init Actions for the CodeMap compiler.

Fine-grained extraction/normalization helpers remain internal implementation
steps.  The public control plane produces exactly one authority:
``.ascendc-pilot/uo/<op>.<arch>.uo``.
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


def analyze(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run deterministic normalization/derivation passes and emit gaps."""
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
    """Prepare/consume only explicit semantic-gap staging output."""
    return pe.resolve_gaps(project_root, payload)


def commit(project_root: Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compile current facts/source directly into the single ``.uo`` product.

    Legacy YAML/SQLite exports are not a prerequisite and are not refreshed as
    a second authority.  Debug/intermediate facts produced by earlier phases may
    still be consumed as compiler evidence by ``compile_codemap``.
    """
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
    try:
        from uo_init.build import compile_codemap
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

    host_ir = None
    kernel_ir = None
    key_fields: list[dict[str, Any]] = []
    declared: dict[str, Any] = {}
    uo = pe._uo_root(root, arch=arch)

    try:
        bundle = pe._ensure_bundle(root, ctx)
        host_ir = bundle.get("host_ir")
        kernel_ir = bundle.get("kernel_ir")
    except Exception:
        pass

    derivation = pe._load(uo / "ir" / "host_derivation.yaml")
    if isinstance(derivation, dict):
        key_fields = list(derivation.get("fields") or derivation.get("dimensions") or [])
    declared = pe._load(uo / "tiling" / "key_space.yaml") or pe._load(
        uo / "ir" / "tiling_key_bindings.yaml"
    ) or {}

    try:
        result = compile_codemap(
            op_name=op_name,
            architecture=arch,
            op_root=root,
            host_ir=host_ir,
            kernel_ir=kernel_ir,
            key_fields=key_fields,
            declared=declared if isinstance(declared, dict) else {},
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
    }
