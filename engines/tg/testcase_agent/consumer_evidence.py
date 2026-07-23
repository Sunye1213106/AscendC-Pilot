"""Consumer evidence from scripts/docs — NOT from sample csv/xls data files.

Value domains come from UO domain_entries, SAFE_CAPS, and LLM/human domain_hints.
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

from .hashing import stable_hash
from .io import read_json, read_yaml, write_yaml
from .csv_domain_cover import normalize_column_name

MAX_SCAN_FILES = 64
MAX_FILE_BYTES = 256 * 1024
MAX_SAMPLE_ROWS = 32
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
        out_root=out_root,
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
            "sample_int_ranges": evidence.get("sample_int_ranges"),
            "domain_hints": evidence.get("domain_hints"),
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
    out_root: Path | None = None,
) -> dict[str, Any]:
    root = consumer_root.resolve() if consumer_root and consumer_root.exists() else None
    files_read: list[dict[str, Any]] = []
    ordered_header_candidates: list[dict[str, Any]] = []
    field_accesses: dict[str, list[dict[str, Any]]] = {}
    # Intentionally empty — do not scrape sample csv/xls for domains.
    sample_values: dict[str, list[Any]] = {}
    sample_int_ranges: dict[str, dict[str, int]] = {}
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
            if path.suffix.lower() == ".py":
                script_info = _scan_python_columns(text, rel)
                for item in script_info["ordered_header_candidates"]:
                    # Normalize Layout → Input_Layout in discovered headers.
                    cols = [normalize_column_name(str(c)) for c in (item.get("columns") or [])]
                    ordered_header_candidates.append({**item, "columns": cols})
                for column, refs in script_info["field_accesses"].items():
                    field_accesses.setdefault(normalize_column_name(column), []).extend(refs)
                for column, refs in script_info["required_optional_evidence"].items():
                    required_optional_evidence.setdefault(normalize_column_name(column), []).extend(refs)
                for column, refs in script_info["type_conversion_evidence"].items():
                    type_conversion_evidence.setdefault(normalize_column_name(column), []).extend(refs)
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

    domain_hints = load_domain_hints(out_root) if out_root else {}
    if domain_hints:
        warnings.append(
            f"domain_hints loaded: {len(domain_hints.get('columns') or {})} columns "
            f"(source={domain_hints.get('source') or 'unknown'})"
        )
    else:
        warnings.append(
            "domain_hints_missing: write realization/domain_hints.yaml (LLM estimate or human confirm) "
            "when UO domain_entries / SAFE_CAPS are insufficient — sample csv/xls are NOT scanned"
        )

    # Apply human/LLM hint values into sample_values for downstream schema merge.
    for column, hint in (domain_hints.get("columns") or {}).items():
        if not isinstance(hint, dict):
            continue
        canon = normalize_column_name(str(column))
        values = hint.get("values") or hint.get("domain") or []
        if isinstance(values, dict):
            if values.get("values") is not None:
                values = values.get("values") or []
            elif values.get("min") is not None and values.get("max") is not None:
                sample_int_ranges[canon] = {
                    "min": int(values["min"]),
                    "max": int(values["max"]),
                }
                continue
        if isinstance(values, list) and values:
            bucket = sample_values.setdefault(canon, [])
            for value in values:
                if value not in bucket:
                    bucket.append(value)
        if hint.get("min") is not None and hint.get("max") is not None:
            sample_int_ranges[canon] = {"min": int(hint["min"]), "max": int(hint["max"])}

    return {
        "version": 1,
        "consumer_root": root.as_posix() if root else "",
        "files_read": files_read,
        "ordered_header_candidates": _dedupe_headers(ordered_header_candidates),
        "field_accesses": {key: value for key, value in sorted(field_accesses.items())},
        "sample_values": {key: value for key, value in sorted(sample_values.items())},
        "sample_values_preview": {key: value[:32] for key, value in sorted(sample_values.items())},
        "sample_int_ranges": {key: sample_int_ranges[key] for key in sorted(sample_int_ranges)},
        "domain_hints": domain_hints,
        "type_conversion_evidence": {key: value for key, value in sorted(type_conversion_evidence.items())},
        "required_optional_evidence": {key: value for key, value in sorted(required_optional_evidence.items())},
        "test_requirement_refs": test_requirement_refs[:MAX_SCAN_FILES],
        "warnings": warnings,
    }


def load_domain_hints(out_root: Path | None) -> dict[str, Any]:
    """Load LLM/human domain hints from realization/domain_hints.yaml or plan/human_supplement.yaml."""
    if out_root is None:
        return {}
    from .io import read_yaml

    for rel in (
        Path("realization") / "domain_hints.yaml",
        Path("plan") / "domain_hints.yaml",
        Path("plan") / "human_supplement.yaml",
    ):
        path = out_root / rel
        if not path.is_file():
            continue
        doc = read_yaml(path)
        if not isinstance(doc, dict):
            continue
        # human_supplement may nest under domain_hints
        if "columns" in doc:
            return {
                "source": str(doc.get("source") or rel.as_posix()),
                "columns": dict(doc.get("columns") or {}),
                "path": path.as_posix(),
            }
        nested = doc.get("domain_hints")
        if isinstance(nested, dict) and nested.get("columns"):
            return {
                "source": str(nested.get("source") or f"{rel.as_posix()}#domain_hints"),
                "columns": dict(nested.get("columns") or {}),
                "path": path.as_posix(),
            }
    return {}


def propose_domain_hints_stub(
    columns: list[str],
    *,
    uo_entries: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    """Stub for LLM/human: pre-fill known UO entries; leave gaps for confirm."""
    columns_doc: dict[str, Any] = {}
    for col in columns:
        entries = (uo_entries or {}).get(col)
        if entries:
            columns_doc[col] = {
                "values": list(entries),
                "source": "uo_domain_entries",
                "status": "proposed",
            }
        else:
            columns_doc[col] = {
                "values": [],
                "min": None,
                "max": None,
                "source": "needs_llm_or_human",
                "status": "pending",
            }
    return {
        "version": 1,
        "source": "domain_hints_stub",
        "columns": columns_doc,
        "hint": (
            "Fill values/min/max via LLM estimate or human confirm, then re-run harness contract_build. "
            "Sample csv/xls are intentionally not scanned."
        ),
    }


def _hint_is_confirmed(hint: dict[str, Any] | None) -> bool:
    if not isinstance(hint, dict):
        return False
    status = str(hint.get("status") or "").lower()
    source = str(hint.get("source") or "").lower()
    return (
        hint.get("locked") is True
        or status in {"confirmed", "human", "final", "locked", "llm_confirmed"}
        or source in {"human", "llm_confirmed"}
    )


def merge_domain_hints_preserving_confirmed(
    existing: dict[str, Any] | None,
    stub: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge stub columns into existing hints without overwriting locked/confirmed entries."""
    existing = existing if isinstance(existing, dict) else {}
    stub = stub if isinstance(stub, dict) else {}
    out_cols: dict[str, Any] = {}
    stub_cols = dict(stub.get("columns") or {}) if isinstance(stub.get("columns"), dict) else {}
    existing_cols = dict(existing.get("columns") or {}) if isinstance(existing.get("columns"), dict) else {}

    for name, hint in stub_cols.items():
        prev = existing_cols.get(name)
        if isinstance(prev, dict) and _hint_is_confirmed(prev):
            out_cols[name] = dict(prev)
        elif isinstance(prev, dict) and prev.get("values"):
            # Keep non-empty prior proposals; fill only brand-new columns from stub.
            merged = dict(hint) if isinstance(hint, dict) else {}
            merged.update({k: v for k, v in prev.items() if v not in (None, "", [], {})})
            if _hint_is_confirmed(prev):
                merged["status"] = prev.get("status")
                if prev.get("locked") is True:
                    merged["locked"] = True
            out_cols[name] = merged
        else:
            out_cols[name] = dict(hint) if isinstance(hint, dict) else hint

    for name, hint in existing_cols.items():
        if name not in out_cols:
            out_cols[name] = dict(hint) if isinstance(hint, dict) else hint

    return {
        "version": int(existing.get("version") or stub.get("version") or 1),
        "source": str(existing.get("source") or stub.get("source") or "merged_domain_hints"),
        "columns": out_cols,
        "hint": existing.get("hint") or stub.get("hint") or "",
    }


def _bounded_scan(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(paths) >= MAX_SCAN_FILES:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
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
            # Skip load_dict[...] Store targets — structural dict keys, not CSV columns.
            if isinstance(getattr(node, "ctx", None), ast.Store) and _is_load_dict_base(node.value):
                continue
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


def _is_load_dict_base(node: ast.AST) -> bool:
    """True for load_dict / *.load_dict bases used as structural bags (not CSV)."""
    name = _call_name(node).lower()
    return name == "load_dict" or name.endswith(".load_dict") or name.endswith("load_dict")


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
