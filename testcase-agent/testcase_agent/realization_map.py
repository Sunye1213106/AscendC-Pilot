from __future__ import annotations

import re
from typing import Any

from .realization_dsl import normalize_realization_map


CSV_PREFIX = "VAR_CSV_"


DEFAULT_DOMAINS: dict[str, list[Any]] = {
    "Enable": ["Enable"],
    "Dtype": ["fp16", "bf16", "fp32"],
    "out_dtype": ["fp16", "bf16", "fp32"],
    "Input_Layout": ["BNSD", "BSND", "TND", "SBH", "BSH"],
    "B": [1, 2, 4, 8, 9],
    "N1": [1, 2, 4, 8, 16],
    "N2": [1, 2, 4, 8, 16],
    "S1": [16, 24, 32, 64, 80, 128, 256, 512],
    "S2": [16, 24, 32, 64, 80, 128, 256, 512],
    "D": [64, 128, 177, 192, 256],
    "D_V": [64, 128, 177, 192, 256],
    "Drop_Out_Possibility": [0, 1],
    "Pre_Tockens": [65536],
    "Next_Tockens": [0, 65536],
    "Atten_mask_dtype": ["NONE", "bool", "BOOL", "uint8"],
    "Atten_mask_shape": ["NONE", "SS", "B1SS", "BNSS", "1SS", "B11S"],
    "sparse_mode": [0, 1, 2, 3],
    "PSE_type": [0, 1, 2, 3],
    "PSE_shape": ["NONE", "SS", "1NSS", "BNSS", "BN1S", "1NHS"],
    "eod": [0],
    "same_as_input": [0, 1],
    "seed": [2],
    "offset": [0],
    "is_deter": ["false", "true", "FALSE", "TRUE"],
    "rope": [0, 1],
    "inner_drop": [0, 1],
    "is_sink": [0, 1],
    "prefix": [""],
}

INT_COLUMNS = {
    "B",
    "N1",
    "N2",
    "S1",
    "S2",
    "D",
    "D_V",
    "Pre_Tockens",
    "Next_Tockens",
    "sparse_mode",
    "PSE_type",
    "eod",
    "same_as_input",
    "seed",
    "offset",
    "rope",
    "inner_drop",
    "is_sink",
}

FLOAT_AS_INT_COLUMNS = {"Drop_Out_Possibility"}
RESULT_PREFIX = "Actual_"
MODEL_COLUMNS = {
    "Dtype",
    "out_dtype",
    "Input_Layout",
    "B",
    "N1",
    "N2",
    "S1",
    "S2",
    "D",
    "D_V",
    "Drop_Out_Possibility",
    "Atten_mask_dtype",
    "Atten_mask_shape",
    "sparse_mode",
    "PSE_type",
    "PSE_shape",
    "rope",
    "inner_drop",
    "is_sink",
}


def build_realization_map(snapshot: dict[str, Any], consumer_schema: dict[str, Any]) -> dict[str, Any]:
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    key_space = _as_dict(files.get("tiling/key_space.yaml"))
    branches_doc = _as_dict(files.get("kernel/branches.yaml"))
    columns = [str(column) for column in consumer_schema.get("columns") or []]
    if not columns:
        return normalize_realization_map(
            {
                "version": 1,
                "status": "fallback",
                "snapshot_hash": snapshot.get("snapshot_hash"),
                "consumer": {"kind": "csv_sheet", "root": consumer_schema.get("consumer_root", ""), "columns": []},
                "csv_variables": [],
                "derived_variables": [],
                "branch_mappings": [],
                "abstract_branches": [],
                "emit": {"csv_from_model_prefix": CSV_PREFIX, "sidecar_coverage": "case_coverage.yaml", "default_columns": _default_column_values()},
                "warnings": consumer_schema.get("warnings") or ["consumer schema has no columns"],
            }
        )
    csv_variables = [_csv_variable(column, consumer_schema) for column in columns if not column.startswith(RESULT_PREFIX)]
    csv_variables = [item for item in csv_variables if item]
    derived_variables = _key_derivations(key_space)
    branch_mappings, abstract_branches = _branch_derivations(branches_doc)
    realization_map = {
        "version": 1,
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
        "derived_variables": derived_variables + [item["derived_variable"] for item in branch_mappings],
        "branch_mappings": [{k: v for k, v in item.items() if k != "derived_variable"} for item in branch_mappings],
        "abstract_branches": abstract_branches,
        "emit": {
            "csv_from_model_prefix": CSV_PREFIX,
            "sidecar_coverage": "case_coverage.yaml",
            "default_columns": _default_column_values(),
        },
        "warnings": consumer_schema.get("warnings") or [],
    }
    return normalize_realization_map(realization_map)


def _csv_variable(column: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    if column not in MODEL_COLUMNS:
        return None
    sample_values = _as_dict(schema.get("sample_values")).get(column) or []
    values = _merge_domain(DEFAULT_DOMAINS.get(column, []), sample_values)
    if column in FLOAT_AS_INT_COLUMNS:
        # The current IR has int/bool/enum only. Model dropout as 0/1 for branch coverage.
        return {"id": csv_var(column), "column": column, "type": "int", "domain": [0, 1], "default": 1}
    if column in INT_COLUMNS:
        ints = []
        for value in values:
            parsed = _parse_int(value)
            if parsed is not None:
                ints.append(parsed)
        if not ints:
            ints = [0]
        return {"id": csv_var(column), "column": column, "type": "int", "domain": sorted(dict.fromkeys(ints)), "default": ints[0]}
    if column in {"Testcase_Name"}:
        return None
    clean = [str(value) for value in values if str(value) != ""]
    if not clean:
        clean = [""]
    return {"id": csv_var(column), "column": column, "type": "enum", "domain": sorted(dict.fromkeys(clean)), "default": clean[0]}


def _key_derivations(key_space: dict[str, Any]) -> list[dict[str, Any]]:
    key_domains = {str(item.get("id")): item.get("values") for item in _iter_items(key_space.get("fields"))}
    derived: list[dict[str, Any]] = []
    add = derived.append
    add(_derived("VAR_KEY_ISTND", "int", key_domains.get("KEY_ISTND", [0, 1]), _ite(_eq_csv("Input_Layout", "TND"), 1, 0), "Input_Layout == TND"))
    add(_derived("VAR_KEY_ISROPE", "int", key_domains.get("KEY_ISROPE", [0, 1]), _ite(_eq_csv("rope", 1), 1, 0), "rope == 1"))
    add(_derived("VAR_KEY_ISATTENMASK", "int", key_domains.get("KEY_ISATTENMASK", [0, 1]), _ite(_ne_csv("Atten_mask_shape", "NONE"), 1, 0), "Atten_mask_shape != NONE"))
    add(
        _derived(
            "VAR_KEY_ISPSE",
            "int",
            key_domains.get("KEY_ISPSE", [0, 1]),
            _ite({"op": "or", "args": [_ne_csv("PSE_shape", "NONE"), _ne_csv("PSE_type", 0)]}, 1, 0),
            "PSE_shape != NONE or PSE_type != 0",
        )
    )
    add(
        _derived(
            "VAR_KEY_ISDROP",
            "int",
            key_domains.get("KEY_ISDROP", [0, 1]),
            _ite({"op": "or", "args": [_ne_csv("Drop_Out_Possibility", 1), _eq_csv("inner_drop", 1)]}, 1, 0),
            "Drop_Out_Possibility != 1 or inner_drop == 1",
        )
    )
    add(_derived("VAR_KEY_ISNEQUAL", "int", key_domains.get("KEY_ISNEQUAL", [0, 1]), _ite(_ne_csv_vars("N1", "N2"), 1, 0), "N1 != N2"))
    add(_derived("VAR_KEY_ISDNOEQUAL", "int", key_domains.get("KEY_ISDNOEQUAL", [0, 1]), _ite(_ne_csv_vars("D", "D_V"), 1, 0), "D != D_V"))
    add(_derived("VAR_KEY_INPUTDTYPE", "int", key_domains.get("KEY_INPUTDTYPE", [0, 1, 2]), _dtype_expr("Dtype"), "Dtype bucket"))
    add(_derived("VAR_KEY_OUTDTYPE", "int", key_domains.get("KEY_OUTDTYPE", [0, 1, 2]), _dtype_expr("out_dtype"), "out_dtype bucket"))
    add(_derived("VAR_KEY_S1TEMPLATENUM", "int", key_domains.get("KEY_S1TEMPLATENUM", [0, 64, 128, 512]), _bucket_expr("S1", [512, 128, 64], [512, 128, 64], 0), "S1 template bucket"))
    add(_derived("VAR_KEY_S2TEMPLATENUM", "int", key_domains.get("KEY_S2TEMPLATENUM", [0, 128, 256, 512]), _bucket_expr("S2", [512, 256, 128], [512, 256, 128], 0), "S2 template bucket"))
    add(_derived("VAR_KEY_DTEMPLATENUM", "int", key_domains.get("KEY_DTEMPLATENUM", [0, 64, 128, 192, 256]), _bucket_expr("D", [256, 192, 128, 64], [256, 192, 128, 64], 0), "D template bucket"))
    return derived


def _branch_derivations(branches_doc: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mappings: list[dict[str, Any]] = []
    abstract: list[dict[str, Any]] = []
    for branch in _iter_items(branches_doc.get("branches")):
        branch_id = str(branch.get("id") or "")
        if not branch_id:
            continue
        var_id = _var_id(branch_id)
        condition = str(branch.get("condition") or "")
        expr = _parse_branch_condition(condition)
        base = {
            "branch_ref": branch_id,
            "var": var_id,
            "condition": condition,
            "determinant_source": branch.get("determinant_source", ""),
            "file_path": branch.get("file_path", ""),
            "start_line": branch.get("start_line"),
        }
        if expr:
            mappings.append(
                {
                    **base,
                    "abstract_only": False,
                    "derived_variable": _derived(var_id, "bool", [False, True], expr, "parsed kernel branch condition"),
                }
            )
        else:
            abstract.append({**base, "abstract_only": True, "reason": "condition is not mapped to CSV/KEY variables"})
    return mappings, abstract


TOKEN_KEY_VALUE: dict[str, tuple[str, int]] = {
    "IS_TND": ("VAR_KEY_ISTND", 1),
    "IS_ROPE": ("VAR_KEY_ISROPE", 1),
    "IS_DROP": ("VAR_KEY_ISDROP", 1),
    "IS_ATTEN_MASK": ("VAR_KEY_ISATTENMASK", 1),
    "IS_PSE": ("VAR_KEY_ISPSE", 1),
    "IS_NZ_OUT": ("VAR_KEY_ISNZOUT", 1),
    "IS_TND_SWIZZLE": ("VAR_KEY_ISTNDSWIZZLE", 1),
    "IS_BN2_MULTIBLK": ("VAR_KEY_ISBN2MULTIBLK", 1),
    "IS_D_NO_EQUAL": ("VAR_KEY_ISDNOEQUAL", 1),
    "IS_N_EQUAL": ("VAR_KEY_ISNEQUAL", 0),
}

DTYPE_VALUES = {
    "DT_FLOAT16": 0,
    "DT_BF16": 1,
    "DT_FLOAT": 2,
    "DT_FLOAT32": 2,
}


def _parse_branch_condition(condition: str) -> dict[str, Any] | None:
    text = _strip_outer_parens(condition.strip())
    if not text or any(op in text for op in ["&&", "||", "?", ":", "<", ">"]):
        return None
    if text.startswith("!"):
        inner = _parse_branch_condition(text[1:].strip())
        return {"op": "not", "arg": inner} if inner else None
    if text in TOKEN_KEY_VALUE:
        var_id, value = TOKEN_KEY_VALUE[text]
        return {"op": "eq", "var": var_id, "value": value}
    match = re.fullmatch(r"\(?\s*ORIG_DTYPE_QUERY\s*==\s*(DT_[A-Z0-9_]+)\s*\)?", text)
    if match and match.group(1) in DTYPE_VALUES:
        return {"op": "eq", "var": "VAR_KEY_INPUTDTYPE", "value": DTYPE_VALUES[match.group(1)]}
    match = re.fullmatch(r"\(?\s*(IS_[A-Z0-9_]+)\s*==\s*(true|false|0|1)\s*\)?", text, flags=re.IGNORECASE)
    if match and match.group(1).upper() in TOKEN_KEY_VALUE:
        var_id, true_value = TOKEN_KEY_VALUE[match.group(1).upper()]
        raw = match.group(2).lower()
        wants_true = raw in {"true", "1"}
        return {"op": "eq", "var": var_id, "value": true_value if wants_true else 1 - true_value}
    return None


def csv_var(column: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in str(column)).strip("_")
    return f"{CSV_PREFIX}{safe}"


def _derived(var_id: str, var_type: str, domain: Any, expr: dict[str, Any], description: str) -> dict[str, Any]:
    return {"id": var_id, "type": var_type, "domain": domain, "expr": {"op": "derived", "var": var_id, "expr": expr}, "description": description}


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
    return {column: values[0] for column, values in DEFAULT_DOMAINS.items() if values}


def _strip_outer_parens(text: str) -> str:
    text = text.strip()
    while text.startswith("(") and text.endswith(")"):
        inner = text[1:-1].strip()
        if inner.count("(") != inner.count(")"):
            break
        text = inner
    return text


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _var_id(name: str) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(name)).strip("_").upper()
    return text if text.startswith("VAR_") else f"VAR_{text or 'UNKNOWN'}"


def _iter_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [{"id": str(key), **item} if isinstance(item, dict) else {"id": str(key), "value": item} for key, item in sorted(value.items())]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
