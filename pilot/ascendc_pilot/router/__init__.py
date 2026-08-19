"""Deterministic slash dispatch. Free-form natural language stays with Primary."""

from __future__ import annotations

from typing import Any

from ascendc_pilot.workflows.specs import WORKFLOWS
from ascendc_pilot.workflows import list_user_workflows


CE_FUTURE_SLASHES = {
    "/ce-form",
    "/ce-implement",
    "/ce-debug",
    "/ce-refactor",
}

CE_NOT_IMPLEMENTED = {
    "ok": False,
    "workflow_id": None,
    "error": "not_implemented",
    "message": (
        "Not implemented.\n"
        "This capability is reserved for future development."
    ),
}


def _slash_map() -> dict[str, str]:
    """Build exact slash → workflow mapping from the workflow spec SSOT."""
    out: dict[str, str] = {}
    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved"):
            continue
        slash = str(meta.get("slash") or "").strip()
        if slash:
            out[slash] = str(meta.get("alias_of") or wid)
    return out


def _workflow_candidates() -> list[dict[str, str]]:
    """Expose workflow ids + descriptions to Primary; never keyword-route them here."""
    items: list[dict[str, str]] = []
    for wid in list_user_workflows():
        meta = WORKFLOWS.get(wid) or {}
        items.append(
            {
                "workflow_id": wid,
                "slash": str(meta.get("slash") or f"/{wid}"),
                "description": str(
                    meta.get("when_to_use")
                    or meta.get("description")
                    or meta.get("label_zh")
                    or wid
                ),
            }
        )
    return items


_UNMATCHED_MSG_ZH = (
    "这是自然语言请求：由 Primary 根据用户目标、当前产物和 workflow description 形成/更新 Task Plan，"
    "再调用 `pilot_run(workflow=<next_workflow_id>)`。本 Router 不做业务意图分类、关键词路由或黄金句匹配。"
)


def route(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {
            "ok": False,
            "workflow_id": None,
            "error": "empty_input",
            "candidates": list_user_workflows(),
            "workflow_candidates": _workflow_candidates(),
            "message_zh": _UNMATCHED_MSG_ZH,
        }

    first = raw.split()[0]
    if first in {"/operator", "operator"}:
        rest = raw[len(first) :].strip()
        if not rest:
            return {
                "ok": False,
                "workflow_id": None,
                "error": "operator_needs_intent",
                "message_zh": "请给出自然语言目标，或使用显式 slash（例如 /operator /uo-init）",
                "candidates": list_user_workflows(),
                "workflow_candidates": _workflow_candidates(),
            }
        inner = route(rest)
        if inner.get("ok"):
            inner = dict(inner)
            inner["via"] = "operator"
        return inner

    if first in CE_FUTURE_SLASHES or first.lstrip("/") in {s.lstrip("/") for s in CE_FUTURE_SLASHES}:
        return dict(CE_NOT_IMPLEMENTED)

    slash_map = _slash_map()
    if first in slash_map:
        wid = slash_map[first]
        return {
            "ok": True,
            "workflow_id": wid,
            "slash": WORKFLOWS[wid].get("slash"),
            "method": "slash",
        }

    if first in WORKFLOWS and (WORKFLOWS[first].get("slash") and not WORKFLOWS[first].get("reserved")):
        meta = WORKFLOWS[first]
        wid = str(meta.get("alias_of") or first)
        return {
            "ok": True,
            "workflow_id": wid,
            "slash": WORKFLOWS[wid].get("slash") if wid in WORKFLOWS else meta.get("slash"),
            "method": "workflow_id",
        }

    return {
        "ok": False,
        "workflow_id": None,
        "error": "primary_agent_route_required",
        "agent_route_required": True,
        "candidates": list_user_workflows(),
        "workflow_candidates": _workflow_candidates(),
        # Compatibility alias for older Host adapters. It contains the same
        # workflow descriptions, not skill ids and not a semantic router.
        "skill_candidates": _workflow_candidates(),
        "message_zh": _UNMATCHED_MSG_ZH,
    }
