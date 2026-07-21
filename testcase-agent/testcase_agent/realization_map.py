from __future__ import annotations

from typing import Any

from .atom_bind import CSV_PREFIX, DTYPE_VALUES, csv_var
from .binding_lexicon import apply_lexicon_key_derivations, empty_lexicon, lexicon_from_key_space, merge_lexicons, normalize_lexicon
from .branch_align import align_branches
from .realization_contract import REALIZATION_MAP_VERSION
from .realization_dsl import normalize_realization_map

# Re-export for tests / callers that imported these from realization_map.
__all__ = [
    "BOOTSTRAP_DOMAINS",
    "CSV_PREFIX",
    "DEFAULT_DOMAINS",
    "DTYPE_VALUES",
    "INT_COLUMNS",
    "MODEL_COLUMNS",
    "TOKEN_KEY_VALUE",
    "build_realization_map",
    "csv_var",
]

# Deprecated empty — kept for import compat. Domains come from consumer evidence / schema.
TOKEN_KEY_VALUE: dict[str, tuple[str, int]] = {}

# Soft type hints only when sample evidence is empty. Prefer evidence / field.value_type.
# Intentionally empty — do not reintroduce per-op domain tables here.
BOOTSTRAP_DOMAINS: dict[str, list[Any]] = {}
DEFAULT_DOMAINS = BOOTSTRAP_DOMAINS
# Common Ascend shape-ish ints used only as last-resort type hint when field.value_type missing.
INT_COLUMNS: set[str] = {"B", "N", "N1", "N2", "S", "S1", "S2", "D", "D_V"}
FLOAT_AS_INT_COLUMNS: set[str] = set()
RESULT_PREFIX = "Actual_"
MODEL_COLUMNS: set[str] = set()


def build_realization_map(
    snapshot: dict[str, Any],
    consumer_schema: dict[str, Any],
    *,
    lexicon: dict[str, Any] | None = None,
    op_name: str = "",
    shape_closure: set[str] | None = None,
    out_root: Any = None,
) -> dict[str, Any]:
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    key_space = _as_dict(files.get("tiling/key_space.yaml"))
    branches_doc = _as_dict(files.get("kernel/branches.yaml"))
    fields = [item for item in consumer_schema.get("fields") or [] if isinstance(item, dict)]
    columns = [str(column) for column in consumer_schema.get("columns") or []]
    if not columns and fields:
        columns = [str(item.get("name") or "") for item in sorted(fields, key=lambda item: int(item.get("order", 0)))]
    merged_lexicon = normalize_lexicon(merge_lexicons(lexicon_from_key_space(key_space), lexicon))
    closure = set(shape_closure or [])
    if not closure and out_root is not None:
        from .shape_derivation import load_shape_closure

        closure = load_shape_closure(out_root)
    if not columns:
        return normalize_realization_map(
            {
                "version": REALIZATION_MAP_VERSION,
                "status": "fallback",
                "snapshot_hash": snapshot.get("snapshot_hash"),
                "consumer": {"kind": "csv_sheet", "root": consumer_schema.get("consumer_root", ""), "columns": []},
                "csv_variables": [],
                "free_variables": [],
                "derived_variables": [],
                "branch_mappings": [],
                "abstract_branches": [],
                "binding_lexicon_source": merged_lexicon.get("source"),
                "emit": {
                    "csv_from_model_prefix": CSV_PREFIX,
                    "sidecar_coverage": "case_coverage.yaml",
                    "default_columns": _default_column_values(),
                    "columns": {},
                },
                "warnings": consumer_schema.get("warnings") or ["consumer schema has no columns"],
            }
        )
    field_by_name = {str(item.get("name") or ""): item for item in fields}
    csv_variables = []
    emit_columns: dict[str, Any] = {}
    for column in columns:
        if column.startswith(RESULT_PREFIX):
            continue
        field = field_by_name.get(column) or {}
        role = str(field.get("role") or "")
        if role == "case_id" or column in {"Testcase_Name", "testcase_name", "Case_Name"}:
            emit_columns[column] = {"op": "template", "template": "{case_id}"}
            continue
        if role in {"constant", "metadata", "expected_result"} or column == "Enable":
            continue
        if role == "tensor_placeholder":
            # Slim CSV: do not emit blob/tensor placeholders (historical sheets omit them).
            continue
        if role == "emit_skip":
            continue
        if role == "emit_derived" or "seqlens" in column.lower() or column.startswith("cu_"):
            emit_columns[column] = _default_emit_for_column(column, columns=columns)
            continue
        if role and role != "solver_input":
            continue
        # LLM may mark importance=low → constant emit, not free cover.
        hint_meta = {}
        domain_hints = (consumer_schema.get("domain_hints") or {}).get("columns") or {}
        if isinstance(domain_hints, dict) and isinstance(domain_hints.get(column), dict):
            hint_meta = domain_hints[column]
        from .domain_policy import hint_importance_is_low

        if hint_importance_is_low(hint_meta) or str(field.get("importance") or "").lower() in {
            "low",
            "noise",
            "optional",
            "skip",
        }:
            default = field.get("default")
            if default in (None, ""):
                default = 0 if column.lower() in {"seed", "offset"} else (2 if column.lower() == "seed" else "")
            if column.lower() == "seed" and default in (None, ""):
                default = 2
            if column.lower() == "offset" and default in (None, ""):
                default = 0
            emit_columns[column] = {"op": "constant", "value": default}
            continue
        if fields:
            csv_var_item = _csv_variable_from_field(column, field, consumer_schema)
        else:
            csv_var_item = _csv_variable(column, consumer_schema)
        if csv_var_item:
            csv_variables.append(csv_var_item)
    derived_variables = apply_lexicon_key_derivations([], merged_lexicon)
    # Drop constant-0 stubs that reference missing CSV vars (e.g. VAR_CSV_B) when column absent.
    derived_variables = _filter_derivations_for_columns(derived_variables, columns)
    aligned = align_branches(
        branches_doc,
        snapshot,
        csv_columns=columns,
        lexicon=merged_lexicon,
        op_name=op_name or str(consumer_schema.get("op_name") or ""),
        shape_closure=closure,
    )
    branch_mappings = aligned.get("branch_mappings") or []
    abstract_branches = aligned.get("abstract_branches") or []
    stub_derived = aligned.get("stub_derived_variables") or []
    free_csv_extra = aligned.get("free_csv_variables") or []
    free_vars_extra = aligned.get("free_variables") or []
    # Deduplicate stubs against existing key derivations.
    existing_ids = {str(item.get("id") or "") for item in derived_variables}
    for item in stub_derived:
        vid = str(item.get("id") or "")
        if vid and vid not in existing_ids:
            derived_variables.append(item)
            existing_ids.add(vid)
    existing_csv = {str(item.get("id") or "") for item in csv_variables}
    for item in free_csv_extra:
        vid = str(item.get("id") or "")
        column = str(item.get("column") or "")
        # Never invent CSV columns absent from consumer schema.
        if column and column not in columns:
            continue
        if vid and vid not in existing_csv:
            csv_variables.append(item)
            existing_csv.add(vid)
    free_variables: list[dict[str, Any]] = []
    existing_free = set(existing_csv) | existing_ids
    for item in free_vars_extra:
        vid = str(item.get("id") or "")
        if vid and vid not in existing_free:
            free_variables.append(item)
            existing_free.add(vid)
    for item in branch_mappings:
        item.setdefault("source_refs", [{"path": item.get("file_path") or "kernel/branches.yaml", "line": item.get("start_line")}])
    realization_map = {
        "version": REALIZATION_MAP_VERSION,
        "status": "ok" if columns else "fallback",
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "consumer": {
            "kind": "csv_sheet",
            "root": consumer_schema.get("consumer_root", ""),
            "columns": columns,
            "result_columns": consumer_schema.get("result_columns") or [],
            "schema_source": consumer_schema.get("schema_source") or [],
        },
        "csv_variables": csv_variables,
        "free_variables": free_variables,
        "derived_variables": derived_variables + [item["derived_variable"] for item in branch_mappings],
        "branch_mappings": [{k: v for k, v in item.items() if k != "derived_variable"} for item in branch_mappings],
        "abstract_branches": abstract_branches,
        "alignment_report": aligned.get("alignment_report") or {},
        "binding_lexicon_source": merged_lexicon.get("source"),
        "emit": {
            "csv_from_model_prefix": "VAR_CSV_",
            "sidecar_coverage": "case_coverage.yaml",
            "default_columns": _default_column_values(),
            "columns": emit_columns,
        },
        "warnings": list(consumer_schema.get("warnings") or [])
        + list(merged_lexicon.get("warnings") or [])
        + [
            "binding_lexicon: per-op KEY/CSV maps come from /tg-csv-contract → realization/binding_lexicon.yaml; "
            "deterministic TG only applies UO set_by + key_space token heuristics"
        ],
    }
    extend_csv_enum_domains_from_exprs(realization_map)
    realization_map = apply_architecture_platform_fixes(realization_map, snapshot)
    return normalize_realization_map(realization_map)


def apply_architecture_platform_fixes(
    realization_map: dict[str, Any],
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fix architecture-declared platform KEYs already present; never invent new KEY ids."""
    from .domain_policy import platform_key_tokens_for_architecture

    arch = _snapshot_architecture(snapshot)
    tokens = platform_key_tokens_for_architecture(arch)
    if not tokens:
        return realization_map
    derived = list(realization_map.get("derived_variables") or [])
    fixed_ids: list[str] = []
    for item in derived:
        if not isinstance(item, dict):
            continue
        vid = str(item.get("id") or "").upper().replace("-", "_")
        if not any(tok in vid for tok in tokens):
            continue
        item["domain"] = [1]
        item["expr"] = {
            "op": "derived",
            "var": item.get("id"),
            "expr": 1,
        }
        item["description"] = (
            str(item.get("description") or "")
            + f" [architecture={arch}: platform KEY fixed to 1]"
        ).strip()
        item["architecture_fixed"] = True
        fixed_ids.append(str(item.get("id")))
    if not fixed_ids:
        return realization_map
    realization_map["derived_variables"] = derived
    realization_map.setdefault("warnings", [])
    warning = f"architecture_fixed:platform_keys={','.join(fixed_ids)} arch={arch}"
    if warning not in realization_map["warnings"]:
        realization_map["warnings"].append(warning)
    return realization_map


def _snapshot_architecture(snapshot: dict[str, Any] | None) -> str:
    if not isinstance(snapshot, dict):
        return ""
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    contract = files.get("contracts/testcase.yaml") if isinstance(files.get("contracts/testcase.yaml"), dict) else {}
    arch = str(contract.get("architecture") or "").strip()
    if arch:
        return arch
    graph = files.get("ir/operator_graph.yaml") if isinstance(files.get("ir/operator_graph.yaml"), dict) else {}
    return str(graph.get("architecture") or graph.get("arch") or "").strip()


def extend_csv_enum_domains_from_exprs(realization_map: dict[str, Any]) -> dict[str, Any]:
    """Union string literals from derived/branch exprs into CSV enum domains (UO evidence)."""
    by_id = {
        str(item.get("id") or ""): item
        for item in realization_map.get("csv_variables") or []
        if isinstance(item, dict) and item.get("id") and str(item.get("type") or "") == "enum"
    }
    if not by_id:
        return realization_map
    extras: dict[str, list[str]] = {vid: [] for vid in by_id}
    for item in list(realization_map.get("derived_variables") or []) + list(
        realization_map.get("branch_mappings") or []
    ):
        if not isinstance(item, dict):
            continue
        expr = item.get("expr")
        if isinstance(expr, dict) and expr.get("op") == "derived":
            expr = expr.get("expr")
        for var_id, value in _collect_enum_literals(expr):
            if var_id in extras and value not in extras[var_id]:
                extras[var_id].append(value)
        # Also scan nested target bindings on branch mappings.
        for binding in item.get("atom_bindings") or []:
            if not isinstance(binding, dict):
                continue
            target = binding.get("target")
            for var_id, value in _collect_enum_literals(target):
                if var_id in extras and value not in extras[var_id]:
                    extras[var_id].append(value)
    for var_id, values in extras.items():
        if not values:
            continue
        spec = by_id[var_id]
        domain = [str(v) for v in (spec.get("domain") or [])]
        merged = list(dict.fromkeys([*domain, *values]))
        if merged != domain:
            spec["domain"] = merged
    return realization_map


def _collect_enum_literals(expr: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not isinstance(expr, dict):
        return out
    op = str(expr.get("op") or "")
    if op in {"eq", "ne"} and "var" in expr and "value" in expr:
        value = expr.get("value")
        if isinstance(value, str) and value and not isinstance(value, bool):
            # Skip numeric-looking strings — those belong to int domains.
            try:
                float(value)
            except (TypeError, ValueError):
                out.append((str(expr["var"]), value))
    for key in ("arg", "lhs", "rhs", "condition", "then", "else", "antecedent", "consequent", "expr"):
        child = expr.get(key)
        if child is not None:
            out.extend(_collect_enum_literals(child))
    for key in ("args", "items"):
        for child in expr.get(key) or []:
            out.extend(_collect_enum_literals(child))
    return out


def _csv_variable_from_field(column: str, field: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any] | None:
    sample_values = _as_dict(schema.get("sample_values")).get(column) or []
    value_type = str(field.get("value_type") or "")
    domain = field.get("domain")
    source_refs = field.get("source_refs") or [{"path": "consumer_schema", "column": column}]
    if value_type == "int" or column in INT_COLUMNS or column in FLOAT_AS_INT_COLUMNS:
        # Preserve generalized range domains from schema inference.
        if isinstance(domain, dict) and (
            domain.get("kind") == "range" or domain.get("min") is not None or domain.get("max") is not None
        ):
            lo = _parse_int(domain.get("min"))
            hi = _parse_int(domain.get("max"))
            if lo is None:
                lo = 1
            if hi is None:
                hi = lo
            if hi < lo:
                hi = lo
            return {
                "id": csv_var(column),
                "column": column,
                "type": "int",
                "domain": {"kind": "range", "min": int(lo), "max": int(hi)},
                "default": field.get("default", int(lo)),
                "free": True,
                "source_refs": source_refs,
            }
        if isinstance(domain, dict) and domain.get("values") is not None:
            ints = [int(item) for item in domain.get("values") or []]
        elif isinstance(domain, list):
            ints = [item for item in (_parse_int(value) for value in domain) if item is not None]
        else:
            values = _merge_domain(BOOTSTRAP_DOMAINS.get(column, []), sample_values)
            ints = [item for item in (_parse_int(value) for value in values) if item is not None]
        if column in FLOAT_AS_INT_COLUMNS:
            ints = [0, 1]
        if not ints:
            ints = [0]
        return {
            "id": csv_var(column),
            "column": column,
            "type": "int",
            "domain": sorted(dict.fromkeys(ints)),
            "default": field.get("default", ints[0]),
            "free": True,
            "source_refs": source_refs,
        }
    if isinstance(domain, list) and domain:
        clean = [str(value) for value in domain if str(value) != ""]
    else:
        clean = []
    # Always merge bootstrap + samples so derived exprs (e.g. fp32) stay in-domain.
    merged = _merge_domain(BOOTSTRAP_DOMAINS.get(column, []), [*clean, *sample_values])
    clean = [str(value) for value in merged if str(value) != "" and str(value) != "_"]
    if not clean:
        clean = ["NONE"]
    return {
        "id": csv_var(column),
        "column": column,
        "type": "enum",
        "domain": sorted(dict.fromkeys(clean)),
        "default": field.get("default", clean[0]) if str(field.get("default") or "") != "_" else clean[0],
        "free": True,
        "source_refs": source_refs,
    }


def _csv_variable(column: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    """Legacy helper used by older tests."""
    sample_values = _as_dict(schema.get("sample_values")).get(column) or []
    values = _merge_domain(BOOTSTRAP_DOMAINS.get(column, []), sample_values)
    if column in FLOAT_AS_INT_COLUMNS:
        return {"id": csv_var(column), "column": column, "type": "int", "domain": [0, 1], "default": 1, "free": True}
    if column in INT_COLUMNS:
        ints = []
        for value in values:
            parsed = _parse_int(value)
            if parsed is not None:
                ints.append(parsed)
        if not ints:
            ints = [0]
        return {"id": csv_var(column), "column": column, "type": "int", "domain": sorted(dict.fromkeys(ints)), "default": ints[0], "free": True}
    if column in {"Testcase_Name"}:
        return None
    clean = [str(value) for value in values if str(value) != ""]
    if not clean:
        # No sample evidence: treat as free int flag/knob rather than empty enum.
        return {"id": csv_var(column), "column": column, "type": "int", "domain": [0, 1], "default": 0, "free": True}
    return {"id": csv_var(column), "column": column, "type": "enum", "domain": sorted(dict.fromkeys(clean)), "default": clean[0], "free": True}


def _default_emit_for_column(column: str, *, columns: list[str] | None = None) -> dict[str, Any]:
    """Emit heuristics by column-name pattern (packed/varlen layouts vs fixed-seq dims)."""
    from .domain_policy import (
        PACKED_OR_VARLEN_LAYOUTS,
        is_varlen_sequence_column,
        primary_layout_column_name,
    )

    lower = column.lower()
    layout_col = primary_layout_column_name(columns) or "Input_Layout"
    packed_cond = {
        "op": "in",
        "var": csv_var(layout_col),
        "values": sorted(PACKED_OR_VARLEN_LAYOUTS),
    }
    if is_varlen_sequence_column(column) or "seqlens_list" in lower or lower.startswith("cu_seqlens"):
        # Prefer S1 for query-side totals, S2 for kv-side when names hint so.
        total_col = "S1"
        if "kv" in lower or lower.endswith("_kv") or lower.endswith("_k"):
            total_col = "S2"
        partition = {
            "op": "balanced_partition",
            "total": {"op": "model_var", "var": csv_var(total_col)},
            "parts": {"op": "model_var", "var": csv_var("B")},
        }
        then_expr: dict[str, Any] = {"op": "list_format", "values": partition}
        if lower.startswith("cu_seqlens") or "cu_seq" in lower:
            then_expr = {
                "op": "list_format",
                "values": {"op": "cumulative_sum", "values": partition},
            }
        return {
            "op": "if_then_else",
            "condition": packed_cond,
            "then": then_expr,
            "else": "",
        }
    return {"op": "constant", "value": ""}


def _filter_derivations_for_columns(derived: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    """Drop lexicon derivations that reference VAR_CSV_* columns not in consumer schema."""
    allowed = {csv_var(c) for c in columns}
    out: list[dict[str, Any]] = []
    for item in derived:
        expr = item.get("expr") if isinstance(item, dict) else None
        inner = expr.get("expr") if isinstance(expr, dict) and expr.get("op") == "derived" else expr
        refs = _collect_csv_refs(inner)
        if refs and not refs.issubset(allowed):
            continue
        out.append(item)
    return out


def _collect_csv_refs(expr: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(expr, dict):
        var = expr.get("var")
        if isinstance(var, str) and var.startswith(CSV_PREFIX):
            out.add(var)
        for key in ("arg", "lhs", "rhs", "condition", "then", "else", "expr"):
            if key in expr:
                out |= _collect_csv_refs(expr[key])
        for child in expr.get("args") or []:
            out |= _collect_csv_refs(child)
    return out


def _derived(var_id: str, var_type: str, domain: Any, expr: dict[str, Any], description: str) -> dict[str, Any]:
    return {
        "id": var_id,
        "type": var_type,
        "domain": domain,
        "expr": {"op": "derived", "var": var_id, "expr": expr},
        "description": description,
        "source_refs": [{"path": "realization_map.bootstrap", "rationale": description}],
    }


def _eq_csv(column: str, value: Any) -> dict[str, Any]:
    return {"op": "eq", "var": csv_var(column), "value": value}


def _ne_csv(column: str, value: Any) -> dict[str, Any]:
    return {"op": "ne", "var": csv_var(column), "value": value}


def _ne_csv_vars(left: str, right: str) -> dict[str, Any]:
    return {"op": "ne", "lhs": {"var": csv_var(left)}, "rhs": {"var": csv_var(right)}}


def _ite(condition: dict[str, Any], then_value: Any, else_value: Any) -> dict[str, Any]:
    return {"op": "if_then_else", "condition": condition, "then": then_value, "else": else_value}


def _dtype_expr(column: str) -> dict[str, Any]:
    return _ite(_eq_csv(column, "bf16"), 1, _ite(_eq_csv(column, "fp32"), 2, 0))


def _bucket_expr(column: str, thresholds: list[int], values: list[int], default: int) -> dict[str, Any]:
    expr: dict[str, Any] | int = default
    for threshold, value in reversed(list(zip(thresholds, values))):
        expr = _ite({"op": "ge", "var": csv_var(column), "value": threshold}, value, expr)
    return expr if isinstance(expr, dict) else {"op": "if_then_else", "condition": {"op": "ge", "var": csv_var(column), "value": 0}, "then": expr, "else": expr}


def _merge_domain(defaults: list[Any], sample_values: list[Any]) -> list[Any]:
    out: list[Any] = []
    for value in [*defaults, *sample_values]:
        if value not in out:
            out.append(value)
    return out


def _default_column_values() -> dict[str, Any]:
    return {column: values[0] for column, values in BOOTSTRAP_DOMAINS.items() if values}


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _iter_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [{"id": str(key), **item} if isinstance(item, dict) else {"id": str(key), "value": item} for key, item in sorted(value.items())]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
