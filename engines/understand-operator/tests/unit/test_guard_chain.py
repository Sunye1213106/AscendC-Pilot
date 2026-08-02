# -*- coding: utf-8 -*-
"""What holds for the statements after an `if` that returns.

A function written as a chain of guarded returns ends in a plain `return`
that runs only when no condition in the chain held. Recording just the first
one makes that ending look like a case the chain might not have covered.
"""
from __future__ import annotations

import pytest

cindex = pytest.importorskip("clang.cindex", reason="libclang bindings not installed")

from uo_init.clang_walk import _guard_clause_negations  # noqa: E402 - after skip


#: The status codes the walker recognises have to exist for the branch that
#: returns one to parse at all; undeclared, it never looks like a return.
PRELUDE = "enum Status { GRAPH_SUCCESS = 0, GRAPH_FAILED = 1 };\n"


def _first_if(source: str, tmp_path):
    path = tmp_path / "sample.cpp"
    path.write_text(PRELUDE + source, encoding="utf-8")
    try:
        tu = cindex.Index.create().parse(str(path), args=["-std=c++17"])
    except Exception as exc:  # noqa: BLE001 - no usable libclang here
        pytest.skip(f"libclang cannot parse: {exc}")
    stack = list(tu.cursor.get_children())
    while stack:
        node = stack.pop(0)
        if node.kind.name == "IF_STMT":
            return node
        stack = list(node.get_children()) + stack
    raise AssertionError("no if statement in the sample")


def _texts(conds):
    return [(c.pretty(), c.kind) for c in conds]


def test_a_lone_guard_clause_gives_the_whole_condition(tmp_path):
    node = _first_if(
        """
        int pick(int a) {
            if (a > 1) { return 7; }
            return 9;
        }
        """,
        tmp_path,
    )
    assert _texts(_guard_clause_negations(node)) == [("!(a>1)", "if")]


def test_every_branch_of_a_returning_chain_is_negated(tmp_path):
    node = _first_if(
        """
        int pick(int a, int b, int c) {
            if (a > 1) { return 1; }
            else if (b > 2) { return 2; }
            else if (c > 3) { return 3; }
            return 4;
        }
        """,
        tmp_path,
    )
    assert _texts(_guard_clause_negations(node)) == [
        ("!(a>1)", "if"),
        ("!(b>2)", "if"),
        ("!(c>3)", "if"),
    ]


def test_a_branch_that_falls_through_keeps_the_chain_untrusted(tmp_path):
    """`b > 2` does not stop the fallthrough, so `!(b > 2)` would be a lie."""
    node = _first_if(
        """
        int pick(int a, int b, int *out) {
            if (a > 1) { return 1; }
            else if (b > 2) { *out = 5; }
            return 4;
        }
        """,
        tmp_path,
    )
    assert _texts(_guard_clause_negations(node)) == [("!(a>1)", "guard_clause")]


def test_a_chain_where_every_road_returns_says_nothing_about_what_follows(tmp_path):
    node = _first_if(
        """
        int pick(int a, int b) {
            if (a > 1) { return 1; }
            else if (b > 2) { return 2; }
            else { return 3; }
        }
        """,
        tmp_path,
    )
    assert _guard_clause_negations(node) == []


def test_a_first_branch_that_does_not_leave_implies_nothing(tmp_path):
    node = _first_if(
        """
        int pick(int a, int *out) {
            if (a > 1) { *out = 5; }
            return 4;
        }
        """,
        tmp_path,
    )
    assert _guard_clause_negations(node) == []


def test_a_rejected_input_is_a_premise_not_a_branch(tmp_path):
    node = _first_if(
        """
        int check(int a) {
            if (a < 0) { return GRAPH_FAILED; }
            return 0;
        }
        """,
        tmp_path,
    )
    assert _texts(_guard_clause_negations(node)) == [("!(a<0)", "bailout")]


def test_a_chain_mixing_in_a_rejection_falls_back_to_the_first_condition(tmp_path):
    """One branch reports the call was refused; that is a premise, not a path.

    Mixing the two kinds into one chain would file a premise as an ordinary
    condition, so the whole-chain reading is given up here.
    """
    node = _first_if(
        """
        int check(int a, int b) {
            if (a < 0) { return GRAPH_FAILED; }
            else if (b > 2) { return 2; }
            return 0;
        }
        """,
        tmp_path,
    )
    assert _texts(_guard_clause_negations(node)) == [("!(a<0)", "bailout")]


def test_a_status_check_names_no_input_and_is_left_out(tmp_path):
    node = _first_if(
        """
        int run(int ret) {
            if (ret != GRAPH_SUCCESS) { return ret; }
            return 0;
        }
        """,
        tmp_path,
    )
    assert _guard_clause_negations(node) == []


def test_the_conditions_are_reported_at_their_own_lines(tmp_path):
    node = _first_if(
        """
        int pick(int a, int b) {
            if (a > 1) { return 1; }
            else if (b > 2) { return 2; }
            return 3;
        }
        """,
        tmp_path,
    )
    got = _guard_clause_negations(node)
    assert [c.line for c in got] == sorted({c.line for c in got})
    assert len({c.line for c in got}) == 2


def test_a_guard_nested_in_a_branch_that_falls_through_is_still_recorded(tmp_path):
    """The alternate-exit shape: a separate encoding for the degenerate case,
    reached only under an arch test, with the ordinary path carrying on after."""
    node = _first_if(
        """
        int other(int);
        int pick(int arch, int empty, int a) {
            if (arch == 35) {
                if (empty) { return other(a); }
            }
            return a;
        }
        """,
        tmp_path,
    )
    assert _texts(_guard_clause_negations(node)) == [
        ("!(arch == 35) || !(empty)", "bailout")
    ]


def test_a_branch_that_falls_through_with_no_inner_exit_says_nothing(tmp_path):
    node = _first_if(
        """
        int pick(int arch, int a) {
            if (arch == 35) { a = a + 1; }
            return a;
        }
        """,
        tmp_path,
    )
    assert _guard_clause_negations(node) == []
