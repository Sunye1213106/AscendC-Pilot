"""Public large-IR stub helpers."""

from __future__ import annotations

from ascendc_pilot.ir_summary import (
    classify_large_ir_read_paths,
    has_large_ir_summary,
    large_ir_must_read_order_lines,
)


def test_classify_and_must_read_order() -> None:
    reads = [
        "uo/ir/foo.summary.yaml",
        "uo/ir/foo.rework_hints.yaml",
        "uo/ir/foo_candidates.yaml",
        "uo/ir/other.yaml",
    ]
    parts = classify_large_ir_read_paths(reads)
    assert parts["summaries"] == ["uo/ir/foo.summary.yaml"]
    assert parts["hints"] == ["uo/ir/foo.rework_hints.yaml"]
    assert parts["full_ir"] == ["uo/ir/foo_candidates.yaml"]
    assert has_large_ir_summary(reads) is True
    lines = large_ir_must_read_order_lines(reads)
    assert any(x.startswith("MUST_READ_ORDER:") for x in lines)
    assert any("readonly_search:" in x for x in lines)
    assert large_ir_must_read_order_lines(["uo/ir/only.yaml"]) == []
