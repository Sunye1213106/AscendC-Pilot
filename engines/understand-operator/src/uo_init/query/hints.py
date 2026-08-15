# -*- coding: utf-8 -*-
"""Query-pattern diagnostics so empty hits are not silent absences."""

from __future__ import annotations

import re
from typing import Any, Iterable

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_REGEX_MARKERS_RE = re.compile(r"(\\\||\||\.\*)")
_PIPE_EMPTY_RE = re.compile(
    r"(PRE_CORE_POST|三相|pipeIn|pipeBase|pipePost|\bPIPE\b|Pre/Main/Post|\bPre\b|\bPost\b)",
    re.I,
)


def identifier_tokens(pattern: str) -> list[str]:
    """Extract C/C++-like identifiers from a free-text pattern."""
    return _TOKEN_RE.findall(str(pattern or ""))


def looks_like_regex(pattern: str) -> bool:
    text = str(pattern or "")
    return bool(_REGEX_MARKERS_RE.search(text))


def is_multi_token(pattern: str) -> bool:
    text = str(pattern or "").strip()
    if not text or "=" in text:
        return False
    return len(identifier_tokens(text)) > 1


def search_needles(pattern: str) -> list[str]:
    """Needles to OR for locate/search. Structured Dim=V stays a single string."""
    text = str(pattern or "").strip()
    if not text:
        return []
    if "=" in text and "," in text:
        return [text]
    if "=" in text and identifier_tokens(text) and not looks_like_regex(text):
        # Single Dim=V belongs to legal_key / template_match, not search OR.
        return [text]
    tokens = identifier_tokens(text)
    if looks_like_regex(text) or len(tokens) > 1:
        return tokens or [text]
    return [text]


def attach_query_hints(
    payload: dict[str, Any],
    pattern: str,
    *,
    count: int,
    indexed: bool | None = None,
    kinds: Iterable[str] | None = None,
    mode: str = "",
) -> dict[str, Any]:
    """Annotate empty / regex / multi-token queries. Does not change hit rows."""
    text = str(pattern or "").strip()
    tokens = identifier_tokens(text)
    regex = looks_like_regex(text)
    multi = is_multi_token(text)
    kinds_u = {str(k).upper() for k in (kinds or ())}
    pipe_empty = int(count or 0) == 0 and (
        "PIPE" in kinds_u
        or str(mode or "") == "kernel_launch"
        or bool(_PIPE_EMPTY_RE.search(text))
    )
    if pipe_empty:
        payload["empty_reason"] = payload.get("empty_reason") or "no_substring_match"
        payload["hint"] = (
            "Use acp uo-query --mode kernel_launch "
            "(pipeIn → pipeBase → pipePost + arch entry / *_entry*.h). "
            "PRE_CORE_POST is not a graph token."
        )
        payload["suggested_retries"] = ["pipeIn", "pipeBase", "pipePost", "kernel_launch"]
    elif regex:
        payload.setdefault("empty_reason", "pattern_looks_like_regex")
        payload["hint"] = (
            "Graph search is not regex; query one identifier. "
            "For Dim=V use template_match or legal_key."
        )
        payload["suggested_retries"] = tokens[:4]
        payload["pattern_tokens"] = tokens
    elif count == 0 and multi:
        payload["empty_reason"] = "no_substring_match"
        payload["hint"] = (
            "Retry one shorter identifier; macros → template_match; "
            "combos → legal_key Dim=V,Other=V."
        )
        payload["suggested_retries"] = tokens[:4]
        payload["pattern_tokens"] = tokens
    elif count == 0:
        payload["empty_reason"] = payload.get("empty_reason") or "no_substring_match"
        payload.setdefault(
            "hint",
            "Retry a shorter name; macros → template_match; "
            "combos → legal_key Dim=V,Other=V. "
            "Empty is not proof the symbol is absent.",
        )
        if tokens:
            payload["suggested_retries"] = tokens[:4]
    if indexed is False:
        extra = "legal_key prefers Dim=V,Other=V; free-text is unindexed."
        prev = str(payload.get("hint") or "").strip()
        payload["hint"] = f"{prev} {extra}".strip() if prev else extra
    return payload
