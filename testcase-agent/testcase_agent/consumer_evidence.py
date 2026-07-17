from __future__ import annotations

import ast
import csv
import hashlib
import re
from pathlib import Path
from typing import Any

from .hashing import stable_hash
from .io import read_json, read_yaml, write_yaml

MAX_SCAN_FILES = 64
MAX_FILE_BYTES = 256 * 1024
MAX_SAMPLE_ROWS = 32
CSV_EXTENSIONS = {".csv"}
TEXT_EXTENSIONS = {".py", ".md", ".markdown", ".yaml", ".yml", ".json", ".txt"}


def prepare_consumer_evidence(
    out_root: Path,
    *,
    consumer_root: Path | None,
    snapshot_path: Path,
    obligations_path: Path,
) -> dict[str, Any]:
    snapshot = read_json(snapshot_path)
    obligations_doc = read_yaml(obligations_path)
    snapshot_hash = str(snapshot.get("snapshot_hash") or "")
    plan_hash = str(obligations_doc.get("plan_hash") or "")
    evidence = build_consumer_evidence(
        consumer_root,
        snapshot=snapshot,
        obligations_doc=obligations_doc,
    )
    evidence["snapshot_hash"] = snapshot_hash
    evidence["plan_hash"] = plan_hash
    evidence["evidence_hash"] = stable_hash(
        {
            "consumer_root": evidence.get("consumer_root"),
            "files_read": evidence.get("files_read"),
            "ordered_header_candidates": evidence.get("ordered_header_candidates"),
            "field_accesses": evidence.get("field_accesses"),
            "sample_values": evidence.get("sample_values"),
            "type_conversion_evidence": evidence.get("type_conversion_evidence"),
            "required_optional_evidence": evidence.get("required_optional_evidence"),
            "test_requirement_refs": evidence.get("test_requirement_refs"),
            "snapshot_hash": snapshot_hash,
            "plan_hash": plan_hash,
        }
    )
    write_yaml(out_root / "realization" / "consumer_evidence.yaml", evidence)
    return evidence


def build_consumer_evidence(
    consumer_root: Path | None,
    *,
    snapshot: dict[str, Any],
    obligations_doc: dict[str, Any],
) -> dict[str, Any]:
    root = consumer_root.resolve() if consumer_root and consumer_root.exists() else None
    files_read: list[dict[str, Any]] = []
    ordered_header_candidates: list[dict[str, Any]] = []
    field_accesses: dict[str, list[dict[str, Any]]] = {}
    sample_values: dict[str, list[Any]] = {}
    type_conversion_evidence: dict[str, list[dict[str, Any]]] = {}
    required_optional_evidence: dict[str, list[dict[str, Any]]] = {}
    test_requirement_refs: list[dict[str, Any]] = []
    warnings: list[str] = []

    if root is None:
        warnings.append("csv consumer root not found")
    else:
        for path in _bounded_scan(root):
            rel = path.relative_to(root).as_posix()
            text = _safe_read_text(path)
            files_read.append(
                {
                    "path": rel,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size": path.stat().st_size,
                }
            )
            if path.suffix.lower() in CSV_EXTENSIONS:
                header, samples = _read_sample_csv(path)
                if header:
                    ordered_header_candidates.append(
                        {
                            "path": rel,
                            "reason": "sample_csv",
                            "columns": header,
                        }
                    )
                    for column, values in samples.items():
                        bucket = sample_values.setdefault(column, [])
                        for value in values:
                            if value not in bucket:
                                bucket.append(value)
            elif path.suffix.lower() == ".py":
                script_info = _scan_python_columns(text, rel)
                for item in script_info["ordered_header_candidates"]:
                    ordered_header_candidates.append(item)
                for column, refs in script_info["field_accesses"].items():
                    field_accesses.setdefault(column, []).extend(refs)
                for column, refs in script_info["required_optional_evidence"].items():
                    required_optional_evidence.setdefault(column, []).extend(refs)
                for column, refs in script_info["type_conversion_evidence"].items():
                    type_conversion_evidence.setdefault(column, []).extend(refs)
            elif path.suffix.lower() in {".md", ".markdown", ".yaml", ".yml", ".json"}:
                refs = _scan_requirement_refs(text, rel)
                test_requirement_refs.extend(refs)

    for obligation in obligations_doc.get("obligations", []) or []:
        if not isinstance(obligation, dict):
            continue
        refs = [str(ref) for ref in obligation.get("target_refs") or []]
        if refs:
            test_requirement_refs.append(
                {
                    "path": "plan/coverage_obligations.yaml",
                    "kind": str(obligation.get("kind") or ""),
                    "target_refs": refs,
                    "obligation_id": str(obligation.get("id") or ""),
                }
            )

    return {
        "version": 1,
        "consumer_root": root.as_posix() if root else "",
        "files_read": files_read,
        "ordered_header_candidates": _dedupe_headers(ordered_header_candidates),
        "field_accesses": {key: value for key, value in sorted(field_accesses.items())},
        "sample_values": {key: value[:MAX_SAMPLE_ROWS] for key, value in sorted(sample_values.items())},
        "type_conversion_evidence": {key: value for key, value in sorted(type_conversion_evidence.items())},
        "required_optional_evidence": {key: value for key, value in sorted(required_optional_evidence.items())},
        "test_requirement_refs": test_requirement_refs[:MAX_SCAN_FILES],
        "warnings": warnings,
    }


def _bounded_scan(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(paths) >= MAX_SCAN_FILES:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in CSV_EXTENSIONS | TEXT_EXTENSIONS:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        paths.append(path)
    return paths


def _scan_python_columns(text: str, rel: str) -> dict[str, Any]:
    field_accesses: dict[str, list[dict[str, Any]]] = {}
    required_optional_evidence: dict[str, list[dict[str, Any]]] = {}
    type_conversion_evidence: dict[str, list[dict[str, Any]]] = {}
    ordered_header_candidates: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {
            "field_accesses": field_accesses,
            "required_optional_evidence": required_optional_evidence,
            "type_conversion_evidence": type_conversion_evidence,
            "ordered_header_candidates": ordered_header_candidates,
        }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name.endswith("get_column_index") and len(node.args) >= 2:
                column = _str_const(node.args[1])
                if column:
                    _add_ref(field_accesses, column, rel, node.lineno, "get_column_index")
                    _add_ref(required_optional_evidence, column, rel, node.lineno, "required_read")
            if name.endswith("DictReader"):
                fieldnames = _keyword_list(node, "fieldnames")
                if fieldnames:
                    ordered_header_candidates.append({"path": rel, "reason": "csv_writer_fieldnames", "columns": fieldnames})
            if name in {"int", "str", "bool"} and node.args:
                column = _subscript_column(node.args[0])
                if column:
                    _add_ref(type_conversion_evidence, column, rel, node.lineno, f"cast:{name}")
            if name.endswith("get"):
                column = _str_const(node.args[0]) if node.args else None
                if column:
                    _add_ref(field_accesses, column, rel, node.lineno, "optional_get")
                    _add_ref(required_optional_evidence, column, rel, node.lineno, "optional_read")
        elif isinstance(node, ast.Subscript):
            column = _subscript_column(node)
            if column:
                _add_ref(field_accesses, column, rel, node.lineno, "subscript")
                _add_ref(required_optional_evidence, column, rel, node.lineno, "required_read")
        elif isinstance(node, ast.Assign):
            header = _literal_string_list(node.value)
            if header:
                ordered_header_candidates.append({"path": rel, "reason": "constant_header", "columns": header})
    return {
        "field_accesses": field_accesses,
        "required_optional_evidence": required_optional_evidence,
        "type_conversion_evidence": type_conversion_evidence,
        "ordered_header_candidates": ordered_header_candidates,
    }


def _scan_requirement_refs(text: str, rel: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for match in re.finditer(r"\b([A-Z][A-Za-z0-9_]*|Input_Layout|Dtype|Actual_[A-Za-z0-9_]+)\b", text):
        refs.append({"path": rel, "token": match.group(1), "line": text.count("\n", 0, match.start()) + 1})
        if len(refs) >= MAX_SAMPLE_ROWS:
            break
    return refs


def _read_sample_csv(path: Path) -> tuple[list[str], dict[str, list[Any]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = list(reader.fieldnames or [])
        samples: dict[str, list[Any]] = {column: [] for column in columns}
        for idx, row in enumerate(reader):
            if idx >= MAX_SAMPLE_ROWS:
                break
            for column in columns:
                value = row.get(column)
                if value in ("", None):
                    continue
                bucket = samples.setdefault(column, [])
                if value not in bucket:
                    bucket.append(value)
        return columns, samples


def _safe_read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _dedupe_headers(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = stable_hash(item.get("columns") or [])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _keyword_list(node: ast.Call, key: str) -> list[str]:
    for kw in node.keywords:
        if kw.arg == key:
            return _literal_string_list(kw.value)
    return []


def _literal_string_list(node: ast.AST) -> list[str]:
    if isinstance(node, (ast.List, ast.Tuple)):
        values = []
        for item in node.elts:
            text = _str_const(item)
            if text is None:
                return []
            values.append(text)
        return values
    return []


def _subscript_column(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Subscript):
        return None
    slice_node = node.slice
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        return slice_node.value
    return None


def _str_const(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _add_ref(bucket: dict[str, list[dict[str, Any]]], column: str, path: str, line: int, kind: str) -> None:
    bucket.setdefault(column, []).append({"path": path, "line": line, "kind": kind})
