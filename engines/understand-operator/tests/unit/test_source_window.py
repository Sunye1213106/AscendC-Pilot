# -*- coding: utf-8 -*-
"""Cutting the piece of source a question is about."""

from __future__ import annotations

import pytest

from uo_init.source_window import blocks_at, evidence_window, read_lines

SOURCE = """\
#include <cstdint>

ge::graphStatus Prepare(Params &p)
{
    int64_t total = 0;
    for (int64_t i = 0; i < p.n; i++) {
        if (p.mask[i] != 0) {
            total += p.len[i];
        }
    }
    p.total = total;
    return ge::GRAPH_SUCCESS;
}

void Other()
{
    return;
}
"""


@pytest.fixture
def src(tmp_path):
    path = tmp_path / "tiling.cpp"
    path.write_text(SOURCE, encoding="utf-8")
    return path


def _line_of(needle: str) -> int:
    for no, text in enumerate(SOURCE.splitlines(), start=1):
        if needle in text:
            return no
    raise AssertionError(f"{needle!r} not in the fixture")


def test_the_blocks_around_a_line_come_back_outermost_first(src):
    lines = read_lines(src)
    spans = blocks_at(lines, _line_of("total += p.len[i]"))
    assert [s[0] for s in spans] == sorted(s[0] for s in spans)
    assert spans[0][0] == _line_of("ge::graphStatus Prepare") + 1
    assert spans[-1][0] == _line_of("if (p.mask[i] != 0)")


def test_a_line_in_one_function_does_not_pick_up_the_next(src):
    lines = read_lines(src)
    spans = blocks_at(lines, _line_of("total += p.len[i]"))
    assert all(end < _line_of("void Other()") for _, end in spans)


def test_the_window_is_the_whole_function_including_its_signature(src):
    got = evidence_window(src, _line_of("total += p.len[i]"))
    assert got["kind"] == "function"
    assert got["line_start"] == _line_of("ge::graphStatus Prepare")
    assert "for (int64_t i = 0" in got["text"]
    assert "return ge::GRAPH_SUCCESS;" in got["text"]
    assert "void Other()" not in got["text"]


def test_a_function_too_large_to_read_falls_back_to_the_largest_block_that_fits(src):
    """Past a point a window stops being evidence and becomes a file dump.

    Falling inward has to stop at the largest block that still fits, not the
    smallest. Asked what the loop computes, the innermost block is the `if`
    inside it: a test, no accumulation, and no way to tell the two apart.
    """
    got = evidence_window(src, _line_of("total += p.len[i]"), max_lines=5)
    assert got["kind"] == "block"
    assert got["line_start"] == _line_of("for (int64_t i = 0")

    tighter = evidence_window(src, _line_of("total += p.len[i]"), max_lines=4)
    assert tighter["line_start"] == _line_of("if (p.mask[i] != 0)")


def test_a_brace_in_a_comment_does_not_open_a_block(tmp_path):
    """Counting braces is only safe once comments and literals are out."""
    path = tmp_path / "c.cpp"
    path.write_text(
        'void f()\n{\n    // opens nothing {\n    const char *s = "}";\n    g();\n}\n',
        encoding="utf-8",
    )
    got = evidence_window(path, 5)
    assert got["kind"] == "function"
    assert got["line_start"] == 1 and got["line_end"] == 6


def test_a_brace_in_a_block_comment_does_not_open_a_block(tmp_path):
    path = tmp_path / "c.cpp"
    path.write_text("void f()\n{\n    /* {\n       } */\n    g();\n}\n", encoding="utf-8")
    assert evidence_window(path, 5)["line_end"] == 6


def test_code_with_no_braces_at_all_still_yields_a_window(tmp_path):
    path = tmp_path / "c.cpp"
    path.write_text("\n".join(f"int v{i} = {i};" for i in range(40)), encoding="utf-8")
    got = evidence_window(path, 20, context=3)
    assert got["kind"] == "window"
    assert (got["line_start"], got["line_end"]) == (17, 23)


def test_a_line_outside_the_file_has_no_window(src):
    assert evidence_window(src, 9999) is None
    assert evidence_window(src, 0) is None


def test_a_file_that_is_not_there_has_no_window(tmp_path):
    assert evidence_window(tmp_path / "nope.cpp", 1) is None
