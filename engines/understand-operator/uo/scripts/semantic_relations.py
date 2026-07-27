"""Atomic semantic relation types for input-rooted Relation Graph.

Authority: policies/evidence — roles/sinks are derived from relations;
intermediate locals are never roots.
"""
from __future__ import annotations

from typing import Any, Iterable

RELATION_TYPES = frozenset(
    {
        "BINDS",
        "WRITES",
        "READS",
        "DERIVES",
        "EQUIVALENT_TO",
        "COMPOSES_KEY",
        "CONTRIBUTES_TO_KEY",
        "GUARDS",
        "SELECTS_TEMPLATE",
        "GROUNDED_IN",
        "CALLS",
        "REACHABLE",
    }
)

ENTITY_KINDS = frozenset(
    {
        "input_root",
        "local",
        "param",
        "receiver",
        "tiling_field",
        "function",
        "macro",
        "condition",
        "branch",
        "template",
        "key",
        "key_dimension",
        "unknown",
    }
)

INPUT_ROOT_KINDS = frozenset(
    {
        "shape_dim",  # B/N/S/D or declared shape dims
        "layout",
        "dtype",
        "attr",
        "optional_tensor",
        "tensor",
        "other_input",
    }
)


def make_entity(
    *,
    entity_id: str,
    kind: str,
    symbol: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind_s = str(kind or "unknown").strip()
    if kind_s not in ENTITY_KINDS:
        kind_s = "unknown"
    out: dict[str, Any] = {
        "id": str(entity_id or "").strip(),
        "kind": kind_s,
        "symbol": str(symbol or entity_id or "").strip(),
    }
    if extra:
        out.update(extra)
    return out


def make_relation(
    *,
    relation_id: str,
    relation_type: str,
    subject: str,
    object: str = "",
    evidence_refs: Iterable[str] | None = None,
    origin: str = "deterministic",
    confidence: str = "high",
    inputs: Iterable[str] | None = None,
    status: str = "confirmed",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rtype = str(relation_type or "").strip().upper()
    if rtype not in RELATION_TYPES:
        raise ValueError(f"unknown relation type: {relation_type}")
    out: dict[str, Any] = {
        "id": str(relation_id or "").strip(),
        "type": rtype,
        "subject": str(subject or "").strip(),
        "object": str(object or "").strip(),
        "evidence_refs": [str(x) for x in (evidence_refs or []) if str(x).strip()],
        "origin": str(origin or "deterministic").strip(),
        "confidence": str(confidence or "medium").strip(),
        "status": str(status or "confirmed").strip(),
    }
    if inputs is not None:
        out["inputs"] = [str(x) for x in inputs if str(x).strip()]
    if extra:
        for k, v in extra.items():
            if k not in out:
                out[k] = v
    return out


def empty_relation_graph(*, version: int = 1) -> dict[str, Any]:
    return {
        "version": version,
        "entities": [],
        "relations": [],
        "unresolved": [],
        "input_roots": [],
    }


def index_entities(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for e in graph.get("entities") or []:
        if isinstance(e, dict) and e.get("id"):
            out[str(e["id"])] = e
    return out


def index_relations_by_type(graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in RELATION_TYPES}
    for r in graph.get("relations") or []:
        if not isinstance(r, dict):
            continue
        t = str(r.get("type") or "").upper()
        if t in out:
            out[t].append(r)
    return out


def is_input_root_entity(entity: dict[str, Any] | None) -> bool:
    if not isinstance(entity, dict):
        return False
    if str(entity.get("kind") or "") == "input_root":
        return True
    return str(entity.get("input_kind") or "") in INPUT_ROOT_KINDS


__all__ = [
    "RELATION_TYPES",
    "ENTITY_KINDS",
    "INPUT_ROOT_KINDS",
    "make_entity",
    "make_relation",
    "empty_relation_graph",
    "index_entities",
    "index_relations_by_type",
    "is_input_root_entity",
]
