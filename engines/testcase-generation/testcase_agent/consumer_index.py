"""Shared consumer repository index for TG contract / binding / evidence."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TEXT_EXTENSIONS = {".py", ".md", ".markdown", ".yaml", ".yml", ".json", ".txt"}
MAX_SCAN_FILES = 64
MAX_FILE_BYTES = 256 * 1024


@dataclass
class ConsumerIndex:
    consumer_root: str
    files: list[dict[str, Any]] = field(default_factory=list)
    text_cache: dict[str, str] = field(default_factory=dict)
    ast_cache: dict[str, Any] = field(default_factory=dict)
    header_candidates: list[dict[str, Any]] = field(default_factory=list)
    field_accesses: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    type_conversions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    api_calls: list[dict[str, Any]] = field(default_factory=list)
    source_read_count: int = 0
    ast_parse_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "consumer_root": self.consumer_root,
            "files": self.files,
            "text_cache": self.text_cache,
            "ast_cache": {k: "cached" for k in self.ast_cache},
            "header_candidates": self.header_candidates,
            "field_accesses": self.field_accesses,
            "type_conversions": self.type_conversions,
            "api_calls": self.api_calls,
            "source_read_count": self.source_read_count,
            "ast_parse_count": self.ast_parse_count,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConsumerIndex:
        return cls(
            consumer_root=str(payload.get("consumer_root") or ""),
            files=list(payload.get("files") or []),
            text_cache=dict(payload.get("text_cache") or {}),
            ast_cache={},
            header_candidates=list(payload.get("header_candidates") or []),
            field_accesses=dict(payload.get("field_accesses") or {}),
            type_conversions=dict(payload.get("type_conversions") or {}),
            api_calls=list(payload.get("api_calls") or []),
            source_read_count=int(payload.get("source_read_count") or 0),
            ast_parse_count=int(payload.get("ast_parse_count") or 0),
        )


def index_path(out_root: Path) -> Path:
    return out_root / "realization" / "consumer_index.json"


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


def _fingerprint_files(root: Path, paths: list[Path]) -> str:
    rows = []
    for path in paths:
        rel = path.relative_to(root).as_posix()
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append((rel, digest, path.stat().st_size))
        except OSError:
            rows.append((rel, "", -1))
    payload = json.dumps(rows, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_or_build_consumer_index(
    out_root: Path,
    consumer_root: Path | None,
    *,
    force_rebuild: bool = False,
) -> ConsumerIndex:
    """Load cached consumer index or build it once."""
    path = index_path(out_root)
    root = consumer_root.resolve() if consumer_root and consumer_root.exists() else None
    if root is None:
        return ConsumerIndex(consumer_root="")

    scan_paths = _bounded_scan(root)
    fp = _fingerprint_files(root, scan_paths)
    if not force_rebuild and path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("fingerprint") == fp:
                idx = ConsumerIndex.from_dict(cached)
                idx.ast_cache = {}
                idx.source_read_count = 0
                idx.ast_parse_count = 0
                return idx
        except (OSError, json.JSONDecodeError):
            pass

    from .consumer_evidence import _scan_python_columns, _scan_requirement_refs
    from .csv_domain_cover import normalize_column_name

    idx = ConsumerIndex(consumer_root=str(root))
    for file_path in scan_paths:
        rel = file_path.relative_to(root).as_posix()
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        idx.source_read_count += 1
        idx.text_cache[rel] = text
        idx.files.append(
            {
                "path": rel,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "size": file_path.stat().st_size,
            }
        )
        if file_path.suffix.lower() == ".py":
            try:
                idx.ast_cache[rel] = ast.parse(text)
                idx.ast_parse_count += 1
            except SyntaxError:
                idx.ast_cache[rel] = None
            script_info = _scan_python_columns(text, rel)
            for item in script_info["ordered_header_candidates"]:
                cols = [normalize_column_name(str(c)) for c in (item.get("columns") or [])]
                idx.header_candidates.append({**item, "columns": cols})
            for column, refs in script_info["field_accesses"].items():
                key = normalize_column_name(column)
                idx.field_accesses.setdefault(key, []).extend(refs)
            for column, refs in script_info.get("type_conversion_evidence", {}).items():
                key = normalize_column_name(column)
                idx.type_conversions.setdefault(key, []).extend(refs)
            for column, refs in script_info.get("required_optional_evidence", {}).items():
                key = normalize_column_name(column)
                idx.field_accesses.setdefault(key, []).extend(refs)
        elif file_path.suffix.lower() in {".md", ".markdown", ".yaml", ".yml", ".json"}:
            idx.api_calls.extend(_scan_requirement_refs(text, rel))

    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = idx.to_dict()
    serializable["fingerprint"] = fp
    path.write_text(json.dumps(serializable, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return idx
