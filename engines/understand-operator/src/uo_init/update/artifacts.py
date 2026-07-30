# -*- coding: utf-8 -*-
"""uo-update helpers: freshness, fingerprints, scope identity (new KB contract)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from uo_init.yaml_io import read_yaml

SOURCE_SUFFIXES = {".cpp", ".cc", ".c", ".h", ".hpp", ".py", ".cuh", ".cu"}
OPERATOR_PATH_MARKERS = ("op_host", "op_kernel", "op_api", "common", "tiling")


def change_set_path(uo_root: Path) -> Path:
    return uo_root / "diff" / "change_set.yaml"


def update_plan_path(uo_root: Path) -> Path:
    return uo_root / "summary" / "update_plan.yaml"


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def git_head(repo_root: Path) -> str:
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


def infer_role(path: str) -> str:
    lower = path.replace("\\", "/").lower()
    if "template_tiling_key" in lower or lower.endswith("tiling_key.h"):
        return "tilingkey"
    if "/op_kernel/" in f"/{lower}" or lower.startswith("op_kernel/"):
        return "kernel"
    if "/op_host/" in f"/{lower}" or lower.startswith("op_host/"):
        return "host"
    if "tiling" in lower:
        return "tiling"
    if "/op_api/" in f"/{lower}" or lower.startswith("op_api/"):
        return "api"
    if "/common/" in f"/{lower}" or lower.startswith("common/"):
        return "common"
    if lower.endswith(".py") and ("cpu_impl" in lower or "golden" in lower):
        return "golden"
    if lower.endswith((".h", ".hpp")):
        return "headers"
    return "other"


def _extract_file_list(doc: dict[str, Any]) -> dict[str, str]:
    raw: list[Any] = []
    frozen = doc.get("frozen_scope")
    if isinstance(frozen, dict):
        raw = (
            frozen.get("confirmed_source_files")
            or frozen.get("confirmed_file_list")
            or frozen.get("files")
            or []
        )
    if not raw:
        raw = (
            doc.get("confirmed_source_files")
            or doc.get("confirmed_file_list")
            or doc.get("files")
            or []
        )
    out: dict[str, str] = {}
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            out[item.replace("\\", "/")] = infer_role(item)
            continue
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or item.get("file") or "").replace("\\", "/")
        if not path:
            continue
        role = str(item.get("role") or "").strip() or infer_role(path)
        out[path] = role
    return out


def load_scope_index(uo_root: Path) -> dict[str, str]:
    man = read_yaml(uo_root / "manifest.yaml")
    run_id = str(man.get("current_run_id") or "")
    candidates: list[Path] = []
    if run_id:
        candidates.append(uo_root / "runs" / run_id / "scope" / "receipt.yaml")
        candidates.append(uo_root / "runs" / run_id / "scope" / "scope_confirmed.yaml")
    runs = uo_root / "runs"
    if runs.is_dir():
        candidates.extend(sorted(runs.glob("*/scope/receipt.yaml"), reverse=True))
        candidates.extend(sorted(runs.glob("*/scope/scope_confirmed.yaml"), reverse=True))
    for path in candidates:
        doc = read_yaml(path)
        if not doc:
            continue
        files = _extract_file_list(doc)
        if files:
            return files
    return {}


def current_scope_identity(uo_root: Path) -> dict[str, Any]:
    scope_index = load_scope_index(uo_root)
    rels = sorted(scope_index)
    man = read_yaml(uo_root / "manifest.yaml")
    revision = man.get("scope_revision")
    if revision is None:
        run_id = str(man.get("current_run_id") or "")
        snap = read_yaml(uo_root / "runs" / run_id / "scope" / "scope_snapshot.yaml") if run_id else {}
        revision = snap.get("scope_revision", 0)
    confirmed_sources_hash = _stable_hash(rels)[:32]
    computed_fp = _stable_hash({"confirmed_sources": rels, "scope_revision": revision})[:32]
    return {
        "scope_revision": revision or 0,
        "scope_fingerprint": computed_fp,
        "confirmed_sources_hash": confirmed_sources_hash,
        "confirmed_sources": rels,
    }


def compute_change_set_fingerprint(
    *,
    head_revision: str,
    base_revision: str,
    scope_fingerprint: str,
    changed_files: list[Any],
) -> str:
    paths = sorted(
        {
            str(item.get("path") or "")
            for item in changed_files
            if isinstance(item, dict)
        }
    )
    return _stable_hash(
        {
            "head": head_revision,
            "base": base_revision,
            "scope": scope_fingerprint,
            "files": paths,
        }
    )[:32]


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
    )[:32]


def load_change_set_if_fresh(
    uo_root: Path,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any] | None:
    path = change_set_path(uo_root)
    if not path.is_file():
        return None
    doc = read_yaml(path)
    if not doc:
        return None
    manifest = read_yaml(uo_root / "manifest.yaml") or {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    base_expected = str(source.get("revision") or "").strip()
    cs_base = str(doc.get("base_revision") or "").strip()
    cs_head = str(doc.get("head_revision") or "").strip()
    cs_scope_fp = str(doc.get("scope_fingerprint") or "").strip()
    cs_fp = str(doc.get("change_set_fingerprint") or doc.get("fingerprint") or "").strip()
    if not base_expected or not cs_base or not cs_head or not cs_scope_fp or not cs_fp:
        return None
    if cs_base != base_expected:
        return None
    root = Path(repo_root) if repo_root is not None else Path(str(source.get("root") or "")).resolve()
    if not str(root) or not root.is_dir():
        return None
    head_now = git_head(root)
    if not head_now or cs_head != head_now:
        return None
    scope_now = current_scope_identity(uo_root)
    if cs_scope_fp != str(scope_now.get("scope_fingerprint") or ""):
        return None
    expected = compute_change_set_fingerprint(
        head_revision=cs_head,
        base_revision=cs_base,
        scope_fingerprint=cs_scope_fp,
        changed_files=list(doc.get("files") or []),
    )
    if cs_fp != expected:
        return None
    return doc


def load_update_plan_if_fresh(
    uo_root: Path,
    *,
    change_set: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    path = update_plan_path(uo_root)
    if not path.is_file() or change_set is None:
        return None
    doc = read_yaml(path)
    if not doc:
        return None
    for key in (
        "head_revision",
        "base_revision",
        "scope_fingerprint",
        "change_set_fingerprint",
        "plan_fingerprint",
    ):
        if not str(doc.get(key) or "").strip():
            return None
    for key in ("head_revision", "base_revision", "scope_fingerprint", "change_set_fingerprint"):
        if str(doc.get(key) or "").strip() != str(change_set.get(key) or "").strip():
            return None
    scope_now = current_scope_identity(uo_root)
    if str(doc.get("scope_fingerprint") or "") != str(scope_now.get("scope_fingerprint") or ""):
        return None
    expected = compute_plan_fingerprint(
        head_revision=str(doc.get("head_revision") or ""),
        base_revision=str(doc.get("base_revision") or ""),
        scope_fingerprint=str(doc.get("scope_fingerprint") or ""),
        change_set_fingerprint=str(doc.get("change_set_fingerprint") or ""),
        mode=str(doc.get("mode") or ""),
        affected_layers=list(doc.get("affected_layers") or []),
    )
    if str(doc.get("plan_fingerprint") or "") != expected:
        return None
    return doc


def resolve_uo_root(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / ".ascendc-pilot" / "uo"
