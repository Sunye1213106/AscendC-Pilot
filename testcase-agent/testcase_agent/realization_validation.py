from __future__ import annotations

from typing import Any

from .constraint_ir import SUPPORTED_EXPR_OPS, collect_expr_variables
from .hashing import stable_hash
from .realization_contract import CONSUMER_SCHEMA_VERSION, REALIZATION_MAP_VERSION, ContractError, contract_hash

ALLOWED_FIELD_ROLES = {
    "solver_input",
    "solver_derived",
    "emit_derived",
    "constant",
    "case_id",
    "expected_result",
    "metadata",
    # Tensor/blob columns that are not free SMT variables (emitted as placeholders).
    "tensor_placeholder",
    "emit_skip",
}
ALLOWED_VALUE_TYPES = {"bool", "int", "enum", "string", "list_int"}
ALLOWED_EMIT_OPS = {
    "constant",
    "model_var",
    "bool_format",
    "enum_format",
    "template",
    "balanced_partition",
    "cumulative_sum",
    "list_format",
    "if_then_else",
}

# Platform KEY tokens that may be constant-fixed when architecture declares them.
# Kept in sync with domain_policy.ARCHITECTURE_PLATFORM_KEY_TOKENS values.
PLATFORM_FIXED_KEY_TOKENS = frozenset({"ISREGBASE", "REGBASE"})

ALLOWED_EMIT_CONDITION_OPS = frozenset({"eq", "in", "or", "and", "ne"})


def validate_contract_artifacts(
    evidence: dict[str, Any],
    consumer_schema: dict[str, Any],
    realization_map: dict[str, Any],
    *,
    snapshot_hash: str,
    plan_hash: str,
    allow_bootstrap: bool = False,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if consumer_schema.get("version") != CONSUMER_SCHEMA_VERSION:
        errors.append(_error("CSV_CONTRACT_REQUIRED", "consumer_schema version mismatch"))
    if realization_map.get("version") != REALIZATION_MAP_VERSION:
        errors.append(_error("CSV_CONTRACT_REQUIRED", "realization_map version mismatch"))
    for key, expected in {
        "evidence_hash": evidence.get("evidence_hash"),
        "snapshot_hash": snapshot_hash,
        "plan_hash": plan_hash,
    }.items():
        if consumer_schema.get(key) != expected or realization_map.get(key) != expected:
            errors.append(_error("CSV_CONTRACT_STALE", f"{key} mismatch"))

    fields = [item for item in consumer_schema.get("fields", []) if isinstance(item, dict)]
    names = [str(item.get("name") or "") for item in fields]
    if [str(item.get("name") or "") for item in sorted(fields, key=lambda item: int(item.get("order", 0)))] != names:
        errors.append(_error("CONSUMER_SCHEMA_AMBIGUOUS", "field order does not match serialized order"))

    evidence_columns = (
        set((evidence.get("field_accesses") or {}).keys())
        | set((evidence.get("sample_values") or {}).keys())
        | {
            str(column)
            for item in evidence.get("ordered_header_candidates") or []
            if isinstance(item, dict)
            for column in item.get("columns") or []
        }
    )
    csv_var_ids = set()
    declared_ids = set()
    field_by_name = {str(item.get("name")): item for item in fields}
    for field in fields:
        name = str(field.get("name") or "")
        role = str(field.get("role") or "")
        value_type = str(field.get("value_type") or "")
        if role not in ALLOWED_FIELD_ROLES:
            errors.append(_error("CONSUMER_SCHEMA_AMBIGUOUS", f"unsupported role for {name}"))
        if value_type not in ALLOWED_VALUE_TYPES:
            errors.append(_error("CONSUMER_SCHEMA_AMBIGUOUS", f"unsupported value_type for {name}"))
        if field.get("required") and not field.get("source_refs"):
            errors.append(_error("CSV_CONTRACT_REQUIRED", f"required field {name} missing source_refs"))
        if name not in evidence_columns and role not in {
            "case_id",
            "expected_result",
            "metadata",
            "constant",
            "emit_derived",
            "tensor_placeholder",
        }:
            if allow_bootstrap:
                continue
            errors.append(_error("CONSUMER_SCHEMA_AMBIGUOUS", f"field {name} is absent from evidence"))

    for spec in realization_map.get("csv_variables", []) or []:
        if not isinstance(spec, dict):
            continue
        column = str(spec.get("column") or "")
        var_id = str(spec.get("id") or "")
        csv_var_ids.add(var_id)
        declared_ids.add(var_id)
        field = field_by_name.get(column)
        if not field:
            errors.append(_error("UNKNOWN_SOLVER_VARIABLE", f"csv variable {var_id} points to unknown column {column}"))
            continue
        if field.get("role") != "solver_input":
            errors.append(_error("REQUIRED_COLUMN_UNMAPPED", f"{column} must be solver_input to be a free csv variable"))
        if spec.get("type") == "enum" and not spec.get("domain"):
            errors.append(_error("EMPTY_VARIABLE_DOMAIN", f"{var_id} has empty enum domain"))
        if spec.get("type") == "int" and not _int_domain_present(spec.get("domain")):
            errors.append(_error("EMPTY_VARIABLE_DOMAIN", f"{var_id} has empty int domain"))

    for spec in realization_map.get("free_variables", []) or []:
        if not isinstance(spec, dict):
            continue
        var_id = str(spec.get("id") or "")
        if not var_id:
            continue
        declared_ids.add(var_id)
        if spec.get("type") == "int" and not _int_domain_present(spec.get("domain")):
            errors.append(_error("EMPTY_VARIABLE_DOMAIN", f"{var_id} has empty int domain"))

    derived_graph: dict[str, set[str]] = {}
    # Pass 1: register all derived ids before dependency checks (branch exprs may reference KEY vars).
    for spec in realization_map.get("derived_variables", []) or []:
        if isinstance(spec, dict) and spec.get("id"):
            declared_ids.add(str(spec.get("id")))
    # Pass 2: validate exprs / deps.
    for spec in realization_map.get("derived_variables", []) or []:
        if not isinstance(spec, dict):
            continue
        var_id = str(spec.get("id") or "")
        expr = spec.get("expr")
        if not isinstance(expr, dict):
            errors.append(_error("UNKNOWN_SOLVER_VARIABLE", f"{var_id} missing expr"))
            continue
        inner = expr.get("expr") if expr.get("op") == "derived" else expr
        deps = collect_expr_variables(inner)
        derived_graph[var_id] = set(deps)
        unknown = deps - declared_ids - csv_var_ids
        if unknown:
            if allow_bootstrap:
                # Bootstrap maps may reference KEY flags not yet wired to CSV; demote later via plan filter.
                continue
            errors.append(_error("UNKNOWN_SOLVER_VARIABLE", f"{var_id} references unknown variables: {sorted(unknown)}"))
        if _is_constant_fixed_expr(inner) and not _is_platform_fixed_key(var_id):
            if allow_bootstrap:
                continue
            errors.append(
                _error(
                    "KEY_FIXED_WITHOUT_ARCHITECTURE",
                    f"{var_id} is a constant fixed derivation (then==else). "
                    "Only architecture-declared platform KEYs may be fixed; "
                    "infer from host/KEY card or leave binding_gaps.",
                )
            )

    cycle = _find_cycle(derived_graph)
    if cycle:
        errors.append(_error("DERIVATION_CYCLE", " -> ".join(cycle)))

    for item in realization_map.get("branch_mappings", []) or []:
        if not isinstance(item, dict):
            continue
        if not item.get("source_refs"):
            errors.append(_error("ABSTRACT_TARGET_NOT_REALIZABLE", f"branch mapping {item.get('branch_ref')} missing source_refs"))
    for item in realization_map.get("abstract_branches", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("mapped") is True:
            errors.append(_error("ABSTRACT_TARGET_NOT_REALIZABLE", f"abstract branch {item.get('branch_ref')} marked as mapped"))

    emit = realization_map.get("emit") or {}
    emit_columns = emit.get("columns") or {}
    for column, expr in emit_columns.items():
        if column not in field_by_name:
            errors.append(_error("REQUIRED_COLUMN_UNMAPPED", f"emit column {column} not in schema"))
            continue
        bad = _validate_emit_expr(expr)
        if bad:
            errors.append(_error("UNSUPPORTED_EMIT_EXPRESSION", f"{column}: {bad}"))

    for field in fields:
        name = str(field.get("name") or "")
        role = str(field.get("role") or "")
        if not field.get("required"):
            continue
        if role == "solver_input" and _csv_var_id(name) not in csv_var_ids:
            errors.append(_error("REQUIRED_COLUMN_UNMAPPED", f"required solver_input {name} missing csv variable"))
        if role == "emit_derived" and name not in emit_columns:
            errors.append(_error("REQUIRED_COLUMN_UNMAPPED", f"required emit_derived {name} missing emit expr"))
        if role == "constant" and "default" not in field:
            errors.append(_error("CSV_CONTRACT_REQUIRED", f"required constant {name} missing default"))

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "contract_hash": contract_hash(consumer_schema, realization_map),
        "evidence_hash": evidence.get("evidence_hash", ""),
        "snapshot_hash": snapshot_hash,
        "plan_hash": plan_hash,
        "csv_solver_variable_count": len(csv_var_ids),
        "emit_derived_field_count": len(
            [item for item in fields if str(item.get("role") or "") == "emit_derived"]
        ),
        "unmapped_required_field_count": len([item for item in errors if item["code"] == "REQUIRED_COLUMN_UNMAPPED"]),
        "abstract_branch_count": len(realization_map.get("abstract_branches") or []),
        "unreachable_derived_value_count": len(
            [
                item
                for item in realization_map.get("derived_variables") or []
                if isinstance(item, dict)
                and item.get("declared_domain")
                and item.get("reachable_values") is not None
                and set(map(str, item.get("declared_domain") or [])) - set(map(str, item.get("reachable_values") or []))
            ]
        ),
    }


def ensure_valid_contract(
    evidence: dict[str, Any],
    consumer_schema: dict[str, Any],
    realization_map: dict[str, Any],
    *,
    snapshot_hash: str,
    plan_hash: str,
) -> dict[str, Any]:
    report = validate_contract_artifacts(
        evidence,
        consumer_schema,
        realization_map,
        snapshot_hash=snapshot_hash,
        plan_hash=plan_hash,
    )
    if report["status"] != "pass":
        first = report["errors"][0]
        raise ContractError(f"{first['code']}: {first['message']}")
    return report


def _validate_emit_expr(expr: Any) -> str:
    if expr in ("", None) or isinstance(expr, (str, int, float, bool)):
        return ""
    if not isinstance(expr, dict):
        return "emit expr must be a mapping"
    op = str(expr.get("op") or "")
    if op not in ALLOWED_EMIT_OPS:
        return f"unsupported op {op}"
    for key in ("arg", "value", "items", "args", "template", "lengths", "values", "count", "parts", "then", "else", "total"):
        child = expr.get(key)
        if isinstance(child, dict):
            bad = _validate_emit_expr(child)
            if bad:
                return bad
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, dict):
                    bad = _validate_emit_expr(item)
                    if bad:
                        return bad
    if "condition" in expr:
        bad = _validate_emit_condition(expr.get("condition"))
        if bad:
            return bad
    return ""


def _validate_emit_condition(cond: Any) -> str:
    if cond in ("", None) or isinstance(cond, (str, int, float, bool)):
        return ""
    if not isinstance(cond, dict):
        return "emit condition must be a mapping"
    op = str(cond.get("op") or "")
    if op not in ALLOWED_EMIT_CONDITION_OPS:
        return f"unsupported condition op {op}"
    for key in ("args", "condition"):
        child = cond.get(key)
        if isinstance(child, dict):
            bad = _validate_emit_condition(child)
            if bad:
                return bad
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, dict):
                    bad = _validate_emit_condition(item)
                    if bad:
                        return bad
    return ""


def _find_cycle(graph: dict[str, set[str]]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, stack: list[str]) -> list[str]:
        if node in visiting:
            return stack + [node]
        if node in visited:
            return []
        visiting.add(node)
        for child in graph.get(node, set()):
            if child in graph:
                cycle = visit(child, stack + [node])
                if cycle:
                    return cycle
        visiting.remove(node)
        visited.add(node)
        return []

    for node in graph:
        cycle = visit(node, [])
        if cycle:
            return cycle
    return []


def _int_domain_present(domain: Any) -> bool:
    if isinstance(domain, list):
        return bool(domain)
    if isinstance(domain, dict):
        return bool(domain.get("values")) or domain.get("min") is not None or domain.get("max") is not None
    return False


def _is_platform_fixed_key(var_id: str) -> bool:
    from .domain_policy import is_architecture_platform_key

    return is_architecture_platform_key(var_id)


def _is_constant_fixed_expr(expr: Any) -> bool:
    """True when derived expr is a no-op constant (typical LLM then==else fixed KEY)."""
    if not isinstance(expr, dict):
        return isinstance(expr, (int, float, bool, str)) and str(expr) != ""
    op = str(expr.get("op") or "")
    if op == "if_then_else":
        then_v = expr.get("then")
        else_v = expr.get("else")
        if then_v == else_v and then_v in (0, 1, True, False, "0", "1"):
            return True
        # Nested constant both sides
        if _is_constant_fixed_expr(then_v) and then_v == else_v:
            return True
    if op in {"", "lit", "const", "constant"} and expr.get("value") in (0, 1, True, False):
        return True
    return False


def _csv_var_id(column: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in column).strip("_")
    return f"VAR_CSV_{safe}"


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
