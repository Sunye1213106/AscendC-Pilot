# -*- coding: utf-8 -*-
"""Scope / content fingerprint helpers for incremental extract (P3).

Extends :mod:`uo_init.update.artifacts` scope identity with a content hash of
confirmed sources so warm re-runs can skip re-walking unchanged TUs (via the
TU disk cache) and CI can assert a replay budget.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from uo_init.tu_cache import sha256_file, tu_cache_dir, uo_cache_root

_ENV_BUDGET = "UO_WARM_REPLAY_BUDGET_S"
_META_NAME = "extract_fingerprint.yaml"


def warm_replay_budget_s(default: float = 120.0) -> float:
    raw = os.environ.get(_ENV_BUDGET, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def content_fingerprint(
    project_root: Path,
    rel_paths: list[str],
) -> str:
    """sha256 over sorted (rel_path, file_sha) pairs for confirmed sources."""
    root = Path(project_root).expanduser().resolve()
    rows: list[list[str]] = []
    for rel in sorted({p.replace("\\", "/") for p in rel_paths}):
        path = root / rel
        if not path.is_file():
            rows.append([rel, "missing"])
            continue
        rows.append([rel, sha256_file(path)])
    return _stable_hash(rows)[:32]


def compute_extract_fingerprint(
    project_root: Path,
    *,
    uo_root: Path | None = None,
    arch: str | None = None,
    build_fingerprint: str = "",
) -> dict[str, Any]:
    """Combine scope identity + source content + optional build fingerprint."""
    from uo_init.update.artifacts import current_scope_identity, resolve_uo_root

    root = Path(project_root).expanduser().resolve()
    uo = Path(uo_root) if uo_root is not None else resolve_uo_root(root)
    # Prefer arch-scoped uo when present.
    if arch and not uo_root:
        cand = root / ".ascendc-pilot" / arch / "uo"
        if cand.is_dir():
            uo = cand
    scope = current_scope_identity(uo)
    rels = list(scope.get("confirmed_sources") or [])
    if not rels:
        # Fall back to common host/kernel globs when scope is not confirmed yet.
        for pattern in (
            "op_host/**/*.cpp",
            "op_host/**/*.h",
            "op_kernel/**/*.cpp",
            "op_kernel/**/*.h",
        ):
            rels.extend(
                p.relative_to(root).as_posix()
                for p in root.glob(pattern)
                if p.is_file()
            )
        rels = sorted(set(rels))
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
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )
    return path


def sources_unchanged(
    project_root: Path,
    *,
    uo_root: Path | None = None,
    arch: str | None = None,
    build_fingerprint: str = "",
) -> tuple[bool, dict[str, Any]]:
    """True when stored extract fingerprint still matches current sources."""
    now = compute_extract_fingerprint(
        project_root,
        uo_root=uo_root,
        arch=arch,
        build_fingerprint=build_fingerprint,
    )
    uo = Path(now["uo_root"])
    prev = load_extract_fingerprint(uo)
    if not prev:
        return False, now
    ok = str(prev.get("extract_fingerprint") or "") == str(now.get("extract_fingerprint") or "")
    now["previous_extract_fingerprint"] = prev.get("extract_fingerprint") or ""
    now["unchanged"] = ok
    return ok, now


def skip_reextract_for_unchanged_tus(
    project_root: Path,
    *,
    uo_root: Path | None = None,
    arch: str | None = None,
    build_fingerprint: str = "",
) -> dict[str, Any]:
    """Return a plan for which confirmed TUs can skip re-extract.

    Unchanged sources rely on :mod:`uo_init.tu_cache` content-hash hits; this
    helper only reports the fingerprint decision for callers / receipts.
    """
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


def replay_extract_walks(
    paths: list[Path],
    walk_fn: Callable[[Path], Any],
    *,
    budget_s: float | None = None,
) -> dict[str, Any]:
    """Run ``walk_fn`` on each path and assert total wall time ≤ budget.

    Used by CI / unit tests with a tiny fixture and a few-second budget.
    Production default budget is ``UO_WARM_REPLAY_BUDGET_S`` (120).
    """
    limit = warm_replay_budget_s() if budget_s is None else float(budget_s)
    t0 = time.perf_counter()
    results = []
    for p in paths:
        results.append(walk_fn(Path(p)))
    elapsed = time.perf_counter() - t0
    return {
        "ok": elapsed <= limit,
        "elapsed_s": round(elapsed, 4),
        "budget_s": limit,
        "n_paths": len(paths),
        "results": results,
    }


def assert_warm_replay_under_budget(
    paths: list[Path],
    walk_fn: Callable[[Path], Any],
    *,
    budget_s: float = 5.0,
) -> dict[str, Any]:
    """CI helper: warm cache + unchanged sources must finish under ``budget_s``."""
    report = replay_extract_walks(paths, walk_fn, budget_s=budget_s)
    if not report["ok"]:
        raise AssertionError(
            f"warm replay exceeded budget: {report['elapsed_s']}s > {report['budget_s']}s "
            f"(n_paths={report['n_paths']})"
        )
    return report
