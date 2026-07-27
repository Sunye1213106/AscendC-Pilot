"""Deterministic repository-local C/C++ include closure.

Only files that physically exist under ``repo_root`` are followed. System/SDK
headers that are not vendored in the repository remain external. Resolution is
fail-closed on ambiguous suffix matches and bounded by depth/file budgets.

SSOT artifact: ``uo/ir/include_closure.yaml`` (readers must not dual-read legacy names).
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*(["<])([^">]+)[">]', re.MULTILINE)
_ARCH_RE = re.compile(r"^arch(\d+)$", re.IGNORECASE)
_SOURCE_SUFFIXES = frozenset({".h", ".hh", ".hpp", ".hxx", ".inc", ".c", ".cc", ".cpp", ".cxx"})


@dataclass
class IncludeClosureResult:
    seed_files: list[Path]
    files: list[Path]
    edges: list[dict[str, str]] = field(default_factory=list)
    unresolved: list[dict[str, object]] = field(default_factory=list)
    truncated: bool = False

    def as_dict(self, repo_root: Path) -> dict[str, object]:
        def rel(path: Path) -> str:
            try:
                return path.relative_to(repo_root).as_posix()
            except ValueError:
                return path.as_posix()

        return {
            "seed_files": [rel(path) for path in self.seed_files],
            "files": [rel(path) for path in self.files],
            "edges": list(self.edges),
            "unresolved": list(self.unresolved),
            "truncated": self.truncated,
        }


def expand_local_include_closure(
    repo_root: Path,
    seed_files: list[Path],
    *,
    architecture: str = "",
    max_depth: int = 32,
    max_files: int = 1024,
) -> IncludeClosureResult:
    """Return a cycle-safe closure of repository-local include dependencies."""
    root = repo_root.resolve()
    seeds = sorted(
        {
            path.resolve()
            for path in seed_files
            if path.is_file() and _inside(path.resolve(), root) and _supported(path)
        },
        key=lambda path: path.as_posix(),
    )
    result = IncludeClosureResult(seed_files=seeds, files=[])
    if not seeds:
        return result

    suffix_index = _build_suffix_index(root, architecture)
    queue: deque[tuple[Path, int]] = deque((path, 0) for path in seeds)
    seen: set[Path] = set()

    while queue:
        path, depth = queue.popleft()
        if path in seen:
            continue
        if len(seen) >= max_files:
            result.truncated = True
            result.unresolved.append(
                {
                    "kind": "include_closure_file_budget",
                    "file_path": _rel(path, root),
                    "max_files": max_files,
                }
            )
            break
        seen.add(path)
        result.files.append(path)
        if depth >= max_depth:
            result.truncated = True
            result.unresolved.append(
                {
                    "kind": "include_closure_depth_budget",
                    "file_path": _rel(path, root),
                    "max_depth": max_depth,
                }
            )
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            result.unresolved.append(
                {"kind": "include_read_failed", "file_path": _rel(path, root)}
            )
            continue

        for match in _INCLUDE_RE.finditer(text):
            delimiter, token = match.group(1), match.group(2).strip().replace("\\", "/")
            target, candidates = _resolve_include(
                root,
                path,
                token,
                delimiter=delimiter,
                suffix_index=suffix_index,
                architecture=architecture,
            )
            source_rel = _rel(path, root)
            if target is None:
                # Missing angle-bracket includes are normally SDK/system headers.
                if candidates or delimiter == '"':
                    result.unresolved.append(
                        {
                            "kind": "include_target_ambiguous" if len(candidates) > 1 else "include_target_missing",
                            "file_path": source_rel,
                            "line": text.count("\n", 0, match.start()) + 1,
                            "include": token,
                            "candidates": [_rel(item, root) for item in candidates],
                        }
                    )
                continue
            target_rel = _rel(target, root)
            result.edges.append(
                {
                    "source": source_rel,
                    "target": target_rel,
                    "include": token,
                    "style": "quote" if delimiter == '"' else "angle",
                }
            )
            if target not in seen:
                queue.append((target, depth + 1))

    result.files.sort(key=lambda path: path.as_posix())
    result.edges = _dedupe_rows(result.edges)
    result.unresolved = _dedupe_rows(result.unresolved)
    return result


def _resolve_include(
    root: Path,
    source: Path,
    token: str,
    *,
    delimiter: str,
    suffix_index: dict[str, list[Path]],
    architecture: str,
) -> tuple[Path | None, list[Path]]:
    direct: list[Path] = []
    if delimiter == '"':
        direct.append((source.parent / token).resolve())
    direct.append((root / token).resolve())
    for candidate in direct:
        if (
            candidate.is_file()
            and _inside(candidate, root)
            and _supported(candidate)
            and _architecture_compatible(candidate, root, architecture)
        ):
            return candidate, [candidate]

    normalized = token.strip("/")
    candidates = list(suffix_index.get(normalized, []))
    if not candidates:
        candidates = list(suffix_index.get(Path(normalized).name, []))
    candidates = sorted(set(candidates), key=lambda path: path.as_posix())
    return (candidates[0], candidates) if len(candidates) == 1 else (None, candidates)


def _build_suffix_index(root: Path, architecture: str) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or not _supported(path):
            continue
        resolved = path.resolve()
        if not _architecture_compatible(resolved, root, architecture):
            continue
        rel = resolved.relative_to(root).as_posix()
        parts = rel.split("/")
        keys = {path.name, rel}
        # Include bounded suffixes so common project include-root layouts resolve.
        for width in range(2, min(7, len(parts)) + 1):
            keys.add("/".join(parts[-width:]))
        for key in keys:
            index.setdefault(key, []).append(resolved)
    return index


def _architecture_compatible(path: Path, root: Path, architecture: str) -> bool:
    requested = str(architecture or "").casefold()
    if not requested:
        return True
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return False
    arch_parts = {part.casefold() for part in parts if _ARCH_RE.fullmatch(part)}
    return not arch_parts or requested in arch_parts


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _supported(path: Path) -> bool:
    return path.suffix.casefold() in _SOURCE_SUFFIXES


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    out: list[dict[str, object]] = []
    for row in rows:
        key = repr(sorted(row.items(), key=lambda item: item[0]))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


INCLUDE_CLOSURE_SSOT = "ir/include_closure.yaml"
_LEGACY_CLOSURE_RELS = (
    "ir/scope_include_closure.yaml",
    "ir/source_scope.yaml",
)


def classify_include_resolution(
    repo_root: Path,
    source: Path,
    token: str,
    *,
    delimiter: str = '"',
    architecture: str = "",
) -> dict[str, Any]:
    """Resolve one include token; never treat basename-only as verified.

    status: resolved_unique | resolved_multiple | not_found |
            external_system_header | generated_header
    """
    root = repo_root.resolve()
    suffix_index = _build_suffix_index(root, architecture)
    target, candidates = _resolve_include(
        root,
        source.resolve() if source.is_file() else source,
        token.strip().replace("\\", "/"),
        delimiter=delimiter,
        suffix_index=suffix_index,
        architecture=architecture,
    )
    if target is not None and len(candidates) <= 1:
        return {
            "status": "resolved_unique",
            "target": _rel(target, root),
            "candidates": [_rel(c, root) for c in candidates],
        }
    if len(candidates) > 1:
        return {
            "status": "resolved_multiple",
            "target": None,
            "candidates": [_rel(c, root) for c in candidates],
            "reason": "include_target_ambiguous",
        }
    # Angle includes with zero candidates are typically SDK/system headers.
    if delimiter == "<":
        low = token.casefold()
        if low.endswith(".h") or "/" in token or token.startswith("acl") or "ascend" in low:
            kind = "external_system_header"
        else:
            kind = "not_found"
        return {"status": kind, "target": None, "candidates": [], "reason": kind}
    if "generated" in token.casefold() or token.endswith(".inc"):
        return {
            "status": "generated_header",
            "target": None,
            "candidates": [],
            "reason": "generated_header",
        }
    return {"status": "not_found", "target": None, "candidates": [], "reason": "include_target_missing"}


def include_closure_ssot_path(uo_root: Path) -> Path:
    return Path(uo_root) / "ir" / "include_closure.yaml"


def write_include_closure_ssot(
    uo_root: Path,
    *,
    closure: IncludeClosureResult | dict[str, Any],
    repo_root: Path,
    scope_revision: Any = None,
    scope_fingerprint: str = "",
    source_snapshot_hash: str = "",
) -> dict[str, Any]:
    """Write the single include-closure SSOT consumed by triage/gates/freshness."""
    from uo.scripts._ir_io import write_yaml

    if isinstance(closure, IncludeClosureResult):
        body = closure.as_dict(repo_root)
        truncated = bool(closure.truncated)
        unresolved = list(closure.unresolved)
    else:
        body = dict(closure)
        truncated = bool(body.get("truncated"))
        unresolved = list(body.get("unresolved") or [])

    ambiguous = [
        u
        for u in unresolved
        if isinstance(u, dict) and str(u.get("kind") or "") == "include_target_ambiguous"
    ]
    blocking_kinds = {
        "include_target_missing",
        "include_target_ambiguous",
        "include_read_failed",
        "include_closure_file_budget",
        "include_closure_depth_budget",
    }
    blocking_unresolved = [
        u
        for u in unresolved
        if isinstance(u, dict) and str(u.get("kind") or "") in blocking_kinds
    ]
    # external_system_header / generated_header do not block completeness.
    if body.get("error"):
        status = "failed"
    elif truncated or blocking_unresolved:
        status = "partial"
    else:
        status = "complete"
    payload = {
        "schema_version": 1,
        "status": status,
        "include_closure_status": status,
        "scope_revision": scope_revision,
        "scope_fingerprint": scope_fingerprint,
        "source_snapshot_hash": source_snapshot_hash,
        "seed_files": list(body.get("seed_files") or []),
        "resolved_files": list(body.get("files") or body.get("resolved_files") or []),
        "files": list(body.get("files") or body.get("resolved_files") or []),
        "edges": list(body.get("edges") or []),
        "unresolved_includes": unresolved,
        "ambiguous_includes": ambiguous,
        "truncated": truncated,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    write_yaml(include_closure_ssot_path(uo_root), payload)
    return payload


def load_include_closure_ssot(uo_root: Path, *, migrate: bool = True) -> dict[str, Any]:
    """Load SSOT; optionally migrate legacy filenames once into ir/include_closure.yaml."""
    from uo.scripts._ir_io import read_yaml, write_yaml

    path = include_closure_ssot_path(uo_root)
    data = read_yaml(path) or {}
    if isinstance(data, dict) and data:
        return data
    if not migrate:
        return {}
    for rel in _LEGACY_CLOSURE_RELS:
        legacy = read_yaml(Path(uo_root) / rel) or {}
        if not isinstance(legacy, dict) or not legacy:
            continue
        status = str(
            legacy.get("include_closure_status")
            or legacy.get("status")
            or legacy.get("closure_status")
            or ("partial" if legacy.get("truncated") else "complete")
        )
        payload = {
            "schema_version": 1,
            "status": status,
            "include_closure_status": status,
            "scope_revision": legacy.get("scope_revision"),
            "scope_fingerprint": legacy.get("scope_fingerprint") or "",
            "source_snapshot_hash": legacy.get("source_snapshot_hash") or "",
            "seed_files": list(legacy.get("seed_files") or []),
            "resolved_files": list(legacy.get("files") or legacy.get("resolved_files") or []),
            "files": list(legacy.get("files") or legacy.get("resolved_files") or []),
            "edges": list(legacy.get("edges") or []),
            "unresolved_includes": list(legacy.get("unresolved") or legacy.get("unresolved_includes") or []),
            "ambiguous_includes": list(legacy.get("ambiguous_includes") or []),
            "truncated": bool(legacy.get("truncated")),
            "migrated_from": rel,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        write_yaml(path, payload)
        return payload
    return {}


def include_closure_is_complete(uo_root: Path) -> bool:
    data = load_include_closure_ssot(uo_root, migrate=True)
    status = str(
        data.get("include_closure_status") or data.get("status") or data.get("closure_status") or ""
    ).casefold()
    return status in {"complete", "closed", "ok"}
