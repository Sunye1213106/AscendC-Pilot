"""Mode-aware TG plan precheck.

The full TilingKey path is `.uo`-native. CSV-consumer compatibility keeps its
legacy initialization/fingerprint checks in the original precheck engine.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def plan_precheck(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.actions import engines as E
    from ascendc_pilot.actions.tg_plan_targets import _global_declared, _uo_identity

    tg_ctx = E._resolve_tg_ctx(project_root, ctx)
    if not E._is_tilingkey_full(tg_ctx):
        return E._run_tg_plan_precheck(project_root, ctx)
    try:
        arch = str(tg_ctx.get("architecture") or "").strip()
        if not arch:
            return {
                "ok": False,
                "engine": "plan_precheck",
                "error": "ARCHITECTURE_MISSING_IN_RUN_STATE",
                "reason_code": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            }
        uo = _uo_identity(
            project_root,
            op_name=str(tg_ctx.get("op_name") or project_root.name),
            architecture=arch,
        )
        declared = _global_declared(project_root)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_precheck", "error": str(exc)[:400]}
    return {
        "ok": bool(declared),
        "engine": "plan_precheck",
        "mode": "tilingkey_full_coverage",
        "uo": uo,
        "declared_count": len(declared),
        "policy": "uo_product_and_current_kernel_schema",
    }


def install(registry: dict[tuple[str, str], Callable[..., dict[str, Any]]]) -> None:
    registry[("tg-plan", "plan_precheck")] = plan_precheck
