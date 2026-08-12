"""Harness-wrapped UO scope steps via uo_init.pilot_engines."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ascendc_pilot.io import print_json


def print_result(payload: dict[str, Any]) -> int:
    """CLI adapter for the legacy-compatible ``uo-scope`` wrapper."""
    print_json(payload)
    ok = payload.get("ok")
    if ok is None:
        obs = payload.get("observation") if isinstance(payload, dict) else None
        if isinstance(obs, dict):
            ok = str(obs.get("outcome") or "") == "success"
        else:
            ok = False
    return 0 if bool(ok) else 1


def _resolve_op_name(project: Path, op_name: str) -> str:
    name = str(op_name or "").strip()
    return name or project.name


def _record_step_result(
    project: Path,
    payload: dict[str, Any],
    *,
    action_id: str,
    step_id: str,
    messages: list[str] | None = None,
) -> dict[str, Any]:
    from ascendc_pilot.observation import record_pilot_result

    ok = bool(payload.get("ok"))
    msgs = list(messages or [])
    extra_msgs = payload.get("messages")
    if isinstance(extra_msgs, list):
        msgs.extend(str(m) for m in extra_msgs if m)
    if not ok and payload.get("error"):
        msgs.append(str(payload["error"]))
    return record_pilot_result(
        project,
        ok=ok,
        action_id=action_id or "uo_scope",
        step_id=step_id,
        messages=msgs,
        extra=payload,
    )


def run_uo_scope(
    project: Path | str,
    step: str,
    *,
    op_name: str = "",
    architecture: str = "arch35",
    decision: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Map legacy acp uo-scope steps onto uo_init.pilot_engines."""
    root = Path(project).expanduser().resolve()
    op = _resolve_op_name(root, op_name)
    ctx = {"op_name": op, "arch_dir": architecture or "arch35", "run_id": ""}
    try:
        from ascendc_pilot.state import load_state

        st = load_state(root) or {}
        ctx["run_id"] = str(st.get("run_id") or "")
    except Exception:  # noqa: BLE001
        pass

    from uo_init import pilot_engines as pe

    step = str(step or "").strip().lower()
    mapping = {
        "prepare": "prepare_layout",
        "prepare_layout": "prepare_layout",
        "scan": "scope_scan",
        "scope_scan": "scope_scan",
        "validate": "scope_validate",
        "scope_validate": "scope_validate",
        # Deprecated aliases — still map to machine validate; prefer `acp run-action prepare`.
        "confirm": "scope_validate",
        "scope_confirm": "scope_validate",
        "checkpoint": "scope_validate",
        "finalize": "scope_validate",
    }
    if step in {"build-evidence", "closure", "stage", "record-index", "stage_cbm"}:
        payload = {
            "ok": False,
            "error": "legacy_scope_step_removed",
            "message_zh": f"步骤 {step} 已随旧引擎移除；请使用 acp run-action prepare（machine Clang scope）",
            "step": step,
        }
        return _record_step_result(root, payload, action_id="uo_scope", step_id=step)

    action = mapping.get(step)
    if action is None:
        payload = {"ok": False, "error": f"unknown_step:{step}", "step": step}
        return _record_step_result(root, payload, action_id="uo_scope", step_id=step)

    if action == "scope_validate" and decision:
        # Notes only — never promote decision=yes into a compiler bypass.
        ctx["decision"] = decision
        ctx["notes"] = notes

    fn = pe.ENGINES[action]
    try:
        out = fn(root, ctx)
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "error": str(exc)[:400], "engine": action}
    out = dict(out or {})
    out.setdefault("step", step)
    out.setdefault("engine", action)
    recorded = _record_step_result(root, out, action_id=action, step_id=step)
    # Observation wrapper historically omitted top-level ``ok``; drivers and
    # print_result need it to distinguish success from parse-only payloads.
    recorded = dict(recorded or {})
    recorded.setdefault("ok", bool(out.get("ok")))
    return recorded
