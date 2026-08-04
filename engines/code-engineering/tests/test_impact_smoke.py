# -*- coding: utf-8 -*-
"""Smoke tests for CE impact / regress."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_parse_diff_ranges():
    from code_engineering.impact import parse_diff_ranges

    text = (
        "diff --git a/foo.cpp b/foo.cpp\n"
        "--- a/foo.cpp\n"
        "+++ b/foo.cpp\n"
        "@@ -10,3 +10,4 @@\n"
        " keep\n"
        "+added\n"
    )
    ranges = parse_diff_ranges(text)
    assert "foo.cpp" in ranges
    assert ranges["foo.cpp"][0] == (10, 13)


def test_impact_against_live_codemap():
    from code_engineering.impact import impact_from_diff

    uo = REPO / ".ascendc-pilot" / "uo"
    if not (uo / "ir" / "host_codemap.yaml").is_file():
        import pytest
        pytest.skip("no live codemap")
    # Synthetic hunk unlikely to hit writers; still must not crash.
    text = (
        "+++ b/does_not_exist.cpp\n"
        "@@ -1,1 +1,2 @@\n"
        "+x\n"
    )
    report = impact_from_diff(text, uo_root=uo)
    assert report.files == ["does_not_exist.cpp"]
    assert report.hit_writers == []


def test_gate_closure_soundness():
    from ascendc_pilot.gates import gate_closure_soundness

    result = gate_closure_soundness(REPO)
    assert result["ok"] is True
    assert result.get("gap", 1) == 0
