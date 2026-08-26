# -*- coding: utf-8 -*-
"""Scope/content fingerprints for deterministic incremental extraction.

The cache contract is semantic: unchanged source/build identity may reuse a
content-addressed TU result, while changed input must invalidate it. Wall-clock
budgets are deliberately not part of UO correctness.

Fingerprints use a two-layer stamp: ``mtime_ns`` + ``size`` first, then sha256
only for files whose stamp drifted. ``/uo-update`` consumes the same per-file
delta so detect/plan/extract do not disagree on which confirmed sources moved.
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


def _file_stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
    return mtime_ns, int(st.st_size)


def _index_stamps(rows: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if isinstance(rows, dict):
        items = rows.items()
        for key, value in items:
            if isinstance(value, dict):
                path = str(value.get("path") or key).replace("\\", "/")
                out[path] = value
        return out
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").replace("\\", "/")
        if path:
            out[path] = row
    return out


def collect_source_stamps(
    project_root: Path,
    rel_paths: list[str],
    *,
    previous: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Per-file mtime/size/sha rows. Matching stamps reuse the stored sha."""
    root = Path(project_root).expanduser().resolve()
    prev_rows = (previous or {}).get("source_stamps") if isinstance(previous, dict) else None
    prev = _index_stamps(prev_rows if prev_rows is not None else previous)
    rows: list[dict[str, Any]] = []
    for rel in sorted({path.replace("\\", "/") for path in rel_paths}):
        path = root / rel
        stamp = _file_stamp(path) if path.is_file() else None
        if stamp is None:
            rows.append(
                {
                    "path": rel,
                    "mtime_ns": 0,
                    "size": 0,
                    "sha": "missing",
                    "hashed": False,
                }
            )
            continue
        mtime_ns, size = stamp
        prior = prev.get(rel) or {}
        prior_sha = str(prior.get("sha") or "")
        try:
            prior_mtime = int(prior.get("mtime_ns") or -1)
            prior_size = int(prior.get("size") or -1)
        except (TypeError, ValueError):
            prior_mtime, prior_size = -1, -1
        if (
            prior_sha
            and prior_sha != "missing"
            and prior_mtime == mtime_ns
            and prior_size == size
        ):
            rows.append(
                {
                    "path": rel,
                    "mtime_ns": mtime_ns,
                    "size": size,
                    "sha": prior_sha,
                    "hashed": False,
                }
            )
        else:
            rows.append(
                {
                    "path": rel,
                    "mtime_ns": mtime_ns,
                    "size": size,
                    "sha": sha256_file(path),
                    "hashed": True,
                }
            )
    return rows


def persist_source_stamps(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": row["path"],
            "mtime_ns": int(row.get("mtime_ns") or 0),
            "size": int(row.get("size") or 0),
            "sha": str(row.get("sha") or ""),
        }
        for row in rows
    ]


def content_fingerprint(
    project_root: Path,
    rel_paths: list[str],
    *,
    previous: dict[str, Any] | None = None,
) -> str:
    """Return a stable hash over sorted ``(relative_path, file_sha)`` pairs."""
    rows = collect_source_stamps(project_root, rel_paths, previous=previous)
    return _stable_hash([[row["path"], row["sha"]] for row in rows])[:32]


def stamp_changed_paths(
    now_rows: list[dict[str, Any]] | None,
    prev_rows: list[dict[str, Any]] | None,
) -> list[str]:
    """Confirmed-source paths whose sha (or presence) drifted."""
    prev_sha = {
        path: str(row.get("sha") or "")
        for path, row in _index_stamps(prev_rows or []).items()
    }
    changed: list[str] = []
    now_paths: set[str] = set()
    for path, row in _index_stamps(now_rows or []).items():
        now_paths.add(path)
        if prev_sha.get(path) != str(row.get("sha") or ""):
            changed.append(path)
    for path in prev_sha:
        if path not in now_paths:
            changed.append(path)
    return sorted(changed)


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
    from uo_init.tu_cache import CACHE_VERSION

    previous = load_extract_fingerprint(uo)
    stamps = collect_source_stamps(root, rels, previous=previous)
    content_fp = _stable_hash([[row["path"], row["sha"]] for row in stamps])[:32]
    extract_fp = _stable_hash(
        {
            "scope_fingerprint": scope.get("scope_fingerprint"),
            "content_fingerprint": content_fp,
            "build_fingerprint": build_fingerprint or "",
            "confirmed_sources": rels,
            "walk_cache_version": CACHE_VERSION,
        }
    )[:32]
    persisted = persist_source_stamps(stamps)
    return {
        "scope_fingerprint": scope.get("scope_fingerprint") or "",
        "scope_revision": scope.get("scope_revision") or 0,
        "content_fingerprint": content_fp,
        "build_fingerprint": build_fingerprint or "",
        "extract_fingerprint": extract_fp,
        "confirmed_sources": rels,
        "uo_root": str(uo),
        "source_stamps": persisted,
        "hashed_files": [row["path"] for row in stamps if row.get("hashed")],
        "reused_stamp_files": [
            row["path"]
            for row in stamps
            if not row.get("hashed") and row.get("sha") != "missing"
        ],
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
    previous_fp = str(meta.get("previous_extract_fingerprint") or "")
    if unchanged:
        changed: list[str] = []
        kept = list(rels)
    elif not previous_fp:
        changed = list(rels)
        kept = []
    else:
        previous = load_extract_fingerprint(Path(meta["uo_root"]))
        changed = stamp_changed_paths(
            meta.get("source_stamps") or [],
            previous.get("source_stamps") or [],
        )
        changed_set = set(changed)
        kept = [path for path in rels if path not in changed_set]
    return {
        "skip_reextract": unchanged,
        "unchanged_tus": kept,
        "changed_or_cold": changed,
        "fingerprint": meta,
        "previous_extract_fingerprint": previous_fp,
        "tu_cache_dir": str(tu_cache_dir(project_root, arch)),
        "cache_root": str(uo_cache_root(project_root, arch)),
    }


def align_scoped_changes(
    files: list[dict[str, Any]],
    skip_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep uo-update's change_set on the same stamp delta extract uses.

    Out-of-scope and non-confirmed rows stay for review. Confirmed sources
    follow ``changed_or_cold`` once a previous extract fingerprint exists.
    """
    previous_fp = str(skip_plan.get("previous_extract_fingerprint") or "")
    if not previous_fp:
        return list(files)
    changed = {
        str(path).replace("\\", "/")
        for path in (skip_plan.get("changed_or_cold") or [])
    }
    confirmed = {
        str(path).replace("\\", "/")
        for path in ((skip_plan.get("fingerprint") or {}).get("confirmed_sources") or [])
    }
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").replace("\\", "/")
        if not path:
            continue
        if not item.get("in_scope"):
            out.append(item)
            seen.add(path)
            continue
        if path not in confirmed:
            out.append(item)
            seen.add(path)
            continue
        if path in changed:
            out.append(item)
            seen.add(path)
    for path in sorted(changed):
        if path in seen:
            continue
        out.append(
            {
                "path": path,
                "status": "M",
                "in_scope": True,
                "role": _infer_role(path),
                "suspicious_out_of_scope": False,
            }
        )
        seen.add(path)
    return out


def _infer_role(path: str) -> str:
    try:
        from uo_init.update.artifacts import infer_role

        return str(infer_role(path) or "")
    except Exception:  # noqa: BLE001
        return ""
