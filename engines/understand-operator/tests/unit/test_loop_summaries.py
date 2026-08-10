# -*- coding: utf-8 -*-
"""Interval coverage and next-fit summary primitives."""

from __future__ import annotations

from uo_init.loop_summary import interval_union_covers, next_fit_cores


def test_full_interval_cover_has_no_gaps():
    got = interval_union_covers(8, [(0, 3), (3, 8)])
    assert got and not got.uncovered


def test_partial_interval_cover_lists_missing_indices():
    got = interval_union_covers(6, [(0, 2), (4, 6)])
    assert not got
    assert got.uncovered == (2, 3)


def test_float32_domain_is_refused_until_quantised():
    """Varlen compares float token bounds to block indices — do not widen."""
    got = interval_union_covers(4, [(0, 4)], dtype="float32")
    assert not got
    assert "float32" in got.reason


def test_next_fit_counts_cores_deterministically():
    got = next_fit_cores([3, 3, 3], capacity=5)
    assert got.cores == 3 and not got.overflows


def test_next_fit_reports_overflow_against_max_cores():
    got = next_fit_cores([4, 4, 4], capacity=4, max_cores=2)
    assert got.overflows and got.cores == 2
