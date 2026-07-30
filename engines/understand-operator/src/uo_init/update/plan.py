# -*- coding: utf-8 -*-
"""Plan which new-engine rebuild phases an update should run."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo_init.update.artifacts import (
    compute_plan_fingerprint,
    current_scope_identity,
    resolve_uo_root,
)
from uo_init.yaml_io import read_yaml, write_yaml

# Layers map onto uo_init.pilot_engines actions (not old build_layered_kb).
ALL_LAYERS = ("host", "tilingkey", "registry", "kernel", "normalize", "export")


def plan_kb_update(
    repo_root: Path,
    op_name: str,
    *,
    change_set: dict[str, Any] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    del op_name
    repo_root = Path(repo_root).expanduser().resolve()
    uo_root = resolve_uo_root(repo_root)
    change_set = change_set or read_yaml(uo_root / "diff" / "change_set.yaml")
    if not change_set:
        raise FileNotFoundError("diff/change_set.yaml missing; run detect_kb_changes first")

    layers: set[str] = set()
    reasons: list[str] = []
    needs_scope = bool(change_set.get("needs_scope_review"))
    scoped_files = [
        f for f in (change_set.get("files") or []) if isinstance(f, dict) and f.get("in_scope")
    ]

    for item in scoped_files:
        role = str(item.get("role") or "other").lower()
        path = str(item.get("path") or "").replace("\\", "/").lower()
        mapped = _layers_for_role(role, path)
        if mapped:
            layers.update(mapped)
            reasons.append(f"{item.get('path')}: role={role} -> {sorted(mapped)}")

    if layers & {"host", "tilingkey", "kernel"}:
        layers.add("normalize")
        layers.add("export")

    common_or_header = any(
        str(f.get("role") or "").lower() in {"common", "headers"}
        or "/common/" in str(f.get("path") or "").replace("\\", "/").lower()
        for f in scoped_files
    )
    if common_or_header:
        layers.update(ALL_LAYERS)
        reasons.append("common/headers change -> full uo_init rebuild")

    mode = "selective"
    if needs_scope and not scoped_files:
        mode = "blocked_scope"
    elif len(layers) >= len(ALL_LAYERS) - 1:
        mode = "full_extract"
        layers.update(ALL_LAYERS)
    if not layers and not needs_scope:
        mode = "noop"

    actions = _actions_for_layers(layers)
    scope_id = current_scope_identity(uo_root)
    scope_fingerprint = str(
        change_set.get("scope_fingerprint") or scope_id.get("scope_fingerprint") or ""
    )
    change_set_fingerprint = str(
        change_set.get("change_set_fingerprint") or change_set.get("fingerprint") or ""
    )
    plan_fingerprint = compute_plan_fingerprint(
        head_revision=str(change_set.get("head_revision") or ""),
        base_revision=str(change_set.get("base_revision") or ""),
        scope_fingerprint=scope_fingerprint,
        change_set_fingerprint=change_set_fingerprint,
        mode=mode,
        affected_layers=sorted(layers),
    )
    plan = {
        "version": 1,
        "op_name": change_set.get("op_name"),
        "base_revision": change_set.get("base_revision"),
        "head_revision": change_set.get("head_revision"),
        "scope_fingerprint": scope_fingerprint,
        "change_set_fingerprint": change_set_fingerprint,
        "plan_fingerprint": plan_fingerprint,
        "mode": mode,
        "affected_layers": sorted(layers),
        "actions": actions,
        "scripts": actions,  # compat with older consumers
        "needs_scope_review": needs_scope,
        "needs_cbm_reindex": bool(scoped_files) or needs_scope,
        "needs_llm_resolve": False,
        "scoped_changed_files": [str(f.get("path")) for f in scoped_files],
        "reasons": reasons,
        "engine": "uo_init.update",
    }
    if write:
        out_dir = uo_root / "summary"
        out_dir.mkdir(parents=True, exist_ok=True)
        write_yaml(out_dir / "update_plan.yaml", plan)
    return plan


def _layers_for_role(role: str, path: str) -> set[str]:
    if role in {"tilingkey"} or "template_tiling_key" in path:
        return {"tilingkey", "normalize", "export"}
    if role in {"kernel"}:
        return {"kernel", "normalize", "export"}
    if role in {"host", "tiling"}:
        return {"host", "tilingkey", "registry", "normalize", "export"}
    if role in {"golden"}:
        return {"export"}
    if role in {"api", "input_output", "proto"}:
        return {"host", "registry", "normalize", "export"}
    if role in {"common", "headers"}:
        return set(ALL_LAYERS)
    if role in {"other", ""}:
        return {"host", "tilingkey", "kernel", "normalize", "export"}
    return set()


def _actions_for_layers(layers: set[str]) -> list[str]:
    ordered: list[str] = []
    if "host" in layers:
        ordered.append("extract_host")
    if "tilingkey" in layers:
        ordered.append("extract_tiling_key")
    if "registry" in layers:
        ordered.append("extract_registry")
    if "kernel" in layers:
        ordered.append("extract_kernel")
    if "normalize" in layers:
        ordered.extend(["normalize_variables", "normalize_predicates"])
    if "export" in layers or layers:
        ordered.extend(["export_kb", "build_index", "export_integrity"])
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for a in ordered:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out
