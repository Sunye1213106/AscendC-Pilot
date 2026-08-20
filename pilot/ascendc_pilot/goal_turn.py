# -*- coding: utf-8 -*-
"""Classify a user turn against the active Goal (conversation, not workflow).

Relations: answer | continue | revise | side_question | switch | cancel.
Conservative: long text that merely mentions a legal arch* is never an answer.
"""

from __future__ import annotations

import re
from typing import Any

REL_ANSWER = "answer"
REL_CONTINUE = "continue"
REL_REVISE = "revise"
REL_SIDE = "side_question"
REL_SWITCH = "switch"
REL_CANCEL = "cancel"

RELATIONS = frozenset(
    {REL_ANSWER, REL_CONTINUE, REL_REVISE, REL_SIDE, REL_SWITCH, REL_CANCEL}
)

_ARCH_TOKEN = re.compile(r"\barch[0-9A-Za-z._-]+\b", re.I)
_ANSWER_ARCH = re.compile(
    r"^(?:请?选|用|就用|就选|用这个|选这个)?\s*arch[0-9A-Za-z._-]+\s*(?:吧|。|！|!)?$",
    re.I,
)
_ANSWER_SHORT_MAX = 24

# New intent / interrupt — never treat as answering a stale AskQuestion.
_NON_ANSWER_CUES = (
    "先别",
    "先不做",
    "先做别的",
    "另外",
    "问一下",
    "我想问",
    "顺便问",
    "改需求",
    "换个",
    "换话题",
    "不要建",
    "先别建",
    "先回答",
    "这个不要了",
    "放下",
    "暂停这个",
    "帮我 review",
    "帮我看一下",
    "先做",
)

_REVISE_CUES = (
    "还要一起",
    "另外支持",
    "补充需求",
    "还要支持",
    "再加上",
    "也要支持",
    "改一下需求",
    "中途加",
    "补一个要求",
    "还有一个要求",
    "还要加",
)

_SWITCH_CUES = (
    "先不做这个",
    "帮我 review",
    "换个任务",
    "先做别的",
    "放下这个",
    "暂停这个",
    "换话题",
    "先别建",
    "先别确认",
)

_CANCEL_CUES = (
    "这个不要了",
    "删掉重新来",
    "取消这个任务",
    "终止本次",
    "不要这个了",
)

_CONTINUE_CUES = (
    "继续上次",
    "接着做",
    "继续当前",
)

_INIT_ARCH_CUES = (
    "建库",
    "建立 codemap",
    "建立 CodeMap",
    "uo-init",
    "/uo-init",
    "更新 codemap",
    "更新 CodeMap",
    "uo-update",
    "/uo-update",
)

_QUERY_CUES = (
    "怎么",
    "如何",
    "哪来的",
    "是什么",
    "问一下",
    "查一下",
    "tilingkey",
    "tiling",
    "s1inner",
    "sparsemode",
)


def _has_cue(text: str, cues: tuple[str, ...]) -> bool:
    s = str(text or "")
    if not s:
        return False
    low = s.lower()
    for cue in cues:
        if cue.lower() in low or cue in s:
            return True
    return False


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip().lower()


def is_answer_shaped(text: str, *, pending: dict[str, Any] | None = None) -> bool:
    """True only when the turn is clearly choosing a pending option."""
    raw = str(text or "").strip()
    if not raw:
        return False
    if _has_cue(raw, _NON_ANSWER_CUES):
        return False
    if _ANSWER_ARCH.fullmatch(raw):
        return True
    compact = compact_text(raw)
    if pending:
        from ascendc_pilot.human_interaction import _option_catalog

        for value, labels in _option_catalog(pending):
            if raw == value or compact == compact_text(value):
                return True
            for lab in labels:
                if raw == lab or compact == compact_text(lab):
                    return True
        from ascendc_pilot.human_interaction import (
            extract_existing_directory,
            pending_allows_free_path,
        )

        if pending_allows_free_path(pending) and extract_existing_directory(raw):
            return True
    if len(raw) <= _ANSWER_SHORT_MAX and not _has_cue(raw, _QUERY_CUES):
        return True
    return False


def is_architecture_pin_turn(text: str) -> bool:
    """Whether a unique arch* in this message may pin/select architecture.

    Init/update requests may name arch35 in a longer sentence. Side questions
    and 'don't build yet' must not silently pin.
    """
    raw = str(text or "").strip()
    if not raw:
        return False
    if _has_cue(raw, _NON_ANSWER_CUES):
        return False
    if _ANSWER_ARCH.fullmatch(raw):
        return True
    if _has_cue(raw, _INIT_ARCH_CUES) and _ARCH_TOKEN.search(raw):
        return True
    if len(raw) <= _ANSWER_SHORT_MAX and _ARCH_TOKEN.search(raw):
        return True
    return False


def classify_goal_turn(
    text: str,
    *,
    pending: dict[str, Any] | None = None,
    workflow_id: str = "",
    goal: dict[str, Any] | None = None,
) -> str:
    """Map the latest user message to a Goal relation."""
    del goal
    raw = str(text or "").strip()
    pending_open = False
    if pending:
        from ascendc_pilot.human_interaction import pending_is_open

        pending_open = pending_is_open(pending)

    if pending_open and is_answer_shaped(raw, pending=pending):
        return REL_ANSWER

    if _has_cue(raw, _CANCEL_CUES):
        return REL_CANCEL
    if _has_cue(raw, _REVISE_CUES):
        return REL_REVISE
    if _has_cue(raw, _SWITCH_CUES):
        return REL_SWITCH
    if _has_cue(raw, _CONTINUE_CUES) or raw in {"继续", "continue"}:
        return REL_CONTINUE if not pending_open else REL_ANSWER

    wid = str(workflow_id or "").strip()
    if _has_cue(raw, _QUERY_CUES) or ("？" in raw or "?" in raw):
        if pending_open:
            return REL_SIDE
        if wid.startswith("ce-") and _has_cue(raw, _REVISE_CUES):
            return REL_REVISE
        return REL_SIDE

    if pending_open:
        return REL_SIDE
    if wid.startswith("ce-") and len(raw) > _ANSWER_SHORT_MAX:
        if _has_cue(raw, _REVISE_CUES):
            return REL_REVISE
    return REL_SIDE if raw else REL_CONTINUE
