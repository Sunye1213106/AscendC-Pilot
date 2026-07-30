# -*- coding: utf-8 -*-
"""TG-side constraint IR: obligations, contracts, snapshots and realization map.

The pure expression/domain core lives in `acp_common.constraint_ir` and is
re-exported here so existing importers keep their current import paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from acp_common.constraint_ir import (
    ConstraintIRError,
    SUPPORTED_EXPR_OPS,
    SUPPORTED_VAR_TYPES,
    _as_dict,
    _as_list,
    _error,
    _int_domain,
    _iter_items,
    _merge_int_domain,
    _normalize_int_domain,
    _validate_variable_domains,
    _var_id,
    collect_expr_variables,
    compile_pattern_to_expr,
    has_explicit_domain,
    normalize_domain,
    normalize_expr,
    parse_bool_literal,
)

__all__ = [
    "ConstraintIRError",
    "SUPPORTED_EXPR_OPS",
    "SUPPORTED_VAR_TYPES",
    "_as_dict",
    "_as_list",
    "_error",
    "_int_domain",
    "_iter_items",
    "_merge_int_domain",
    "_normalize_int_domain",
    "_validate_variable_domains",
    "_var_id",
    "collect_expr_variables",
    "compile_pattern_to_expr",
    "has_explicit_domain",
    "normalize_domain",
    "normalize_expr",
    "parse_bool_literal",
    "IRBuildResult",
    "TargetCompileResult",
    "_add_variable",
    "_apply_realization_map",
    "_branch_var_id",
    "_collect_contract_targets",
    "_domain_authority",
    "_ensure_bool",
    "_ensure_enum",
    "_ensure_int",
    "_entity_var_id",
    "_force_derived_variable",
    "_key_var_id",
    "_list_is_ints",
    "_optional_var_id",
    "_realization_ir_metadata",
    "_register_derived_variable",
    "_relation_var_id",
    "_target_failure",
    "_target_outside_declared_domain",
    "_variables_from_context_slice",
    "_variables_from_interface",
    "_variables_from_obligations",
    "build_constraint_ir",
    "compile_obligation_target",
    "compile_relation_expr",
    "obligation_target_expr",
]

@dataclass(frozen=True)
class IRBuildResult:
    ir: dict[str, Any]
    errors: list[dict[str, Any]]
    global_errors: list[dict[str, Any]]
    obligation_errors: dict[str, list[dict[str, Any]]]

@dataclass(frozen=True)
class TargetCompileResult:
    status: str
    expr: dict[str, Any] | None
    code: str = ""
    reason: str = ""

def build_constraint_ir(
    snapshot: dict[str, Any],
    obligations_doc: dict[str, Any],
    human_supplement: dict[str, Any] | None = None,
    realization_map: dict[str, Any] | None = None,
) -> IRBuildResult:
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    contract = _as_dict(files.get("contracts/testcase.yaml"))
    obligations = [item for item in obligations_doc.get("obligations", []) if isinstance(item, dict)]
    human_supplement = human_supplement if isinstance(human_supplement, dict) else {}
    global_errors: list[dict[str, Any]] = []
    obligation_errors: dict[str, list[dict[str, Any]]] = {}
    variables: dict[str, dict[str, Any]] = {}
    constraints: list[dict[str, Any]] = []

    context_slice = _as_dict(snapshot.get("context_slice") or files.get("context_slice") or files.get("__context_slice__"))
    _variables_from_context_slice(variables, context_slice, global_errors)
    for spec in _iter_items(contract.get("variables")) + _iter_items(_as_dict(contract.get("constraint_ir")).get("variables")):
        _add_variable(variables, spec, global_errors, "contracts/testcase.yaml.variables")
    _variables_from_interface(variables, contract, global_errors)
    _variables_from_obligations(variables, obligations, obligation_errors)
    _apply_realization_map(variables, constraints, realization_map, global_errors)
    _validate_variable_domains(variables, global_errors)

    constraint_specs = []
    constraint_specs.extend(_iter_items(contract.get("typed_constraints")))
    constraint_specs.extend(_iter_items(_as_dict(contract.get("constraint_ir")).get("constraints")))
    constraint_specs.extend(_iter_items(human_supplement.get("constraints")))

    seen_constraint_ids: set[str] = set()
    for idx, spec in enumerate(constraint_specs, start=1):
        cid = str(spec.get("id") or spec.get("constraint_id") or f"CONTRACT_CONSTRAINT_{idx:03d}")
        if cid in seen_constraint_ids:
            continue
        seen_constraint_ids.add(cid)
        try:
            expr = normalize_expr(spec.get("expr") if "expr" in spec else spec)
            _register_derived_variable(variables, spec, expr, global_errors)
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
            global_errors.append(_error("UNSUPPORTED_EXPRESSION", scope="global", constraint_id=cid, message=str(exc)))

    for constraint in constraints:
        for var_id in sorted(collect_expr_variables(constraint["expr"])):
            if var_id not in variables:
                global_errors.append(
                    _error(
                        "UNKNOWN_VARIABLE_REFERENCE",
                        scope="global",
                        variable_id=var_id,
                        constraint_id=str(constraint["id"]),
                        message=f"Constraint references undeclared variable: {var_id}",
                    )
                )

    for var in list(variables.values()):
        if var["type"] == "enum" and not var.get("domain"):
            global_errors.append(_error("ENUM_DOMAIN_REQUIRED", scope="global", variable_id=var["id"], message="Enum variables must declare an explicit domain"))
        if var.get("derived") and not var.get("definition"):
            global_errors.append(_error("DERIVED_DEFINITION_REQUIRED", scope="global", variable_id=var["id"], message="Derived Field must be defined by an expression"))

    all_errors = global_errors + [error for errors in obligation_errors.values() for error in errors]
    ir = {
        "version": 1,
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "variables": sorted(variables.values(), key=lambda item: item["id"]),
        "constraints": sorted(constraints, key=lambda item: item["id"]),
        "obligation_count": len(obligations),
        "compile_errors": {"global": global_errors, "by_obligation": obligation_errors},
        "realization": _realization_ir_metadata(realization_map),
    }
    return IRBuildResult(ir=ir, errors=all_errors, global_errors=global_errors, obligation_errors=obligation_errors)

def compile_obligation_target(obligation: dict[str, Any], ir: dict[str, Any] | set[str]) -> TargetCompileResult:
    variable_ids = set(ir) if isinstance(ir, set) else {str(item.get("id")) for item in ir.get("variables", []) if isinstance(item, dict)}
    priority = str(obligation.get("priority") or "normal").lower()
    if isinstance(ir, dict) and str(obligation.get("kind") or "") == "kernel_branch":
        refs = [str(ref) for ref in obligation.get("target_refs") or []]
        if refs:
            branch_var = _branch_var_id(refs[0])
            abstract = set(_as_list(_as_dict(ir.get("realization")).get("abstract_branch_vars")))
            if branch_var in abstract:
                return TargetCompileResult(
                    status="skipped",
                    expr=None,
                    code="ABSTRACT_BRANCH_NOT_REALIZABLE",
                    reason=f"{refs[0]} is not mapped to CSV-realizable SMT variables",
                )
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
                if variable.get("type") == "int":
                    domain = _normalize_int_domain(domain, variable.get("domain_authority", "inferred"))
                    if domain.get("kind") == "discrete" and int(value) not in [int(item) for item in domain.get("values", [])]:
                        return str(node["var"]), value, domain
                    if domain.get("kind") == "range" and ((domain.get("min") is not None and value < domain["min"]) or (domain.get("max") is not None and value > domain["max"])):
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
    if kind == "runtime_variable_state" and target_refs:
        return {"op": "eq", "var": _var_id(target_refs[0]), "value": obligation.get("target_value")}
    if kind == "csv_domain_cover" and target_refs:
        return {"op": "eq", "var": _var_id(target_refs[0]), "value": obligation.get("target_value")}
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
        expr = compile_pattern_to_expr(constraints.get("pattern") or constraints.get("key_pattern") or constraints.get("matches"))
        return expr or compile_relation_expr(constraints)
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
        mode = str(constraints.get("compile_mode") or constraints.get("mode") or "witness").lower()
        antecedent = {"op": "eq", "var": _relation_var_id(str(source)), "value": True}
        consequent = {"op": "eq", "var": _relation_var_id(str(target)), "value": True}
        if mode == "legal":
            # True implication for GlobalLegal constraints.
            return {"op": "implies", "antecedent": antecedent, "consequent": consequent}
        # Coverage witness: force antecedent∧consequent so the edge is exercised.
        return {"op": "and", "args": [antecedent, consequent]}
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

def _add_variable(variables: dict[str, dict[str, Any]], spec: dict[str, Any], errors: list[dict[str, Any]], source: str) -> None:
    var_id = str(spec.get("id") or spec.get("stable_id") or spec.get("var") or "")
    if not var_id:
        return
    var_type = str(spec.get("type") or spec.get("data_type") or spec.get("kind") or "enum").lower()
    if var_type in {"boolean"}:
        var_type = "bool"
    if var_type not in SUPPORTED_VAR_TYPES:
        errors.append(_error("UNSUPPORTED_VARIABLE_TYPE", scope="global", variable_id=var_id, source=source, message=f"Unsupported variable type: {var_type}"))
        return
    try:
        derived = parse_bool_literal(spec.get("derived", False))
    except ConstraintIRError as exc:
        errors.append(_error("INVALID_BOOL_LITERAL", scope="global", variable_id=var_id, source=source, message=str(exc)))
        return
    if var_type == "bool":
        _ensure_bool(variables, var_id, source=source, errors=errors)
    elif var_type == "int":
        values = spec.get("values")
        domain = spec.get("domain")
        if isinstance(domain, dict):
            if "values" in domain:
                domain_values = domain.get("values")
                _ensure_int(variables, var_id, [int(item) for item in _as_list(domain_values)], source=source, errors=errors)
            else:
                _ensure_int(variables, var_id, min_value=domain.get("min"), max_value=domain.get("max"), source=source, errors=errors)
        elif isinstance(domain, list) and domain and all(isinstance(item, int) and not isinstance(item, bool) for item in domain):
            _ensure_int(variables, var_id, [int(item) for item in domain], source=source, errors=errors)
        elif isinstance(values, list) and values and all(isinstance(item, int) and not isinstance(item, bool) for item in values):
            _ensure_int(variables, var_id, [int(item) for item in values], source=source, errors=errors)
        else:
            _ensure_int(variables, var_id, min_value=spec.get("min"), max_value=spec.get("max"), source=source if has_explicit_domain(spec, var_type) else f"{source}.type_only", errors=errors)
    else:
        domain_values = spec.get("domain") or spec.get("values") or spec.get("enum_values") or []
        if isinstance(domain_values, list) and domain_values:
            _ensure_enum(variables, var_id, [str(item) for item in domain_values], source=source, errors=errors)
        elif var_id not in variables:
            variables[var_id] = {"id": var_id, "name": str(spec.get("name") or spec.get("canonical_name") or var_id), "type": "enum", "domain": [], "domain_authority": "inferred", "domain_sources": [f"{source}.type_only"], "stable_id": var_id, "free": True, "derived": False, "definition": None, "source": f"{source}.type_only"}
    if var_id in variables:
        variables[var_id]["name"] = str(spec.get("name") or spec.get("canonical_name") or variables[var_id].get("name") or var_id)
        free = not derived
        if source == "realization_map.csv_variables" or str(var_id).startswith("VAR_CSV_"):
            free = True
            derived = False
        if source == "realization_map.free_variables":
            free = True
            derived = False
        if spec.get("free") is True:
            free = True
            derived = False
        variables[var_id]["free"] = free
        variables[var_id]["derived"] = derived
        variables[var_id]["definition"] = spec.get("definition") or spec.get("expr")

def _variables_from_interface(variables: dict[str, dict[str, Any]], contract: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    interface = _as_dict(contract.get("interface"))
    _ensure_enum(variables, "VAR_DTYPE_LAYOUT_CLASS", [str(item.get("id") or item.get("name") or item.get("class") or item.get("dtype")) for item in _iter_items(interface.get("dtype_layout_domains")) if item], source="interface.dtype_layout_domains", errors=errors)
    for item in _iter_items(interface.get("optional_inputs")):
        name = str(item.get("id") or item.get("name") or item.get("input") or "")
        if name:
            _ensure_bool(variables, _optional_var_id(name), source="interface.optional_inputs", errors=errors)

def _variables_from_context_slice(variables: dict[str, dict[str, Any]], context_slice: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    bucket_members: dict[str, list[str]] = {
        "VAR_FAMILY": [],
        "VAR_KERNEL_PATH": [],
        "VAR_TEMPLATE": [],
        "VAR_NUMERICAL_MODE": [],
    }
    for entity in _iter_items(context_slice.get("entities")):
        entity_id = str(entity.get("id") or entity.get("stable_id") or "")
        if not entity_id:
            continue
        if entity_id.startswith("FAM_"):
            bucket_members["VAR_FAMILY"].append(entity_id)
            continue
        if entity_id.startswith("KPATH_"):
            bucket_members["VAR_KERNEL_PATH"].append(entity_id)
            continue
        if entity_id.startswith("KTPL_"):
            bucket_members["VAR_TEMPLATE"].append(entity_id)
            continue
        if entity_id.startswith("NUM_"):
            bucket_members["VAR_NUMERICAL_MODE"].append(entity_id)
            continue
        var_id = _entity_var_id(entity_id)
        if not var_id:
            continue
        data_type = str(entity.get("data_type") or entity.get("type") or entity.get("value_type") or "").lower()
        domain = entity.get("domain") or entity.get("values") or entity.get("enum_values")
        if entity_id.startswith(("KBR_", "KDEC_")) or data_type in {"bool", "boolean"}:
            _ensure_bool(variables, var_id, source="context_entity", errors=errors)
        elif data_type in {"int", "integer"} or _list_is_ints(domain):
            values = [int(value) for value in domain] if isinstance(domain, list) and domain else None
            min_value = entity.get("min")
            max_value = entity.get("max")
            _ensure_int(variables, var_id, values, min_value=min_value, max_value=max_value, source="context_entity" if (values or min_value is not None or max_value is not None) else "context_entity_type_only", errors=errors)
        elif isinstance(domain, list) and domain:
            _ensure_enum(variables, var_id, [str(item) for item in domain], source="context_entity", errors=errors)
        elif entity_id.startswith(("KEY_", "TDF_", "KVAR_")):
            _ensure_int(variables, var_id, source="context_entity_type_only", errors=errors)
    for var_id, members in bucket_members.items():
        _ensure_enum(variables, var_id, sorted(set(members)), source="context_entity_bucket", errors=errors)

def _variables_from_obligations(variables: dict[str, dict[str, Any]], obligations: list[dict[str, Any]], obligation_errors: dict[str, list[dict[str, Any]]]) -> None:
    def errors_for(item: dict[str, Any]) -> list[dict[str, Any]]:
        return obligation_errors.setdefault(str(item.get("id") or ""), [])

    for item in obligations:
        kind = str(item.get("kind") or "")
        refs = [str(ref) for ref in item.get("target_refs") or []]
        if kind == "family":
            _ensure_enum(variables, "VAR_FAMILY", refs, source="obligation_target", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
        elif kind == "kernel_path":
            _ensure_enum(variables, "VAR_KERNEL_PATH", refs, source="obligation_target", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
        elif kind == "compile_template":
            _ensure_enum(variables, "VAR_TEMPLATE", refs, source="obligation_target", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
        elif kind == "dtype_layout_class":
            _ensure_enum(variables, "VAR_DTYPE_LAYOUT_CLASS", refs, source="obligation_target", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
        elif kind == "numerical_mode":
            _ensure_enum(variables, "VAR_NUMERICAL_MODE", refs, source="obligation_target", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
        elif kind == "kernel_branch":
            for ref in refs:
                _ensure_bool(variables, _branch_var_id(ref), source="obligation_target", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
        elif kind == "runtime_variable_state":
            target_value = item.get("target_value")
            for ref in refs:
                if isinstance(target_value, bool):
                    _ensure_bool(variables, _var_id(ref), source="obligation_target", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
                elif isinstance(target_value, int):
                    _ensure_int(variables, _var_id(ref), [target_value], source="obligation_target_value", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
                elif target_value not in (None, ""):
                    _ensure_enum(variables, _var_id(ref), [str(target_value)], source="obligation_target", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
        elif kind == "optional_input_mode":
            for ref in refs:
                _ensure_bool(variables, _optional_var_id(ref), source="obligation_target", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
        elif kind in {"tiling_key_field", "tiling_key_field_value"}:
            constraints = _as_dict(item.get("constraints"))
            field = str(constraints.get("field") or constraints.get("field_name") or (refs[0] if refs else ""))
            values = constraints.get("values")
            target_value = item.get("target_value")
            if field:
                var_id = _key_var_id(refs[0] if refs else field, field)
                if isinstance(values, list) and all(isinstance(v, int) and not isinstance(v, bool) for v in values):
                    _ensure_int(variables, var_id, values, source="obligation_values", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
                elif isinstance(target_value, int) and not isinstance(target_value, bool):
                    _ensure_int(variables, var_id, [target_value], source="obligation_target_value", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
                else:
                    enum_values = [str(v) for v in _as_list(values)] or ([str(target_value)] if target_value not in (None, "") else refs)
                    _ensure_enum(variables, var_id, enum_values, source="obligation_target", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
        elif kind in {"tilingdata_boundary", "core_split_boundary", "tail_boundary", "workspace_boundary", "pipeline_resource_mode"}:
            var = {
                "tilingdata_boundary": "VAR_TILINGDATA_BUCKET",
                "core_split_boundary": "VAR_CORE_SPLIT_BUCKET",
                "tail_boundary": "VAR_TAIL_BUCKET",
                "workspace_boundary": "VAR_WORKSPACE_BUCKET",
                "pipeline_resource_mode": "VAR_PIPELINE_RESOURCE_MODE",
            }[kind]
            _ensure_enum(variables, var, refs, source="obligation_target", errors=errors_for(item), obligation_id=str(item.get("id") or ""))
    for oid in [oid for oid, errors in obligation_errors.items() if not errors]:
        obligation_errors.pop(oid, None)

def _apply_realization_map(
    variables: dict[str, dict[str, Any]],
    constraints: list[dict[str, Any]],
    realization_map: dict[str, Any] | None,
    errors: list[dict[str, Any]],
) -> None:
    if not isinstance(realization_map, dict):
        return
    for spec in _iter_items(realization_map.get("csv_variables")):
        _add_variable(variables, spec, errors, "realization_map.csv_variables")
    for spec in _iter_items(realization_map.get("free_variables")):
        # UO-rooted SMT free ints (no CSV projection).
        patched = dict(spec)
        patched["free"] = True
        _add_variable(variables, patched, errors, "realization_map.free_variables")
    for spec in _iter_items(realization_map.get("derived_variables")):
        expr = spec.get("expr")
        if not isinstance(expr, dict):
            continue
        try:
            normalized = normalize_expr(expr)
            _force_derived_variable(variables, spec, normalized, errors)
            constraints.append(
                {
                    "id": str(spec.get("id") or normalized.get("var")),
                    "kind": "realization_map",
                    "expr": normalized,
                    "source": "realization_map.yaml",
                    "tags": ["realization"],
                }
            )
        except ConstraintIRError as exc:
            errors.append(_error("UNSUPPORTED_EXPRESSION", scope="global", variable_id=str(spec.get("id") or ""), source="realization_map.yaml", message=str(exc)))

def _force_derived_variable(variables: dict[str, dict[str, Any]], spec: dict[str, Any], expr: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    if expr.get("op") != "derived":
        return
    var_id = str(expr.get("var"))
    var_type = str(spec.get("var_type") or spec.get("type") or "int")
    existing = variables.get(var_id)
    if existing and existing.get("type") != var_type:
        errors.append(_error("VARIABLE_TYPE_CONFLICT", scope="global", variable_id=var_id, source="realization_map.yaml", message=f"Variable {var_id} declared as both {existing.get('type')} and {var_type}"))
        return
    if not existing:
        if var_type == "bool":
            _ensure_bool(variables, var_id, source="realization_map.derived", errors=errors)
        elif var_type == "int":
            domain = spec.get("domain")
            values = domain.get("values") if isinstance(domain, dict) else domain
            _ensure_int(variables, var_id, [int(item) for item in _as_list(values)] if values else None, source="realization_map.derived", errors=errors)
        elif var_type == "enum":
            _ensure_enum(variables, var_id, [str(item) for item in _as_list(spec.get("domain"))], source="realization_map.derived", errors=errors)
        existing = variables.get(var_id)
    if not existing:
        return
    existing["free"] = False
    existing["derived"] = True
    existing["definition"] = expr["expr"]
    existing["domain_sources"] = sorted(set(existing.get("domain_sources", [])) | {"realization_map.yaml"})
    existing["source"] = ",".join(sorted(set(str(existing.get("source") or "").split(",")) | {"realization_map.yaml"}))

def _realization_ir_metadata(realization_map: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(realization_map, dict):
        return {"enabled": False, "abstract_branch_vars": [], "mapped_branch_vars": []}
    abstract = []
    for item in _iter_items(realization_map.get("abstract_branches")):
        var = str(item.get("var") or "")
        if var:
            abstract.append(var)
    mapped = []
    for item in _iter_items(realization_map.get("branch_mappings")):
        var = str(item.get("var") or "")
        if var:
            mapped.append(var)
    return {
        "enabled": True,
        "consumer_columns": _as_list(_as_dict(realization_map.get("consumer")).get("columns")),
        "abstract_branch_vars": sorted(set(abstract)),
        "mapped_branch_vars": sorted(set(mapped)),
    }

def _register_derived_variable(variables: dict[str, dict[str, Any]], spec: dict[str, Any], expr: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    if expr.get("op") != "derived":
        return
    var_id = str(expr.get("var"))
    existing = variables.get(var_id)
    var_type = str(spec.get("var_type") or spec.get("type") or "int")
    if existing and existing.get("type") != var_type:
        errors.append(_error("VARIABLE_TYPE_CONFLICT", scope="global", variable_id=var_id, source="contracts/testcase.yaml.typed_constraints", message=f"Variable {var_id} declared as both {existing.get('type')} and {var_type}"))
        return
    if existing and existing.get("free"):
        errors.append(_error("DERIVED_FIELD_FREE", scope="global", variable_id=var_id, message="Derived Field cannot be a free variable"))
    if existing:
        existing["free"] = False
        existing["derived"] = True
        existing["definition"] = expr["expr"]
        existing["source"] = ",".join(sorted(set(str(existing.get("source") or "").split(",")) | {"contracts/testcase.yaml.typed_constraints"}))
        existing["domain_sources"] = sorted(set(existing.get("domain_sources", [])) | {"contracts/testcase.yaml.typed_constraints"})
        return
    variables[var_id] = {
        "id": var_id,
        "name": str(spec.get("name") or var_id),
        "type": var_type,
        "domain": normalize_domain(var_type, spec),
        "stable_id": var_id,
        "free": False,
        "derived": True,
        "definition": expr["expr"],
        "source": "contracts/testcase.yaml.typed_constraints",
    }

def _target_failure(obligation: dict[str, Any], priority: str, reason: str, *, code: str = "OBLIGATION_TARGET_NOT_COMPILED") -> TargetCompileResult:
    if code == "OBLIGATION_OUTSIDE_DECLARED_DOMAIN":
        return TargetCompileResult(status="error", expr=None, code=code, reason=reason)
    if priority in {"hard", "high"}:
        return TargetCompileResult(status="error", expr=None, code=code, reason=reason)
    return TargetCompileResult(status="skipped", expr=None, code=code, reason=reason)

def _ensure_bool(
    variables: dict[str, dict[str, Any]],
    var_id: str,
    *,
    source: str = "bool",
    errors: list[dict[str, Any]] | None = None,
    obligation_id: str | None = None,
) -> None:
    existing = variables.get(var_id)
    if existing and existing.get("type") != "bool" and errors is not None:
        errors.append(_error("VARIABLE_TYPE_CONFLICT", scope="obligation" if obligation_id else "global", obligation_id=obligation_id, variable_id=var_id, source=source, message=f"Variable {var_id} declared as both {existing.get('type')} and bool"))
        return
    variables.setdefault(var_id, {"id": var_id, "name": var_id, "type": "bool", "domain": [False, True], "domain_authority": "intrinsic", "domain_sources": [source], "stable_id": var_id, "free": True, "derived": False, "definition": None, "source": source})

def _ensure_int(
    variables: dict[str, dict[str, Any]],
    var_id: str,
    values: list[int] | None = None,
    *,
    min_value: Any = None,
    max_value: Any = None,
    source: str = "derived_from_plan",
    errors: list[dict[str, Any]] | None = None,
    obligation_id: str | None = None,
) -> None:
    authority = _domain_authority(source)
    domain = _int_domain(values, min_value=min_value, max_value=max_value, source=source, authority=authority)
    if var_id not in variables:
        variables[var_id] = {"id": var_id, "name": var_id, "type": "int", "domain": domain, "domain_authority": authority, "domain_sources": [source], "stable_id": var_id, "free": True, "derived": False, "definition": None, "source": source}
        return
    existing = variables[var_id]
    if existing.get("type") != "int":
        if errors is not None:
            errors.append(_error("VARIABLE_TYPE_CONFLICT", scope="global" if not obligation_id else "obligation", variable_id=var_id, obligation_id=obligation_id, source=source, message=f"Variable {var_id} declared as both {existing.get('type')} and int"))
        return
    if existing.get("derived"):
        return
    merged, merge_errors = _merge_int_domain(existing.get("domain"), domain, existing.get("domain_authority", "inferred"), authority)
    existing["domain"] = merged
    existing["domain_authority"] = merged.get("authority", existing.get("domain_authority", "inferred"))
    existing["domain_sources"] = merged.get("sources", [])
    if errors is not None:
        for error in merge_errors:
            scope = "obligation" if error["code"].startswith("OBLIGATION_") else "global"
            errors.append(_error(error["code"], scope=scope, variable_id=var_id, obligation_id=obligation_id, source=source, **{k: v for k, v in error.items() if k != "code"}))
    existing["source"] = ",".join(sorted(set(str(existing.get("source") or "").split(",")) | {source}))

def _ensure_enum(variables: dict[str, dict[str, Any]], var_id: str, domain: list[str], *, source: str = "derived_from_plan", errors: list[dict[str, Any]] | None = None, obligation_id: str | None = None) -> None:
    clean = sorted(dict.fromkeys(str(item) for item in domain if str(item)))
    if not clean:
        return
    if var_id in variables:
        if variables[var_id]["type"] != "enum":
            if errors is not None:
                errors.append(_error("VARIABLE_TYPE_CONFLICT", scope="global" if not obligation_id else "obligation", variable_id=var_id, obligation_id=obligation_id, source=source, message=f"Variable {var_id} declared as both {variables[var_id].get('type')} and enum"))
            return
        if variables[var_id]["type"] == "enum":
            existing = [str(value) for value in variables[var_id].get("domain", [])]
            existing_authority = variables[var_id].get("domain_authority", "inferred")
            incoming_authority = _domain_authority(source)
            if existing_authority == "explicit" and incoming_authority != "explicit":
                outside = sorted(set(clean) - set(existing))
                if outside and errors is not None:
                    errors.extend(_error("OBLIGATION_OUTSIDE_DECLARED_DOMAIN", scope="obligation", obligation_id=obligation_id, variable_id=var_id, requested_value=value, declared_domain=existing, source=source) for value in outside)
            elif existing_authority == "explicit" and incoming_authority == "explicit":
                common = sorted(set(existing) & set(clean))
                if not common and errors is not None:
                    errors.append(_error("DOMAIN_CONFLICT", scope="global", variable_id=var_id, source=source, message="Explicit enum domains do not intersect"))
                elif common:
                    variables[var_id]["domain"] = common
                    variables[var_id]["domain_authority"] = "explicit"
            elif existing_authority != "explicit" and incoming_authority == "explicit":
                variables[var_id]["domain"] = clean
                variables[var_id]["domain_authority"] = "explicit"
            else:
                variables[var_id]["domain"] = sorted(dict.fromkeys([*existing, *clean]))
            variables[var_id]["domain_sources"] = sorted(set(variables[var_id].get("domain_sources", [])) | {source})
        return
    variables[var_id] = {"id": var_id, "name": var_id, "type": "enum", "domain": clean, "domain_authority": _domain_authority(source), "domain_sources": [source], "stable_id": var_id, "free": True, "derived": False, "definition": None, "source": source}

def _domain_authority(source: str) -> str:
    if source in {"contracts/testcase.yaml.variables", "context_entity", "context_entity_bucket", "interface.dtype_layout_domains", "interface.optional_inputs", "realization_map.csv_variables"}:
        return "explicit"
    if source == "bool":
        return "intrinsic"
    return "inferred"

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
