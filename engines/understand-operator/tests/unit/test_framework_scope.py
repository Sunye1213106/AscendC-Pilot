# -*- coding: utf-8 -*-
"""Reading one step past the operator, for call order only.

A tiling class hands its base class the say in when its hooks run. Scoped out
by filename, the base class's calls vanish and every hook looks like a
function nobody calls — which downstream reads as "this might not run".
"""
from __future__ import annotations

import pytest

cindex = pytest.importorskip("clang.cindex", reason="libclang bindings not installed")

from uo_init.clang_walk import (  # noqa: E402 - after the skip guard
    _framework_headers,
    _norm,
    _Walker,
)

FRAMEWORK = """\
struct Driver {
    int state;
    virtual int Hook() { return 0; }
    int Run() {
        state = 7;
        return Hook();
    }
};
"""

OPERATOR = """\
#include "driver.h"

struct WidgetTiling : Driver {
    int answer;
    int Hook() override {
        answer = 3;
        return answer;
    }
};
"""


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    root = tmp_path_factory.mktemp("frame")
    (root / "driver.h").write_text(FRAMEWORK, encoding="utf-8")
    source = root / "widget_tiling.cpp"
    source.write_text(OPERATOR, encoding="utf-8")
    try:
        index = cindex.Index.create()
        tu = index.parse(str(source), args=["-std=c++17", f"-I{root}"])
    except Exception as exc:  # noqa: BLE001 - no usable libclang on this box
        pytest.skip(f"libclang cannot parse: {exc}")
    return tu, root


def test_the_base_class_header_is_found_through_the_inheritance_edge(parsed):
    tu, root = parsed
    found = _framework_headers(tu.cursor, "widget", str(root))
    assert {_norm(str(root / "driver.h"))} == found


def test_a_base_class_inside_the_operator_is_not_reported_as_foreign(parsed):
    """It is already in scope; naming it again would widen nothing."""
    tu, root = parsed
    # An empty needle makes everything under the root count as the operator.
    assert _framework_headers(tu.cursor, "", str(root)) == set()


def _walk(tu, needle, root, frame):
    w = _Walker(needle, op_root=str(root), frame_files=frozenset(frame))
    for child in tu.cursor.get_children():
        w.walk(child, [], "")
    return w


def test_the_base_class_call_order_is_recorded(parsed):
    tu, root = parsed
    frame = _framework_headers(tu.cursor, "widget", str(root))
    w = _walk(tu, "widget", root, frame)
    assert ("Run", "Hook") in {(s.caller, s.callee) for s in w.call_sites}


def test_without_it_the_hook_looks_like_nobody_calls_it(parsed):
    tu, root = parsed
    w = _walk(tu, "widget", root, frozenset())
    assert "Hook" not in {s.callee for s in w.call_sites}


def test_the_base_class_state_is_not_the_operator_s_state(parsed):
    """Its calls are read; its writes and fields stay out."""
    tu, root = parsed
    frame = _framework_headers(tu.cursor, "widget", str(root))
    w = _walk(tu, "widget", root, frame)
    written = {rec.path for rec in w.writes}
    assert not any("state" in path for path in written)
    assert "state" not in w.class_fields
    assert any("answer" in path for path in written)
