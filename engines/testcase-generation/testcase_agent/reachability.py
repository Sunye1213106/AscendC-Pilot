"""Compute reachable images of derived expressions over finite CSV domains."""

from __future__ import annotations

from typing import Any


def csv_domains_from_map(realization_map: dict[str, Any]) -> dict[str, list[Any]]:
    domains: dict[str, list[Any]] = {}
    for spec in realization_map.get("csv_variables") or []:
        if not isinstance(spec, dict):
            continue
        var_id = str(spec.get("id") or "")
        if not var_id:
            continue
        domains[var_id] = _normalize_domain_values(spec.get("domain"), spec.get("type"))
    for spec in realization_map.get("free_variables") or []:
        if not isinstance(spec, dict):
            continue
        var_id = str(spec.get("id") or "")
        if not var_id:
            continue
        domains[var_id] = _normalize_domain_values(spec.get("domain"), spec.get("type") or "int")
    return domains


def annotate_reachable_values(realization_map: dict[str, Any]) -> dict[str, Any]:
    """Mutate/copy derived_variables with reachable_values; evaluate in dependency order.

    KEY/KVAR stubs that only reference CSV are computed first; branch derived vars that
    reference KEY then see KEY images in the domain environment (fixes image=unknown).
    """
    out = dict(realization_map)
    env: dict[str, list[Any]] = dict(csv_domains_from_map(out))
    specs = [item for item in out.get("derived_variables") or [] if isinstance(item, dict)]
    remaining = {str(item.get("id") or ""): dict(item) for item in specs if item.get("id")}
    derived_out: list[dict[str, Any]] = []
    progressed = True
    while remaining and progressed:
        progressed = False
        ready_ids = []
        for var_id, item in remaining.items():
            expr = item.get("expr")
            inner = expr.get("expr") if isinstance(expr, dict) and expr.get("op") == "derived" else expr
            if not isinstance(inner, dict):
                ready_ids.append(var_id)
                continue
            needed = _collect_vars(inner)
            if all(var in env and env[var] for var in needed):
                ready_ids.append(var_id)
        if not ready_ids:
            # Break cycles / missing deps: annotate remaining as unknown.
            break
        for var_id in ready_ids:
            item = remaining.pop(var_id)
            expr = item.get("expr")
            inner = expr.get("expr") if isinstance(expr, dict) and expr.get("op") == "derived" else expr
            if not isinstance(inner, dict):
                item["reachable_values"] = []
                item["reachable_status"] = "unknown"
                derived_out.append(item)
                progressed = True
                continue
            try:
                image = evaluate_expr_image(inner, env)
                item["reachable_values"] = image
                item["reachable_status"] = "ok"
                declared = _normalize_domain_values(item.get("domain"), item.get("type") or item.get("var_type"))
                if declared and image:
                    narrowed = [value for value in declared if _value_in(value, image)]
                    if not narrowed:
                        narrowed = list(image)
                    item["domain"] = narrowed
                    item["declared_domain"] = declared
                elif image:
                    item["domain"] = list(image)
                env[var_id] = list(item.get("domain") or image or [])
            except ReachabilityError as exc:
                item["reachable_values"] = []
                item["reachable_status"] = "unknown"
                item["reachable_error"] = str(exc)
            derived_out.append(item)
            progressed = True

    for var_id, item in remaining.items():
        expr = item.get("expr")
        inner = expr.get("expr") if isinstance(expr, dict) and expr.get("op") == "derived" else expr
        if not isinstance(inner, dict):
            item["reachable_values"] = []
            item["reachable_status"] = "unknown"
            derived_out.append(item)
            continue
        try:
            image = evaluate_expr_image(inner, env)
            item["reachable_values"] = image
            item["reachable_status"] = "ok"
            declared = _normalize_domain_values(item.get("domain"), item.get("type") or item.get("var_type"))
            if declared and image:
                narrowed = [value for value in declared if _value_in(value, image)]
                if not narrowed:
                    narrowed = list(image)
                item["domain"] = narrowed
                item["declared_domain"] = declared
            elif image:
                item["domain"] = list(image)
        except ReachabilityError as exc:
            item["reachable_values"] = []
            item["reachable_status"] = "unknown"
            item["reachable_error"] = str(exc)
        derived_out.append(item)

    # Preserve original order when possible.
    order = [str(item.get("id") or "") for item in specs]
    by_id = {str(item.get("id") or ""): item for item in derived_out}
    ordered = [by_id[i] for i in order if i in by_id]
    # Append any extras
    seen = set(order)
    ordered.extend(item for item in derived_out if str(item.get("id") or "") not in seen)
    out["derived_variables"] = ordered
    return out


def reachable_values_for_var(realization_map: dict[str, Any], var_id: str) -> list[Any] | None:
    """Return reachable values for a derived var, or None if unknown/not present."""
    for spec in realization_map.get("derived_variables") or []:
        if not isinstance(spec, dict):
            continue
        if str(spec.get("id") or "") != var_id:
            continue
        if spec.get("reachable_status") == "unknown":
            return None
        values = spec.get("reachable_values")
        if isinstance(values, list):
            return list(values)
        return _normalize_domain_values(spec.get("domain"), spec.get("type") or spec.get("var_type"))
    return None


def is_value_reachable(realization_map: dict[str, Any], var_id: str, value: Any) -> bool | None:
    """True/False if known; None if reachability unknown (do not filter)."""
    values = reachable_values_for_var(realization_map, var_id)
    if values is None:
        return None
    return _value_in(value, values)


def abstract_branch_ids(realization_map: dict[str, Any]) -> set[str]:
    return {
        str(item.get("branch_ref") or "")
        for item in realization_map.get("abstract_branches") or []
        if isinstance(item, dict) and item.get("branch_ref")
    }


def mapped_branch_ids(realization_map: dict[str, Any]) -> set[str]:
    return {
        str(item.get("branch_ref") or "")
        for item in realization_map.get("branch_mappings") or []
        if isinstance(item, dict) and item.get("branch_ref")
    }


class ReachabilityError(RuntimeError):
    pass


def evaluate_expr_image(expr: Any, domains: dict[str, list[Any]], *, max_assignments: int = 200_000) -> list[Any]:
    """Enumerate finite assignments for vars referenced by expr; return unique result values."""
    if not isinstance(expr, dict):
        return [_literal(expr)]
    vars_needed = sorted(_collect_vars(expr))
    missing = [var for var in vars_needed if var not in domains or not domains[var]]
    if missing:
        raise ReachabilityError(f"missing csv domains for {missing}")
    sizes = [len(domains[var]) for var in vars_needed]
    total = 1
    for size in sizes:
        total *= size
        if total > max_assignments:
            raise ReachabilityError(f"domain product too large ({total})")
    if not vars_needed:
        return [_eval(expr, {})]

    results: list[Any] = []
    seen: set[str] = set()

    def walk(index: int, assignment: dict[str, Any]) -> None:
        if index >= len(vars_needed):
            value = _eval(expr, assignment)
            key = repr(value)
            if key not in seen:
                seen.add(key)
                results.append(value)
            return
        var = vars_needed[index]
        for value in domains[var]:
            assignment[var] = value
            walk(index + 1, assignment)
        assignment.pop(var, None)

    walk(0, {})
    return results


def _collect_vars(expr: Any) -> set[str]:
    if isinstance(expr, dict):
        if "var" in expr and expr.get("op") in {None, "", "var"} and "op" not in expr:
            return {str(expr["var"])}
        if expr.get("op") is None and "var" in expr and len(expr) <= 2:
            return {str(expr["var"])}
        out: set[str] = set()
        if "var" in expr and str(expr.get("op") or "") in {"eq", "ne", "ge", "gt", "le", "lt"}:
            out.add(str(expr["var"]))
        for key in ("arg", "lhs", "rhs", "condition", "then", "else", "antecedent", "consequent", "expr"):
            child = expr.get(key)
            if child is not None:
                out |= _collect_vars(child)
        for key in ("args", "items"):
            for child in expr.get(key) or []:
                out |= _collect_vars(child)
        return out
    return set()


def _eval(expr: Any, assignment: dict[str, Any]) -> Any:
    if not isinstance(expr, dict):
        return _literal(expr)
    op = str(expr.get("op") or "")
    if op in {"", "var"} or ("var" in expr and op == ""):
        return assignment[str(expr["var"])]
    if "var" in expr and op == "" and "value" not in expr:
        return assignment[str(expr["var"])]
    if op == "lit":
        return expr.get("value")
    if op == "eq":
        if "var" in expr and "lhs" not in expr:
            return _norm(assignment.get(str(expr["var"]))) == _norm(expr.get("value"))
        return _norm(_eval(expr.get("lhs"), assignment)) == _norm(_eval(expr.get("rhs"), assignment))
    if op == "ne":
        if "var" in expr and "lhs" not in expr:
            return _norm(assignment.get(str(expr["var"]))) != _norm(expr.get("value"))
        return _norm(_eval(expr.get("lhs"), assignment)) != _norm(_eval(expr.get("rhs"), assignment))
    if op in {"ge", "gt", "le", "lt"}:
        if "var" in expr and "lhs" not in expr:
            left = _as_number(assignment.get(str(expr["var"])))
            right = _as_number(expr.get("value"))
        else:
            left = _as_number(_eval(expr.get("lhs"), assignment))
            right = _as_number(_eval(expr.get("rhs"), assignment))
        if op == "ge":
            return left >= right
        if op == "gt":
            return left > right
        if op == "le":
            return left <= right
        return left < right
    if op == "not":
        return not bool(_eval(expr.get("arg"), assignment))
    if op == "and":
        return all(bool(_eval(item, assignment)) for item in expr.get("args") or [])
    if op == "or":
        return any(bool(_eval(item, assignment)) for item in expr.get("args") or [])
    if op == "if_then_else":
        cond = bool(_eval(expr.get("condition"), assignment))
        return _eval(expr.get("then") if cond else expr.get("else"), assignment)
    if op == "derived":
        return _eval(expr.get("expr"), assignment)
    if op in {"add", "sub", "mul", "div", "mod"}:
        args = [_as_number(_eval(item, assignment)) for item in expr.get("args") or []]
        if not args:
            return 0
        if op == "add":
            return sum(args)
        if op == "sub":
            head = args[0]
            for item in args[1:]:
                head -= item
            return head
        if op == "mul":
            head = args[0]
            for item in args[1:]:
                head *= item
            return head
        if op == "div":
            return args[0] / args[1] if len(args) > 1 and args[1] else args[0]
        if op == "mod":
            return args[0] % args[1] if len(args) > 1 and args[1] else args[0]
    # bare var ref {"var": "X"}
    if "var" in expr and op not in {"eq", "ne", "ge", "gt", "le", "lt"}:
        return assignment[str(expr["var"])]
    raise ReachabilityError(f"unsupported op for reachability: {op}")


# Full expand for tiny ranges; larger ranges are sampled for image analysis only.
# Planning still keeps the real {min,max} bounds — this list is NOT the domain.
_MAX_RANGE_EXPAND = 256
_RANGE_SAMPLE_ANCHORS = (
    0,
    1,
    2,
    4,
    8,
    16,
    32,
    64,
    128,
    192,
    256,
    512,
    768,
    1024,
    2048,
    4096,
    8192,
    16384,
    32768,
    65536,
)


def _sample_int_range(lower: int, upper: int) -> list[int]:
    """Representative points covering min/max and common shape/template thresholds."""
    if upper < lower:
        lower, upper = upper, lower
    span = upper - lower
    if span + 1 <= _MAX_RANGE_EXPAND:
        return list(range(lower, upper + 1))
    points = {lower, upper}
    for anchor in _RANGE_SAMPLE_ANCHORS:
        if lower <= anchor <= upper:
            points.add(anchor)
    # A few evenly spaced interiors so ge/le bucket thresholds can fire.
    steps = 16
    for i in range(1, steps):
        points.add(lower + (span * i) // steps)
    return sorted(points)


def _normalize_domain_values(domain: Any, var_type: Any = None) -> list[Any]:
    if isinstance(domain, list):
        values = list(domain)
    elif isinstance(domain, dict):
        if domain.get("values") is not None:
            values = list(domain.get("values") or [])
        elif domain.get("min") is not None and domain.get("max") is not None:
            lower, upper = int(domain["min"]), int(domain["max"])
            values = _sample_int_range(lower, upper)
        else:
            values = []
    else:
        values = []
    if str(var_type or "") == "bool":
        return [False, True] if not values else [_truthy(item) for item in values]
    return values


def _value_in(value: Any, values: list[Any]) -> bool:
    norm = _norm(value)
    return any(_norm(item) == norm for item in values)


def _norm(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer():
            return int(value)
        return float(value)
    text = str(value)
    lower = text.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    try:
        number = float(text)
        if number.is_integer():
            return int(number)
        return number
    except (TypeError, ValueError):
        return text


def _literal(value: Any) -> Any:
    return value


def _as_number(value: Any) -> float:
    if isinstance(value, bool):
        return float(int(value))
    return float(value)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).lower() in {"true", "1", "yes"}
