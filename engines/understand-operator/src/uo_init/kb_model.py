# -*- coding: utf-8 -*-
"""In-memory graph model shared by export, index and query.

One graph with layered views, per `spec/kb_schema.yaml`. Everything the KB
asserts is a node or an edge, and everything a consumer might act on carries
`status`, `confidence` and at least one evidence reference.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml

from uo_init.ids import KIND_PREFIX, content_hash, edge_id, evidence_id, parse_kind

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "spec" / "kb_schema.yaml"

STATUS_EXTRACTED = "extracted"
STATUS_PARTIAL = "partial"
STATUS_UNRESOLVED = "unresolved"
STATUS_NOT_EXTRACTED = "not_extracted"

VALID_STATUSES = frozenset(
    {STATUS_EXTRACTED, STATUS_PARTIAL, STATUS_UNRESOLVED, STATUS_NOT_EXTRACTED}
)

# Roots a test generator can actually set when constructing a case. Everything
# else may still be "closed" but is not a control knob.
CONTROLLABLE_ROOTS = frozenset(
    {
        "INPUT_SHAPE",
        "INPUT_DTYPE",
        "INPUT_FORMAT",
        "INPUT_VALUE",
        "OPTIONAL_INPUT_PRESENCE",
        "ATTRIBUTE",
        "SESSION_OPTION",
    }
)

# Not knobs, but fixed once the CANN profile and build are chosen, so a case can
# still be constructed against them — they behave as constants at generation
# time rather than as unknowns.
PLATFORM_LOCKED_ROOTS = frozenset(
    {
        "PLATFORM_ARCH",
        "PLATFORM_CORE_COUNT",
        "PLATFORM_MEMORY_SIZE",
        "PLATFORM_L2_SIZE",
        "PLATFORM_AIV_COUNT",
        "COMPILE_INFO",
        "COMPILE_DEFINE",
        "TEMPLATE_LITERAL",
        "CONSTANT",
    }
)

#: How far a derivation got toward something a test case can drive. Orthogonal
#: to `exactness`, which only says whether the *expression* closed: a field can
#: be exact and still be undrivable. `IsTnd` is exactly that — its predicate form is
#: the single comparison `layoutType == 4`, with no free variables at all, but
#: `layoutType` is host state the resolver stopped on instead of the layout
#: attribute behind it, so nothing a generator sets reaches it.
IC_CONTROLLABLE = "controllable"
IC_PLATFORM_LOCKED = "platform_locked"
IC_HOST_STATE = "host_state"
IC_NONE = "none"


def classify_input_closure(roots: Iterable[str]) -> str:
    """Grade a set of input roots by whether a test case can drive them.

    Anything unrecognized counts as host state. Guessing the other way would
    report a dimension as drivable on the strength of a root nobody classified.
    """
    seen = {str(r) for r in roots if str(r)}
    if not seen:
        return IC_NONE
    if seen <= CONTROLLABLE_ROOTS:
        return IC_CONTROLLABLE
    if seen <= (CONTROLLABLE_ROOTS | PLATFORM_LOCKED_ROOTS):
        return IC_PLATFORM_LOCKED
    return IC_HOST_STATE


def input_closure_is_drivable(closure: str) -> bool:
    """A constant field is drivable: nothing needs setting to reach its value."""
    return closure in (IC_CONTROLLABLE, IC_PLATFORM_LOCKED, IC_NONE)


def load_schema() -> dict[str, Any]:
    return yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8")) or {}


@dataclass
class Evidence:
    id: str
    file: str
    line_start: int
    line_end: int
    snippet: str = ""
    source_hash: str = ""

    @classmethod
    def at(
        cls,
        file: str,
        line: int,
        *,
        snippet: str = "",
        line_end: int | None = None,
        root: str = "",
    ) -> "Evidence":
        end = int(line_end if line_end is not None else line)
        return cls(
            id=evidence_id(file, int(line), end, root),
            file=str(file).replace("\\", "/"),
            line_start=int(line),
            line_end=end,
            snippet=(snippet or "")[:400],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "snippet": self.snippet,
            "source_hash": self.source_hash,
        }


@dataclass
class Domain:
    """Value domain of a Variable.

    `completeness` is the honest part: `open` says the upper bound is a test
    策略 decision, not something the source proves.
    """

    var_id: str
    value_type: str = "int"
    lo: int | None = None
    hi: int | None = None
    values: list[Any] = field(default_factory=list)
    completeness: str = "open"
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "type": self.value_type,
            "completeness": self.completeness,
            "source": self.source,
        }
        if self.lo is not None:
            out["lo"] = self.lo
        if self.hi is not None:
            out["hi"] = self.hi
        if self.values:
            out["domain"] = list(self.values)
        return out


@dataclass
class Node:
    id: str
    kind: str
    name: str = ""
    layer: str = ""
    status: str = STATUS_EXTRACTED
    confidence: float = 1.0
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def evidence_refs(self) -> list[str]:
        return [e.id for e in self.evidence]

    def to_dict(self) -> dict[str, Any]:
        # Reserved identity fields must win over accidental data key collisions
        # (e.g. ctrl_kind historically stored as data["kind"]).
        out = dict(self.data)
        out.update(
            {
                "id": self.id,
                "kind": self.kind,
                "name": self.name,
                "layer": self.layer,
                "status": self.status,
                "confidence": round(float(self.confidence), 4),
                "evidence_refs": self.evidence_refs,
            }
        )
        return out


@dataclass
class Edge:
    id: str
    kind: str
    src: str
    dst: str
    status: str = STATUS_EXTRACTED
    confidence: float = 1.0
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def make(cls, kind: str, src: str, dst: str, **kw: Any) -> "Edge":
        return cls(id=edge_id(kind, src, dst), kind=kind, src=src, dst=dst, **kw)

    def to_dict(self) -> dict[str, Any]:
        out = {
            "id": self.id,
            "kind": self.kind,
            "src": self.src,
            "dst": self.dst,
            "status": self.status,
            "confidence": round(float(self.confidence), 4),
        }
        out.update(self.data)
        return out


@dataclass
class Blocker:
    """One normalization failure, with every node it holds open.

    This is the unit of LLM work. A single unresolved symbol commonly blocks
    dozens of branches, so batching by node would multiply the same question.
    """

    id: str
    text: str
    reason_code: str
    affected_nodes: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    hint: str = ""
    #: Variables an answer to this blocker may name. Not a hint: a condition
    #: mentioning anything else is rejected as invented, so a blocker without
    #: this leaves a model guessing at names it cannot see.
    readable_vars: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = {
            "id": self.id,
            "text": self.text,
            "reason_code": self.reason_code,
            "affected_node_count": len(self.affected_nodes),
            "affected_nodes": sorted(self.affected_nodes)[:50],
            "evidence_refs": [e.id for e in self.evidence],
            # Inline evidence so resolve_gaps staging can hand the LLM a closed
            # pack without a second index lookup.
            "evidence": [e.to_dict() for e in self.evidence[:5]],
            "hint": self.hint,
        }
        if self.readable_vars:
            out["readable_vars"] = list(self.readable_vars)
        return out


class KnowledgeBase:
    """Accumulates nodes, edges and evidence, then hands them to the exporter."""

    def __init__(self, op_name: str = "", architecture: str = "") -> None:
        self.op_name = op_name
        self.architecture = architecture
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}
        self.evidence: dict[str, Evidence] = {}
        self.domains: dict[str, Domain] = {}
        self.blockers: dict[str, Blocker] = {}
        self.notes: dict[str, Any] = {}

    # -- mutation ----------------------------------------------------------
    def add_node(self, node: Node) -> Node:
        if node.status not in VALID_STATUSES:
            raise ValueError(f"invalid status {node.status!r} on {node.id}")
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
        else:
            # Same entity reached from two extraction passes: union the
            # evidence rather than letting the later pass silently win.
            for ev in node.evidence:
                if ev.id not in {e.id for e in existing.evidence}:
                    existing.evidence.append(ev)
            existing.data.update(node.data)
            if node.status != STATUS_EXTRACTED:
                existing.status = node.status
            node = existing
        for ev in node.evidence:
            self.evidence.setdefault(ev.id, ev)
        return node

    def add_edge(self, edge: Edge) -> Edge:
        self.edges.setdefault(edge.id, edge)
        return self.edges[edge.id]

    def link(self, kind: str, src: str, dst: str, **kw: Any) -> Edge:
        return self.add_edge(Edge.make(kind, src, dst, **kw))

    def add_domain(self, domain: Domain) -> Domain:
        self.domains[domain.var_id] = domain
        return domain

    def add_blocker(self, blocker: Blocker) -> Blocker:
        existing = self.blockers.get(blocker.id)
        if existing is None:
            self.blockers[blocker.id] = blocker
            for ev in blocker.evidence:
                self.evidence.setdefault(ev.id, ev)
            return blocker
        for node_id in blocker.affected_nodes:
            if node_id not in existing.affected_nodes:
                existing.affected_nodes.append(node_id)
        for ev in blocker.evidence:
            if ev.id not in {e.id for e in existing.evidence}:
                existing.evidence.append(ev)
                self.evidence.setdefault(ev.id, ev)
        return existing

    # -- views -------------------------------------------------------------
    def by_kind(self, kind: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.kind == kind]

    def edges_from(self, node_id: str, kind: str | None = None) -> list[Edge]:
        return [
            e
            for e in self.edges.values()
            if e.src == node_id and (kind is None or e.kind == kind)
        ]

    def edges_to(self, node_id: str, kind: str | None = None) -> list[Edge]:
        return [
            e
            for e in self.edges.values()
            if e.dst == node_id and (kind is None or e.kind == kind)
        ]

    def iter_nodes(self) -> Iterator[Node]:
        return iter(sorted(self.nodes.values(), key=lambda n: n.id))

    def iter_edges(self) -> Iterator[Edge]:
        return iter(sorted(self.edges.values(), key=lambda e: e.id))

    # -- integrity ---------------------------------------------------------
    def check_invariants(self) -> list[str]:
        """Return every invariant violation; empty means the gate passes."""
        errors: list[str] = []
        for node in self.nodes.values():
            kind = parse_kind(node.id)
            if kind is None:
                errors.append(f"id_prefix_matches_kind: {node.id} has no known prefix")
            elif kind != node.kind:
                errors.append(
                    f"id_prefix_matches_kind: {node.id} declares kind={node.kind} "
                    f"but prefix maps to {kind}"
                )
            if node.status in (STATUS_EXTRACTED, STATUS_PARTIAL) and not node.evidence:
                errors.append(f"no_evidence_free_node: {node.id} ({node.kind})")
        for edge in self.edges.values():
            if edge.src not in self.nodes:
                errors.append(f"edge_endpoints_exist: {edge.id} src {edge.src} missing")
            if edge.dst not in self.nodes:
                errors.append(f"edge_endpoints_exist: {edge.id} dst {edge.dst} missing")
        for node in self.by_kind("Predicate"):
            owner = str(node.data.get("owner_id") or "")
            if owner and owner not in self.nodes:
                errors.append(f"predicate_owner_exists: {node.id} owner {owner} missing")
        return errors

    def fingerprint(self) -> str:
        """Content digest of the whole graph, for idempotence assertions."""
        return content_hash(
            {
                "nodes": [n.to_dict() for n in self.iter_nodes()],
                "edges": [e.to_dict() for e in self.iter_edges()],
                "domains": {k: v.to_dict() for k, v in sorted(self.domains.items())},
            }
        )
