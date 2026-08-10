"""Action runtime facade with TG primary-session specializations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ascendc_pilot.actions import engines as _engines
from ascendc_pilot.actions import runtime as _runtime
from ascendc_pilot.actions.fast_uo_engines import invoke_fast_uo_engine
from ascendc_pilot.actions.tg_plan_targets import install as _install_tg_plan_targets
from ascendc_pilot.actions.tg_primary import (
    PRIMARY_TG_ACTIONS,
    materialize_primary_decision,
    primary_interactive_steps,
    rollback_primary_decision,
)

# Public uo-init Actions are composites over deterministic compiler steps.
# Analyze now reports structural CodeMap gaps only; it no longer derives every
# TilingKey value expression or asks a global SAT solver to close the key space.
_UO_COMPOSITE_OUTPUT_CONTRACTS: dict[str, list[str]] = {
    "uo-prepare-v1": [
        "uo/runs/{run_id}/scope/scope_confirmed.yaml",
        "uo/runs/{run_id}/scope/receipt.yaml",
    ],
    "uo-extract-v1": [
        "uo/ir/host_extract_receipt.yaml",
        "uo/tiling/key_bind_receipt.yaml",
        "uo/tiling/families.yaml",
        "uo/kernel/fold_receipt.yaml",
    ],
    "uo-analyze-v1": [
        "uo/ir/codemap_analyze_receipt.yaml",
        "uo/ir/unresolved.yaml",
    ],
    "uo-commit-v1": ["uo/*.uo"],
    "uo-review-v1": ["uo/*.uo"],
}
_engines.OUTPUT_CONTRACT_PATHS.update(_UO_COMPOSITE_OUTPUT_CONTRACTS)
_engines.OUTPUT_CONTRACT_NONEMPTY_GLOBS.update(_UO_COMPOSITE_OUTPUT_CONTRACTS)

# Full TilingKey TG is plan-scoped: tg-plan freezes T, tg-solve closes exactly
# T with the existing replay/construct/lemma engine. CSV-consumer compatibility
# remains untouched and is the only route that may still use the SMT backend.
_install_tg_plan_targets(_engines.ENGINE_REGISTRY)


def _sanitize_semantic_bind_session(result: dict[str, Any]) -> None:
    """Ensure the producer stops after writing its staged patch."""

    if not result.get("ok") or result.get("action_id") != "semantic_bind":
        return
    replacements = {
        "然后执行：`acp run-action semantic_bind --finalize`":
            "写出补丁后立即停止并返回结果；由 Primary 执行 `acp run-action semantic_bind --finalize`。",
        "4. 执行 `acp run-action semantic_bind --finalize`（finalize 会应用补丁并校验）。":
            "4. 写出补丁后立即停止；不得执行 finalize。Primary 将调用 finalize 应用补丁并校验。",
    }
    for key in ("prompt_path", "method_path"):
        raw = str(result.get(key) or "")
        path = Path(raw) if raw else None
        if path is None or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for old, new in replacements.items():
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")


def _prepare_with_fast_uo_engine(project_root: Path, action_id: str) -> dict[str, Any]:
    """Scope a temporary engine router to one synchronous CLI prepare call."""

    original = _runtime.invoke_engine

    def routed(
        root: Path,
        workflow_id: str,
        engine_action_id: str,
        *,
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return invoke_fast_uo_engine(
            Path(root),
            workflow_id,
            engine_action_id,
            ctx=ctx,
            fallback=original,
        )

    _runtime.invoke_engine = routed
    try:
        return _runtime.prepare_action(project_root, action_id)
    finally:
        _runtime.invoke_engine = original


def prepare_action(project_root: Path, action_id: str) -> dict[str, Any]:
    result = _prepare_with_fast_uo_engine(project_root, action_id)
    _sanitize_semantic_bind_session(result)
    if result.get("ok") and action_id in PRIMARY_TG_ACTIONS:
        result["interactive_steps"] = primary_interactive_steps(
            action_id,
            Path(project_root),
            result,
        )
        result["dispatch_task"] = False
        result["message_zh"] = (
            f"已准备 TG primary_interactive Action `{action_id}`。"
            "请先审阅合同与 unresolved，并通过 AskQuestion 获取明确决定；"
            "只有确认/批准分支才能调用 --finalize。"
        )
    return result


def finalize_action(
    project_root: Path,
    action_id: str,
    *,
    engine_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if action_id not in PRIMARY_TG_ACTIONS or engine_result is not None:
        return _runtime.finalize_action(project_root, action_id, engine_result=engine_result)

    materialized = materialize_primary_decision(Path(project_root), action_id)
    if not materialized.get("ok"):
        return materialized

    result = _runtime.finalize_action(project_root, action_id)
    result["primary_decision_artifact"] = str(materialized.get("path") or "")
    if not result.get("ok"):
        rollback_primary_decision(materialized)
        result["primary_decision_rolled_back"] = True
    return result


def run_action(project_root: Path, action_id: str, *, finalize: bool = False) -> dict[str, Any]:
    if finalize:
        return finalize_action(project_root, action_id)
    return prepare_action(project_root, action_id)


__all__ = ["finalize_action", "prepare_action", "run_action"]
