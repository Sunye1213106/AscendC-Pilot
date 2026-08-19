# -*- coding: utf-8 -*-
"""Query-pattern diagnostics so empty hits are not silent absences."""

from __future__ import annotations

import re
from typing import Any, Iterable

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_REGEX_MARKERS_RE = re.compile(r"(\\\||\||\.\*)")
_PIPE_EMPTY_RE = re.compile(
    r"(PRE_CORE_POST|三相|\bPIPE\b|\bTPipe\b|Pre/Main/Post|\bPre\b|\bPost\b)",
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
            "Omit the identifier and call acp uo-query --project <operator-abs> "
            "for the operator index (launch phases). PRE_CORE_POST is not a graph token."
        )
        payload["suggested_retries"] = [
            "TPipe",
            "InitBuffer",
            "PopStackBuffer",
            "InitShareBufStart",
        ]
    elif regex:
        payload.setdefault("empty_reason", "pattern_looks_like_regex")
        payload["hint"] = (
            "Graph search is not regex; query one identifier. "
            "For template coverage use Dim=V[,Other=V]."
        )
        payload["suggested_retries"] = tokens[:4]
        payload["pattern_tokens"] = tokens
    elif count == 0 and str(mode or "") == "around":
        payload["ok"] = False
        payload["empty_reason"] = "no_entity_at_line"
        payload["hint"] = (
            "No CodeMap span covers this line (format-only hunks are expected empty). "
            "This is not proof the file is unindexed. Query Added identifiers (form-1) instead."
        )
    elif count == 0 and multi:
        payload["empty_reason"] = "no_substring_match"
        payload["hint"] = (
            "Retry one shorter identifier, or Dim=V for template coverage, "
            "or --file --line from a previous card."
        )
        payload["suggested_retries"] = tokens[:4]
        payload["pattern_tokens"] = tokens
    elif count == 0:
        payload["empty_reason"] = payload.get("empty_reason") or "no_substring_match"
        payload.setdefault(
            "hint",
            "Retry a shorter identifier, or Dim=V for template coverage, "
            "or --file --line from a previous card. "
            "Empty is not proof the symbol is absent.",
        )
        if tokens:
            payload["suggested_retries"] = tokens[:4]
    if indexed is False:
        extra = "Template coverage prefers Dim=V[,Other=V]; free-text is unindexed."
        prev = str(payload.get("hint") or "").strip()
        payload["hint"] = f"{prev} {extra}".strip() if prev else extra
    return payload
