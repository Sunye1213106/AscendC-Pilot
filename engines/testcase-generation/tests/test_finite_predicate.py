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
