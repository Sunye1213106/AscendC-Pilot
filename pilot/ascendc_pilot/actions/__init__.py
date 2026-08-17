"""Action runtime facade with TG primary-session specializations."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ascendc_pilot.actions import engines as _engines
from ascendc_pilot.actions import runtime as _runtime
from ascendc_pilot.actions.fast_uo_engines import invoke_fast_uo_engine
from ascendc_pilot.actions.tg_compaction import compact_after_plan_approve
from ascendc_pilot.actions.tg_full_precheck import install as _install_tg_full_precheck
from ascendc_pilot.actions.tg_plan_targets import install as _install_tg_plan_targets
from ascendc_pilot.actions.uo_product_compaction import install as _install_uo_product_compaction
from ascendc_pilot.human_confirm import (
    compact_key,
    is_hosted_confirm,
    materialize_primary_decision,
    primary_interactive_steps,
    rollback_primary_decision,
)

_UO_COMPOSITE_OUTPUT_CONTRACTS: dict[str, list[str]] = {
    "uo-prepare-v1": [
        "uo/manifest.yaml",
        "uo/operator.yaml",
        "uo/ir/build_variant.yaml",
        "uo/runs/{run_id}/scope/scope_validated.yaml",
        "uo/runs/{run_id}/scope/receipt.yaml",
    ],
    "uo-extract-v1": [
        "uo/ir/host_extract_receipt.yaml",
        "uo/ir/kernel_ir.yaml",
    ],
    "uo-analyze-v1": [
        "uo/ir/codemap_analyze_receipt.yaml",
        "uo/ir/unresolved.yaml",
    ],
    "uo-commit-v1": ["uo/*.uo"],
    "uo-verify-v1": ["uo/checks/integrity.yaml", "uo/checks/quality.yaml"],
    "uo-investigate-v1": [
        "uo/ir/gap_investigation.yaml",
        "runs/{run_id}/actions/investigate/report.yaml",
    ],
}
_TG_LOOP_OUTPUT_CONTRACTS: dict[str, list[str]] = {
    "lemma-loop-v1": ["tg/closure/lemma_loop.yaml"],
}
_engines.OUTPUT_CONTRACT_PATHS.update(_UO_COMPOSITE_OUTPUT_CONTRACTS)
_engines.OUTPUT_CONTRACT_PATHS.update(_TG_LOOP_OUTPUT_CONTRACTS)
_engines.OUTPUT_CONTRACT_NONEMPTY_GLOBS.update(_UO_COMPOSITE_OUTPUT_CONTRACTS)
_engines.OUTPUT_CONTRACT_NONEMPTY_GLOBS.update(_TG_LOOP_OUTPUT_CONTRACTS)

_install_tg_plan_targets(_engines.ENGINE_REGISTRY)
_install_tg_full_precheck(_engines.ENGINE_REGISTRY)
_install_uo_product_compaction(_engines.ENGINE_REGISTRY)


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


_NATIVE_TASK_RESULT_CAP = 200_000


def _strip_kb_answer_fences(text: str) -> str:
    """Keep the Explore-style prose; drop trailing kb-answer-v1 fences."""
    raw = str(text or "")
    return re.sub(
        r"```(?:ya?ml)?\s*\n[\s\S]*?schema\s*:\s*kb-answer-v1[\s\S]*?```",
        "",
        raw,
        flags=re.I,
    ).strip()


def _parse_host_action_result(text: str) -> dict[str, Any] | None:
    """Parse a native Task final message (Cursor Explore style).

    The full child message is the payload. A trailing ``kb-answer-v1`` fence
    is only a status/adequacy trailer — never a replacement for the prose.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    fenced = re.findall(r"```(?:yaml|yml)?\s*\n([\s\S]*?)```", raw, flags=re.I)
    candidates = [c.strip() for c in fenced if "kb-answer-v1" in c]
    candidates.extend([c.strip() for c in fenced if c.strip() and c.strip() not in candidates])
    candidates.append(raw)
    try:
        import yaml
    except ImportError:  # pragma: no cover
        yaml = None  # type: ignore[assignment]
    structured: dict[str, Any] | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = yaml.safe_load(candidate) if yaml is not None else None
        except Exception:  # noqa: BLE001
            data = None
        if isinstance(data, dict):
            structured = data
            break
    prose = _strip_kb_answer_fences(raw)[:_NATIVE_TASK_RESULT_CAP]
    if structured is None:
        return {
            "schema": "kb-answer-v1",
            "status": "ANSWERED",
            "answer_zh": raw[:_NATIVE_TASK_RESULT_CAP],
            "adequacy": "ANSWERED",
            "_transport": "native_task",
        }
    yaml_zh = str(structured.get("answer_zh") or structured.get("answer") or "").strip()
    if len(prose) > len(yaml_zh):
        structured["answer_zh"] = prose
    structured.setdefault("schema", "kb-answer-v1")
    structured["_transport"] = "native_task"
    return structured


def _host_action_result_from_env(
    project_root: Path,
    action_id: str,
) -> dict[str, Any] | None:
    """Read an ephemeral Host→Runtime Task return without cross-run leakage.

    New Host adapters stamp project/action alongside the payload. Missing stamps
    remain accepted for manual compatibility, but an explicit mismatch is
    rejected rather than applying one Task result to another project/action.
    """
    text = os.environ.get("ASCENDC_ACTION_RESULT", "")
    if not text.strip():
        return None
    env_project = str(os.environ.get("ASCENDC_ACTION_RESULT_PROJECT") or "").strip()
    if env_project:
        try:
            if Path(env_project).expanduser().resolve() != Path(project_root).expanduser().resolve():
                return None
        except OSError:
            return None
    env_action = str(os.environ.get("ASCENDC_ACTION_RESULT_ACTION") or "").strip()
    if env_action and env_action != str(action_id):
        return None
    return _parse_host_action_result(text)


def prepare_action(project_root: Path, action_id: str) -> dict[str, Any]:
    result = _prepare_with_fast_uo_engine(project_root, action_id)
    root = Path(project_root)
    wid = str(result.get("workflow_id") or "")
    if result.get("ok") and is_hosted_confirm(root, action_id, workflow_id=wid):
        result["interactive_steps"] = primary_interactive_steps(
            action_id,
            root,
            result,
            workflow_id=wid,
        )
        result["dispatch_task"] = False
        result["message_zh"] = (
            f"已准备需要你确认的步骤 `{action_id}`。"
            "请按弹出的选项作答；只有确认/批准分支才能调用 --finalize。"
        )
    return result


def finalize_action(
    project_root: Path,
    action_id: str,
    *,
    engine_result: dict[str, Any] | None = None,
    result_file: Path | str | None = None,
    action_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_root)
    if engine_result is not None or not is_hosted_confirm(root, action_id):
        return _runtime.finalize_action(
            project_root,
            action_id,
            engine_result=engine_result,
            result_file=result_file,
            action_result=action_result,
        )

    materialized = materialize_primary_decision(root, action_id)
    if not materialized.get("ok"):
        return materialized

    result = _runtime.finalize_action(project_root, action_id)
    result["primary_decision_artifact"] = str(materialized.get("path") or "")
    if not result.get("ok"):
        rollback_primary_decision(materialized)
        result["primary_decision_rolled_back"] = True
        return result

    if compact_key(root, action_id) == "plan_approve":
        compact = compact_after_plan_approve(root)
        result["compaction"] = compact
        if not compact.get("ok"):
            result["compaction_warning"] = "TG_COMPACTION_INCOMPLETE"
    return result


def run_action(
    project_root: Path,
    action_id: str,
    *,
    finalize: bool = False,
    result_file: Path | str | None = None,
    action_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not finalize and action_id in {"auto", "drive"}:
        from ascendc_pilot.actions.drive import drive_until_interaction

        return drive_until_interaction(
            Path(project_root),
            prepare=prepare_action,
        )
    if finalize and action_id in {"auto", "drive"}:
        return {
            "ok": False,
            "error": "AUTO_DRIVE_NOT_FINALIZABLE",
            "message_zh": "auto/drive 是 Host 调度动作，不是可 finalize 的 Workflow Action。",
        }
    if finalize:
        # Explicit API/result-file values take precedence. Otherwise consume the
        # Host's one-shot in-memory Task result scoped to this project/action.
        env_result = None
        if action_result is None and result_file is None:
            env_result = _host_action_result_from_env(Path(project_root), action_id)
        return finalize_action(
            project_root,
            action_id,
            result_file=result_file,
            action_result=action_result or env_result,
        )
    return prepare_action(project_root, action_id)


__all__ = [
    "finalize_action",
    "prepare_action",
    "run_action",
    "_parse_host_action_result",
    "_host_action_result_from_env",
]
