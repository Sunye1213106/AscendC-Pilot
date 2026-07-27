"""Shared freshness helpers for uo-update change_set / update_plan artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml


def change_set_path(uo_root: Path) -> Path:
    return uo_root / "diff" / "change_set.yaml"


def update_plan_path(uo_root: Path) -> Path:
    return uo_root / "summary" / "update_plan.yaml"


def _git_head(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return (result.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def current_scope_identity(uo_root: Path) -> dict[str, Any]:
    """Return scope_revision / scope_fingerprint / confirmed_sources_hash for freshness.

    Fingerprint is always recomputed from confirmed scope content. Persisted
    snapshot fingerprints are validation-only and must not gate freshness.
    """
    from uo.scripts.scope_expansion import _confirmed_rels, _latest_scope_confirmed

    path, scope = _latest_scope_confirmed(uo_root)
    rels = sorted(_confirmed_rels(scope))
    revision = scope.get("scope_revision")
    snap: dict[str, Any] = {}
    if path is not None:
        snap = read_yaml(path.parent / "scope_snapshot.yaml") or {}
        if revision is None:
            revision = snap.get("scope_revision")
    if revision is None:
        revision = 0
    confirmed_sources_hash = _stable_hash(rels)[:32]
    computed_fp = _stable_hash({"confirmed_sources": rels, "scope_revision": revision})[:32]
    persisted_fp = str(snap.get("scope_fingerprint") or snap.get("source_snapshot_hash") or "")
    out: dict[str, Any] = {
        "scope_revision": revision,
        "scope_fingerprint": computed_fp,
        "confirmed_sources_hash": confirmed_sources_hash,
        "confirmed_sources": rels,
    }
    if persisted_fp and persisted_fp != computed_fp:
        out["status"] = "inconsistent"
        out["persisted_scope_fingerprint"] = persisted_fp
    return out


def compute_change_set_fingerprint(
    *,
    head_revision: str,
    base_revision: str,
    scope_fingerprint: str,
    changed_files: list[Any],
    detection_config: dict[str, Any] | None = None,
) -> str:
    norms = sorted(
        str(f.get("path") if isinstance(f, dict) else f).replace("\\", "/")
        for f in (changed_files or [])
    )
    return _stable_hash(
        {
            "head_revision": head_revision,
            "base_revision": base_revision,
            "scope_fingerprint": scope_fingerprint,
            "changed_files": norms,
            "detection_config": detection_config or {"markers": ["op_host", "op_kernel", "op_api", "common", "tiling"]},
        }
    )


def compute_plan_fingerprint(
    *,
    head_revision: str,
    base_revision: str,
    scope_fingerprint: str,
    change_set_fingerprint: str,
    mode: str,
    affected_layers: list[Any],
) -> str:
    return _stable_hash(
        {
            "head_revision": head_revision,
            "base_revision": base_revision,
            "scope_fingerprint": scope_fingerprint,
            "change_set_fingerprint": change_set_fingerprint,
            "mode": mode,
            "affected_layers": sorted(str(x) for x in (affected_layers or [])),
        }
    )


def load_change_set_if_fresh(
    uo_root: Path,
    *,
    repo_root: Path | None = None,
    expected_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Return change_set only when all required freshness fields match (fail-closed)."""
    path = change_set_path(uo_root)
    if not path.is_file():
        return None
    doc = read_yaml(path)
    if not isinstance(doc, dict) or not doc:
        return None

    manifest = read_yaml(uo_root / "manifest.yaml") or {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    base_expected = str(source.get("revision") or "").strip()
    cs_base = str(doc.get("base_revision") or "").strip()
    cs_head = str(doc.get("head_revision") or "").strip()
    cs_scope_fp = str(doc.get("scope_fingerprint") or "").strip()
    cs_fp = str(doc.get("change_set_fingerprint") or doc.get("fingerprint") or "").strip()
    # Missing required fields → stale (no skip-when-missing).
    if not base_expected or not cs_base or not cs_head or not cs_scope_fp or not cs_fp:
        return None
    if cs_base != base_expected:
        return None

    root = Path(repo_root) if repo_root is not None else Path(str(source.get("root") or "")).resolve()
    if not str(root) or not root.is_dir():
        return None
    head_now = _git_head(root)
    if not head_now or cs_head != head_now:
        return None

    scope_now = current_scope_identity(uo_root)
    if cs_scope_fp != str(scope_now.get("scope_fingerprint") or ""):
        return None
    cs_rev = doc.get("scope_revision")
    if cs_rev is not None and int(cs_rev) != int(scope_now.get("scope_revision") or 0):
        return None
    cs_sources_hash = str(doc.get("confirmed_sources_hash") or "").strip()
    if cs_sources_hash and cs_sources_hash != str(scope_now.get("confirmed_sources_hash") or ""):
        return None

    expected_cs_fp = compute_change_set_fingerprint(
        head_revision=cs_head,
        base_revision=cs_base,
        scope_fingerprint=cs_scope_fp,
        changed_files=list(doc.get("files") or []),
    )
    if cs_fp != expected_cs_fp:
        return None

    if expected_fingerprint is not None and cs_fp != expected_fingerprint:
        return None
    return doc


def load_update_plan_if_fresh(
    uo_root: Path,
    *,
    change_set: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return update_plan only when fingerprints fully match change_set + scope."""
    path = update_plan_path(uo_root)
    if not path.is_file():
        return None
    doc = read_yaml(path)
    if not isinstance(doc, dict) or not doc:
        return None
    if change_set is None:
        return None

    required_plan = (
        "head_revision",
        "base_revision",
        "scope_fingerprint",
        "change_set_fingerprint",
        "plan_fingerprint",
    )
    for key in required_plan:
        if not str(doc.get(key) or "").strip():
            return None

    for key in ("head_revision", "base_revision", "scope_fingerprint", "change_set_fingerprint"):
        if str(doc.get(key) or "").strip() != str(change_set.get(key) or "").strip():
            return None

    scope_now = current_scope_identity(uo_root)
    if str(doc.get("scope_fingerprint") or "") != str(scope_now.get("scope_fingerprint") or ""):
        return None

    expected_plan_fp = compute_plan_fingerprint(
        head_revision=str(doc.get("head_revision") or ""),
        base_revision=str(doc.get("base_revision") or ""),
        scope_fingerprint=str(doc.get("scope_fingerprint") or ""),
        change_set_fingerprint=str(doc.get("change_set_fingerprint") or ""),
        mode=str(doc.get("mode") or ""),
        affected_layers=list(doc.get("affected_layers") or []),
    )
    if str(doc.get("plan_fingerprint") or "") != expected_plan_fp:
        return None
    return doc
