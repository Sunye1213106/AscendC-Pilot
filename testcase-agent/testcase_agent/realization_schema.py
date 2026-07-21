from __future__ import annotations

import ast
import csv
import os
from pathlib import Path
from typing import Any

from .realization_contract import CONSUMER_SCHEMA_VERSION
from .domain_policy import (
    classify_column_role,
    expand_enum_domain,
    fold_shape_layout_columns,
    hint_values_take_priority,
    is_discrete_int_column,
    is_drop_rate_column,
    is_probability_column,
    is_shape_int_column,
    is_switch_int_column,
    is_tensor_placeholder_domain,
    merge_discrete_int_domain,
    OPTIONAL_ABSENT,
    parse_int,
    probability_domain_values,
    sanitize_domain_values,
    shape_range_domain,
)
from .csv_domain_cover import extract_uo_domain_entries_by_column, normalize_column_name


# Metadata / identity columns that are not free SMT variables by default.
CASE_ID_COLUMNS = {"Testcase_Name", "testcase_name", "Case_Name"}
CONSTANT_DEFAULTS = {"Enable": "Enable"}
RESULT_PREFIX = "Actual_"


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
    """Resolve consumer root. Only explicit path or TG_CSV_CONSUMER_ROOT (no silent FAG discovery)."""
    _ = project_root
    if explicit_root:
        root = explicit_root.resolve()
        return root if root.exists() else None
    env = os.environ.get("TG_CSV_CONSUMER_ROOT")
    if env:
        root = Path(env).resolve()
        if root.exists():
            return root
    return None


def extract_consumer_schema(consumer_root: Path | None) -> dict[str, Any]:
    """Legacy column scan used by tests. No hardcoded column aliases or FASG filenames."""
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
    columns = list(sample_columns)
    for column in script_columns:
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
        "aliases": {},
        "warnings": [],
    }


def build_consumer_schema_from_evidence(
    evidence: dict[str, Any],
    consumer_root: Path,
    *,
    key_space: dict[str, Any] | None = None,
    snapshot_files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build consumer_schema from scripts + UO/domain_hints (not sample csv/xls)."""
    raw_columns = [normalize_column_name(c) for c in _ordered_columns_from_evidence(evidence)]
    raw_columns = list(dict.fromkeys(raw_columns))
    columns, layout_aliases = fold_shape_layout_columns(raw_columns)
    sample_values = dict(evidence.get("sample_values") or {})
    sample_int_ranges = dict(evidence.get("sample_int_ranges") or {})
    domain_hints = dict((evidence.get("domain_hints") or {}).get("columns") or {})
    field_accesses = evidence.get("field_accesses") or {}
    required_optional = evidence.get("required_optional_evidence") or {}
    type_evidence = evidence.get("type_conversion_evidence") or {}
    evidence_tokens = [
        str(item.get("token") or "")
        for item in (evidence.get("test_requirement_refs") or [])
        if isinstance(item, dict) and item.get("token")
    ]
    uo_entries = extract_uo_domain_entries_by_column(snapshot_files or {}, columns)
    optional_names = {
        str(item.get("name") or "")
        for item in ((snapshot_files or {}).get("contracts/testcase.yaml", {}) or {}).get("interface", {}).get("optional_inputs", [])
        if isinstance(item, dict) and item.get("name")
    }
    fields: list[dict[str, Any]] = []
    for order, column in enumerate(columns):
        hint = domain_hints.get(column) if isinstance(domain_hints.get(column), dict) else {}
        role, value_type, domain, default, serializer = _infer_field(
            column,
            sample_values,
            type_evidence,
            int_range=sample_int_ranges.get(column),
            key_space=key_space,
            evidence_tokens=evidence_tokens,
            uo_values=uo_entries.get(column),
            hint=hint,
            optional_names=optional_names,
        )
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
                "aliases": [alias for alias, canon in layout_aliases.items() if canon == column],
                "source_refs": source_refs,
                "confidence": "high" if source_refs or uo_entries.get(column) or hint else "medium",
                "rationale": f"domain from UO/hints/SAFE_CAPS for column {column}",
            }
        )
    result_columns = [column for column in columns if column.startswith(RESULT_PREFIX)]
    return {
        "version": CONSUMER_SCHEMA_VERSION,
        "status": "bootstrap",
        "consumer_root": consumer_root.as_posix(),
        "schema_source": ["consumer_evidence", "uo_domain_entries", "domain_hints"],
        "columns": columns,
        "layout_aliases": layout_aliases,
        "result_columns": result_columns,
        "sample_values": sample_values,
        "sample_int_ranges": sample_int_ranges,
        "uo_domain_entries": uo_entries,
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
    *,
    int_range: dict[str, Any] | None = None,
    key_space: dict[str, Any] | None = None,
    evidence_tokens: list[str] | None = None,
    uo_values: list[Any] | None = None,
    hint: dict[str, Any] | None = None,
    optional_names: set[str] | None = None,
) -> tuple[str, str, Any, Any, str]:
    if column in CASE_ID_COLUMNS:
        return "case_id", "string", ["*"], "", "string"
    if column.startswith(RESULT_PREFIX):
        return "expected_result", "string", [], "", "string"
    if column in CONSTANT_DEFAULTS:
        return "constant", "string", [CONSTANT_DEFAULTS[column]], CONSTANT_DEFAULTS[column], "string"

    samples = list(sample_values.get(column) or [])
    hint = hint or {}
    hint_values = list(hint.get("values") or [])
    # Confirmed/locked hints win over CaseConfig/sample inference on contract rebuild.
    if hint_values_take_priority(hint):
        return _field_from_confirmed_hint(column, hint, hint_values)
    role_hint = classify_column_role(column, samples=samples, uo_values=uo_values, optional_names=optional_names)
    casts = {str(item.get("kind") or "") for item in type_evidence.get(column) or []}
    if "cast:bool" in casts or column.lower() in {"is_deter"}:
        domain = ["true", "false"]
        return "solver_input", "enum", domain, domain[0], "string"

    if "seqlens" in column.lower() or column.startswith("cu_"):
        return "emit_derived", "list_int", [], [], "list_string"
    if column in {"prefix"}:
        return "constant", "string", [""], "", "string"

    looks_int = (
        "cast:int" in casts
        or _samples_look_int(samples)
        or _samples_look_int(hint_values)
        or _samples_look_int(uo_values or [])
        or is_shape_int_column(column)
        or is_discrete_int_column(column)
    )
    if is_switch_int_column(column):
        return "solver_input", "int", {"values": [0, 1]}, 0, "string"
    if is_probability_column(column) or role_hint == "probability":
        vals = probability_domain_values(samples, hint_values, column=column)
        return "solver_input", "enum", {"values": vals}, vals[0], "string"
    if role_hint == "tensor_placeholder":
        return "tensor_placeholder", "string", [""], "", "string"
    if role_hint == "optional_presence":
        clean = expand_enum_domain(
            column,
            samples,
            evidence_tokens=evidence_tokens,
            hint_values=[*(uo_values or []), *hint_values],
            hint=hint,
        )
        clean = sanitize_domain_values(clean, allow_none=True)
        if not clean:
            clean = [OPTIONAL_ABSENT]
        return "solver_input", "enum", clean, clean[0], "string"
    # Shape ranges take precedence over any accidental UO discrete match.
    if is_shape_int_column(column):
        ints = [v for v in (parse_int(value) for value in [*samples, *hint_values]) if v is not None]
        domain = shape_range_domain(
            column,
            sample_ints=ints,
            int_range=int_range,
            key_space=key_space,
            hint_domain=hint if hint.get("min") is not None or hint.get("max") is not None else None,
        )
        return "solver_input", "int", domain, _shape_default(domain), "string"
    if is_discrete_int_column(column) or (uo_values and all(parse_int(v) is not None for v in uo_values)):
        domain_vals = merge_discrete_int_domain(samples, uo_values, hint_values, hint=hint)
        return "solver_input", "int", {"values": domain_vals}, domain_vals[0], "string"
    if looks_int and _prefer_range(samples, int_range, hint):
        ints = [v for v in (parse_int(value) for value in [*samples, *hint_values]) if v is not None]
        domain = shape_range_domain(
            column,
            sample_ints=ints,
            int_range=int_range,
            key_space=key_space,
            hint_domain=hint if hint.get("min") is not None or hint.get("max") is not None else None,
        )
        return "solver_input", "int", domain, _shape_default(domain), "string"
    if looks_int:
        ints = merge_discrete_int_domain(samples, uo_values, hint_values, hint=hint)
        return "solver_input", "int", {"values": ints}, ints[0], "string"

    clean = expand_enum_domain(
        column,
        samples,
        evidence_tokens=evidence_tokens,
        hint_values=[*(uo_values or []), *hint_values],
        hint=hint,
    )
    clean = sanitize_domain_values(clean, allow_none=True)
    if role_hint == "layout_secondary" and not clean:
        # Thin secondary layout should have been folded; if not, leave NONE for review.
        clean = [OPTIONAL_ABSENT]
        return "solver_input", "enum", clean, clean[0], "string"
    if not clean:
        clean = [OPTIONAL_ABSENT]
        return "solver_input", "enum", clean, clean[0], "string"
    return "solver_input", "enum", clean, clean[0], "string"


def _field_from_confirmed_hint(
    column: str,
    hint: dict[str, Any],
    hint_values: list[Any],
) -> tuple[str, str, Any, Any, str]:
    """Exclusive domain from locked/confirmed domain_hints — do not re-infer float/_."""
    if hint.get("min") is not None or hint.get("max") is not None:
        lo = int(hint["min"]) if hint.get("min") is not None else 0
        hi = int(hint["max"]) if hint.get("max") is not None else lo
        if hi < lo:
            hi = lo
        domain = {"kind": "range", "min": lo, "max": hi}
        return "solver_input", "int", domain, _shape_default(domain), "string"
    if is_probability_column(column):
        vals = probability_domain_values(None, hint_values, column=column) or (
            [0.0, 0.1, 0.2, 1.0] if is_drop_rate_column(column) else [0.5, 0.8, 0.9, 1.0]
        )
        return "solver_input", "enum", {"values": vals}, vals[0], "string"
    ints = [parse_int(v) for v in hint_values]
    if hint_values and all(v is not None for v in ints):
        domain_vals = list(dict.fromkeys(int(v) for v in ints if v is not None))
        return "solver_input", "int", {"values": domain_vals}, domain_vals[0], "string"
    clean = sanitize_domain_values([str(v) for v in hint_values if str(v) != ""], allow_none=True)
    if not clean:
        clean = [OPTIONAL_ABSENT]
    return "solver_input", "enum", clean, clean[0], "string"


def _shape_default(domain: dict[str, Any]) -> int:
    """Prefer a mid/safe anchor over min=1 so free solves do not collapse to all-ones."""
    lo = int(domain.get("min", 1))
    hi = int(domain.get("max", lo))
    for anchor in (16, 32, 64, 8, 4, 2):
        if lo <= anchor <= hi:
            return anchor
    if hi > lo:
        return lo + max(1, (hi - lo) // 4)
    return lo


def _prefer_range(
    samples: list[Any],
    int_range: dict[str, Any] | None,
    hint: dict[str, Any] | None = None,
) -> bool:
    """Use range for shape-like spans; hints with min/max also force range."""
    if isinstance(hint, dict) and hint.get("min") is not None and hint.get("max") is not None:
        return True
    ints = [v for v in (parse_int(value) for value in samples) if v is not None]
    if int_range:
        lo = parse_int(int_range.get("min"))
        hi = parse_int(int_range.get("max"))
        if lo is not None and hi is not None and hi - lo >= 2:
            return True
    if not ints:
        # Shape columns without samples still get SAFE_CAPS ranges.
        return True
    return max(ints) - min(ints) >= 2 or max(ints) >= 8


def _samples_look_int(samples: list[Any]) -> bool:
    if not samples:
        return False
    parsed = [parse_int(value) for value in samples]
    return all(value is not None for value in parsed)


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
    """Prefer any CSV under data/, else first CSV under consumer root (no FASG filename hardcode)."""
    data_dir = root / "data"
    if data_dir.is_dir():
        data_csvs = sorted(data_dir.glob("*.csv"))
        if data_csvs:
            return data_csvs[0]
    csv_files = sorted(root.rglob("*.csv"))
    return csv_files[0] if csv_files else None


def _extract_get_column_index_columns(root: Path) -> tuple[list[str], list[dict[str, Any]]]:
    columns: list[str] = []
    locations: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.py")):
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
    return parse_int(value)