from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo._operator.spec import spec_bundle_hash
from uo.scripts._ir_io import read_yaml, write_yaml

ALL_LAYERS = ("entrypoints", "host", "kernel", "tilingkey", "golden", "bridge")


def plan_kb_update(
    repo_root: Path,
    op_name: str,
    *,
    change_set: dict[str, Any] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    change_set = change_set or read_yaml(uo_root / "diff" / "change_set.yaml") or read_yaml(uo_root / "summary" / "change_set.yaml")
    if not change_set:
        raise FileNotFoundError("change_set.yaml missing; run detect_kb_changes first")

    layers: set[str] = set()
    scripts: list[str] = []
    reasons: list[str] = []
    needs_scope = bool(change_set.get("needs_scope_review"))
    scoped_files = [f for f in (change_set.get("files") or []) if isinstance(f, dict) and f.get("in_scope")]

    for item in scoped_files:
        role = str(item.get("role") or "other").lower()
        path = str(item.get("path") or "").replace("\\", "/").lower()
        mapped = _layers_for_role(role, path)
        if mapped:
            layers.update(mapped)
            reasons.append(f"{item.get('path')}: role={role} -> {sorted(mapped)}")

    # Always rebuild bridge when any structural layer changes
    if layers & {"host", "kernel", "tilingkey"}:
        layers.add("bridge")

    # Entrypoint re-resolve when host/kernel symbols may move
    if layers & {"host", "kernel"}:
        layers.add("entrypoints")

    common_or_header = any(
        str(f.get("role") or "").lower() in {"common", "headers"} or "/common/" in str(f.get("path") or "").replace("\\", "/").lower()
        for f in scoped_files
    )
    if common_or_header:
        layers.update(ALL_LAYERS)
        reasons.append("common/headers change -> conservative full extract")

    manifest = read_yaml(uo_root / "manifest.yaml")
    expected_hash = str((manifest.get("spec") or {}).get("bundle_hash") or "")
    current_hash = spec_bundle_hash()
    if expected_hash and expected_hash != current_hash:
        layers.update(ALL_LAYERS)
        needs_scope = True
        reasons.append("spec_bundle_hash mismatch -> full extract + scope review")

    mode = "selective"
    if needs_scope or not scoped_files and change_set.get("files"):
        # out-of-scope-only changes with suspicious files still block
        if needs_scope and not scoped_files:
            mode = "blocked_scope"
        elif len(layers) >= len(ALL_LAYERS) - 1:
            mode = "full_extract"
            layers.update(ALL_LAYERS)
    if len(layers) >= len(ALL_LAYERS) - 1:
        mode = "full_extract" if mode != "blocked_scope" else mode
        layers.update(ALL_LAYERS)

    if not layers and not needs_scope:
        mode = "noop"

    scripts = _scripts_for_layers(layers)
    needs_cbm_reindex = bool(scoped_files) or needs_scope

    plan = {
        "version": 1,
        "op_name": op_name,
        "base_revision": change_set.get("base_revision"),
        "head_revision": change_set.get("head_revision"),
        "mode": mode,
        "affected_layers": sorted(layers),
        "scripts": scripts,
        "needs_scope_review": needs_scope,
        "needs_cbm_reindex": needs_cbm_reindex,
        "needs_llm_resolve": "entrypoints" in layers,
        "scoped_changed_files": [str(f.get("path")) for f in scoped_files],
        "reasons": reasons,
    }
    if write:
        out_dir = uo_root / "summary"
        out_dir.mkdir(parents=True, exist_ok=True)
        write_yaml(out_dir / "update_plan.yaml", plan)
    return plan


def _layers_for_role(role: str, path: str) -> set[str]:
    if role in {"tilingkey"} or "template_tiling_key" in path:
        return {"tilingkey", "bridge"}
    if role in {"kernel"}:
        return {"kernel", "bridge", "entrypoints"}
    if role in {"host", "tiling"}:
        return {"host", "bridge", "entrypoints"}
    if role in {"golden"} or path.endswith("cpu_impl.py") or "golden" in path:
        return {"golden"}
    if role in {"api", "input_output", "proto"}:
        return {"host", "golden", "bridge", "entrypoints"}
    if role in {"common", "headers"}:
        return set(ALL_LAYERS)
    if role in {"other", ""}:
        # unknown scoped role: conservative
        return {"host", "kernel", "tilingkey", "bridge", "entrypoints"}
    return set()


def _scripts_for_layers(layers: set[str]) -> list[str]:
    ordered: list[str] = []
    if "entrypoints" in layers:
        ordered.append("resolve_entrypoints")
    if "tilingkey" in layers:
        ordered.append("extract_tilingkey_space")
    if "host" in layers:
        ordered.append("extract_host_subgraph")
    if "kernel" in layers:
        ordered.append("extract_kernel_subgraph")
    if "golden" in layers:
        ordered.append("extract_golden")
    if "bridge" in layers or layers & {"host", "kernel", "tilingkey"}:
        if "reconcile_bridge" not in ordered:
            ordered.append("reconcile_bridge")
    if layers:
        ordered.append("materialize_testcase_contract_files")
        if layers & {"host", "tilingkey"}:
            ordered.append("extract_key_predicates")
        ordered.append("validate_kb")
    return ordered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan selective KB update from change_set")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    plan = plan_kb_update(repo_root, op_name, write=not args.no_write)
    print(
        f"update_plan mode={plan['mode']} layers={plan['affected_layers']} "
        f"scope={plan['needs_scope_review']} cbm={plan['needs_cbm_reindex']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
