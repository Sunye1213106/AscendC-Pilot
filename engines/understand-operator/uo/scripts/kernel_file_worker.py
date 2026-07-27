"""Kernel per-file facts worker and deterministic merge helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "nodes": self.nodes,
            "edges": self.edges,
            "branches": self.branches,
            "unresolved": self.unresolved,
            "functions": self.functions,
            "loaded_fields": self.loaded_fields,
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
    loaded_fields: set[str] = set()
    for item in ordered:
        payload = item.as_dict() if isinstance(item, KernelFileFacts) else item
        nodes.extend(payload.get("nodes") or [])
        edges.extend(payload.get("edges") or [])
        branches.extend(payload.get("branches") or [])
        unresolved.extend(payload.get("unresolved") or [])
        functions.extend(payload.get("functions") or [])
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
        "loaded_fields": sorted(loaded_fields),
    }
