"""Shared consumer repository index for TG contract / binding / evidence."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TEXT_EXTENSIONS = {".py", ".md", ".markdown", ".yaml", ".yml", ".json", ".txt"}
MAX_SCAN_FILES = 64
MAX_FILE_BYTES = 256 * 1024


def _verify_hash_enabled() -> bool:
    return os.environ.get("TG_CONSUMER_CACHE_VERIFY_HASH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass
class ConsumerIndex:
    consumer_root: str
    files: list[dict[str, Any]] = field(default_factory=list)
    text_cache: dict[str, str] = field(default_factory=dict)
    ast_cache: dict[str, Any] = field(default_factory=dict)
    header_candidates: list[dict[str, Any]] = field(default_factory=list)
    field_accesses: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    required_optional_evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    type_conversions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    api_calls: list[dict[str, Any]] = field(default_factory=list)
    bytes_read_count: int = 0
    ast_parse_count: int = 0
    stat_only_hits: int = 0
    # Back-compat aliases used by older tests / callers.
    source_read_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 2,
            "consumer_root": self.consumer_root,
            "files": self.files,
            "text_cache": self.text_cache,
            "ast_cache": {k: "cached" for k in self.ast_cache},
            "header_candidates": self.header_candidates,
            "field_accesses": self.field_accesses,
            "required_optional_evidence": self.required_optional_evidence,
            "type_conversions": self.type_conversions,
            "api_calls": self.api_calls,
            "bytes_read_count": self.bytes_read_count,
            "ast_parse_count": self.ast_parse_count,
            "stat_only_hits": self.stat_only_hits,
            "source_read_count": self.bytes_read_count,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConsumerIndex:
        bytes_read = int(payload.get("bytes_read_count") or payload.get("source_read_count") or 0)
        return cls(
            consumer_root=str(payload.get("consumer_root") or ""),
            files=list(payload.get("files") or []),
            text_cache=dict(payload.get("text_cache") or {}),
            ast_cache={},
            header_candidates=list(payload.get("header_candidates") or []),
            field_accesses=dict(payload.get("field_accesses") or {}),
            required_optional_evidence=dict(payload.get("required_optional_evidence") or {}),
            type_conversions=dict(payload.get("type_conversions") or {}),
            api_calls=list(payload.get("api_calls") or []),
            bytes_read_count=bytes_read,
            ast_parse_count=int(payload.get("ast_parse_count") or 0),
            stat_only_hits=int(payload.get("stat_only_hits") or 0),
            source_read_count=bytes_read,
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
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        paths.append(path)
    return paths


def _file_stat_row(root: Path, path: Path) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    try:
        st = path.stat()
        return {
            "path": rel,
            "size": int(st.st_size),
            "mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
            "ctime_ns": int(getattr(st, "st_ctime_ns", int(st.st_ctime * 1e9))),
        }
    except OSError:
        return {"path": rel, "size": -1, "mtime_ns": -1, "ctime_ns": -1}


def _stat_fingerprint(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        [(r.get("path"), r.get("size"), r.get("mtime_ns"), r.get("ctime_ns")) for r in rows],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stats_match_cached(
    cached_files: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    *,
    root: Path | None = None,
    verify_hash: bool = False,
) -> bool:
    if len(cached_files) != len(current_rows):
        return False
    by_path = {str(f.get("path") or ""): f for f in cached_files if isinstance(f, dict)}
    for row in current_rows:
        prev = by_path.get(str(row.get("path") or ""))
        if not prev:
            return False
        if int(prev.get("size") or -2) != int(row.get("size") or -1):
            return False
        if int(prev.get("mtime_ns") or -2) != int(row.get("mtime_ns") or -1):
            return False
        # Older caches without ctime_ns still match on size/mtime; new builds record it.
        if "ctime_ns" in prev and int(prev.get("ctime_ns") or -2) != int(row.get("ctime_ns") or -1):
            return False
        if not prev.get("sha256"):
            return False
        if verify_hash and root is not None:
            try:
                raw = (root / str(row["path"])).read_bytes()
            except OSError:
                return False
            if hashlib.sha256(raw).hexdigest() != str(prev.get("sha256") or ""):
                return False
    return True


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
    current_rows = [_file_stat_row(root, p) for p in scan_paths]
    fp = _stat_fingerprint(current_rows)

    verify_hash = _verify_hash_enabled()
    if not force_rebuild and path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (
                isinstance(cached, dict)
                and cached.get("fingerprint") == fp
                and _stats_match_cached(
                    list(cached.get("files") or []),
                    current_rows,
                    root=root,
                    verify_hash=verify_hash,
                )
            ):
                idx = ConsumerIndex.from_dict(cached)
                idx.ast_cache = {}
                # VERIFY_HASH reads bytes for integrity but is not a rebuild scan.
                idx.bytes_read_count = len(current_rows) if verify_hash else 0
                idx.source_read_count = idx.bytes_read_count
                idx.ast_parse_count = 0
                idx.stat_only_hits = 0 if verify_hash else len(current_rows)
                return idx
        except (OSError, json.JSONDecodeError):
            pass

    from .consumer_evidence import _scan_python_columns, _scan_requirement_refs
    from .csv_domain_cover import normalize_column_name

    idx = ConsumerIndex(consumer_root=str(root))
    for file_path, row in zip(scan_paths, current_rows):
        rel = str(row["path"])
        try:
            raw = file_path.read_bytes()
        except OSError:
            continue
        idx.bytes_read_count += 1
        idx.source_read_count = idx.bytes_read_count
        digest = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8", errors="ignore")
        idx.text_cache[rel] = text
        idx.files.append(
            {
                "path": rel,
                "sha256": digest,
                "size": int(row["size"]),
                "mtime_ns": int(row["mtime_ns"]),
                "ctime_ns": int(row.get("ctime_ns") or -1),
            }
        )
        if file_path.suffix.lower() == ".py":
            tree: Any = None
            try:
                tree = ast.parse(text)
                idx.ast_parse_count += 1
                idx.ast_cache[rel] = tree
            except SyntaxError:
                idx.ast_cache[rel] = None
            script_info = _scan_python_columns(text, rel, tree=tree)
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
                idx.required_optional_evidence.setdefault(key, []).extend(refs)
        elif file_path.suffix.lower() in {".md", ".markdown", ".yaml", ".yml", ".json"}:
            idx.api_calls.extend(_scan_requirement_refs(text, rel))

    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = idx.to_dict()
    serializable["fingerprint"] = fp
    path.write_text(json.dumps(serializable, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return idx
