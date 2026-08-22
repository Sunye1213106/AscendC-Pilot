from __future__ import annotations

from uo_init.pipe_lifetime import (
    continued_line_ranges,
    lifetime_edges,
    order_pipe_names,
    topo_pipe_ordinals,
)
from uo_init.semantics.const_expr import integer_occupancy, occupancy_overlap, worth_sharing


def test_continued_ranges_join_backslash_define() -> None:
    text = (
        "#define BODY \\\n"
        "  pipeIn.Destroy(); \\\n"
        "  TPipe pipeBase; \\\n"
        "  pipeBase.Destroy(); \\\n"
        "  TPipe pipePost;\n"
        "void Launch() {\n"
        "  TPipe pipeIn;\n"
        "}\n"
    )
    ranges = continued_line_ranges(text)
    assert ranges[0] == (1, 5)
    assert (6, 6) in ranges


def test_destroy_chain_ignores_later_function_construct() -> None:
    constructs = [("pipeBase", 3), ("pipePost", 5), ("pipeIn", 7)]
    destroys = [(2, "pipeIn"), (4, "pipeBase"), (6, "pipeBase")]
    ranges = [(1, 5), (6, 6), (7, 7)]
    edges = lifetime_edges(constructs, destroys, ranges)
    assert ("pipeIn", "pipeBase") in edges
    assert ("pipeBase", "pipePost") in edges
    assert ("pipeBase", "pipeIn") not in edges
    ordinals = topo_pipe_ordinals(
        ["pipeBase", "pipePost", "pipeIn"],
        edges,
        line_of={"pipeBase": 3, "pipePost": 5, "pipeIn": 7},
    )
    assert ordinals["pipeIn"] == 1
    assert ordinals["pipeBase"] == 2
    assert ordinals["pipePost"] == 3
    names = order_pipe_names(
        ["pipeBase", "pipePost", "pipeIn"],
        constructs,
        destroys,
        ranges,
        line_of={"pipeBase": 3, "pipePost": 5, "pipeIn": 7},
    )
    assert names == ["pipeIn", "pipeBase", "pipePost"]


def test_no_destroy_keeps_line_order() -> None:
    names = order_pipe_names(
        ["alpha", "beta", "gamma"],
        [("alpha", 10), ("beta", 20), ("gamma", 30)],
        [],
        [(10, 10), (20, 20), (30, 30)],
        line_of={"alpha": 10, "beta": 20, "gamma": 30},
    )
    assert names == ["alpha", "beta", "gamma"]


def test_flag_occupancy_shares_scalar_with_brace_list() -> None:
    assert integer_occupancy("10") == frozenset({10})
    assert integer_occupancy("{10, 11}") == frozenset({10, 11})
    overlap = occupancy_overlap("10", "{10, 11}")
    assert overlap == frozenset({10})
    assert worth_sharing(overlap, "10", "{10, 11}")
    assert not worth_sharing(frozenset({0}), "0", "0")
