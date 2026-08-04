"""Slash → workflow_id. Natural-language intent is agent + skill description, not this module."""

from __future__ import annotations

from typing import Any

from ascendc_pilot.workflows.specs import WORKFLOWS
from ascendc_pilot.workflows import list_user_workflows


CE_FUTURE_SLASHES = {
    "/ce-impact",
    "/ce-fix",
    "/ce-implement",
    "/ce-explain",
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

# Built from WORKFLOWS so slash map stays in sync with specs.
def _slash_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved"):
            continue
        slash = str(meta.get("slash") or "").strip()
        if slash:
            # Alias entries keep their slash but resolve to the target workflow.
            out[slash] = str(meta.get("alias_of") or wid)
    return out


def _skill_candidates() -> list[dict[str, str]]:
    """Name + short hint for agent skill selection (not keyword routing)."""
    items: list[dict[str, str]] = []
    for wid in list_user_workflows():
        meta = WORKFLOWS.get(wid) or {}
        items.append(
            {
                "workflow_id": wid,
                "slash": str(meta.get("slash") or f"/{wid}"),
                "hint_zh": str(meta.get("label_zh") or meta.get("description") or wid),
            }
        )
    return items


_UNMATCHED_MSG_ZH = (
    "自然语言意图请由 Agent 按 workflow skill 的 description 自行加载对应 Skill，"
    "然后执行 acp start <workflow_id>。"
    "acp route 仅支持 slash（如 /uo-init）。"
)


def route(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {
            "ok": False,
            "workflow_id": None,
            "error": "empty_input",
            "candidates": list_user_workflows(),
            "skill_candidates": _skill_candidates(),
            "message_zh": _UNMATCHED_MSG_ZH,
        }

    # /operator is an optional alias for acp route — strip and re-route
    first = raw.split()[0]
    if first in {"/operator", "operator"}:
        rest = raw[len(first) :].strip()
        if not rest:
            return {
                "ok": False,
                "workflow_id": None,
                "error": "operator_needs_intent",
                "message_zh": "请加载对应 workflow skill，或使用 slash（例如 /operator /uo-init）",
                "candidates": list_user_workflows(),
                "skill_candidates": _skill_candidates(),
            }
        inner = route(rest)
        if inner.get("ok"):
            inner = dict(inner)
            inner["via"] = "operator"
        return inner

    if first in CE_FUTURE_SLASHES or first.lstrip("/") in {s.lstrip("/") for s in CE_FUTURE_SLASHES}:
        return dict(CE_NOT_IMPLEMENTED)

    slash_map = _slash_map()
    # Exact slash (first token)
    if first in slash_map:
        wid = slash_map[first]
        return {
            "ok": True,
            "workflow_id": wid,
            "slash": WORKFLOWS[wid].get("slash"),
            "method": "slash",
        }

    # Also accept bare workflow id as first token (uo-init)
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
        "error": "unmatched",
        "candidates": list_user_workflows(),
        "skill_candidates": _skill_candidates(),
        "message_zh": _UNMATCHED_MSG_ZH,
    }
