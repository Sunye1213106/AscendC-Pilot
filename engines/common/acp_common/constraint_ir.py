# -*- coding: utf-8 -*-
"""Solver-facing constraint IR shared by the uo-init and testcase-generation engines.

Extracted verbatim from `testcase_agent.constraint_ir` so both engines normalize
and validate expressions through one implementation. Everything here is pure:
no obligations, no snapshots, no realization map. Those stay in the TG layer,
which re-exports these names so its own importers keep working unchanged.
"""
from __future__ import annotations

from typing import Any

SUPPORTED_VAR_TYPES = {"bool", "int", "enum"}

SUPPORTED_EXPR_OPS = {
    "eq",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
    "in",
    "not_in",
    "and",
    "or",
    "not",
    "implies",
    "requires",
    "mutex",
    "add",
    "sub",
    "mul",
    "div",
    "mod",
    "aligned",
    "derived",
    "if_then_else",
    "lit",
}

def _error(code: str, *, scope: str, severity: str = "error", **fields: Any) -> dict[str, Any]:
    return {"code": code, "scope": scope, "severity": severity, **fields}

class ConstraintIRError(ValueError):
    pass

def compile_pattern_to_expr(pattern: Any) -> dict[str, Any] | None:
    if not isinstance(pattern, dict) or not pattern:
        return None
    args = [{"op": "eq", "var": _var_id(str(key)), "value": value} for key, value in sorted(pattern.items())]
    return args[0] if len(args) == 1 else {"op": "and", "args": args}

def normalize_expr(expr: Any, memo: dict[int, Any] | None = None) -> dict[str, Any]:
    """Rewrite an expression into the canonical shape, recursively.

    `memo` makes that recursion proportional to the number of distinct nodes
    rather than to paths through them. An expression reached along many paths
    is one shared node, and rebuilding it per path is what turns a DAG of ten
    thousand nodes into a tree of more nodes than can be counted. Pass one
    whenever the input may be a DAG; it is keyed on identity and holds a
    reference to every node it answers for, so no id is recycled while in use.
    """
    if memo is not None and isinstance(expr, dict):
        hit = memo.get(id(expr))
        if hit is not None:
            return hit[1]
    out = _normalize_expr_uncached(expr, memo)
    if memo is not None and isinstance(expr, dict):
        memo[id(expr)] = (expr, out)
        # The result is canonical already, so normalising it again yields an
        # equal value -- but a freshly built one, whose children are new
        # objects that miss every identity-keyed memo below. Callers do
        # normalise twice (once at the assertion, once inside the compile), and
        # without this each pass rebuilt the whole graph one level deeper,
        # turning a shared DAG back into work proportional to its paths.
        if isinstance(out, dict):
            memo.setdefault(id(out), (out, out))
    return out


def _normalize_expr_uncached(expr: Any, memo: dict[int, Any] | None) -> dict[str, Any]:
    if not isinstance(expr, dict):
        raise ConstraintIRError(f"Constraint expression must be a mapping, got {type(expr).__name__}")
    op = str(expr.get("op") or expr.get("type") or "").strip()
    if not op:
        if {"var", "value"} <= set(expr):
            op = "eq"
        else:
            raise ConstraintIRError(f"Expression is missing op: {expr}")
    if op not in SUPPORTED_EXPR_OPS:
        raise ConstraintIRError(f"Unsupported expression op: {op}")
    out: dict[str, Any] = {"op": op}
    if op in {"eq", "ne", "lt", "le", "gt", "ge"}:
        if "lhs" in expr or "rhs" in expr:
            out["lhs"] = _normalize_value_or_expr(expr.get("lhs"), memo)
            out["rhs"] = _normalize_value_or_expr(expr.get("rhs"), memo)
        else:
            out["var"] = _require_var(expr)
            out["value"] = expr.get("value")
    elif op in {"in", "not_in"}:
        out["var"] = _require_var(expr)
        out["values"] = _as_list(expr.get("values") if "values" in expr else expr.get("value"))
    elif op in {"and", "or"}:
        out["args"] = [normalize_expr(arg, memo) for arg in _require_args(expr)]
    elif op == "not":
        out["arg"] = normalize_expr(expr.get("arg") or expr.get("expr"), memo)
    elif op in {"implies", "requires"}:
        out["antecedent"] = normalize_expr(expr.get("antecedent") or expr.get("if") or expr.get("requires"), memo)
        out["consequent"] = normalize_expr(expr.get("consequent") or expr.get("then") or expr.get("required"), memo)
    elif op == "mutex":
        out["args"] = [normalize_expr(arg, memo) for arg in _require_args(expr)]
    elif op in {"add", "sub", "mul", "div", "mod"}:
        out["args"] = [_normalize_arith_arg(arg, memo) for arg in _require_args(expr)]
    elif op == "lit":
        out["value"] = expr.get("value")
    elif op == "aligned":
        out["var"] = _require_var(expr)
        out["alignment"] = int(expr.get("alignment") or expr.get("value") or 1)
    elif op == "derived":
        out["var"] = _require_var(expr)
        out["expr"] = normalize_expr(expr.get("expr") or expr.get("definition"), memo)
    elif op == "if_then_else":
        out["condition"] = normalize_expr(expr.get("condition") or expr.get("if"), memo)
        out["then"] = _normalize_value_or_expr(expr.get("then"), memo)
        out["else"] = _normalize_value_or_expr(expr.get("else"), memo)
    return out

def normalize_domain(var_type: str, spec: dict[str, Any]) -> Any:
    if var_type == "bool":
        return [False, True]
    if "domain" in spec:
        domain = spec["domain"]
        if var_type == "int" and isinstance(domain, dict):
            return {"kind": "range", "min": domain.get("min"), "max": domain.get("max"), "explicit": True, "authority": "explicit", "sources": ["contract_variables"]}
        if var_type == "int" and isinstance(domain, list):
            return {"kind": "discrete", "values": sorted(dict.fromkeys(int(item) for item in domain)), "explicit": True, "authority": "explicit", "sources": ["contract_variables"]}
        return domain
    if "values" in spec:
        values = spec["values"]
        if var_type == "int" and isinstance(values, list) and values:
            return {"kind": "discrete", "values": sorted(dict.fromkeys(int(item) for item in values)), "explicit": True, "authority": "explicit", "sources": ["contract_variables"]}
        return values
    if "enum_values" in spec:
        return spec["enum_values"]
    if var_type == "int":
        if "min" in spec or "max" in spec:
            return {"kind": "range", "min": spec.get("min"), "max": spec.get("max"), "explicit": True, "authority": "explicit", "sources": ["contract_variables"]}
        return {"kind": "range", "min": None, "max": None, "explicit": False, "authority": "inferred", "sources": ["contract_type_only"]}
    return []

def has_explicit_domain(spec: dict[str, Any], var_type: str) -> bool:
    if var_type == "bool":
        return True
    if "domain" in spec and spec.get("domain") not in (None, [], {}):
        return True
    if "values" in spec and spec.get("values") not in (None, []):
        return True
    if "enum_values" in spec and spec.get("enum_values") not in (None, []):
        return True
    return "min" in spec or "max" in spec

def parse_bool_literal(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text == "true":
            return True
        if text == "false":
            return False
    raise ConstraintIRError(f"INVALID_BOOL_LITERAL: {value!r}")

def collect_expr_variables(expr: Any) -> set[str]:
    found: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            var = node.get("var") or node.get("variable")
            if isinstance(var, str):
                found.add(var)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(expr)
    return found

def _int_domain(values: list[int] | None = None, *, min_value: Any = None, max_value: Any = None, source: str, authority: str) -> dict[str, Any]:
    clean = sorted(dict.fromkeys(int(value) for value in values or []))
    if clean:
        return {"kind": "discrete", "values": clean, "explicit": authority == "explicit", "authority": authority, "sources": [source]}
    if min_value is not None or max_value is not None:
        return {
            "kind": "range",
            "min": int(min_value) if min_value is not None else None,
            "max": int(max_value) if max_value is not None else None,
            "explicit": authority == "explicit",
            "authority": authority,
            "sources": [source],
        }
    return {"kind": "range", "min": None, "max": None, "explicit": False, "authority": authority, "sources": [source]}

def _merge_int_domain(left: Any, right: Any, left_authority: str, right_authority: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    left = _normalize_int_domain(left, left_authority)
    right = _normalize_int_domain(right, right_authority)
    errors: list[dict[str, Any]] = []
    for domain in (left, right):
        if domain.get("kind") != "range":
            continue
        if domain.get("min") is not None and domain.get("max") is not None and int(domain["min"]) > int(domain["max"]):
            errors.append({"code": "INVALID_INT_DOMAIN", "message": "min is greater than max"})
    def outside(value: Any, domain: dict[str, Any]) -> bool:
        if domain.get("kind") == "discrete":
            return int(value) not in [int(item) for item in domain.get("values", [])]
        return (domain.get("min") is not None and value < int(domain["min"])) or (domain.get("max") is not None and value > int(domain["max"]))
    def requested_values(domain: dict[str, Any]) -> list[int]:
        if domain.get("kind") == "discrete":
            return [int(item) for item in domain.get("values", [])]
        return [int(value) for value in (domain.get("min"), domain.get("max")) if value is not None]
    if left_authority == "explicit" and right_authority != "explicit":
        for value in requested_values(right):
            if outside(int(value), left):
                errors.append({"code": "OBLIGATION_OUTSIDE_DECLARED_DOMAIN", "requested_value": str(value), "declared_domain": _format_int_domain(left)})
        result = dict(left)
        result.update({"authority": "explicit", "explicit": True, "sources": sorted(set(_as_list(left.get("sources")) + _as_list(right.get("sources"))))})
        return result, errors
    if left_authority != "explicit" and right_authority == "explicit":
        result = dict(right)
        result.update({"authority": "explicit", "explicit": True, "sources": sorted(set(_as_list(left.get("sources")) + _as_list(right.get("sources"))))})
        return result, errors
    if left_authority == "explicit" and right_authority == "explicit":
        result = _intersect_int_domains(left, right, "explicit")
        result["sources"] = sorted(set(_as_list(left.get("sources")) + _as_list(right.get("sources"))))
        if _int_domain_empty(result):
            errors.append({"code": "DOMAIN_CONFLICT", "message": "Explicit integer domains do not intersect"})
        return result, errors
    result = _merge_inferred_int_domains(left, right)
    result["sources"] = sorted(set(_as_list(left.get("sources")) + _as_list(right.get("sources"))))
    return result, errors

def _normalize_int_domain(domain: Any, authority: str = "inferred") -> dict[str, Any]:
    if isinstance(domain, list):
        return {"kind": "discrete", "values": sorted(dict.fromkeys(int(item) for item in domain)), "authority": authority, "explicit": authority == "explicit", "sources": []}
    if not isinstance(domain, dict):
        return {"kind": "range", "min": None, "max": None, "authority": authority, "explicit": authority == "explicit", "sources": []}
    if domain.get("kind") == "discrete" or "values" in domain:
        return {
            "kind": "discrete",
            "values": sorted(dict.fromkeys(int(item) for item in _as_list(domain.get("values")))),
            "authority": domain.get("authority", authority),
            "explicit": bool(domain.get("explicit", authority == "explicit")),
            "sources": _as_list(domain.get("sources")),
        }
    return {
        "kind": "range",
        "min": int(domain["min"]) if domain.get("min") is not None else None,
        "max": int(domain["max"]) if domain.get("max") is not None else None,
        "authority": domain.get("authority", authority),
        "explicit": bool(domain.get("explicit", authority == "explicit")),
        "sources": _as_list(domain.get("sources")),
    }

def _intersect_int_domains(left: dict[str, Any], right: dict[str, Any], authority: str) -> dict[str, Any]:
    if left.get("kind") == "discrete" and right.get("kind") == "discrete":
        return {"kind": "discrete", "values": sorted(set(left.get("values", [])) & set(right.get("values", []))), "authority": authority, "explicit": authority == "explicit"}
    if left.get("kind") == "range" and right.get("kind") == "range":
        mins = [value for value in (left.get("min"), right.get("min")) if value is not None]
        maxs = [value for value in (left.get("max"), right.get("max")) if value is not None]
        return {"kind": "range", "min": max(mins) if mins else None, "max": min(maxs) if maxs else None, "authority": authority, "explicit": authority == "explicit"}
    discrete = left if left.get("kind") == "discrete" else right
    range_domain = right if left.get("kind") == "discrete" else left
    values = [int(value) for value in discrete.get("values", []) if not _value_outside_range(int(value), range_domain)]
    return {"kind": "discrete", "values": sorted(values), "authority": authority, "explicit": authority == "explicit"}

def _merge_inferred_int_domains(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if left.get("kind") == "discrete" or right.get("kind") == "discrete":
        values = []
        values.extend(int(item) for item in left.get("values", []) if left.get("kind") == "discrete")
        values.extend(int(item) for item in right.get("values", []) if right.get("kind") == "discrete")
        if values:
            return {"kind": "discrete", "values": sorted(set(values)), "authority": "inferred", "explicit": False}
    mins = [value for value in (left.get("min"), right.get("min")) if value is not None]
    maxs = [value for value in (left.get("max"), right.get("max")) if value is not None]
    return {"kind": "range", "min": min(mins) if mins else None, "max": max(maxs) if maxs else None, "authority": "inferred", "explicit": False}

def _value_outside_range(value: int, domain: dict[str, Any]) -> bool:
    return (domain.get("min") is not None and value < int(domain["min"])) or (domain.get("max") is not None and value > int(domain["max"]))

def _int_domain_empty(domain: dict[str, Any]) -> bool:
    if domain.get("kind") == "discrete":
        return not domain.get("values")
    return domain.get("min") is not None and domain.get("max") is not None and int(domain["min"]) > int(domain["max"])

def _format_int_domain(domain: dict[str, Any]) -> Any:
    if domain.get("kind") == "discrete":
        return list(domain.get("values", []))
    return f"{domain.get('min')}..{domain.get('max')}"

def _validate_variable_domains(variables: dict[str, dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    for var_id, variable in variables.items():
        domain = variable.get("domain")
        if variable.get("type") != "int" or not isinstance(domain, dict):
            continue
        domain = _normalize_int_domain(domain, variable.get("domain_authority", "inferred"))
        variable["domain"] = domain
        lower, upper = domain.get("min"), domain.get("max")
        if domain.get("kind") == "range" and lower is not None and upper is not None and int(lower) > int(upper):
            errors.append(_error("INVALID_INT_DOMAIN", scope="global", variable_id=var_id, message="min is greater than max"))

def _require_var(expr: dict[str, Any]) -> str:
    var = expr.get("var") or expr.get("variable")
    if not var:
        raise ConstraintIRError(f"Expression requires var: {expr}")
    return str(var)

def _require_args(expr: dict[str, Any]) -> list[Any]:
    args = expr.get("args")
    if not isinstance(args, list) or not args:
        raise ConstraintIRError(f"Expression requires non-empty args: {expr}")
    return args

def _normalize_arith_arg(arg: Any, memo: dict[int, Any] | None = None) -> Any:
    if isinstance(arg, dict):
        if arg.get("op") == "lit":
            return arg.get("value")
        if "op" in arg:
            return normalize_expr(arg, memo)
        return {"var": _require_var(arg)}
    return arg

def _normalize_value_or_expr(value: Any, memo: dict[int, Any] | None = None) -> Any:
    if isinstance(value, dict) and "op" in value:
        return normalize_expr(value, memo)
    return value

def _var_id(name: str) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(name)).strip("_").upper()
    if text.startswith("VAR_"):
        return text
    return f"VAR_{text or 'UNKNOWN'}"

def _iter_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [{"id": str(key), **item} if isinstance(item, dict) else {"id": str(key), "value": item} for key, item in sorted(value.items())]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []

def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}

def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]
