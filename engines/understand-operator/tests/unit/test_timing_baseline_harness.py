# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_harness():
    path = (
        Path(__file__).resolve().parents[2] / "tools" / "timing_baseline.py"
    )
    spec = importlib.util.spec_from_file_location("timing_baseline", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_parse_timing_lines_and_render():
    mod = _load_harness()
    text = (
        "[uo-timing]   12.345s  extract_host  closure_mode=full\n"
        "[uo-timing]  200.000s SLOW  walk_file  file=a.cpp\n"
        "noise\n"
    )
    rows = mod.parse_timing_lines(text)
    assert len(rows) == 2
    assert rows[0]["phase"] == "extract_host"
    assert rows[0]["seconds"] == 12.345
    assert rows[1]["slow"] is True
    md = mod.render_markdown(rows, measured=True)
    assert "`extract_host`" in md
    assert "31.7s → 2.0s" in md
    assert "UO_TU_CACHE" in md


def test_both_columns_are_filled_from_two_captures():
    """P1: a baseline with an empty Warm column is not a baseline."""
    mod = _load_harness()
    cold = mod.parse_timing_lines("[uo-timing]  180.000s  walk_file  file=a.cpp\n")
    warm = mod.parse_timing_lines("[uo-timing]    1.400s  walk_file  file=a.cpp\n")
    md = mod.render_markdown(
        cold, measured=True, warm_rows=warm, totals={"cold_s": 180.4, "warm_s": 1.4}
    )
    assert "| `extract_host` | 180.400 | 1.400 |" in md
    assert "| `walk_file` | 180.000 | 1.400 |" in md
    assert "not yet measured" not in md.split("## Inside")[1].split("## Still")[0]
    assert "× faster than cold" in md


def test_informational_timing_lines_do_not_become_phases():
    """The timing channel carries notes too; a note is not a measurement."""
    mod = _load_harness()
    rows = mod.parse_timing_lines(
        "[uo-timing]   1.000s  build_host_ir\n"
        "[uo-timing] extract_host_bundle start  closure_mode=off\n"
        "[uo-timing]   summary    1.000s  build_host_ir\n"
    )
    grouped = mod._by_phase(rows)
    assert list(grouped) == ["build_host_ir"]
