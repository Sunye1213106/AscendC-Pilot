from __future__ import annotations

import ast
import csv
import os
from pathlib import Path
from typing import Any

from .realization_contract import CONSUMER_SCHEMA_VERSION


DEFAULT_SAMPLE_CSV = Path("data") / "FASG_PSE_cases.csv"

# Metadata / identity columns that are not free SMT variables by default.
CASE_ID_COLUMNS = {"Testcase_Name", "testcase_name", "Case_Name"}
CONSTANT_DEFAULTS = {"Enable": "Enable"}
RESULT_PREFIX = "Actual_"

# Soft type hints when sample evidence lacks casts. Not an exclusive allow-list.
INT_HINT_COLUMNS = {
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
FLOAT_AS_INT_HINTS = {"Drop_Out_Possibility"}


class ConsumerRootError(RuntimeError):
    pass


def require_consumer_root(explicit_root: Path | None) -> Path:
    if explicit_root is None:
        raise ConsumerRootError(
            "CSV_CONSUMER_ROOT_REQUIRED: pass --csv-consumer-root <test_script_root> "
            "(directory containing the CSV consumer / test scripts)."
        )
    root = explicit_root.resolve()
    if not root.exists():
        raise ConsumerRootError(f"CSV_CONSUMER_ROOT_MISSING: {root} does not exist")
    return root


def discover_consumer_root(project_root: Path, explicit_root: Path | None = None) -> Path | None:
    """Legacy helper. Prefer require_consumer_root for new paths."""
    if explicit_root:
        root = explicit_root.resolve()
        return root if root.exists() else None
    env = os.environ.get("FAG_DEBUG_TOOLS_ROOT") or os.environ.get("TG_CSV_CONSUMER_ROOT")
    if env:
        root = Path(env).resolve()
        if root.exists():
            return root
    return None


def extract_consumer_schema(consumer_root: Path | None) -> dict[str, Any]:
    """Legacy column scan used by tests and legacy fallback."""
    if consumer_root is None or not consumer_root.exists():
        return {
            "version": CONSUMER_SCHEMA_VERSION,
            "status": "fallback",
            "consumer_root": "",
            "columns": [],
            "script_columns": [],
            "sample_columns": [],
            "result_columns": [],
            "sample_values": {},
            "warnings": ["csv consumer root not found"],
        }

    script_columns, locations = _extract_get_column_index_columns(consumer_root)
    sample_path = _find_sample_csv(consumer_root)
    sample_columns, sample_values = _read_sample_csv(sample_path) if sample_path else ([], {})
    aliases = {
        "Drop_Out_Possibility": ["keep_prob"],
        "Input_Layout": ["Layout"],
        "Atten_mask_shape": ["Atten_mask_layout"],
        "PSE_shape": ["PSE_layout"],
    }
    alias_to_canonical = {alias: canonical for canonical, values in aliases.items() for alias in values}
    columns = list(sample_columns)
    for column in script_columns:
        canonical = alias_to_canonical.get(column)
        if canonical and canonical in columns:
            continue
        if column not in columns:
            columns.append(column)
    result_columns = [column for column in columns if column.startswith(RESULT_PREFIX)]
    return {
        "version": CONSUMER_SCHEMA_VERSION,
        "status": "ok",
        "consumer_root": consumer_root.as_posix(),
        "schema_source": ["scan_get_column_index", sample_path.as_posix() if sample_path else ""],
        "columns": columns,
        "script_columns": script_columns,
        "sample_columns": sample_columns,
        "result_columns": result_columns,
        "column_locations": locations,
        "sample_values": sample_values,
        "aliases": aliases,
        "warnings": [],
    }


def build_consumer_schema_from_evidence(evidence: dict[str, Any], consumer_root: Path) -> dict[str, Any]:
    """Build versioned consumer_schema with fields from script/sample evidence (no hardcoded header list)."""
    columns = _ordered_columns_from_evidence(evidence)
    sample_values = dict(evidence.get("sample_values") or {})
    field_accesses = evidence.get("field_accesses") or {}
    required_optional = evidence.get("required_optional_evidence") or {}
    type_evidence = evidence.get("type_conversion_evidence") or {}
    fields: list[dict[str, Any]] = []
    for order, column in enumerate(columns):
        role, value_type, domain, default, serializer = _infer_field(column, sample_values, type_evidence)
        required = _is_required(column, role, required_optional, field_accesses)
        source_refs = _source_refs_for_column(column, evidence)
        fields.append(
            {
                "name": column,
                "order": order,
                "required": required,
                "role": role,
                "value_type": value_type,
                "domain": domain,
                "default": default,
                "serializer": serializer,
                "aliases": [],
                "source_refs": source_refs,
                "confidence": "high" if source_refs else "medium",
                "rationale": f"bootstrap from evidence for column {column}",
            }
        )
    result_columns = [column for column in columns if column.startswith(RESULT_PREFIX)]
    return {
        "version": CONSUMER_SCHEMA_VERSION,
        "status": "bootstrap",
        "consumer_root": consumer_root.as_posix(),
        "schema_source": ["consumer_evidence"],
        "columns": columns,
        "result_columns": result_columns,
        "sample_values": sample_values,
        "fields": fields,
        "warnings": list(evidence.get("warnings") or []),
    }


def _ordered_columns_from_evidence(evidence: dict[str, Any]) -> list[str]:
    columns: list[str] = []
    for item in evidence.get("ordered_header_candidates") or []:
        if not isinstance(item, dict):
            continue
        for column in item.get("columns") or []:
            name = str(column)
            if name and name not in columns:
                columns.append(name)
    for column in sorted((evidence.get("field_accesses") or {}).keys()):
        if column not in columns:
            columns.append(column)
    for column in sorted((evidence.get("sample_values") or {}).keys()):
        if column not in columns:
            columns.append(column)
    return columns


def _infer_field(
    column: str,
    sample_values: dict[str, list[Any]],
    type_evidence: dict[str, list[dict[str, Any]]],
) -> tuple[str, str, Any, Any, str]:
    if column in CASE_ID_COLUMNS:
        return "case_id", "string", ["*"], "", "string"
    if column.startswith(RESULT_PREFIX):
        return "expected_result", "string", [], "", "string"
    if column in CONSTANT_DEFAULTS:
        return "constant", "string", [CONSTANT_DEFAULTS[column]], CONSTANT_DEFAULTS[column], "string"

    samples = list(sample_values.get(column) or [])
    casts = {str(item.get("kind") or "") for item in type_evidence.get(column) or []}
    if column in FLOAT_AS_INT_HINTS or "cast:int" in casts and column in FLOAT_AS_INT_HINTS:
        return "solver_input", "int", {"values": [0, 1]}, 1, "string"
    if column in INT_HINT_COLUMNS or "cast:int" in casts:
        ints = [_parse_int(value) for value in samples]
        ints = [value for value in ints if value is not None]
        if not ints:
            ints = [0, 1, 2, 4, 8, 16, 32, 64, 128, 256]
        domain_vals = sorted(dict.fromkeys(ints))
        return "solver_input", "int", {"values": domain_vals}, domain_vals[0], "string"
    if "cast:bool" in casts or column in {"is_deter"}:
        domain = ["true", "false"]
        return "solver_input", "enum", domain, domain[0], "string"

    # list-like columns → emit_derived (filled from model / emit templates)
    if "seqlens" in column.lower() or column.startswith("cu_"):
        return "emit_derived", "list_int", [], [], "list_string"
    if column in {"prefix"}:
        return "constant", "string", [""], "", "string"

    clean = [str(value) for value in samples if str(value) != ""]
    if not clean:
        # Still a free solver input so SMT can choose; domain is a placeholder until LLM/samples refine.
        clean = ["_"]
        return "solver_input", "enum", clean, clean[0], "string"
    return "solver_input", "enum", sorted(dict.fromkeys(clean)), clean[0], "string"


def _is_required(column: str, role: str, required_optional: dict[str, Any], field_accesses: dict[str, Any]) -> bool:
    if role in {"case_id", "constant", "solver_input"}:
        return True
    if role == "expected_result":
        return False
    refs = required_optional.get(column) or field_accesses.get(column) or []
    return any(str(item.get("kind") or "").startswith("required") for item in refs)


def _source_refs_for_column(column: str, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in (evidence.get("field_accesses") or {}).get(column) or []:
        if isinstance(item, dict):
            refs.append({"path": item.get("path"), "line": item.get("line"), "kind": item.get("kind")})
    for item in evidence.get("ordered_header_candidates") or []:
        if not isinstance(item, dict):
            continue
        if column in (item.get("columns") or []):
            refs.append({"path": item.get("path"), "reason": item.get("reason")})
    if column in (evidence.get("sample_values") or {}):
        refs.append({"path": "sample_values", "column": column})
    if not refs:
        refs.append({"path": "consumer_evidence", "column": column, "reason": "inferred_column"})
    return refs


def _find_sample_csv(root: Path) -> Path | None:
    preferred = root / DEFAULT_SAMPLE_CSV
    if preferred.exists():
        return preferred
    csv_files = sorted(root.rglob("*.csv"))
    return csv_files[0] if csv_files else None


def _extract_get_column_index_columns(root: Path) -> tuple[list[str], list[dict[str, Any]]]:
    columns: list[str] = []
    locations: list[dict[str, Any]] = []
    search_roots = [root / "fag_test", root]
    seen_files: set[Path] = set()
    for base in search_roots:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if path in seen_files:
                continue
            seen_files.add(path)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if name != "get_column_index" or len(node.args) < 2:
                    continue
                arg = node.args[1]
                if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                    continue
                column = arg.value
                if column not in columns:
                    columns.append(column)
                locations.append(
                    {
                        "column": column,
                        "file": path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix(),
                        "line": node.lineno,
                    }
                )
    return columns, locations


def _read_sample_csv(path: Path) -> tuple[list[str], dict[str, list[Any]]]:
    if not path.exists():
        return [], {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = list(reader.fieldnames or [])
        values: dict[str, list[Any]] = {column: [] for column in columns}
        for row_idx, row in enumerate(reader):
            if row_idx >= 200:
                break
            for column in columns:
                value = row.get(column)
                if value in (None, ""):
                    continue
                bucket = values.setdefault(column, [])
                if value not in bucket:
                    bucket.append(value)
        return columns, values


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None
