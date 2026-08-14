# -*- coding: utf-8 -*-
"""Scope/content fingerprints for deterministic incremental extraction.

The cache contract is semantic: unchanged source/build identity may reuse a
content-addressed TU result, while changed input must invalidate it. Wall-clock
budgets are deliberately not part of UO correctness.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from uo_init.tu_cache import sha256_file, tu_cache_dir, uo_cache_root

_META_NAME = "extract_fingerprint.yaml"


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def content_fingerprint(project_root: Path, rel_paths: list[str]) -> str:
    """Return a stable hash over sorted ``(relative_path, file_sha)`` pairs."""
    root = Path(project_root).expanduser().resolve()
    rows: list[list[str]] = []
    for rel in sorted({path.replace("\\", "/") for path in rel_paths}):
        path = root / rel
        rows.append([rel, sha256_file(path) if path.is_file() else "missing"])
    return _stable_hash(rows)[:32]


def compute_extract_fingerprint(
    project_root: Path,
    *,
    uo_root: Path | None = None,
    arch: str | None = None,
    build_fingerprint: str = "",
) -> dict[str, Any]:
    """Combine scope identity, source bytes and build identity."""
    from uo_init.update.artifacts import current_scope_identity, resolve_uo_root

    root = Path(project_root).expanduser().resolve()
    uo = Path(uo_root) if uo_root is not None else resolve_uo_root(root)
    if arch and not uo_root:
        candidate = root / ".ascendc-pilot" / arch / "uo"
        if candidate.is_dir():
            uo = candidate
    scope = current_scope_identity(uo)
    rels = list(scope.get("confirmed_sources") or [])
    if not rels:
        # Never fall back to an arch-blind glob — that is how foreign-arch
        # sources leak into confirmed_sources. Callers must finish prepare
        # (Clang-complete scope_set.yaml) before extract fingerprinting.
        raise RuntimeError(
            "SCOPE_CONFIRMED_SOURCES_MISSING: no Clang-confirmed file list under "
            f"{uo}; run prepare until clang_scope_status=complete writes "
            "summary/scope_set.yaml confirmed_source_files"
        )
    content_fp = content_fingerprint(root, rels)
    extract_fp = _stable_hash(
        {
            "scope_fingerprint": scope.get("scope_fingerprint"),
            "content_fingerprint": content_fp,
            "build_fingerprint": build_fingerprint or "",
            "confirmed_sources": rels,
        }
    )[:32]
    return {
        "scope_fingerprint": scope.get("scope_fingerprint") or "",
        "scope_revision": scope.get("scope_revision") or 0,
        "content_fingerprint": content_fp,
        "build_fingerprint": build_fingerprint or "",
        "extract_fingerprint": extract_fp,
        "confirmed_sources": rels,
        "uo_root": str(uo),
    }


def fingerprint_meta_path(uo_root: Path) -> Path:
    return Path(uo_root) / "cache" / _META_NAME


def load_extract_fingerprint(uo_root: Path) -> dict[str, Any]:
    path = fingerprint_meta_path(uo_root)
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def store_extract_fingerprint(uo_root: Path, meta: dict[str, Any]) -> Path:
    import yaml

    path = fingerprint_meta_path(uo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(meta)
    payload["stored_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=True), encoding="utf-8")
    return path


def sources_unchanged(
    project_root: Path,
    *,
    uo_root: Path | None = None,
    arch: str | None = None,
    build_fingerprint: str = "",
) -> tuple[bool, dict[str, Any]]:
    """Return whether the stored extraction identity still matches source/build input."""
    now = compute_extract_fingerprint(
        project_root,
        uo_root=uo_root,
        arch=arch,
        build_fingerprint=build_fingerprint,
    )
    uo = Path(now["uo_root"])
    previous = load_extract_fingerprint(uo)
    if not previous:
        return False, now
    unchanged = str(previous.get("extract_fingerprint") or "") == str(now.get("extract_fingerprint") or "")
    now["previous_extract_fingerprint"] = previous.get("extract_fingerprint") or ""
    now["unchanged"] = unchanged
    return unchanged, now


def skip_reextract_for_unchanged_tus(
    project_root: Path,
    *,
    uo_root: Path | None = None,
    arch: str | None = None,
    build_fingerprint: str = "",
) -> dict[str, Any]:
    """Describe the deterministic reuse decision for confirmed translation units."""
    unchanged, meta = sources_unchanged(
        project_root,
        uo_root=uo_root,
        arch=arch,
        build_fingerprint=build_fingerprint,
    )
    rels = list(meta.get("confirmed_sources") or [])
    return {
        "skip_reextract": unchanged,
        "unchanged_tus": list(rels) if unchanged else [],
        "changed_or_cold": [] if unchanged else list(rels),
        "fingerprint": meta,
        "tu_cache_dir": str(tu_cache_dir(project_root, arch)),
        "cache_root": str(uo_cache_root(project_root, arch)),
    }
