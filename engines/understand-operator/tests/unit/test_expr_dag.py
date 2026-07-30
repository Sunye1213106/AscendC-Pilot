# -*- coding: utf-8 -*-
"""Serialising a shared `value_expr` must cost the DAG, not the unfolded tree.

Normalisation memoises by node identity, so one sub-expression is reachable by
many paths. JSON and YAML cannot express that, so a plain dump writes it once
per path. A FAG field hit ~10MB that way and the report ran out of memory,
which is why `value_expr` now goes through `encode_expr_dag`.

These are pure structural tests: no operator source, no clang.
"""
from __future__ import annotations

import json

import pytest

from uo_init.derive_key_fields import (
    DAG_ENVELOPE_MIN_NODES,
    collect_vars_dag,
    decode_expr_dag,
    encode_expr_dag,
    expr_tree_size,
    smt_value_leaves,
)

LEAF = {"op": "eq", "var": "VAR_X", "value": True}


def shared_chain(depth: int) -> dict:
    """A DAG of `depth` levels whose unfolded form grows as 2**depth.

    This is the shape a guarded assignment chain actually takes: each level
    reuses the level below in both arms, under a guard of its own.
    """
    node: dict = dict(LEAF)
    for i in range(depth):
        node = {
            "op": "if_then_else",
            "condition": {"op": "eq", "var": f"VAR_G{i}", "value": True},
            "then": node,
            "else": node,
        }
    return node


def test_small_expression_is_left_alone():
    """Below the threshold the plain form stays, so artifacts stay readable."""
    expr = shared_chain(2)
    assert encode_expr_dag(expr) is expr
    assert decode_expr_dag(expr) is expr


def test_scalars_and_none_pass_through():
    for value in (None, 1, True, "x"):
        assert encode_expr_dag(value) is value
        assert decode_expr_dag(value) is value


def test_round_trip_preserves_the_expression():
    expr = shared_chain(4)
    encoded = encode_expr_dag(expr, min_tree_nodes=0)
    assert encoded["$dag"] == 1
    assert decode_expr_dag(encoded) == expr


def test_round_trip_restores_sharing_not_just_shape():
    """The point of the envelope is the sharing.

    A consumer handed an equal-but-unfolded tree would pay exactly the cost
    this encoding exists to avoid, and every DAG-aware walk downstream
    (`collect_vars_dag`, `substitute_vars`) would silently go quadratic.
    """
    expr = shared_chain(6)
    back = decode_expr_dag(encode_expr_dag(expr, min_tree_nodes=0))
    assert back["then"] is back["else"]
    assert back["then"]["then"] is back["then"]["else"]


def test_encoding_a_deep_dag_stays_small():
    """20 levels unfold to ~10M nodes; the encoding must track the real ~60."""
    expr = shared_chain(20)
    assert expr_tree_size(expr) > 10**7

    encoded = encode_expr_dag(expr)
    assert encoded["$dag"] == 1
    assert encoded["nodes"] < 100
    # The size that matters is the serialised one: this is the assertion that
    # would have caught the MemoryError.
    assert len(json.dumps(encoded)) < 20_000

    assert collect_vars_dag(decode_expr_dag(encoded)) == collect_vars_dag(expr)


def test_threshold_decides_when_the_envelope_appears():
    expr = shared_chain(20)
    assert encode_expr_dag(expr, min_tree_nodes=expr_tree_size(expr)) is expr
    assert "$dag" in encode_expr_dag(expr, min_tree_nodes=expr_tree_size(expr) - 1)


def test_default_threshold_wraps_what_would_hurt():
    small = shared_chain(3)
    assert expr_tree_size(small) < DAG_ENVELOPE_MIN_NODES
    assert encode_expr_dag(small) is small
    assert "$dag" in encode_expr_dag(shared_chain(20))


def test_lists_keep_their_order():
    inner = shared_chain(3)
    expr = {"op": "and", "args": [inner, {"op": "not", "arg": inner}, inner]}
    back = decode_expr_dag(encode_expr_dag(expr, min_tree_nodes=0))
    assert back == expr
    assert back["args"][0] is back["args"][2]


def test_a_dangling_reference_is_an_error_not_a_silent_hole():
    with pytest.raises(ValueError):
        decode_expr_dag({"$dag": 1, "root": {"$ref": "n9"}, "defs": {}})


def test_value_leaves_walks_the_dag_once():
    """`smt_value_leaves` reads the same DAG, so it must share the walk too.

    It only follows the value arms, so 30 shared levels are 2**30 paths: with a
    plain tree walk this call does not come back.
    """
    node: dict = {"lit": 1}
    for i in range(30):
        node = {
            "op": "if_then_else",
            "condition": {"op": "eq", "var": f"VAR_G{i}", "value": True},
            "then": node,
            "else": {"lit": 0} if i == 0 else node,
        }
    assert smt_value_leaves(node) == {"1", "0"}
