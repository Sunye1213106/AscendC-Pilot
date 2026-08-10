# -*- coding: utf-8 -*-
"""Detect in-scope source changes against the KB manifest revision."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from uo_init.update.artifacts import (
    OPERATOR_PATH_MARKERS,
    SOURCE_SUFFIXES,
    compute_change_set_fingerprint,
    current_scope_identity,
    git_head,
    infer_role,
    load_scope_index,
    resolve_uo_root,
)
from uo_init.yaml_io import read_yaml, write_yaml


def detect_kb_changes(
    repo_root: Path,
    op_name: str,
    *,
    base: str | None = None,
    head: str | None = None,
    write: bool = True,
) -> dict[str, Any]:
    del op_name  # op identity comes from project layout / manifest
    repo_root = Path(repo_root).expanduser().resolve()
    uo_root = resolve_uo_root(repo_root)
    if not (uo_root / "manifest.yaml").exists():
        raise FileNotFoundError(f"KB missing at {uo_root}; run /uo-init first")

    manifest = read_yaml(uo_root / "manifest.yaml")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    base_revision = (base or str(source.get("revision") or "")).strip()
    if not base_revision or base_revision == "unknown":
        # Soft fallback: treat current HEAD as base so first update after init works
        base_revision = git_head(repo_root) or "unknown"
    if not base_revision or base_revision == "unknown":
        raise ValueError("manifest.source.revision is unknown; run /uo-init first")

    head_revision = (head or git_head(repo_root)).strip() or "unknown"
    if head_revision == "unknown":
        raise ValueError("cannot resolve git HEAD")

    scope_index = load_scope_index(uo_root)
    name_status = _git_name_status(repo_root, base_revision, head_revision)

    files: list[dict[str, Any]] = []
    needs_scope_review = False
    for status, path in name_status:
        norm = path.replace("\\", "/")
        if _is_kb_artifact_path(norm):
            continue
        role = scope_index.get(norm, "")
        in_scope = norm in scope_index
        suspicious = (not in_scope) and _looks_like_operator_source(norm)
        if suspicious:
            needs_scope_review = True
        files.append(
            {
                "path": norm,
                "status": status,
                "in_scope": in_scope,
                "role": role or infer_role(norm),
                "suspicious_out_of_scope": suspicious,
            }
        )

    scope_id = current_scope_identity(uo_root)
    scope_fingerprint = str(scope_id.get("scope_fingerprint") or "")
    change_set_fingerprint = compute_change_set_fingerprint(
        head_revision=head_revision,
        base_revision=base_revision,
        scope_fingerprint=scope_fingerprint,
        changed_files=files,
    )
    payload = {
        "version": 1,
        "op_name": str(manifest.get("op_name") or repo_root.name),
        "base_revision": base_revision,
        "head_revision": head_revision,
        "scope_revision": scope_id.get("scope_revision"),
        "scope_fingerprint": scope_fingerprint,
        "confirmed_sources_hash": scope_id.get("confirmed_sources_hash"),
        "change_set_fingerprint": change_set_fingerprint,
        "fingerprint": change_set_fingerprint,
        "needs_scope_review": needs_scope_review,
        "scoped_change_count": sum(1 for item in files if item["in_scope"]),
        "files": files,
        "engine": "uo_init.update",
    }
    if write:
        out = uo_root / "diff" / "change_set.yaml"
        write_yaml(out, payload)
    return payload


def _git_name_status(repo_root: Path, base: str, head: str) -> list[tuple[str, str]]:
    if base == head:
        return []
    result = subprocess.run(
        ["git", "diff", "--name-status", f"{base}..{head}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # First init / shallow history: empty change set rather than hard fail
        return []
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][0].upper()
        path = parts[-1].replace("\\", "/")
        rows.append((status, path))
    return rows


def _is_kb_artifact_path(path: str) -> bool:
    norm = path.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.startswith(".ascendc-pilot/") or "/.ascendc-pilot/" in f"/{norm}"


def _looks_like_operator_source(path: str) -> bool:
    lower = path.lower()
    if Path(path).suffix.lower() not in SOURCE_SUFFIXES:
        return False
    return any(marker in lower for marker in OPERATOR_PATH_MARKERS)
