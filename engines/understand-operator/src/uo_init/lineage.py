# -*- coding: utf-8 -*-
"""Source lineage and closure gates."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from uo_init.expr_ir import Expr, Unknown, pretty
from uo_init.source_resolver import SourceResolver, resolve_with_path

LEGAL_ROOTS = {
    "INPUT_SHAPE",
    "INPUT_DTYPE",
    "INPUT_FORMAT",
    "INPUT_VALUE",
    "OPTIONAL_INPUT_PRESENCE",
    "ATTRIBUTE",
    "PLATFORM_ARCH",
    "PLATFORM_CORE_COUNT",
    "PLATFORM_MEMORY_SIZE",
    "COMPILE_INFO",
    "COMPILE_DEFINE",
    "TILING_KEY",
    "TILING_DATA",
    "TEMPLATE_LITERAL",
    "KERNEL_BUILTIN",
    "EXECUTION_ROLE",
    "LOOP_INDUCTION",
    "LOOP_DERIVED",
    "CONSTANT",
    "EXTERNAL",
    "UNKNOWN",
}


@dataclass
class Lineage:
    node_id: str
    root_kind: str
    expression: str
    reason_code: str | None = None
    roots: list[str] = field(default_factory=list)
    file: str = ""
    line: int = 0
    universe: str = "PRODUCTION"
    guards: list[str] = field(default_factory=list)
    via: list[str] = field(default_factory=list)
    function: str = ""
    kind: str = ""
    induction_vars: tuple[str, ...] = ()


@dataclass
class GateReport:
    branch_closed: int = 0
    branch_open: int = 0
    template_closed: int = 0
    schema_closed: int = 0
    lineage_closed: int = 0
    reasons: list[str] = field(default_factory=list)
    reason_histogram: dict[str, int] = field(default_factory=dict)
    root_histogram: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.branch_closed + self.branch_open

    @property
    def deterministic_closure(self) -> float:
        den = self.branch_closed + self.branch_open
        return (self.branch_closed / den) if den else 1.0


def terminate(root_kind: str, node_id: str, expr: str = "") -> Lineage:
    if root_kind not in LEGAL_ROOTS:
        return Lineage(node_id, "UNKNOWN", expr, reason_code="ILLEGAL_ROOT")
    return Lineage(node_id, root_kind, expr)


def mark_input_value_deps(indices: Iterable[int], names: list[str]) -> dict[int, str]:
    out = {}
    for i in indices:
        name = names[i] if i < len(names) else f"input_{i}"
        out[i] = f"INPUT_VALUE:{name}"
    return out


def tpl_vs_host_diff(
    legal: set[tuple],
    reachable: set[tuple],
) -> dict[str, list]:
    return {
        "declared_unreachable": sorted(legal - reachable),
        "reachable_undeclared": sorted(reachable - legal),
    }


def tnd_unroll(b: int, prefix: str = "actual_seq_qlen") -> list[str]:
    if b < 1:
        raise ValueError("B must be >= 1")
    return [f"{prefix}[{i}]" for i in range(b)]


LOOP_KINDS = ("for", "while", "do")


def lineage_for_node(
    node,
    resolver,
    func_locals: dict[str, dict[str, str]] | None = None,
    func_params: dict[str, set[str]] | None = None,
    param_actuals: dict[str, dict[str, list[str]]] | None = None,
) -> Lineage:
    """Resolve one BranchInventory control node to its root Sources."""
    fn = getattr(node, "function", "")
    scoped = resolver.scoped(
        bindings=(func_locals or {}).get(fn, {}),
        local_roots={v: "LOOP_INDUCTION" for v in getattr(node, "induction_vars", ())},
        parameters=(func_params or {}).get(fn, set()),
        param_actuals=(param_actuals or {}).get(fn, {}),
    )
    own, guards = resolve_with_path(node, scoped)
    guard_texts = [g.condition for g in guards]
    if not own.closed and node.kind in LOOP_KINDS and getattr(node, "induction_vars", ()):
        # A counted loop with no analysable bound is still rooted in its
        # induction variable; record that rather than reporting it as unknown.
        return Lineage(
            node_id=node.id,
            root_kind="LOOP_INDUCTION",
            expression=node.condition,
            roots=["LOOP_INDUCTION"] + [r for r in own.roots if r != "LOOP_INDUCTION"],
            file=node.file,
            line=node.line,
            universe=node.universe,
            guards=guard_texts,
            function=fn,
            kind=node.kind,
            induction_vars=tuple(getattr(node, "induction_vars", ())),
        )
    if own.closed:
        via: list[str] = []
        for a in own.atoms:
            via.extend(a.via)
        return Lineage(
            node_id=node.id,
            root_kind=own.roots[0] if own.roots else "CONSTANT",
            expression=node.condition,
            roots=own.roots,
            file=node.file,
            line=node.line,
            universe=node.universe,
            guards=guard_texts,
            via=via,
            function=fn,
            kind=node.kind,
            induction_vars=tuple(getattr(node, "induction_vars", ())),
        )
    reasons = own.reasons or ["UNKNOWN"]
    return Lineage(
        node_id=node.id,
        root_kind="UNKNOWN",
        expression=node.condition,
        reason_code=reasons[0],
        roots=own.roots,
        file=node.file,
        line=node.line,
        universe=node.universe,
        guards=guard_texts,
        function=fn,
        kind=node.kind,
        induction_vars=tuple(getattr(node, "induction_vars", ())),
    )


def build_lineages(
    inventory,
    resolver,
    *,
    universe: str | None = "PRODUCTION",
    func_locals: dict[str, dict[str, str]] | None = None,
    func_params: dict[str, set[str]] | None = None,
    param_actuals: dict[str, dict[str, list[str]]] | None = None,
) -> list[Lineage]:
    """One lineage per control node in the inventory. No node is skipped."""
    nodes = inventory.nodes if universe is None else inventory.by_universe(universe)
    return [
        lineage_for_node(n, resolver, func_locals, func_params, param_actuals)
        for n in nodes
    ]


def run_gates(
    *,
    lineages: list[Lineage],
    template_ok: int,
    schema_ok: bool,
) -> GateReport:
    rep = GateReport()
    for L in lineages:
        if L.reason_code:
            rep.branch_open += 1
            rep.reasons.append(f"{L.node_id}:{L.reason_code}")
            rep.reason_histogram[L.reason_code] = rep.reason_histogram.get(L.reason_code, 0) + 1
        else:
            rep.branch_closed += 1
            rep.lineage_closed += 1
            for r in L.roots or [L.root_kind]:
                rep.root_histogram[r] = rep.root_histogram.get(r, 0) + 1
    rep.template_closed = template_ok
    rep.schema_closed = 1 if schema_ok else 0
    return rep
