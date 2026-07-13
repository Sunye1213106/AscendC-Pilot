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


@dataclass(frozen=True)
class TargetCompileResult:
    status: str
    expr: dict[str, Any] | None
    code: str = ""
    reason: str = ""


def build_constraint_ir(snapshot: dict[str, Any], obligations_doc: dict[str, Any], human_supplement: dict[str, Any] | None = None) -> IRBuildResult:
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    contract = _as_dict(files.get("contracts/testcase.yaml"))
    obligations = [item for item in obligations_doc.get("obligations", []) if isinstance(item, dict)]
    human_supplement = human_supplement if isinstance(human_supplement, dict) else {}
    errors: list[dict[str, str]] = []
    variables: dict[str, dict[str, Any]] = {}
    constraints: list[dict[str, Any]] = []

    context_slice = _as_dict(snapshot.get("context_slice") or files.get("context_slice") or files.get("__context_slice__"))
    _variables_from_context_slice(variables, context_slice)
    for spec in _iter_items(contract.get("variables")) + _iter_items(_as_dict(contract.get("constraint_ir")).get("variables")):
        _add_variable(variables, spec, errors, "contracts/testcase.yaml.variables")
    _variables_from_interface(variables, contract)
    _variables_from_obligations(variables, obligations, errors)
    _validate_variable_domains(variables, errors)

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

    for constraint in constraints:
        for var_id in sorted(collect_expr_variables(constraint["expr"])):
            if var_id not in variables:
                errors.append(
                    {
                        "code": "UNKNOWN_VARIABLE_REFERENCE",
                        "variable_id": var_id,
                        "constraint_id": str(constraint["id"]),
                        "message": f"Constraint references undeclared variable: {var_id}",
                    }
                )

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


def compile_obligation_target(obligation: dict[str, Any], ir: dict[str, Any] | set[str]) -> TargetCompileResult:
    variable_ids = set(ir) if isinstance(ir, set) else {str(item.get("id")) for item in ir.get("variables", []) if isinstance(item, dict)}
    priority = str(obligation.get("priority") or "normal").lower()
    try:
        expr = obligation_target_expr(obligation, variable_ids)
    except ConstraintIRError as exc:
        code = "RELATION_NOT_ATOMIC" if str(exc).startswith("RELATION_NOT_ATOMIC") else "OBLIGATION_TARGET_NOT_COMPILED"
        return _target_failure(obligation, priority, str(exc), code=code)
    if expr is None:
        return _target_failure(obligation, priority, "Obligation has no compilable target expression")
    unknown = sorted(var_id for var_id in collect_expr_variables(expr) if var_id not in variable_ids)
    if unknown:
        return _target_failure(obligation, priority, f"Target references undeclared variable(s): {', '.join(unknown)}")
    if isinstance(ir, dict):
        outside = _target_outside_declared_domain(expr, ir)
        if outside:
            variable_id, value, domain = outside
            return _target_failure(
                obligation,
                priority,
                f"{variable_id} target {value!r} is outside declared domain {domain!r}",
                code="OBLIGATION_OUTSIDE_DECLARED_DOMAIN",
            )
    return TargetCompileResult(status="ok", expr=expr)


def _target_outside_declared_domain(expr: dict[str, Any], ir: dict[str, Any]) -> tuple[str, Any, Any] | None:
    variables = {str(item.get("id")): item for item in ir.get("variables", []) if isinstance(item, dict)}

    def visit(node: Any) -> tuple[str, Any, Any] | None:
        if not isinstance(node, dict):
            return None
        if node.get("op") == "eq" and "var" in node:
            variable = variables.get(str(node["var"]))
            if variable and variable.get("domain_authority") == "explicit":
                domain = variable.get("domain")
                value = node.get("value")
                if variable.get("type") == "enum" and value not in domain:
                    return str(node["var"]), value, domain
                if variable.get("type") == "int" and isinstance(domain, dict):
                    if (domain.get("min") is not None and value < domain["min"]) or (domain.get("max") is not None and value > domain["max"]):
                        return str(node["var"]), value, domain
        for child in node.values():
            if isinstance(child, list):
                for item in child:
                    result = visit(item)
                    if result:
                        return result
            else:
                result = visit(child)
                if result:
                    return result
        return None

    return visit(expr)


def obligation_target_expr(obligation: dict[str, Any], variable_ids: set[str]) -> dict[str, Any] | None:
    constraints = _as_dict(obligation.get("constraints"))
    hints = _as_dict(obligation.get("realization_hints"))
    if isinstance(obligation.get("target_expr"), dict):
        return normalize_expr(obligation["target_expr"])
    for key in ("expr", "constraint", "constraints"):
        if key in constraints:
            return normalize_expr(constraints[key])
    must_cover = constraints.get("must_cover")
    if isinstance(must_cover, list) and must_cover:
        if len(must_cover) != 1:
            raise ConstraintIRError("RELATION_NOT_ATOMIC: must_cover must be atomized by planner before target compilation")
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
        return {"op": "eq", "var": _branch_var_id(target_refs[0]), "value": obligation.get("target_value", True)}
    if kind == "optional_input_mode" and target_refs:
        return {"op": "eq", "var": _optional_var_id(target_refs[0]), "value": obligation.get("target_value", True)}
    if kind == "dtype_layout_class" and target_refs:
        return {"op": "eq", "var": "VAR_DTYPE_LAYOUT_CLASS", "value": target_refs[0]}
    if kind == "numerical_mode" and target_refs:
        return {"op": "eq", "var": "VAR_NUMERICAL_MODE", "value": target_refs[0]}
    if kind.endswith("_boundary") or kind == "pipeline_resource_mode":
        var = {
            "tilingdata_boundary": "VAR_TILINGDATA_BUCKET",
            "core_split_boundary": "VAR_CORE_SPLIT_BUCKET",
            "tail_boundary": "VAR_TAIL_BUCKET",
            "workspace_boundary": "VAR_WORKSPACE_BUCKET",
            "pipeline_resource_mode": "VAR_PIPELINE_RESOURCE_MODE",
        }.get(kind)
        if var and target_refs:
            return {"op": "eq", "var": var, "value": target_refs[0]}
    if kind == "tiling_key_relation":
        return compile_relation_expr(constraints)
    field = constraints.get("field") or constraints.get("field_name")
    values = constraints.get("values")
    if field and isinstance(values, list) and values:
        return {"op": "eq", "var": _var_id(f"KEY_{field}"), "value": values[0]}
    return None


def compile_relation_expr(constraints: dict[str, Any]) -> dict[str, Any] | None:
    relation_type = str(constraints.get("relation_type") or "").lower()
    if not relation_type:
        return None
    if relation_type == "mutex":
        fields = [str(item) for item in _as_list(constraints.get("fields")) if str(item)]
        if len(fields) < 2:
            raise ConstraintIRError("mutex relation requires at least two fields")
        return {"op": "not", "arg": {"op": "and", "args": [{"op": "eq", "var": _relation_var_id(field), "value": True} for field in fields]}}
    if relation_type in {"implies", "requires"}:
        source = constraints.get("source")
        target = constraints.get("target")
        if not source or not target:
            fields = [str(item) for item in _as_list(constraints.get("fields")) if str(item)]
            if len(fields) >= 2:
                source, target = fields[0], fields[1]
        if not source or not target:
            raise ConstraintIRError(f"{relation_type} relation requires source and target")
        return {
            "op": "and",
            "args": [
                {"op": "eq", "var": _relation_var_id(str(source)), "value": True},
                {"op": "eq", "var": _relation_var_id(str(target)), "value": True},
            ],
        }
    if relation_type == "compatible_set":
        combinations = constraints.get("combinations") or constraints.get("must_cover")
        if isinstance(combinations, list) and len(combinations) == 1:
            args = []
            for combo in combinations:
                if isinstance(combo, dict):
                    args.append({"op": "and", "args": [{"op": "eq", "var": _relation_var_id(str(key)), "value": value} for key, value in sorted(combo.items())]})
            if args:
                return args[0]
        if isinstance(combinations, list) and len(combinations) > 1:
            raise ConstraintIRError("RELATION_NOT_ATOMIC: compatible_set must be atomized by planner before target compilation")
        raise ConstraintIRError("compatible_set relation requires concrete combinations")
    if relation_type in {"pairwise", "must_cover"}:
        raise ConstraintIRError(f"{relation_type} relation does not provide a deterministic target expression")
    raise ConstraintIRError(f"Unsupported relation_type: {relation_type}")


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
    try:
        derived = parse_bool_literal(spec.get("derived", False))
    except ConstraintIRError as exc:
        errors.append({"code": "INVALID_BOOL_LITERAL", "variable_id": var_id, "message": str(exc)})
        return
    domain = normalize_domain(var_type, spec)
    variables[var_id] = {
        "id": var_id,
        "name": str(spec.get("name") or spec.get("canonical_name") or var_id),
        "type": var_type,
        "domain": domain,
        "domain_authority": "intrinsic" if var_type == "bool" else "explicit",
        "domain_sources": [source],
        "stable_id": var_id,
        "free": not derived,
        "derived": derived,
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
            _ensure_bool(variables, _optional_var_id(name))


def _variables_from_context_slice(variables: dict[str, dict[str, Any]], context_slice: dict[str, Any]) -> None:
    for entity in _iter_items(context_slice.get("entities")):
        entity_id = str(entity.get("id") or entity.get("stable_id") or "")
        if not entity_id:
            continue
        var_id = _entity_var_id(entity_id)
        if not var_id:
            continue
        data_type = str(entity.get("data_type") or entity.get("type") or entity.get("value_type") or "").lower()
        domain = entity.get("domain") or entity.get("values") or entity.get("enum_values")
        if entity_id.startswith(("KBR_", "KDEC_")) or data_type in {"bool", "boolean"}:
            _ensure_bool(variables, var_id)
        elif data_type in {"int", "integer"} or _list_is_ints(domain):
            values = [int(value) for value in domain] if isinstance(domain, list) and domain else None
            min_value = entity.get("min")
            max_value = entity.get("max")
            _ensure_int(variables, var_id, values, min_value=min_value, max_value=max_value, source="context_entity")
        elif isinstance(domain, list) and domain:
            _ensure_enum(variables, var_id, [str(item) for item in domain], source="context_entity")
        elif entity_id.startswith(("KEY_", "TDF_", "KVAR_")):
            _ensure_int(variables, var_id, source="context_entity_type_only")
        elif entity_id.startswith(("KPATH_", "KTPL_", "FAM_", "NUM_")):
            bucket_var = {
                "KPATH_": "VAR_KERNEL_PATH",
                "KTPL_": "VAR_TEMPLATE",
                "FAM_": "VAR_FAMILY",
                "NUM_": "VAR_NUMERICAL_MODE",
            }[next(prefix for prefix in ("KPATH_", "KTPL_", "FAM_", "NUM_") if entity_id.startswith(prefix))]
            _ensure_enum(variables, bucket_var, [entity_id])


def _variables_from_obligations(variables: dict[str, dict[str, Any]], obligations: list[dict[str, Any]], errors: list[dict[str, str]]) -> None:
    family_domain = [ref for item in obligations if item.get("kind") == "family" for ref in item.get("target_refs") or []]
    path_domain = [ref for item in obligations if item.get("kind") == "kernel_path" for ref in item.get("target_refs") or []]
    template_domain = [ref for item in obligations if item.get("kind") == "compile_template" for ref in item.get("target_refs") or []]
    dtype_domain = [ref for item in obligations if item.get("kind") == "dtype_layout_class" for ref in item.get("target_refs") or []]
    numerical_domain = [ref for item in obligations if item.get("kind") == "numerical_mode" for ref in item.get("target_refs") or []]
    _ensure_enum(variables, "VAR_FAMILY", family_domain, source="obligation_target", errors=errors)
    _ensure_enum(variables, "VAR_KERNEL_PATH", path_domain, source="obligation_target", errors=errors)
    _ensure_enum(variables, "VAR_TEMPLATE", template_domain, source="obligation_target", errors=errors)
    _ensure_enum(variables, "VAR_DTYPE_LAYOUT_CLASS", dtype_domain, source="obligation_target", errors=errors)
    _ensure_enum(variables, "VAR_NUMERICAL_MODE", numerical_domain, source="obligation_target", errors=errors)
    for item in obligations:
        kind = str(item.get("kind") or "")
        refs = [str(ref) for ref in item.get("target_refs") or []]
        if kind == "kernel_branch":
            for ref in refs:
                _ensure_bool(variables, _branch_var_id(ref))
        elif kind == "optional_input_mode":
            for ref in refs:
                _ensure_bool(variables, _optional_var_id(ref))
        elif kind in {"tiling_key_field", "tiling_key_field_value"}:
            constraints = _as_dict(item.get("constraints"))
            field = str(constraints.get("field") or constraints.get("field_name") or (refs[0] if refs else ""))
            values = constraints.get("values")
            target_value = item.get("target_value")
            if field:
                var_id = _key_var_id(refs[0] if refs else field, field)
                if isinstance(values, list) and all(isinstance(v, int) and not isinstance(v, bool) for v in values):
                    _ensure_int(variables, var_id, values, source="obligation_values", errors=errors)
                elif isinstance(target_value, int) and not isinstance(target_value, bool):
                    _ensure_int(variables, var_id, [target_value], source="obligation_target_value", errors=errors)
                else:
                    enum_values = [str(v) for v in _as_list(values)] or ([str(target_value)] if target_value not in (None, "") else refs)
                    _ensure_enum(variables, var_id, enum_values, source="obligation_target", errors=errors)
        elif kind in {"tilingdata_boundary", "core_split_boundary", "tail_boundary", "workspace_boundary", "pipeline_resource_mode"}:
            var = {
                "tilingdata_boundary": "VAR_TILINGDATA_BUCKET",
                "core_split_boundary": "VAR_CORE_SPLIT_BUCKET",
                "tail_boundary": "VAR_TAIL_BUCKET",
                "workspace_boundary": "VAR_WORKSPACE_BUCKET",
                "pipeline_resource_mode": "VAR_PIPELINE_RESOURCE_MODE",
            }[kind]
            _ensure_enum(variables, var, refs, source="obligation_target", errors=errors)


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
        domain = spec["domain"]
        if var_type == "int" and isinstance(domain, dict):
            return {"min": domain.get("min"), "max": domain.get("max"), "explicit": True, "sources": ["contract_variables"]}
        return domain
    if "values" in spec:
        values = spec["values"]
        if var_type == "int" and isinstance(values, list) and values:
            return {"min": min(values), "max": max(values), "explicit": True, "sources": ["contract_variables"]}
        return values
    if "enum_values" in spec:
        return spec["enum_values"]
    if var_type == "int":
        if "min" in spec or "max" in spec:
            return {"min": spec.get("min"), "max": spec.get("max"), "explicit": True, "sources": ["contract_variables"]}
        return {"min": None, "max": None, "explicit": False, "sources": ["contract_type_only"]}
    return []


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


def _target_failure(obligation: dict[str, Any], priority: str, reason: str, *, code: str = "OBLIGATION_TARGET_NOT_COMPILED") -> TargetCompileResult:
    if priority in {"hard", "high"}:
        return TargetCompileResult(status="error", expr=None, code=code, reason=reason)
    return TargetCompileResult(status="skipped", expr=None, code=code, reason=reason)


def _ensure_bool(variables: dict[str, dict[str, Any]], var_id: str) -> None:
    variables.setdefault(var_id, {"id": var_id, "name": var_id, "type": "bool", "domain": [False, True], "domain_authority": "intrinsic", "domain_sources": ["bool"], "stable_id": var_id, "free": True, "derived": False, "definition": None, "source": "derived_from_plan"})


def _ensure_int(
    variables: dict[str, dict[str, Any]],
    var_id: str,
    values: list[int] | None = None,
    *,
    min_value: Any = None,
    max_value: Any = None,
    source: str = "derived_from_plan",
    errors: list[dict[str, str]] | None = None,
) -> None:
    authority = _domain_authority(source)
    domain = _int_domain(values, min_value=min_value, max_value=max_value, source=source, authority=authority)
    if var_id not in variables:
        variables[var_id] = {"id": var_id, "name": var_id, "type": "int", "domain": domain, "domain_authority": authority, "domain_sources": [source], "stable_id": var_id, "free": True, "derived": False, "definition": None, "source": source}
        return
    existing = variables[var_id]
    if existing.get("type") != "int" or existing.get("derived"):
        return
    merged, merge_errors = _merge_int_domain(existing.get("domain"), domain, existing.get("domain_authority", "inferred"), authority)
    existing["domain"] = merged
    existing["domain_authority"] = merged.get("authority", existing.get("domain_authority", "inferred"))
    existing["domain_sources"] = merged.get("sources", [])
    if errors is not None:
        errors.extend({**error, "variable_id": var_id} for error in merge_errors)
    existing["source"] = ",".join(sorted(set(str(existing.get("source") or "").split(",")) | {source}))


def _ensure_enum(variables: dict[str, dict[str, Any]], var_id: str, domain: list[str], *, source: str = "derived_from_plan", errors: list[dict[str, str]] | None = None) -> None:
    clean = sorted(dict.fromkeys(str(item) for item in domain if str(item)))
    if not clean:
        return
    if var_id in variables:
        if variables[var_id]["type"] == "enum":
            existing = [str(value) for value in variables[var_id].get("domain", [])]
            existing_authority = variables[var_id].get("domain_authority", "inferred")
            incoming_authority = _domain_authority(source)
            if existing_authority == "explicit" and incoming_authority != "explicit":
                outside = sorted(set(clean) - set(existing))
                if outside and errors is not None:
                    errors.extend({"code": "OBLIGATION_OUTSIDE_DECLARED_DOMAIN", "variable_id": var_id, "requested_value": value, "declared_domain": str(existing)} for value in outside)
            elif existing_authority == "explicit" and incoming_authority == "explicit":
                common = sorted(set(existing) & set(clean))
                if not common and errors is not None:
                    errors.append({"code": "DOMAIN_CONFLICT", "variable_id": var_id, "message": "Explicit enum domains do not intersect"})
                elif common:
                    variables[var_id]["domain"] = common
            else:
                variables[var_id]["domain"] = sorted(dict.fromkeys([*existing, *clean]))
            variables[var_id]["domain_sources"] = sorted(set(variables[var_id].get("domain_sources", [])) | {source})
        return
    variables[var_id] = {"id": var_id, "name": var_id, "type": "enum", "domain": clean, "domain_authority": _domain_authority(source), "domain_sources": [source], "stable_id": var_id, "free": True, "derived": False, "definition": None, "source": source}


def _int_domain(values: list[int] | None = None, *, min_value: Any = None, max_value: Any = None, source: str, authority: str) -> dict[str, Any]:
    clean = sorted(dict.fromkeys(int(value) for value in values or []))
    if clean:
        return {"min": min(clean), "max": max(clean), "explicit": authority == "explicit", "authority": authority, "sources": [source]}
    if min_value is not None or max_value is not None:
        return {
            "min": int(min_value) if min_value is not None else None,
            "max": int(max_value) if max_value is not None else None,
            "explicit": authority == "explicit",
            "authority": authority,
            "sources": [source],
        }
    return {"min": None, "max": None, "explicit": False, "authority": authority, "sources": [source]}


def _merge_int_domain(left: Any, right: Any, left_authority: str, right_authority: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    left = left if isinstance(left, dict) else {"min": None, "max": None, "sources": []}
    right = right if isinstance(right, dict) else {"min": None, "max": None, "sources": []}
    errors: list[dict[str, str]] = []
    for domain in (left, right):
        if domain.get("min") is not None and domain.get("max") is not None and int(domain["min"]) > int(domain["max"]):
            errors.append({"code": "INVALID_INT_DOMAIN", "message": "min is greater than max"})
    def outside(value: Any, domain: dict[str, Any]) -> bool:
        return (domain.get("min") is not None and value < int(domain["min"])) or (domain.get("max") is not None and value > int(domain["max"]))
    if left_authority == "explicit" and right_authority != "explicit":
        requested = [value for value in (right.get("min"), right.get("max")) if value is not None]
        for value in requested:
            if outside(int(value), left):
                errors.append({"code": "OBLIGATION_OUTSIDE_DECLARED_DOMAIN", "requested_value": str(value), "declared_domain": f"{left.get('min')}..{left.get('max')}"})
        result = dict(left)
        result.update({"authority": "explicit", "explicit": True, "sources": sorted(set(_as_list(left.get("sources")) + _as_list(right.get("sources"))))})
        return result, errors
    if left_authority == "explicit" and right_authority == "explicit":
        mins = [value for value in (left.get("min"), right.get("min")) if value is not None]
        maxs = [value for value in (left.get("max"), right.get("max")) if value is not None]
        result = {"min": max(mins) if mins else None, "max": min(maxs) if maxs else None, "authority": "explicit", "explicit": True, "sources": sorted(set(_as_list(left.get("sources")) + _as_list(right.get("sources"))))}
        if result["min"] is not None and result["max"] is not None and result["min"] > result["max"]:
            errors.append({"code": "DOMAIN_CONFLICT", "message": "Explicit integer domains do not intersect"})
        return result, errors
    mins = [value for value in (left.get("min"), right.get("min")) if value is not None]
    maxs = [value for value in (left.get("max"), right.get("max")) if value is not None]
    return {"min": min(mins) if mins else None, "max": max(maxs) if maxs else None, "authority": "inferred", "explicit": False, "sources": sorted(set(_as_list(left.get("sources")) + _as_list(right.get("sources"))))}, errors


def _domain_authority(source: str) -> str:
    if source in {"contracts/testcase.yaml.variables", "context_entity"}:
        return "explicit"
    if source == "bool":
        return "intrinsic"
    return "inferred"


def _validate_variable_domains(variables: dict[str, dict[str, Any]], errors: list[dict[str, str]]) -> None:
    for var_id, variable in variables.items():
        domain = variable.get("domain")
        if variable.get("type") != "int" or not isinstance(domain, dict):
            continue
        lower, upper = domain.get("min"), domain.get("max")
        if lower is not None and upper is not None and int(lower) > int(upper):
            errors.append({"code": "INVALID_INT_DOMAIN", "variable_id": var_id, "message": "min is greater than max"})


def _key_var_id(target_ref: str, field: str) -> str:
    if target_ref.startswith("KEY_"):
        return _var_id(target_ref)
    return _var_id(f"KEY_{field}")


def _branch_var_id(target_ref: str) -> str:
    if target_ref.startswith(("KBR_", "KDEC_")):
        return _var_id(target_ref)
    if target_ref.startswith("VAR_BRANCH_"):
        return target_ref
    return _var_id(f"BRANCH_{target_ref}")


def _optional_var_id(ref: str) -> str:
    if ref.startswith("VAR_OPTIONAL_"):
        return ref
    return _var_id(f"OPTIONAL_{ref}")


def _relation_var_id(ref: str) -> str:
    if ref.startswith("VAR_"):
        return ref
    if ref.startswith(("KEY_", "TDF_", "KVAR_", "KBR_", "KDEC_")):
        return _var_id(ref)
    return _var_id(ref)


def _entity_var_id(entity_id: str) -> str:
    if entity_id.startswith("VAR_"):
        return entity_id
    if entity_id.startswith(("KEY_", "TDF_", "KVAR_", "KBR_", "KDEC_", "PIPE_")):
        return _var_id(entity_id)
    return ""


def _list_is_ints(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, int) and not isinstance(item, bool) for item in value)


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
