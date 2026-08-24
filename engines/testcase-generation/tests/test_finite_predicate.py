from __future__ import annotations

from testcase_agent.closure.finite_predicate import Truth, evaluate


def test_unknown_and_unsupported_are_not_false() -> None:
    assert evaluate({"op": "eq", "field": "x", "value": 1}, {}).result is Truth.UNKNOWN
    assert evaluate({"op": "unknown-op"}, {}).result is Truth.UNSUPPORTED
    assert evaluate({"op": "and", "args": [{"op": "eq", "field": "x", "value": 1}, {"op": "eq", "field": "y", "value": 2}]}, {"x": 1}).result is Truth.UNKNOWN


def test_four_valued_composition_and_schema_ops() -> None:
    assert evaluate({"op": "and", "args": [{"op": "eq", "field": "x", "value": 0}, {"op": "eq", "field": "missing", "value": 1}]}, {"x": 1}).result is Truth.FALSE
    assert evaluate({"op": "implies", "when": {"op": "eq", "field": "x", "value": 0}, "then": {"op": "eq", "field": "missing", "value": 1}}, {"x": 1}).result is Truth.TRUE
    assert evaluate({"op": "mutex", "items": [{"op": "eq", "field": "a", "value": 1}, {"op": "eq", "field": "b", "value": 1}]}, {"a": 1, "b": 1}).result is Truth.FALSE
    assert evaluate({"op": "compatible_set", "fields": ["layout", "dtype"], "allowed": [{"layout": "NZ", "dtype": "fp16"}]}, {"layout": "NZ", "dtype": "fp16"}).result is Truth.TRUE


def test_typed_integer_and_enum_are_explicit() -> None:
    expr = {"op": "eq", "field": "x", "value": 7, "type": "int", "width": 3, "signed": False}
    assert evaluate(expr, {"x": 7}).result is Truth.TRUE
    assert evaluate(expr, {"x": 8}).result is Truth.UNSUPPORTED
    enum = {"op": "eq", "field": "layout", "value": "NZ", "type": "enum", "domain": ["NZ", "ND"]}
    assert evaluate(enum, {"layout": "BAD"}).result is Truth.UNSUPPORTED


def test_numeric_text_matches_numeric_literal() -> None:
    """Case tables carry columns as text; plan predicates spell them as numbers."""
    eq = {"op": "eq", "field": "sparse_mode", "value": 4}
    assert evaluate(eq, {"sparse_mode": "4"}).result is Truth.TRUE
    assert evaluate(eq, {"sparse_mode": 4}).result is Truth.TRUE
    assert evaluate(eq, {"sparse_mode": "3"}).result is Truth.FALSE
    # reversed: text literal against a numeric observation
    assert evaluate({"op": "eq", "field": "s", "value": "4"}, {"s": 4}).result is Truth.TRUE
    # float / int spelling of the same number
    assert evaluate({"op": "eq", "field": "s", "value": 4}, {"s": "4.0"}).result is Truth.TRUE


def test_membership_normalises_each_candidate() -> None:
    expr = {"op": "in", "field": "sparse_mode", "values": [5, 6]}
    assert evaluate(expr, {"sparse_mode": "5"}).result is Truth.TRUE
    assert evaluate(expr, {"sparse_mode": "4"}).result is Truth.FALSE
    neg = {"op": "not_in", "field": "sparse_mode", "values": [5, 6]}
    assert evaluate(neg, {"sparse_mode": "4"}).result is Truth.TRUE
    assert evaluate(neg, {"sparse_mode": "6"}).result is Truth.FALSE


def test_normalisation_does_not_conflate_bool_or_free_text() -> None:
    # plain equality is untouched, so bool still matches 1 / 0 as it always did
    # (an `expected: true` evidence must keep matching a uint8 field of 1)
    assert evaluate({"op": "eq", "field": "f", "value": 1}, {"f": True}).result is Truth.TRUE
    # but bool never joins the *numeric text* normalisation
    assert evaluate({"op": "eq", "field": "f", "value": True}, {"f": "1"}).result is Truth.FALSE
    assert evaluate({"op": "eq", "field": "f", "value": "true"}, {"f": True}).result is Truth.FALSE
    # a non-numeric string never matches a number
    assert evaluate({"op": "eq", "field": "f", "value": 0}, {"f": "BNSD"}).result is Truth.FALSE
    # empty text is not zero
    assert evaluate({"op": "eq", "field": "f", "value": 0}, {"f": ""}).result is Truth.FALSE
    # enum strings still compare exactly, modulo surrounding whitespace
    assert evaluate({"op": "eq", "field": "f", "value": "BNSD"}, {"f": " BNSD "}).result is Truth.TRUE
    assert evaluate({"op": "eq", "field": "f", "value": "BNSD"}, {"f": "bnsd"}).result is Truth.FALSE
