# -*- coding: utf-8 -*-
"""Eval gates for claim-driven uo-query Explore (tool counts are hard metrics)."""

from __future__ import annotations

import re
from pathlib import Path

EVAL_FAMILIES = (
    "symbol",
    "call_chain",
    "tiling_key",
    "tiling_data",
    "kernel",
    "template",
    "buffer",
    "cross_layer",
    "unresolved",
    "source_detail",
    "sel_coverage",
)

HARD_GATES = {
    "median_tools_max": 8,
    "p95_tools_max": 12,
    "duplicate_semantic_or_span": 0,
    "repo_grep_escape": 0,
    "decisive_citation_when_answered": 1.0,
    "partial_then_continue_loop": 0,
}

_REPO_GREP_RE = re.compile(
    r"\b(findstr|grep|rg|ripgrep|Select-String)\b", re.I
)


def _is_repo_grep(event: dict) -> bool:
    tool = str(event.get("tool") or event.get("bucket") or "").lower()
    if tool in {"grep", "rg", "findstr"}:
        return True
    cmd = str(event.get("command") or "")
    if "acp " in cmd.lower():
        return False
    return bool(_REPO_GREP_RE.search(cmd))


def score_trace(tool_events: list[dict]) -> dict:
    """Score a recorded explore trace (unit-testable without LLM)."""
    total = len(tool_events)
    source = sum(1 for e in tool_events if e.get("bucket") == "source")
    semantic_keys = [e.get("key") for e in tool_events if e.get("bucket") == "semantic"]
    span_keys = [e.get("key") for e in tool_events if e.get("bucket") == "source"]
    dup_sem = len(semantic_keys) - len(set(semantic_keys))
    dup_span = len(span_keys) - len(set(span_keys))
    return {
        "tools": total,
        "source": source,
        "duplicate_semantic": max(0, dup_sem),
        "duplicate_span": max(0, dup_span),
        "repo_grep_escape": sum(1 for e in tool_events if _is_repo_grep(e)),
    }


def passes_hard_gates(scores: list[dict], *, answered_with_citation: list[bool]) -> dict:
    tools = sorted(s["tools"] for s in scores)
    n = len(tools) or 1
    median = tools[n // 2]
    p95 = tools[min(n - 1, int(0.95 * (n - 1)))] if n > 1 else tools[0]
    dups = sum(s["duplicate_semantic"] + s["duplicate_span"] for s in scores)
    greps = sum(int(s.get("repo_grep_escape") or 0) for s in scores)
    cite_ok = all(answered_with_citation) if answered_with_citation else True
    return {
        "ok": (
            median <= HARD_GATES["median_tools_max"]
            and p95 <= HARD_GATES["p95_tools_max"]
            and dups == HARD_GATES["duplicate_semantic_or_span"]
            and greps == HARD_GATES["repo_grep_escape"]
            and cite_ok
        ),
        "median_tools": median,
        "p95_tools": p95,
        "duplicates": dups,
        "repo_grep_escape": greps,
        "citation_ok": cite_ok,
    }


def test_eval_families_cover_baseline() -> None:
    product_map = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "uo-query"
        / "references"
        / "uo-product-map.md"
    )
    text = product_map.read_text(encoding="utf-8")
    assert "non-normative" in text
    for fam in ("tiling", "kernel", "unresolved"):
        assert fam in text.lower() or fam.replace("_", "") in text.lower()


def test_score_trace_hard_gates() -> None:
    good = [
        score_trace(
            [
                {"bucket": "semantic", "key": "a"},
                {"bucket": "semantic", "key": "b"},
                {"bucket": "source", "key": "s1"},
            ]
        )
    ]
    assert passes_hard_gates(good, answered_with_citation=[True])["ok"] is True
    bad = [
        score_trace(
            [{"bucket": "semantic", "key": "a"} for _ in range(12)]
            + [{"bucket": "source", "key": "s1"} for _ in range(3)]
        )
    ]
    assert passes_hard_gates(bad, answered_with_citation=[True])["ok"] is False
    grepped = [
        score_trace(
            [
                {"bucket": "semantic", "key": "a"},
                {"bucket": "bash", "command": 'findstr /S "ARGS_SEL" *.h'},
            ]
        )
    ]
    assert grepped[0]["repo_grep_escape"] >= 1
    assert passes_hard_gates(grepped, answered_with_citation=[True])["ok"] is False