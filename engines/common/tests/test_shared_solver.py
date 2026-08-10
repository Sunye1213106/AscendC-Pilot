# -*- coding: utf-8 -*-
"""The shared solver contract both engines depend on."""
from __future__ import annotations

import pytest

from acp_common.constraint_ir import (
    ConstraintIRError,
    collect_expr_variables,
    normalize_expr,
    parse_bool_literal,
)
from acp_common.z3_backend import SolveConfig, Z3Backend

z3 = pytest.importorskip("z3")


def _ir(variables, constraints=None):
    return {"variables": variables, "constraints": constraints or []}


BOOL_A = {"id": "VAR_A", "type": "bool"}
BOOL_B = {"id": "VAR_B", "type": "bool"}
INT_N = {"id": "VAR_N", "type": "int", "domain": {"kind": "range", "min": 1, "max": 64}}


def test_normalize_expr_rejects_unknown_op():
    with pytest.raises(ConstraintIRError):
        normalize_expr({"op": "nand", "args": []})


#: A DAG: one shared subtree reached along two paths, which is the shape the
#: derived key expressions have and the one naive normalisation duplicates.
def _shared_dag():
    leaf = {"op": "eq", "var": "VAR_A", "value": True}
    mid = {"op": "and", "args": [leaf, {"op": "gt", "lhs": {"var": "VAR_N"}, "rhs": 8}]}
    return {"op": "or", "args": [mid, {"op": "not", "arg": mid}]}, mid


def test_normalising_an_already_normal_expression_changes_nothing():
    """Idempotence is what makes it safe to hand the result back to the memo."""
    once = normalize_expr(_shared_dag()[0], {})
    assert normalize_expr(once, {}) == once


def test_a_normalised_result_is_returned_as_is_on_a_second_pass():
    """Otherwise every re-normalisation rebuilds the graph one level deeper.

    Callers normalise more than once -- at the assertion and again inside the
    compile -- and each rebuild hands the layer below fresh objects that miss
    every identity-keyed memo, which is what made compiling the key expressions
    take minutes.
    """
    memo: dict = {}
    once = normalize_expr(_shared_dag()[0], memo)
    assert normalize_expr(once, memo) is once


def test_a_shared_subtree_normalises_to_one_object():
    memo: dict = {}
    root = normalize_expr(_shared_dag()[0], memo)
    left = root["args"][0]
    right = root["args"][1]["arg"]
    assert left is right, "sharing must survive normalisation, not be copied"


def test_collect_expr_variables_walks_nested_expressions():
    expr = {
        "op": "and",
        "args": [
            {"op": "eq", "var": "VAR_A", "value": True},
            {"op": "gt", "lhs": {"var": "VAR_N"}, "rhs": 8},
        ],
    }
    assert collect_expr_variables(expr) == {"VAR_A", "VAR_N"}


def test_parse_bool_literal_accepts_yaml_spellings():
    assert parse_bool_literal("true") is True
    assert parse_bool_literal(0) is False


def test_solve_expr_returns_witness_within_declared_domain():
    backend = Z3Backend(_ir([INT_N]), SolveConfig(timeout_ms=2000))
    result = backend.solve_expr({"op": "gt", "lhs": {"var": "VAR_N"}, "rhs": 60})
    assert result["status"] == "sat"
    assert 60 < result["model"]["VAR_N"] <= 64


def test_solve_expr_is_unsat_outside_declared_domain():
    backend = Z3Backend(_ir([INT_N]))
    assert backend.solve_expr({"op": "gt", "lhs": {"var": "VAR_N"}, "rhs": 100})["status"] == "unsat"


def test_prove_equivalent_accepts_a_restatement():
    backend = Z3Backend(_ir([BOOL_A, BOOL_B]))
    lhs = {"op": "or", "args": [{"op": "eq", "var": "VAR_A", "value": True}, {"op": "eq", "var": "VAR_B", "value": True}]}
    rhs = {"op": "not", "arg": {"op": "and", "args": [
        {"op": "eq", "var": "VAR_A", "value": False},
        {"op": "eq", "var": "VAR_B", "value": False},
    ]}}
    assert backend.prove_equivalent(lhs, rhs)["status"] == "proved"


def test_prove_equivalent_refutes_with_a_counterexample():
    backend = Z3Backend(_ir([BOOL_A, BOOL_B]))
    lhs = {"op": "eq", "var": "VAR_A", "value": True}
    rhs = {"op": "and", "args": [
        {"op": "eq", "var": "VAR_A", "value": True},
        {"op": "eq", "var": "VAR_B", "value": True},
    ]}
    verdict = backend.prove_equivalent(lhs, rhs)
    assert verdict["status"] == "refuted"
    assert verdict["model"]["VAR_A"] is True and verdict["model"]["VAR_B"] is False


def test_prove_implies_uses_base_constraints_as_premises():
    """A key condition only holds under the operator's validity predicate."""
    ir = _ir(
        [BOOL_A, INT_N],
        [{"id": "VALIDITY", "expr": {"op": "implies",
                                     "antecedent": {"op": "eq", "var": "VAR_A", "value": True},
                                     "consequent": {"op": "ge", "lhs": {"var": "VAR_N"}, "rhs": 32}}}],
    )
    backend = Z3Backend(ir)
    proved = backend.prove_implies({"op": "eq", "var": "VAR_A", "value": True},
                                   {"op": "ge", "lhs": {"var": "VAR_N"}, "rhs": 16})
    assert proved["status"] == "proved"

    refuted = Z3Backend(_ir([BOOL_A, INT_N])).prove_implies(
        {"op": "eq", "var": "VAR_A", "value": True},
        {"op": "ge", "lhs": {"var": "VAR_N"}, "rhs": 16},
    )
    assert refuted["status"] == "refuted"


def test_derived_variables_are_hidden_unless_exposed():
    derived = {"id": "VAR_D", "type": "bool", "derived": True,
               "definition": {"op": "gt", "lhs": {"var": "VAR_N"}, "rhs": 8}}
    plain = Z3Backend(_ir([INT_N, derived]))
    assert "VAR_D" not in plain.solve_expr({"op": "eq", "var": "VAR_D", "value": True})["model"]

    class Exposing(Z3Backend):
        exposed_derived_prefixes = ("VAR_D",)

    assert Exposing(_ir([INT_N, derived])).solve_expr({"op": "eq", "var": "VAR_D", "value": True})["model"]["VAR_D"] is True


def test_generalization_heuristic_is_off_by_default():
    """TG opts into breaking the all-ones cube; other callers must not inherit it."""
    variables = [
        {"id": "VAR_SHAPE_B", "type": "int", "domain": {"kind": "range", "min": 1, "max": 8}},
        {"id": "VAR_SHAPE_N", "type": "int", "domain": {"kind": "range", "min": 1, "max": 8}},
    ]
    trivial = {"op": "ge", "lhs": {"var": "VAR_SHAPE_B"}, "rhs": 1}

    default_model = Z3Backend(_ir(variables)).solve_expr(trivial)["model"]
    assert default_model == {"VAR_SHAPE_B": 1, "VAR_SHAPE_N": 1}

    class Generalizing(Z3Backend):
        generalize_prefixes = ("VAR_SHAPE_",)

    widened = Generalizing(_ir(variables)).solve_expr(trivial)["model"]
    assert max(widened.values()) > 1
