from __future__ import annotations

import ast
import csv
import os
from pathlib import Path
from typing import Any


DEFAULT_SAMPLE_CSV = Path("data") / "FASG_PSE_cases.csv"


def discover_consumer_root(project_root: Path, explicit_root: Path | None = None) -> Path | None:
    if explicit_root:
        root = explicit_root.resolve()
        return root if root.exists() else None
    env = os.environ.get("FAG_DEBUG_TOOLS_ROOT")
    if env:
        root = Path(env).resolve()
        if root.exists():
            return root
    project_root = project_root.resolve()
    candidates: list[Path] = []
    for parent in [project_root, *project_root.parents]:
        candidates.append(parent / "fag_debug_tools")
        candidates.append(parent / "TEST" / "fag_debug_tools")
    for candidate in candidates:
        if (candidate / "fag_test").exists():
            return candidate.resolve()
    return None


def extract_consumer_schema(consumer_root: Path | None) -> dict[str, Any]:
    if consumer_root is None or not consumer_root.exists():
        return {
            "version": 1,
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
    sample_columns, sample_values = _read_sample_csv(consumer_root / DEFAULT_SAMPLE_CSV)
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
    result_columns = [column for column in columns if column.startswith("Actual_")]
    return {
        "version": 1,
        "status": "ok",
        "consumer_root": consumer_root.as_posix(),
        "schema_source": ["scan_get_column_index", DEFAULT_SAMPLE_CSV.as_posix()],
        "columns": columns,
        "script_columns": script_columns,
        "sample_columns": sample_columns,
        "result_columns": result_columns,
        "column_locations": locations,
        "sample_values": sample_values,
        "aliases": aliases,
        "warnings": [],
    }


def _extract_get_column_index_columns(root: Path) -> tuple[list[str], list[dict[str, Any]]]:
    columns: list[str] = []
    locations: list[dict[str, Any]] = []
    for path in sorted((root / "fag_test").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Name) or func.id != "get_column_index" or len(node.args) < 2:
                continue
            arg = node.args[1]
            if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                continue
            column = arg.value
            if column not in columns:
                columns.append(column)
            locations.append({"column": column, "file": path.relative_to(root).as_posix(), "line": node.lineno})
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
