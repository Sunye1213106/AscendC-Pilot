# -*- coding: utf-8 -*-
"""Eval gates for claim-driven uo-query Explore (tool counts are hard metrics)."""

from __future__ import annotations

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
)

HARD_GATES = {
    "median_tools_max": 6,
    "p95_tools_max": 10,
    "source_median_max": 1,
    "duplicate_semantic_or_span": 0,
    "decisive_citation_when_answered": 1.0,
    "partial_then_continue_loop": 0,
}


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
    }


def passes_hard_gates(scores: list[dict], *, answered_with_citation: list[bool]) -> dict:
    tools = sorted(s["tools"] for s in scores)
    sources = sorted(s["source"] for s in scores)
    n = len(tools) or 1
    median = tools[n // 2]
    p95 = tools[min(n - 1, int(0.95 * (n - 1)))] if n > 1 else tools[0]
    source_median = sources[n // 2]
    dups = sum(s["duplicate_semantic"] + s["duplicate_span"] for s in scores)
    cite_ok = all(answered_with_citation) if answered_with_citation else True
    return {
        "ok": (
            median <= HARD_GATES["median_tools_max"]
            and p95 <= HARD_GATES["p95_tools_max"]
            and source_median <= HARD_GATES["source_median_max"]
            and dups == HARD_GATES["duplicate_semantic_or_span"]
            and cite_ok
        ),
        "median_tools": median,
        "p95_tools": p95,
        "source_median": source_median,
        "duplicates": dups,
        "citation_ok": cite_ok,
    }


def test_eval_families_cover_baseline() -> None:
    baseline = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "operator-analysis"
        / "examples"
        / "uo-query-splitaxis"
        / "eval-baseline.md"
    )
    text = baseline.read_text(encoding="utf-8")
    for fam in EVAL_FAMILIES:
        assert fam in text or fam.replace("_", "") in text.replace("_", "")


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
