# -*- coding: utf-8 -*-
"""Structured predicates for tg-plan/v3. Free-form strings are unsupported."""

from __future__ import annotations

from typing import Any

from testcase_agent.closure.finite_predicate import Evaluation, Truth, evaluate as _finite_evaluate

KNOWN_OPS = frozenset(
    {
        "eq",
        "ne",
        "in",
        "not_in",
        "and",
        "or",
        "not",
        "lt",
        "le",
        "gt",
        "ge",
        "mod_eq",
        "is_null",
        "is_present",
        "implies",
        "requires",
    }
)


def is_predicate(expr: Any) -> bool:
    return isinstance(expr, dict) and str(expr.get("op") or "").lower() in KNOWN_OPS


def predicate_fields(expr: Any) -> list[str]:
    """Collect field names referenced by a structured predicate."""
    if not isinstance(expr, dict):
        return []
    out: list[str] = []
    op = str(expr.get("op") or "").lower()
    if op == "mod_eq":
        for key in ("left", "field"):
            raw = expr.get(key)
            if isinstance(raw, str) and raw.strip():
                out.append(raw.strip())
                break
        right = expr.get("right")
        if isinstance(right, str) and right.strip() and not _numeric_text(right):
            out.append(right.strip())
    else:
        raw = expr.get("field") or expr.get("left")
        if isinstance(raw, str) and raw.strip():
            out.append(raw.strip())
    for child in expr.get("args") or []:
        out.extend(predicate_fields(child))
    for key in ("arg", "when", "then"):
        if expr.get(key) is not None:
            out.extend(predicate_fields(expr.get(key)))
    return out


def _numeric_text(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, str):
        return False
    text = value.strip()
    if not text or text.lower() in {"inf", "+inf", "-inf", "nan"}:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def validate_predicate(expr: Any, *, path: str = "predicate") -> list[str]:
    errors: list[str] = []
    if not isinstance(expr, dict):
        return [f"{path} must be a mapping with op="]
    op = str(expr.get("op") or "").lower()
    if op not in KNOWN_OPS:
        errors.append(f"{path} unknown op {op!r}")
        return errors
    if op in {"and", "or"}:
        args = expr.get("args")
        if not isinstance(args, list) or not args:
            errors.append(f"{path}.args must be a nonempty list")
        else:
            for i, child in enumerate(args):
                errors.extend(validate_predicate(child, path=f"{path}.args[{i}]"))
    elif op == "not":
        errors.extend(validate_predicate(expr.get("arg"), path=f"{path}.arg"))
    elif op in {"implies", "requires"}:
        errors.extend(validate_predicate(expr.get("when"), path=f"{path}.when"))
        errors.extend(validate_predicate(expr.get("then"), path=f"{path}.then"))
    elif op in {"eq", "ne"}:
        raw = expr.get("field") if expr.get("field") is not None else expr.get("left")
        if not isinstance(raw, str) or not raw.strip():
            errors.append(f"{path} {op} requires string field")
        if "value" not in expr:
            errors.append(f"{path} {op} requires value")
        elif isinstance(expr.get("value"), (dict, list, tuple)):
            errors.append(f"{path} {op} value must be a scalar")
    elif op in {"in", "not_in"}:
        if not str(expr.get("field") or "").strip():
            errors.append(f"{path} {op} requires field")
        values = expr.get("values")
        if not isinstance(values, list) or not values:
            errors.append(f"{path} {op} requires nonempty values list")
    elif op in {"lt", "le", "gt", "ge"}:
        raw = expr.get("field") if expr.get("field") is not None else expr.get("left")
        if not isinstance(raw, str) or not raw.strip():
            errors.append(f"{path} {op} requires string field")
        if "value" not in expr:
            errors.append(f"{path} {op} requires value")
        elif isinstance(expr.get("value"), (dict, list, tuple)):
            errors.append(f"{path} {op} value must be a scalar")
    elif op in {"is_null", "is_present"}:
        if not str(expr.get("field") or "").strip():
            errors.append(f"{path} {op} requires field")
    elif op == "mod_eq":
        if not str(expr.get("left") or expr.get("field") or "").strip():
            errors.append(f"{path} mod_eq requires left/field")
        has_right = isinstance(expr.get("right"), str) and str(expr.get("right")).strip()
        if not has_right and expr.get("divisor") is None and expr.get("right") is None:
            errors.append(f"{path} mod_eq requires right field or divisor")
    return errors


def flatten_observe(observe: dict[str, Any] | None) -> dict[str, Any]:
    """Flatten {case, replay, probe} plus dotted aliases into one value map."""
    doc = observe if isinstance(observe, dict) else {}
    out: dict[str, Any] = {}

    def _put(prefix: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        for key, value in payload.items():
            name = str(key or "").strip()
            if not name:
                continue
            dotted = f"{prefix}.{name}"
            out[dotted] = value
            out.setdefault(name, value)

    _put("case", doc.get("case"))
    _put("replay", doc.get("replay"))
    _put("probe", doc.get("probe"))
    for key, value in doc.items():
        if key in {"case", "replay", "probe"}:
            continue
        if isinstance(value, dict):
            continue
        name = str(key or "").strip()
        if name:
            out.setdefault(name, value)
    return out


def _lookup(expr: dict[str, Any], values: dict[str, Any]) -> tuple[bool, Any]:
    field = expr.get("field") or expr.get("left")
    if not isinstance(field, str) or not field:
        return False, None
    if field in values:
        return True, values[field]
    return False, None


def _as_number(value: Any) -> tuple[bool, float | int]:
    if isinstance(value, bool):
        return False, 0
    if isinstance(value, int):
        return True, value
    if isinstance(value, float):
        if value in (float("inf"), float("-inf")) or value != value:
            return False, 0.0
        return True, value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.lower() in {"inf", "+inf", "-inf", "nan"}:
            return False, 0.0
        sign = text[0] in "+-"
        digits = text[1:] if sign else text
        if digits.isdigit():
            try:
                return True, int(text)
            except ValueError:
                return False, 0.0
        try:
            parsed = float(text)
        except ValueError:
            return False, 0.0
        if parsed in (float("inf"), float("-inf")) or parsed != parsed:
            return False, 0.0
        return True, parsed
    return False, 0.0


def _is_nullish(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "nil"}:
        return True
    return False


def evaluate(expr: Any, values: dict[str, Any] | None = None) -> Evaluation:
    data = values if isinstance(values, dict) else {}
    if not isinstance(expr, dict):
        return Evaluation(Truth.UNSUPPORTED, {"reason": "expression_not_mapping"})
    op = str(expr.get("op") or "").lower()
    if op not in KNOWN_OPS:
        return Evaluation(Truth.UNSUPPORTED, {"op": op or None, "reason": "operator_unsupported"})

    if op in {"is_null", "is_present"}:
        field = str(expr.get("field") or "").strip()
        if not field:
            return Evaluation(Truth.UNSUPPORTED, {"op": op, "reason": "field_missing"})
        if field not in data:
            nullish = True
        else:
            nullish = _is_nullish(data.get(field))
        hit = nullish if op == "is_null" else not nullish
        return Evaluation(Truth.TRUE if hit else Truth.FALSE, {"op": op, "field": field, "nullish": nullish})

    if op in {"lt", "le", "gt", "ge"}:
        present, actual = _lookup(expr, data)
        if not present:
            return Evaluation(Truth.UNKNOWN, {"op": op, "reason": "field_absent"})
        ok_a, left = _as_number(actual)
        ok_b, right = _as_number(expr.get("value"))
        if not ok_a or not ok_b:
            return Evaluation(Truth.UNSUPPORTED, {"op": op, "reason": "not_numeric"})
        matched = {
            "lt": left < right,
            "le": left <= right,
            "gt": left > right,
            "ge": left >= right,
        }[op]
        return Evaluation(Truth.TRUE if matched else Truth.FALSE, {"op": op, "actual": left, "expected": right})

    if op == "mod_eq":
        left_field = expr.get("left") or expr.get("field")
        right_field = expr.get("right")
        if not isinstance(left_field, str) or not left_field:
            return Evaluation(Truth.UNSUPPORTED, {"op": op, "reason": "left_missing"})
        if left_field not in data:
            return Evaluation(Truth.UNKNOWN, {"op": op, "reason": "left_absent"})
        ok_l, left = _as_number(data.get(left_field))
        if isinstance(right_field, str) and right_field:
            if right_field not in data:
                return Evaluation(Truth.UNKNOWN, {"op": op, "reason": "right_absent"})
            ok_r, right = _as_number(data.get(right_field))
        else:
            ok_r, right = _as_number(expr.get("divisor") if expr.get("divisor") is not None else right_field)
        ok_v, expect = _as_number(expr.get("value") if expr.get("value") is not None else 0)
        if not ok_l or not ok_r or not ok_v or right == 0:
            return Evaluation(Truth.UNSUPPORTED, {"op": op, "reason": "mod_domain"})
        if isinstance(left, int) and isinstance(right, int) and isinstance(expect, int):
            matched = left % right == expect
        else:
            matched = int(left) % int(right) == int(expect)
        return Evaluation(
            Truth.TRUE if matched else Truth.FALSE,
            {"op": op, "left": left, "right": right, "value": expect},
        )

    if op in {"and", "or", "not", "eq", "ne", "in", "not_in", "implies", "requires"}:
        return _finite_evaluate(expr, data)
    return Evaluation(Truth.UNSUPPORTED, {"op": op, "reason": "operator_unsupported"})
