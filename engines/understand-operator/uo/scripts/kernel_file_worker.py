"""Kernel per-file facts worker and deterministic merge helpers."""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class KernelFileFacts:
    file_path: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    branches: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    functions: list[dict[str, Any]] = field(default_factory=list)
    loaded_fields: list[str] = field(default_factory=list)
    function_dicts: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "nodes": self.nodes,
            "edges": self.edges,
            "branches": self.branches,
            "unresolved": self.unresolved,
            "functions": self.functions,
            "loaded_fields": self.loaded_fields,
            "function_dicts": self.function_dicts,
        }


def node_sort_key(node: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(node.get("layer") or ""),
        str(node.get("role") or node.get("node_type") or ""),
        str(node.get("file_path") or ""),
        int(node.get("start_line") or 0),
        str(node.get("symbol") or node.get("name") or node.get("id") or ""),
    )


def edge_sort_key(edge: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(edge.get("type") or edge.get("edge_type") or ""),
        str(edge.get("source") or edge.get("source_id") or ""),
        str(edge.get("target") or edge.get("target_id") or ""),
        str(edge.get("id") or ""),
    )


def unresolved_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(item.get("kind") or ""),
        str(item.get("file_path") or item.get("file") or ""),
        int(item.get("line") or item.get("start_line") or 0),
        str(item.get("id") or ""),
    )


def merge_kernel_file_facts(facts_list: list[KernelFileFacts | dict[str, Any]]) -> dict[str, Any]:
    """Deterministically merge per-file kernel facts (parent reducer)."""
    ordered = sorted(
        facts_list,
        key=lambda item: str(
            item.file_path if isinstance(item, KernelFileFacts) else item.get("file_path") or ""
        ),
    )
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    function_dicts: list[dict[str, Any]] = []
    loaded_fields: set[str] = set()
    for item in ordered:
        payload = item.as_dict() if isinstance(item, KernelFileFacts) else item
        nodes.extend(payload.get("nodes") or [])
        edges.extend(payload.get("edges") or [])
        branches.extend(payload.get("branches") or [])
        unresolved.extend(payload.get("unresolved") or [])
        functions.extend(payload.get("functions") or [])
        function_dicts.extend(payload.get("function_dicts") or [])
        loaded_fields.update(str(v) for v in (payload.get("loaded_fields") or []))

    dedup_nodes: dict[str, dict[str, Any]] = {}
    for node in sorted(nodes, key=node_sort_key):
        nid = str(node.get("id") or "")
        if nid:
            dedup_nodes[nid] = node
    dedup_edges: dict[str, dict[str, Any]] = {}
    for edge in sorted(edges, key=edge_sort_key):
        eid = str(edge.get("id") or "")
        if eid:
            dedup_edges[eid] = edge

    return {
        "nodes": list(dedup_nodes.values()),
        "edges": list(dedup_edges.values()),
        "branches": branches,
        "unresolved": sorted(unresolved, key=unresolved_sort_key),
        "functions": functions,
        "function_dicts": function_dicts,
        "loaded_fields": sorted(loaded_fields),
    }


def run_kernel_file_worker(args: tuple[Any, ...]) -> dict[str, Any]:
    """Parse one kernel source file; return local facts only (no shared writes)."""
    (
        repo_root_s,
        rel,
        text,
        architecture,
        file_entry_id,
        file_class,
        extraction_unit_id,
        path_family,
    ) = args
    import sys

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from uo.scripts._ir_io import stable_id
    from uo.scripts.extract_kernel_subgraph import (
        TDF_ASSIGN_RE,
        _function_definition_node,
        _line_for,
        _line_starts,
    )
    from uo.scripts.function_body import iter_function_definitions_from_text
    from uo.scripts.semantic_identity import mint_edge_id, mint_symbol_identity

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    loaded_fields: list[str] = []
    function_dicts: list[dict[str, Any]] = []

    file_fns = list(
        iter_function_definitions_from_text(
            Path(repo_root_s), rel, text, architecture=architecture
        )
    )
    class_ids: dict[str, str] = {}
    for fn in file_fns:
        function_dicts.append(fn.as_dict())
        fn_node = _function_definition_node(fn, extraction_unit_id=extraction_unit_id)
        nodes.append(fn_node)
        cls = fn.class_or_namespace or file_class or "Unknown"
        if cls not in class_ids:
            kcls = mint_symbol_identity(
                kind="kernel_class",
                name=cls,
                file_path=rel,
                qualified_name=cls,
                class_or_namespace=cls,
                architecture=architecture,
                path_family=path_family,
                prefix="KCLS",
            )
            class_ids[cls] = kcls.stable_id
            nodes.append(
                {
                    "id": kcls.stable_id,
                    "layer": "kernel",
                    "node_type": "KernelClass",
                    "name": cls,
                    "qualified_name": cls,
                    "file_path": rel,
                    "start_line": 0,
                    "end_line": 0,
                    "identity_key": kcls.identity_key,
                    "symbol_ref": kcls.as_dict(),
                    "extraction_unit_id": extraction_unit_id or None,
                }
            )
            edges.append(
                {
                    "id": mint_edge_id("contains", file_entry_id, kcls.stable_id),
                    "type": "contains",
                    "source": file_entry_id,
                    "target": kcls.stable_id,
                }
            )
        edges.append(
            {
                "id": mint_edge_id("contains", class_ids[cls], fn.stable_id),
                "type": "contains",
                "source": class_ids[cls],
                "target": fn.stable_id,
            }
        )

    file_scope_id = stable_id("FSCOPE_", rel)
    nodes.append(
        {
            "id": file_scope_id,
            "layer": "kernel",
            "node_type": "FileScope",
            "name": Path(rel).name,
            "qualified_name": rel,
            "file_path": rel,
            "start_line": 0,
            "end_line": 0,
        }
    )
    for match in TDF_ASSIGN_RE.finditer(text):
        tdf_path = match.group(2)
        leaf = str(tdf_path).split(".")[-1]
        if leaf:
            loaded_fields.append(leaf)

    return KernelFileFacts(
        file_path=rel,
        nodes=nodes,
        edges=edges,
        functions=[fn.as_dict() for fn in file_fns],
        function_dicts=function_dicts,
        loaded_fields=sorted(set(loaded_fields)),
    ).as_dict()


def parallel_kernel_file_enabled(*, explicit: bool | None = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return os.environ.get("UO_KERNEL_FILE_PARALLEL", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def map_kernel_files_parallel(
    jobs: list[tuple[Any, ...]],
    *,
    parallel: bool | None = None,
    min_files: int = 2,
    meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run file workers in sorted job order; never use completion order for ids.

    When ``meta`` is provided, records ``parallel_used`` / ``fallback`` /
    ``fallback_reason`` instead of silently swallowing ProcessPool failures.
    """
    ordered = sorted(jobs, key=lambda j: str(j[1]))  # rel is args[1]
    if meta is not None:
        meta.update(
            {
                "parallel_enabled": parallel_kernel_file_enabled(explicit=parallel),
                "file_count": len(ordered),
                "parallel_used": False,
                "fallback": False,
                "fallback_reason": "",
            }
        )
    if not parallel_kernel_file_enabled(explicit=parallel) or len(ordered) < min_files:
        return [run_kernel_file_worker(job) for job in ordered]
    try:
        with ProcessPoolExecutor(max_workers=min(4, len(ordered))) as pool:
            # Submit in sorted order; collect by index (not completion order).
            futures = [pool.submit(run_kernel_file_worker, job) for job in ordered]
            results = [fut.result() for fut in futures]
        if meta is not None:
            meta["parallel_used"] = True
        return results
    except Exception as exc:  # noqa: BLE001
        if meta is not None:
            meta["fallback"] = True
            meta["fallback_reason"] = f"{type(exc).__name__}: {exc}"[:300]
        return [run_kernel_file_worker(job) for job in ordered]
