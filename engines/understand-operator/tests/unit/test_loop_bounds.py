# -*- coding: utf-8 -*-
"""Loop header facts read off the AST: initial value and per-iteration step.

Self-contained C++ with no includes, so these need libclang but not CANN.

Neither value appears in `CtrlNode.condition`, and `snippet` is token-truncated,
so a trip count has no other honest source. Every shape we do not read must say
None rather than produce a number inferred from position — a wrong bound would
silently authorise a "proof" that a container stays under some size.
"""
from __future__ import annotations

import pytest

from uo_init.clang_walk import _loop_header, _loop_step, _text_of

cindex = pytest.importorskip("clang.cindex", reason="libclang not installed")


def _loops(tmp_path, body: str) -> list[tuple[int, tuple]]:
    """Every loop in `body`, as (line, _loop_header result)."""
    src = tmp_path / "loops.cpp"
    src.write_text(f"void f(int n) {{ int acc = 0;\n{body}\n}}\n", encoding="utf-8")
    tu = cindex.TranslationUnit.from_source(str(src), args=["-std=c++17"])
    out: list[tuple[int, tuple]] = []

    def visit(cur):
        kinds = {"FOR_STMT": "for", "WHILE_STMT": "while", "DO_STMT": "do"}
        kind = kinds.get(cur.kind.name)
        if kind:
            out.append(
                (cur.location.line, _loop_header(list(cur.get_children()), kind))
            )
        for ch in cur.get_children():
            visit(ch)

    visit(tu.cursor)
    return out


def _only(tmp_path, body: str):
    loops = _loops(tmp_path, body)
    assert len(loops) == 1, f"expected one loop, got {len(loops)}"
    return loops[0][1]


def test_text_of_extent_matches_tokens_for_a_simple_condition(tmp_path):
    """Call/condition text used in kernel walks prefers source extent."""
    from uo_init.clang_walk import _extent_tls_clear, _extent_tls_set, _text_of, _tokens, normalize_expr_text

    src = tmp_path / "c.cpp"
    src.write_text(
        "void f(int n) { for (int i = 0; i < n; ++i) { (void)n; } }\n",
        encoding="utf-8",
    )
    tu = cindex.TranslationUnit.from_source(str(src), args=["-std=c++17"])
    cond = None

    def visit(cur):
        nonlocal cond
        if cur.kind.name == "FOR_STMT":
            children = list(cur.get_children())
            from uo_init.clang_walk import _loop_header

            cond, _ind, _init, _step = _loop_header(children, "for")
            return
        for ch in cur.get_children():
            visit(ch)

    visit(tu.cursor)
    assert cond is not None
    _extent_tls_set([])
    try:
        extent_text = _text_of(cond, 200)
        token_text = normalize_expr_text(" ".join(_tokens(cond, 200)))
        assert extent_text == token_text == "i<n"
    finally:
        _extent_tls_clear()


def test_a_counted_loop_yields_its_initial_value_and_step(tmp_path):
    cond, induction, init, step = _only(
        tmp_path, "for (unsigned int coreId = 0; coreId < 36; coreId++) { acc++; }"
    )
    assert _text_of(cond, 8) == "coreId<36"
    assert induction == ("coreId",)
    assert init == 0
    assert step == 1


def test_an_initial_value_needing_conversion_is_still_read(tmp_path):
    """`unsigned x = 0` wraps the literal in UNEXPOSED_EXPR; 0 is still 0."""
    _cond, _ind, init, step = _only(
        tmp_path, "for (unsigned long i = 0; i < 8; i++) { acc++; }"
    )
    assert (init, step) == (0, 1)


def test_a_descending_loop_reports_a_negative_step(tmp_path):
    _cond, _ind, init, step = _only(tmp_path, "for (int i = 10; i > 0; i--) { acc++; }")
    assert (init, step) == (10, -1)


def test_a_prefix_increment_is_the_same_step_as_a_postfix_one(tmp_path):
    """`++i` and `i++` differ only in token order."""
    _cond, _ind, init, step = _only(tmp_path, "for (int i = 5; i < n; ++i) { acc++; }")
    assert (init, step) == (5, 1)


@pytest.mark.parametrize(
    "clause,expected", [("i += 4", 4), ("i -= 2", -2), ("i += 1", 1)]
)
def test_a_compound_assignment_step_is_its_constant(tmp_path, clause, expected):
    _cond, _ind, _init, step = _only(
        tmp_path, f"for (int i = 0; i < n; {clause}) {{ acc++; }}"
    )
    assert step == expected


def test_a_step_by_a_variable_amount_is_not_a_number(tmp_path):
    _cond, _ind, _init, step = _only(
        tmp_path, "for (int i = 0; i < n; i += n) { acc++; }"
    )
    assert step is None


def test_two_induction_variables_with_one_increment_report_no_initial_value(tmp_path):
    """A shape whose trip count we have not established must not report one."""
    _cond, induction, init, _step = _only(
        tmp_path, "for (int i = 0, j = 1; i < n; i += 2) { acc += j; }"
    )
    assert induction == ("i", "j")
    assert init is None


def test_a_non_constant_initial_value_is_not_invented(tmp_path):
    _cond, _ind, init, step = _only(tmp_path, "for (int i = n; i > 0; i -= 2) { acc++; }")
    assert init is None
    assert step == -2


def test_a_loop_with_no_init_clause_reports_neither(tmp_path):
    """libclang omits absent clauses, so this `for` has one child fewer."""
    _cond, _ind, init, step = _only(tmp_path, "int k = 0; for (; k < n; ++k) { acc++; }")
    assert (init, step) == (None, None)


def test_an_empty_header_reports_nothing(tmp_path):
    cond, induction, init, step = _only(tmp_path, "for (;;) { break; }")
    assert (cond, induction, init, step) == (None, (), None, None)


def test_a_while_loop_has_no_init_or_step(tmp_path):
    cond, _ind, init, step = _only(tmp_path, "int k = 0; while (k < n) { k++; }")
    assert _text_of(cond, 8) == "k<n"
    assert (init, step) == (None, None)


def test_an_assignment_style_init_is_not_mistaken_for_the_condition(tmp_path):
    """`i = 0` is a BINARY_OPERATOR too, so scanning for the first one found it.

    Reading `i = 0` as the loop condition sends every guard under the loop to
    the wrong predicate.
    """
    cond, _ind, init, step = _only(
        tmp_path, "int i; for (i = 0; i < n; i++) { acc++; }"
    )
    assert _text_of(cond, 8) == "i<n"
    # The init clause is not a declaration, so there is no value to read.
    assert init is None
    assert step == 1


def test_nested_loops_are_each_read_separately(tmp_path):
    loops = _loops(
        tmp_path,
        "for (int a = 0; a < 36; a++) { for (int b = 3; b > 0; b--) { acc++; } }",
    )
    assert [(h[2], h[3]) for _line, h in loops] == [(0, 1), (3, -1)]


def test_a_step_clause_that_is_not_an_increment_is_not_a_step(tmp_path):
    """A call in the increment slot changes the variable in unknown ways."""
    src = "for (int i = 0; i < n; acc = i * 2) { i++; }"
    _cond, _ind, _init, step = _only(tmp_path, src)
    assert step is None


def test_loop_step_rejects_a_missing_clause():
    assert _loop_step(None) is None


# --- trip counts ----------------------------------------------------------
#
# Driven through a real parse rather than hand-built nodes: the point is that
# what libclang gives us is enough to count with, which a fabricated CtrlNode
# would assume rather than show.


def _bound(tmp_path, body: str, constants: dict[str, int] | None = None):
    from uo_init.clang_walk import CtrlNode
    from uo_init.loop_summary import loop_bound

    line, (cond, induction, init, step) = _loops(tmp_path, body)[0]
    node = CtrlNode(
        id="L",
        kind="for",
        file="f.cpp",
        line=line,
        condition=_text_of(cond, 12) if cond is not None else "",
        induction_vars=induction,
        init_value=init,
        step=step,
    )
    return loop_bound(node, constants)


def test_the_core_loop_runs_at_most_core_list_num_times(tmp_path):
    """The shape this whole summary exists for."""
    b = _bound(
        tmp_path,
        "for (unsigned int coreId = 0; coreId < CORE_LIST_NUM; coreId++) { acc++; }",
        {"CORE_LIST_NUM": 36},
    )
    assert b.max_trip == 36
    assert b.exact


def test_a_literal_bound_needs_no_constant_table(tmp_path):
    assert _bound(tmp_path, "for (int i = 0; i < 8; i++) { acc++; }").max_trip == 8


def test_an_inclusive_bound_counts_its_last_iteration(tmp_path):
    assert _bound(tmp_path, "for (int i = 0; i <= 8; i++) { acc++; }").max_trip == 9


def test_a_stride_divides_the_span_and_rounds_up(tmp_path):
    """0,3,6,9 is four iterations, not three."""
    assert _bound(tmp_path, "for (int i = 0; i < 10; i += 3) { acc++; }").max_trip == 4


def test_a_descending_loop_counts_down_to_its_bound(tmp_path):
    assert _bound(tmp_path, "for (int i = 10; i > 0; i--) { acc++; }").max_trip == 10


def test_a_descending_inclusive_bound_counts_its_last_iteration(tmp_path):
    assert _bound(tmp_path, "for (int i = 10; i >= 0; i--) { acc++; }").max_trip == 11


def test_a_loop_whose_bound_is_already_passed_runs_zero_times(tmp_path):
    assert _bound(tmp_path, "for (int i = 10; i < 5; i++) { acc++; }").max_trip == 0


def test_a_bound_the_constant_table_does_not_know_is_not_a_number(tmp_path):
    b = _bound(tmp_path, "for (int i = 0; i < LIMIT; i++) { acc++; }", {})
    assert b.max_trip is None
    assert "bound_not_constant" in b.reason
    assert not b


def test_a_bound_that_is_a_runtime_value_is_not_a_number(tmp_path):
    assert _bound(tmp_path, "for (int i = 0; i < n; i++) { acc++; }").max_trip is None


def test_a_reversed_comparison_is_read_the_same_way(tmp_path):
    """`36 > i` bounds `i` exactly as `i < 36` does."""
    assert _bound(tmp_path, "for (int i = 0; 36 > i; i++) { acc++; }").max_trip == 36


def test_a_condition_on_another_variable_does_not_bound_this_loop(tmp_path):
    b = _bound(tmp_path, "int m = 0; for (int i = 0; m < 4; i++) { m++; }")
    assert b.max_trip is None
    assert "not_on_induction_var" in b.reason


def test_a_step_going_away_from_the_bound_is_refused(tmp_path):
    """`i-- ` under `i < 36` never terminates; it must not report 36."""
    b = _bound(tmp_path, "for (int i = 0; i < 36; i--) { acc++; }")
    assert b.max_trip is None
    assert b.reason == "step_and_comparison_disagree"


def test_a_loop_without_a_readable_init_gets_no_count(tmp_path):
    b = _bound(tmp_path, "int k = 0; for (; k < 36; ++k) { acc++; }")
    assert b.max_trip is None
    assert b.reason == "no_initial_value"


def test_a_while_loop_is_not_counted(tmp_path):
    from uo_init.clang_walk import CtrlNode
    from uo_init.loop_summary import loop_bound

    node = CtrlNode(id="L", kind="while", file="f.cpp", line=1, condition="k < 36")
    assert loop_bound(node).reason.startswith("not_a_for_loop")


def test_a_boolean_bound_is_not_treated_as_one(tmp_path):
    """Python's bool is an int; a loop bounded by `true` is not a count of 1."""
    from uo_init.clang_walk import CtrlNode
    from uo_init.loop_summary import loop_bound

    node = CtrlNode(
        id="L",
        kind="for",
        file="f.cpp",
        line=1,
        condition="i < true",
        induction_vars=("i",),
        init_value=0,
        step=1,
    )
    assert loop_bound(node).max_trip is None


def _synthetic_bound(bound: int, *, init: int = 0, step: int = 1):
    from uo_init.clang_walk import CtrlNode
    from uo_init.loop_summary import loop_bound

    node = CtrlNode(
        id="L",
        kind="for",
        file="f.cpp",
        line=1,
        condition=f"i < {bound}",
        induction_vars=("i",),
        init_value=init,
        step=step,
    )
    return loop_bound(node)


@pytest.mark.parametrize(
    "bound,step",
    [
        (2**53 + 1, 1),
        (2**53 + 3, 2),
        (2**62 + 7, 3),
        (2**60 - 1, 7),
    ],
)
def test_a_span_too_large_for_a_float_is_still_counted_exactly(bound, step):
    """Above 2**53 a float cannot hold the span. Measured on these inputs the
    error runs low -- 2**62+7 over a step of 3 came out 88 iterations short --
    and a trip count below the real one is the dangerous direction here: it is
    used to argue a container never exceeds some size."""
    got = _synthetic_bound(bound, step=step).max_trip
    assert got == -(-bound // step)


def test_the_count_never_comes_back_as_a_float():
    """A float trip count compares and indexes differently from an int, and the
    difference only shows up on the inputs that were already the problem."""
    got = _synthetic_bound(2**53 + 1).max_trip
    assert isinstance(got, int) and not isinstance(got, bool)


def test_a_span_that_divides_exactly_does_not_gain_an_iteration():
    assert _synthetic_bound(2**54, step=2).max_trip == 2**53
