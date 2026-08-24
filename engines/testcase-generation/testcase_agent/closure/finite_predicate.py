"""Deterministic four-valued evaluator for finite TilingKey relations.

This deliberately accepts only a small declarative schema.  Unsupported input
or a missing source value stays visible as ``UNSUPPORTED``/``UNKNOWN`` and is
never silently collapsed into a negative reachability conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Truth(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class Evaluation:
    result: Truth
    trace: dict[str, Any]


def _merge_unknown(values: list[Evaluation]) -> Truth:
    return Truth.UNSUPPORTED if any(v.result is Truth.UNSUPPORTED for v in values) else Truth.UNKNOWN


def _typed(value: Any, spec: dict[str, Any]) -> tuple[bool, Any]:
    kind = str(spec.get("type") or "").lower()
    if not kind:
        return True, value
    if kind == "bool":
        return isinstance(value, bool), value
    if kind == "enum":
        domain = spec.get("domain")
        return isinstance(domain, list) and value in domain, value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return False, value
        width = int(spec.get("width") or 0)
        signed = bool(spec.get("signed", True))
        if width <= 0:
            return False, value
        low = -(1 << (width - 1)) if signed else 0
        high = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
        return low <= value <= high, value
    return False, value


def _as_number(value: Any) -> float | int | None:
    """Numeric view of a scalar, or None when it is not a clean number.

    ``bool`` is excluded on purpose so ``True`` never compares equal to ``1``.
    Integer spellings stay integers so values above 2^53 do not round through float.
    inf / nan are rejected.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value in (float("inf"), float("-inf")) or value != value:
            return None
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"inf", "+inf", "-inf", "nan"}:
            return None
        sign = text[0] in "+-"
        digits = text[1:] if sign else text
        if digits.isdigit():
            try:
                return int(text)
            except ValueError:
                return None
        try:
            parsed = float(text)
        except ValueError:
            return None
        if parsed in (float("inf"), float("-inf")) or parsed != parsed:
            return None
        return parsed
    return None


def _scalar_equal(actual: Any, expected: Any) -> bool:
    """Compare one observed value against one expected literal.

    Case tables carry every column as text while plan predicates spell numeric
    columns as numbers, so equality must not depend on which side happened to be
    quoted. This only *adds* two normalisations on top of plain equality —
    numeric strings and surrounding whitespace. A non-numeric string never
    matches a number, and ``bool`` never takes part in numeric normalisation.
    """
    if actual == expected:
        return True
    left, right = _as_number(actual), _as_number(expected)
    if left is not None and right is not None:
        if isinstance(left, int) and isinstance(right, int):
            return left == right
        return float(left) == float(right)
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.strip() == expected.strip()
    return False


def _field(expr: dict[str, Any], values: dict[str, Any]) -> tuple[Truth | None, Any, str]:
    field = expr.get("field")
    if not isinstance(field, str) or not field:
        return Truth.UNSUPPORTED, None, "field_missing"
    if field not in values:
        return Truth.UNKNOWN, None, "field_absent"
    value = values[field]
    if value is None:
        return Truth.UNKNOWN, None, "field_null"
    ok, value = _typed(value, expr)
    if not ok:
        return Truth.UNSUPPORTED, value, "type_mismatch"
    return None, value, ""


def evaluate(expr: Any, values: dict[str, Any]) -> Evaluation:
    """Evaluate one finite predicate and retain an auditable recursive trace."""
    if not isinstance(expr, dict):
        return Evaluation(Truth.UNSUPPORTED, {"reason": "expression_not_mapping"})
    op = str(expr.get("op") or "").lower()

    if op in {"eq", "ne", "in", "not_in", "compile_time_fixed"}:
        state, actual, reason = _field(expr, values)
        if state is not None:
            return Evaluation(state, {"op": op, "field": expr.get("field"), "reason": reason})
        expected = expr.get("value") if op in {"eq", "ne", "compile_time_fixed"} else expr.get("values")
        if op in {"in", "not_in"} and not isinstance(expected, list):
            return Evaluation(Truth.UNSUPPORTED, {"op": op, "reason": "values_not_list"})
        if op in {"in", "not_in"}:
            matched = any(_scalar_equal(actual, item) for item in expected)
        else:
            matched = _scalar_equal(actual, expected)
        if op in {"ne", "not_in"}:
            matched = not matched
        return Evaluation(Truth.TRUE if matched else Truth.FALSE, {"op": op, "field": expr["field"], "actual": actual, "expected": expected})

    if op in {"and", "or"}:
        raw_args = expr.get("args")
        if not isinstance(raw_args, list) or not raw_args:
            return Evaluation(Truth.UNSUPPORTED, {"op": op, "reason": "args_not_nonempty_list"})
        children = [evaluate(item, values) for item in raw_args]
        results = [child.result for child in children]
        if op == "and":
            result = Truth.FALSE if Truth.FALSE in results else (Truth.TRUE if all(r is Truth.TRUE for r in results) else _merge_unknown(children))
        else:
            result = Truth.TRUE if Truth.TRUE in results else (Truth.FALSE if all(r is Truth.FALSE for r in results) else _merge_unknown(children))
        return Evaluation(result, {"op": op, "children": [child.trace for child in children]})

    if op == "not":
        child = evaluate(expr.get("arg"), values)
        result = {Truth.TRUE: Truth.FALSE, Truth.FALSE: Truth.TRUE}.get(child.result, child.result)
        return Evaluation(result, {"op": op, "child": child.trace})

    if op in {"implies", "requires"}:
        antecedent = evaluate(expr.get("when"), values)
        consequent = evaluate(expr.get("then"), values)
        if antecedent.result is Truth.FALSE or consequent.result is Truth.TRUE:
            result = Truth.TRUE
        elif antecedent.result is Truth.TRUE:
            result = consequent.result
        elif consequent.result is Truth.FALSE:
            result = _merge_unknown([antecedent])
        else:
            result = _merge_unknown([antecedent, consequent])
        return Evaluation(result, {"op": op, "when": antecedent.trace, "then": consequent.trace})

    if op == "mutex":
        raw_items = expr.get("items")
        if not isinstance(raw_items, list) or len(raw_items) < 2:
            return Evaluation(Truth.UNSUPPORTED, {"op": op, "reason": "items_not_pair"})
        children = [evaluate(item, values) for item in raw_items]
        true_count = sum(child.result is Truth.TRUE for child in children)
        result = Truth.FALSE if true_count > 1 else (Truth.TRUE if all(child.result in {Truth.TRUE, Truth.FALSE} for child in children) else _merge_unknown(children))
        return Evaluation(result, {"op": op, "children": [child.trace for child in children]})

    if op == "compatible_set":
        allowed = expr.get("allowed")
        fields = expr.get("fields")
        if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields) or not isinstance(allowed, list):
            return Evaluation(Truth.UNSUPPORTED, {"op": op, "reason": "invalid_compatible_set_schema"})
        missing = [field for field in fields if field not in values or values[field] is None]
        if missing:
            return Evaluation(Truth.UNKNOWN, {"op": op, "missing": missing})
        actual = {field: values[field] for field in fields}
        matched = any(isinstance(item, dict) and all(item.get(field) == actual[field] for field in fields) for item in allowed)
        return Evaluation(Truth.TRUE if matched else Truth.FALSE, {"op": op, "actual": actual, "allowed_count": len(allowed)})

    return Evaluation(Truth.UNSUPPORTED, {"op": op or None, "reason": "operator_unsupported"})
