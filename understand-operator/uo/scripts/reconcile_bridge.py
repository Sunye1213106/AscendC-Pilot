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
from uo.scripts._ir_io import read_yaml, stable_id, write_yaml

# Compile-time / runtime symbols that extractors sometimes treat as tiling fields.
# Normalized via _norm_key (alnum + casefold).
_NON_TILING_KEYS = frozenset(
    {
        "origdtypequery",
        "gcoretype",
        "mmidx",
        "splitaxis",
        "aic",
        "aiv",
    }
)
_NON_TILING_PREFIXES = (
    "origdtype",
)


def reconcile_bridge(repo_root: Path, op_name: str) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    host = read_yaml(uo_root / "ir" / "host_subgraph.yaml")
    kernel = read_yaml(uo_root / "ir" / "kernel_subgraph.yaml")
    tilingkey = read_yaml(uo_root / "ir" / "tilingkey_space.yaml")

    host_by_key = _collect_fields(
        [
            str(n.get("name") or "").split(".")[-1]
            for n in host.get("nodes") or []
            if n.get("node_type") == "TilingDataField" and n.get("name")
        ]
    )
    # Prefer real node names over uppercase TDF_* id leftovers.
    tdf_nodes = {
        str(n.get("id")): str(n.get("name") or "").split(".")[-1]
        for n in host.get("nodes") or []
        if n.get("node_type") == "TilingDataField" and n.get("id")
    }
    for edge in host.get("edges") or []:
        if edge.get("type") != "writes":
            continue
        target = str(edge.get("target") or "")
        if target in tdf_nodes and tdf_nodes[target]:
            _add_field(host_by_key, tdf_nodes[target])
        elif target.startswith("TDF_"):
            _add_field(host_by_key, target.removeprefix("TDF_"))

    kernel_by_key = _collect_fields(list(kernel.get("loaded_tiling_fields") or []))
    for n in kernel.get("nodes") or []:
        if n.get("node_type") == "TilingDataField" and n.get("name"):
            _add_field(kernel_by_key, str(n.get("name")).split(".")[-1])

    # Drop known non-tiling symbols before set-diff (reduces LLM residual noise).
    host_by_key = {k: v for k, v in host_by_key.items() if not _is_non_tiling_key(k)}
    kernel_by_key = {k: v for k, v in kernel_by_key.items() if not _is_non_tiling_key(k)}

    host_keys = set(host_by_key)
    kernel_keys = set(kernel_by_key)
    unused_keys = sorted(host_keys - kernel_keys)
    missing_keys = sorted(kernel_keys - host_keys)
    unused = [host_by_key[k] for k in unused_keys]
    missing = [kernel_by_key[k] for k in missing_keys]

    diagnostics = []
    for field in unused:
        diagnostics.append(
            {
                "id": stable_id("DIAG_UNUSED_", field),
                "code": "unused_tiling_field",
                "field": field,
                "severity": "warning",
                "message": f"Host writes TilingDataField {field} but Kernel does not load it",
            }
        )
    for field in missing:
        diagnostics.append(
            {
                "id": stable_id("DIAG_MISSING_", field),
                "code": "missing_tiling_field_producer",
                "field": field,
                "severity": "warning",
                "message": f"Kernel loads TilingDataField {field} but Host graph has no write producer",
            }
        )

    bridge_nodes = []
    for n in (host.get("nodes") or []) + (kernel.get("nodes") or []) + (tilingkey.get("nodes") or []):
        if n.get("layer") == "bridge" or n.get("node_type") in {
            "TilingKey",
            "TilingDataField",
            "KernelTemplateArgument",
            "BlockDim",
            "Workspace",
            "KernelDispatch",
            "KernelEntry",
        }:
            bridge_nodes.append(n)

    by_id = {str(n.get("id")): n for n in bridge_nodes if n.get("id")}
    edges = []
    for edge in (host.get("edges") or []) + (kernel.get("edges") or []):
        if edge.get("type") in {"writes", "sets", "reserves", "dispatches", "selects", "loads_into", "determines"}:
            edges.append(edge)
    edge_by_id = {str(e.get("id")): e for e in edges if e.get("id")}

    unresolved = []
    for diag in diagnostics:
        unresolved.append(
            {
                "id": diag["id"],
                "kind": diag["code"],
                "message": diag["message"],
                "file_path": "",
                "snippet": diag["field"],
                "needs_llm": True,
            }
        )

    return {
        "version": 1,
        "op_name": op_name,
        "bridge_nodes": list(by_id.values()),
        "bridge_edges": list(edge_by_id.values()),
        "diagnostics": diagnostics,
        "unused_tiling_fields": unused,
        "missing_tiling_field_producers": missing,
        "unresolved": unresolved,
    }


def _norm_key(name: str) -> str:
    return "".join(ch for ch in str(name or "") if ch.isalnum()).casefold()


def _is_non_tiling_key(key: str) -> bool:
    k = str(key or "")
    if k in _NON_TILING_KEYS:
        return True
    return any(k.startswith(prefix) for prefix in _NON_TILING_PREFIXES)


def _prefer_display(existing: str, candidate: str) -> str:
    if not existing:
        return candidate
    if not candidate:
        return existing
    # Prefer camelCase / mixed over ALLCAPS dumps from TDF_* ids.
    if existing.isupper() and not candidate.isupper():
        return candidate
    if candidate.isupper() and not existing.isupper():
        return existing
    return existing if len(existing) >= len(candidate) else candidate


def _add_field(bucket: dict[str, str], raw: str) -> None:
    leaf = str(raw or "").split(".")[-1].strip()
    if not leaf:
        return
    key = _norm_key(leaf)
    if not key:
        return
    bucket[key] = _prefer_display(bucket.get(key, ""), leaf)


def _collect_fields(names: list[str]) -> dict[str, str]:
    bucket: dict[str, str] = {}
    for name in names:
        _add_field(bucket, name)
    return bucket


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile Host writes vs Kernel reads on bridge nodes")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    payload = reconcile_bridge(repo_root, op_name)
    if args.write:
        write_yaml(existing_operator_root(repo_root, op_name) / "ir" / "bridge.yaml", payload)
    print(
        f"bridge unused={len(payload['unused_tiling_fields'])} missing={len(payload['missing_tiling_field_producers'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
