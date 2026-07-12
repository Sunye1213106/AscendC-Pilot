from __future__ import annotations

from dataclasses import dataclass
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
}


class ConstraintIRError(ValueError):
    pass


@dataclass(frozen=True)
class IRBuildResult:
    ir: dict[str, Any]
    errors: list[dict[str, str]]


def build_constraint_ir(snapshot: dict[str, Any], obligations_doc: dict[str, Any], human_supplement: dict[str, Any] | None = None) -> IRBuildResult:
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    contract = _as_dict(files.get("contracts/testcase.yaml"))
    obligations = [item for item in obligations_doc.get("obligations", []) if isinstance(item, dict)]
    human_supplement = human_supplement if isinstance(human_supplement, dict) else {}
    errors: list[dict[str, str]] = []
    variables: dict[str, dict[str, Any]] = {}
    constraints: list[dict[str, Any]] = []

    for spec in _iter_items(contract.get("variables")) + _iter_items(_as_dict(contract.get("constraint_ir")).get("variables")):
        _add_variable(variables, spec, errors, "contracts/testcase.yaml.variables")
    _variables_from_interface(variables, contract)
    _variables_from_obligations(variables, obligations)

    constraint_specs = []
    constraint_specs.extend(_iter_items(contract.get("typed_constraints")))
    constraint_specs.extend(_iter_items(_as_dict(contract.get("constraint_ir")).get("constraints")))
    constraint_specs.extend(_iter_items(human_supplement.get("constraints")))

    for idx, spec in enumerate(constraint_specs, start=1):
        cid = str(spec.get("id") or spec.get("constraint_id") or f"CONTRACT_CONSTRAINT_{idx:03d}")
        try:
            expr = normalize_expr(spec.get("expr") if "expr" in spec else spec)
            _register_derived_variable(variables, spec, expr, errors)
            constraints.append(
                {
                    "id": cid,
                    "kind": str(spec.get("kind") or "contract"),
                    "expr": expr,
                    "source": str(spec.get("source") or "contracts/testcase.yaml"),
                    "tags": [str(tag) for tag in _as_list(spec.get("tags"))],
                }
            )
        except ConstraintIRError as exc:
            errors.append({"code": "UNSUPPORTED_EXPRESSION", "constraint_id": cid, "message": str(exc)})

    for var in list(variables.values()):
        if var["type"] == "enum" and not var.get("domain"):
            errors.append({"code": "ENUM_DOMAIN_REQUIRED", "variable_id": var["id"], "message": "Enum variables must declare an explicit domain"})
        if var.get("derived") and not var.get("definition"):
            errors.append({"code": "DERIVED_DEFINITION_REQUIRED", "variable_id": var["id"], "message": "Derived Field must be defined by an expression"})

    ir = {
        "version": 1,
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "variables": sorted(variables.values(), key=lambda item: item["id"]),
        "constraints": sorted(constraints, key=lambda item: item["id"]),
        "obligation_count": len(obligations),
        "compile_errors": errors,
    }
    return IRBuildResult(ir=ir, errors=errors)


def obligation_target_expr(obligation: dict[str, Any], variable_ids: set[str]) -> dict[str, Any] | None:
    constraints = _as_dict(obligation.get("constraints"))
    hints = _as_dict(obligation.get("realization_hints"))
    for key in ("expr", "constraint", "constraints"):
        if key in constraints:
            return normalize_expr(constraints[key])
    must_cover = constraints.get("must_cover")
    if isinstance(must_cover, list) and must_cover:
        first = must_cover[0]
        if isinstance(first, dict):
            return normalize_expr({"op": "and", "args": [{"op": "eq", "var": _var_id(k), "value": v} for k, v in sorted(first.items())]})
        if isinstance(first, str):
            raise ConstraintIRError(f"String expressions are not supported for obligation {obligation.get('id')}: {first}")
    target_refs = [str(ref) for ref in obligation.get("target_refs") or []]
    kind = str(obligation.get("kind") or "")
    if kind == "family" and target_refs:
        return {"op": "eq", "var": "VAR_FAMILY", "value": target_refs[0]}
    if kind == "kernel_path" and target_refs:
        return {"op": "eq", "var": "VAR_KERNEL_PATH", "value": target_refs[0]}
    if kind == "compile_template" and target_refs:
        return {"op": "eq", "var": "VAR_TEMPLATE", "value": target_refs[0]}
    if kind == "kernel_branch" and target_refs:
        return {"op": "eq", "var": _var_id(f"branch_{target_refs[0]}"), "value": True}
    if kind == "optional_input_mode" and target_refs:
        return {"op": "eq", "var": _var_id(f"optional_{target_refs[0]}"), "value": True}
    if kind == "dtype_layout_class" and target_refs:
        return {"op": "eq", "var": "VAR_DTYPE_LAYOUT_CLASS", "value": target_refs[0]}
    if kind == "numerical_mode" and target_refs:
        return {"op": "eq", "var": "VAR_NUMERICAL_MODE", "value": target_refs[0]}
    if kind.endswith("_boundary") and target_refs:
        var = {
            "tilingdata_boundary": "VAR_TILINGDATA_BUCKET",
            "core_split_boundary": "VAR_CORE_SPLIT_BUCKET",
            "tail_boundary": "VAR_TAIL_BUCKET",
            "workspace_boundary": "VAR_WORKSPACE_BUCKET",
            "pipeline_resource_mode": "VAR_PIPELINE_RESOURCE_MODE",
        }.get(kind)
        if var:
            return {"op": "eq", "var": var, "value": target_refs[0]}
    field = constraints.get("field") or constraints.get("field_name")
    values = constraints.get("values")
    if field and isinstance(values, list) and values:
        return {"op": "eq", "var": _var_id(str(field)), "value": values[0]}
    return None


def normalize_expr(expr: Any) -> dict[str, Any]:
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
            out["lhs"] = _normalize_value_or_expr(expr.get("lhs"))
            out["rhs"] = _normalize_value_or_expr(expr.get("rhs"))
        else:
            out["var"] = _require_var(expr)
            out["value"] = expr.get("value")
    elif op in {"in", "not_in"}:
        out["var"] = _require_var(expr)
        out["values"] = _as_list(expr.get("values") if "values" in expr else expr.get("value"))
    elif op in {"and", "or"}:
        out["args"] = [normalize_expr(arg) for arg in _require_args(expr)]
    elif op == "not":
        out["arg"] = normalize_expr(expr.get("arg") or expr.get("expr"))
    elif op in {"implies", "requires"}:
        out["antecedent"] = normalize_expr(expr.get("antecedent") or expr.get("if") or expr.get("requires"))
        out["consequent"] = normalize_expr(expr.get("consequent") or expr.get("then") or expr.get("required"))
    elif op == "mutex":
        out["args"] = [normalize_expr(arg) for arg in _require_args(expr)]
    elif op in {"add", "sub", "mul", "div", "mod"}:
        out["args"] = [_normalize_arith_arg(arg) for arg in _require_args(expr)]
    elif op == "aligned":
        out["var"] = _require_var(expr)
        out["alignment"] = int(expr.get("alignment") or expr.get("value") or 1)
    elif op == "derived":
        out["var"] = _require_var(expr)
        out["expr"] = normalize_expr(expr.get("expr") or expr.get("definition"))
    elif op == "if_then_else":
        out["condition"] = normalize_expr(expr.get("condition") or expr.get("if"))
        out["then"] = _normalize_value_or_expr(expr.get("then"))
        out["else"] = _normalize_value_or_expr(expr.get("else"))
    return out


def _add_variable(variables: dict[str, dict[str, Any]], spec: dict[str, Any], errors: list[dict[str, str]], source: str) -> None:
    var_id = str(spec.get("id") or spec.get("stable_id") or spec.get("var") or "")
    if not var_id:
        return
    var_type = str(spec.get("type") or spec.get("data_type") or spec.get("kind") or "enum").lower()
    if var_type in {"boolean"}:
        var_type = "bool"
    if var_type not in SUPPORTED_VAR_TYPES:
        errors.append({"code": "UNSUPPORTED_VARIABLE_TYPE", "variable_id": var_id, "message": f"Unsupported variable type: {var_type}"})
        return
    variables[var_id] = {
        "id": var_id,
        "name": str(spec.get("name") or spec.get("canonical_name") or var_id),
        "type": var_type,
        "domain": normalize_domain(var_type, spec),
        "stable_id": var_id,
        "free": not bool(spec.get("derived")),
        "derived": bool(spec.get("derived")),
        "definition": spec.get("definition") or spec.get("expr"),
        "source": source,
    }


def _variables_from_interface(variables: dict[str, dict[str, Any]], contract: dict[str, Any]) -> None:
    interface = _as_dict(contract.get("interface"))
    _ensure_enum(variables, "VAR_FAMILY", _collect_contract_targets(contract, "families") + _collect_contract_targets(contract, "family_obligations"))
    _ensure_enum(variables, "VAR_KERNEL_PATH", _collect_contract_targets(contract, "kernel_paths"))
    _ensure_enum(variables, "VAR_TEMPLATE", _collect_contract_targets(contract, "compile_templates") + _collect_contract_targets(contract, "template_bindings"))
    _ensure_enum(variables, "VAR_DTYPE_LAYOUT_CLASS", [str(item.get("id") or item.get("name") or item.get("class") or item.get("dtype")) for item in _iter_items(interface.get("dtype_layout_domains")) if item])
    _ensure_enum(variables, "VAR_NUMERICAL_MODE", _collect_contract_targets(contract, "numerical"))
    for item in _iter_items(interface.get("optional_inputs")):
        name = str(item.get("id") or item.get("name") or item.get("input") or "")
        if name:
            _ensure_bool(variables, _var_id(f"optional_{name}"))


def _variables_from_obligations(variables: dict[str, dict[str, Any]], obligations: list[dict[str, Any]]) -> None:
    family_domain = [ref for item in obligations if item.get("kind") == "family" for ref in item.get("target_refs") or []]
    path_domain = [ref for item in obligations if item.get("kind") == "kernel_path" for ref in item.get("target_refs") or []]
    template_domain = [ref for item in obligations if item.get("kind") == "compile_template" for ref in item.get("target_refs") or []]
    dtype_domain = [ref for item in obligations if item.get("kind") == "dtype_layout_class" for ref in item.get("target_refs") or []]
    numerical_domain = [ref for item in obligations if item.get("kind") == "numerical_mode" for ref in item.get("target_refs") or []]
    _ensure_enum(variables, "VAR_FAMILY", family_domain)
    _ensure_enum(variables, "VAR_KERNEL_PATH", path_domain)
    _ensure_enum(variables, "VAR_TEMPLATE", template_domain)
    _ensure_enum(variables, "VAR_DTYPE_LAYOUT_CLASS", dtype_domain)
    _ensure_enum(variables, "VAR_NUMERICAL_MODE", numerical_domain)
    for item in obligations:
        kind = str(item.get("kind") or "")
        refs = [str(ref) for ref in item.get("target_refs") or []]
        if kind == "kernel_branch":
            for ref in refs:
                _ensure_bool(variables, _var_id(f"branch_{ref}"))
        elif kind == "optional_input_mode":
            for ref in refs:
                _ensure_bool(variables, _var_id(f"optional_{ref}"))
        elif kind == "tiling_key_field":
            constraints = _as_dict(item.get("constraints"))
            field = str(constraints.get("field") or constraints.get("field_name") or (refs[0] if refs else ""))
            values = constraints.get("values")
            if field:
                if isinstance(values, list) and all(isinstance(v, int) and not isinstance(v, bool) for v in values):
                    _ensure_int(variables, _var_id(field), values)
                else:
                    _ensure_enum(variables, _var_id(field), [str(v) for v in _as_list(values)] or refs)
        elif kind in {"tilingdata_boundary", "core_split_boundary", "tail_boundary", "workspace_boundary", "pipeline_resource_mode"}:
            var = {
                "tilingdata_boundary": "VAR_TILINGDATA_BUCKET",
                "core_split_boundary": "VAR_CORE_SPLIT_BUCKET",
                "tail_boundary": "VAR_TAIL_BUCKET",
                "workspace_boundary": "VAR_WORKSPACE_BUCKET",
                "pipeline_resource_mode": "VAR_PIPELINE_RESOURCE_MODE",
            }[kind]
            _ensure_enum(variables, var, refs)


def _register_derived_variable(variables: dict[str, dict[str, Any]], spec: dict[str, Any], expr: dict[str, Any], errors: list[dict[str, str]]) -> None:
    if expr.get("op") != "derived":
        return
    var_id = str(expr.get("var"))
    existing = variables.get(var_id)
    if existing and existing.get("free"):
        errors.append({"code": "DERIVED_FIELD_FREE", "variable_id": var_id, "message": "Derived Field cannot be a free variable"})
    variables[var_id] = {
        "id": var_id,
        "name": str(spec.get("name") or var_id),
        "type": str(spec.get("var_type") or spec.get("type") or "int"),
        "domain": normalize_domain(str(spec.get("var_type") or spec.get("type") or "int"), spec),
        "stable_id": var_id,
        "free": False,
        "derived": True,
        "definition": expr["expr"],
        "source": "contracts/testcase.yaml.typed_constraints",
    }


def normalize_domain(var_type: str, spec: dict[str, Any]) -> Any:
    if var_type == "bool":
        return [False, True]
    if "domain" in spec:
        return spec["domain"]
    if "values" in spec:
        return spec["values"]
    if "enum_values" in spec:
        return spec["enum_values"]
    if var_type == "int":
        return {"min": int(spec.get("min", 0)), "max": int(spec.get("max", 1024))}
    return []


def _ensure_bool(variables: dict[str, dict[str, Any]], var_id: str) -> None:
    variables.setdefault(var_id, {"id": var_id, "name": var_id, "type": "bool", "domain": [False, True], "stable_id": var_id, "free": True, "derived": False, "definition": None, "source": "derived_from_plan"})


def _ensure_int(variables: dict[str, dict[str, Any]], var_id: str, values: list[int] | None = None) -> None:
    domain = sorted(dict.fromkeys(values or [0, 1]))
    variables.setdefault(var_id, {"id": var_id, "name": var_id, "type": "int", "domain": {"min": min(domain), "max": max(domain)}, "stable_id": var_id, "free": True, "derived": False, "definition": None, "source": "derived_from_plan"})


def _ensure_enum(variables: dict[str, dict[str, Any]], var_id: str, domain: list[str]) -> None:
    clean = sorted(dict.fromkeys(str(item) for item in domain if str(item)))
    if not clean:
        return
    if var_id in variables:
        if variables[var_id]["type"] == "enum":
            variables[var_id]["domain"] = sorted(dict.fromkeys([*variables[var_id].get("domain", []), *clean]))
        return
    variables[var_id] = {"id": var_id, "name": var_id, "type": "enum", "domain": clean, "stable_id": var_id, "free": True, "derived": False, "definition": None, "source": "derived_from_plan"}


def _collect_contract_targets(contract: dict[str, Any], bucket: str) -> list[str]:
    items = _iter_items(_as_dict(contract.get("coverage_obligations")).get(bucket))
    out: list[str] = []
    for item in items:
        out.extend(str(ref) for ref in _as_list(item.get("target_refs") or item.get("target_ref") or item.get("family_id") or item.get("id")) if str(ref))
    return out


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


def _normalize_arith_arg(arg: Any) -> Any:
    if isinstance(arg, dict):
        return normalize_expr(arg) if "op" in arg else {"var": _require_var(arg)}
    return arg


def _normalize_value_or_expr(value: Any) -> Any:
    if isinstance(value, dict) and "op" in value:
        return normalize_expr(value)
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
