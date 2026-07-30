# -*- coding: utf-8 -*-
"""Per-branch controllability records and honest closure metrics.

Two things live here because they answer the same question from both ends:

1. For every control node, what does a test case have to set to drive it true,
   and separately to drive it false. A branch is only covered when both sides
   are reachable, so one record per node would silently halve the obligation
   list. Satisfiability itself is left to TG's Z3 — this layer states the
   constraint, it does not solve it.

2. How much of the operator is actually pinned down. `source_closure` counts a
   branch tracked to any root, including loop counters and constants;
   `input_controllability` counts only branches a test case can steer. Quoting
   the first number alone makes an operator look understood when nothing about
   it can be varied on purpose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from uo_init.ids import branch_id as make_branch_id
from uo_init.ids import predicate_id
from uo_init.kb_model import CONTROLLABLE_ROOTS, Evidence
from uo_init.predicate import NormalizedPredicate, PredicateNormalizer, conjoin
from uo_init.source_resolver import LEGAL_ROOTS, SourceResolver

# Roots that close a lineage but give a test case nothing to set.
NON_STEERABLE_ROOTS = frozenset(LEGAL_ROOTS) - CONTROLLABLE_ROOTS


@dataclass
class BranchRecord:
    """One control node driven to one target value."""

    branch_id: str
    side: str
    kind: str
    file: str
    line: int
    function: str
    condition: str
    target_value: bool
    guard: dict[str, Any] | None = None
    path_condition: dict[str, Any] | None = None
    controlling_vars: list[str] = field(default_factory=list)
    source_roots: list[str] = field(default_factory=list)
    status: str = "extracted"
    unresolved_reason: str = ""
    dropped_path_guards: int = 0

    @property
    def predicate_id(self) -> str:
        canonical = str(self.guard) if self.guard is not None else self.condition
        return predicate_id(self.branch_id, self.target_value, canonical)

    @property
    def input_controllable(self) -> bool:
        return bool(self.controlling_vars) and any(
            r in CONTROLLABLE_ROOTS for r in self.source_roots
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.predicate_id,
            "branch_id": self.branch_id,
            "side": self.side,
            "kind": self.kind,
            "function": self.function,
            "condition": self.condition,
            "target_value": self.target_value,
            "controlling_vars": list(self.controlling_vars),
            "source_roots": list(self.source_roots),
            "input_controllable": self.input_controllable,
            "status": self.status,
            "file": self.file,
            "line": self.line,
        }
        if self.guard is not None:
            out["guard"] = self.guard
        if self.path_condition is not None:
            out["path_condition"] = self.path_condition
        if self.unresolved_reason:
            out["unresolved_reason"] = self.unresolved_reason
        if self.dropped_path_guards:
            out["dropped_path_guards"] = self.dropped_path_guards
        return out


@dataclass
class NodeAnalysis:
    """Everything derived from one control node, before it is split by polarity."""

    node: Any
    branch_id: str
    own: NormalizedPredicate
    path: list[NormalizedPredicate]
    roots: list[str]
    closed: bool
    partial: bool
    reasons: list[str]
    # Kept so the gap clusterer can name the exact atom that failed, rather
    # than attributing the whole guard to one reason code.
    atoms: list[Any] = field(default_factory=list)

    def evidence(self) -> Evidence:
        return Evidence.at(
            self.node.file,
            self.node.line,
            snippet=(self.node.condition or self.node.snippet or "")[:200],
        )


class ControllabilityBuilder:
    """Analyses control nodes once and emits both polarities per node."""

    def __init__(
        self,
        resolver: SourceResolver,
        model,
        *,
        side: str = "host",
        op_root: str = "",
    ) -> None:
        self.resolver = resolver
        self.model = model
        self.side = side
        self.op_root = op_root
        self.normalizer = PredicateNormalizer(resolver, model)
        self._ordinals: dict[tuple[str, str, str], int] = {}

    def _next_ordinal(self, file: str, function: str, guard: str) -> int:
        key = (file, function, guard)
        n = self._ordinals.get(key, 0)
        self._ordinals[key] = n + 1
        return n

    def _scoped(self, node) -> SourceResolver:
        """Resolve a node's guard with its own function's locals in view."""
        host_ir = self.resolver.host_ir
        if host_ir is None or not node.function:
            base = self.resolver
        else:
            bindings = dict(host_ir.locals_by_function().get(node.function, {}))
            bindings.update(host_ir.output_bindings_by_function().get(node.function, {}))
            base = self.resolver.scoped(
                bindings=bindings,
                def_lists=host_ir.defs_by_function().get(node.function, {}),
                parameters=host_ir.params_by_function().get(node.function, set()),
                param_actuals=host_ir.param_bindings().get(node.function, {}),
            )
        if node.induction_vars:
            base = base.scoped(
                local_roots={v: "LOOP_INDUCTION" for v in node.induction_vars}
            )
        return base

    def analyse(self, node) -> NodeAnalysis:
        resolver = self._scoped(node)
        normalizer = PredicateNormalizer(resolver, self.model)
        own = normalizer.normalize(node.condition or "")
        path = [
            normalizer.normalize(pc.pretty())
            for pc in node.path_conditions
            if not pc.is_opaque
        ]
        res = resolver.resolve(node.condition or "")
        closed = res.closed
        roots = list(res.roots)
        reasons = list(res.reasons)
        # Macro / truncated text that collapsed to a C++ keyword is not a real
        # operator-authored guard — treat as closed constant noise.
        kw = (node.condition or "").strip()
        if (
            not closed
            and kw
            in {"for", "while", "if", "switch", "return", "do", "sizeof"}
            and (
                all(r.split(":")[0] == "NO_CONDITION_TEXT" for r in reasons)
                or all(r.split(":")[0] == "UNMAPPED_SYMBOL" for r in reasons)
                or all(r.split(":")[0] == "UNMAPPED_CALL" for r in reasons)
            )
        ):
            closed = True
            roots = ["CONSTANT"]
            reasons = []
        # Align with lineage: loop headers whose only open atoms are induction
        # variables are closed as LOOP_INDUCTION.
        if (
            not closed
            and getattr(node, "kind", "") in ("for", "while", "do", "cxx_for_range")
            and node.induction_vars
        ):
            open_atoms = [a for a in res.atoms if a.reason or a.partial]
            if open_atoms and all(
                (a.symbol in node.induction_vars)
                or (a.text in node.induction_vars)
                or (a.root == "LOOP_INDUCTION")
                for a in open_atoms
            ):
                closed = True
                roots = roots or ["LOOP_INDUCTION"]
                reasons = []
        # Pure FUNCTION_PARAMETER atoms whose formals only ever receive
        # Params-derived or constant actuals — close with that root.
        if not closed and reasons == ["FUNCTION_PARAMETER"] and res.atoms:
            upgraded = _close_params_as_derived(resolver, res.atoms)
            if upgraded is not None:
                closed = True
                roots = [upgraded]
                reasons = []
        # Range-for / opaque loop headers: no readable guard beyond induction.
        if (
            not closed
            and getattr(node, "kind", "") in ("for", "while", "do", "cxx_for_range")
            and (
                "NO_CONDITION_TEXT" in {r.split(":")[0] for r in reasons}
                or not (node.condition or "").strip()
                or (node.condition or "").lstrip().startswith(("for", "while", "do"))
            )
        ):
            closed = True
            roots = ["LOOP_INDUCTION"] if node.induction_vars else ["CONSTANT"]
            reasons = []
        bid = make_branch_id(
            side=self.side,
            file=node.file,
            function=node.function,
            # The normalized form makes the id immune to reformatting; when
            # normalization failed the collapsed text is the best available.
            guard=own.canonical,
            ordinal=self._next_ordinal(node.file, node.function, own.canonical),
            root=self.op_root,
        )
        return NodeAnalysis(
            node=node,
            branch_id=bid,
            own=own,
            path=path,
            roots=roots,
            closed=closed,
            partial=res.partial and not closed,
            reasons=reasons,
            atoms=list(res.atoms),
        )

    def records_for(self, analysis: NodeAnalysis) -> list[BranchRecord]:
        node = analysis.node
        path_smt = conjoin(analysis.path)
        dropped = sum(1 for p in analysis.path if not p.ok)
        out: list[BranchRecord] = []
        for target in (True, False):
            pred = analysis.own if target else analysis.own.negated()
            status = "extracted" if pred.ok else "unresolved"
            variables = sorted(set(pred.variables) | _vars_of(analysis.path))
            out.append(
                BranchRecord(
                    branch_id=analysis.branch_id,
                    side=self.side,
                    kind=node.kind,
                    file=node.file,
                    line=node.line,
                    function=node.function,
                    condition=node.condition or "",
                    target_value=target,
                    guard=pred.smt,
                    path_condition=path_smt,
                    controlling_vars=variables,
                    source_roots=list(analysis.roots),
                    status=status,
                    unresolved_reason=pred.reason,
                    dropped_path_guards=dropped,
                )
            )
        return out

    def build(self, nodes: Iterable[Any]) -> tuple[list[NodeAnalysis], list[BranchRecord]]:
        analyses = [self.analyse(n) for n in nodes]
        records: list[BranchRecord] = []
        for a in analyses:
            records.extend(self.records_for(a))
        return analyses, records


def _vars_of(preds: list[NormalizedPredicate]) -> set[str]:
    out: set[str] = set()
    for p in preds:
        out |= set(p.variables)
    return out


def _close_params_as_derived(resolver, atoms) -> str | None:
    """If every failing atom is a formal whose actuals are Params/constant, close."""
    from uo_init.source_resolver import _PARAMS_DERIVED_RE, _norm_expr

    root = None
    for a in atoms:
        if (a.reason or "").split(":")[0] != "FUNCTION_PARAMETER":
            return None
        sym = a.symbol or a.text
        actuals = resolver.param_actuals.get(sym, [])
        if not actuals:
            return None
        for actual in actuals:
            act = _norm_expr(actual)
            if _PARAMS_DERIVED_RE.search(act):
                root = root or "TILING_DATA"
                continue
            sub = resolver.resolve(act)
            if sub.closed and sub.roots:
                if all(r in ("CONSTANT", "TILING_DATA", "LOOP_INDUCTION") for r in sub.roots):
                    root = root or sub.roots[0]
                    continue
                if all(
                    r.startswith("INPUT_") or r in ("ATTRIBUTE", "OPTIONAL_INPUT_PRESENCE")
                    for r in sub.roots
                ):
                    root = root or sub.roots[0]
                    continue
            return None
    return root


@dataclass
class ClosureMetrics:
    total_nodes: int = 0
    closed_nodes: int = 0
    partial_nodes: int = 0
    open_nodes: int = 0
    controllable_nodes: int = 0
    normalized_predicates: int = 0
    total_predicates: int = 0
    root_histogram: dict[str, int] = field(default_factory=dict)
    reason_histogram: dict[str, int] = field(default_factory=dict)

    @property
    def source_closure(self) -> float:
        return _ratio(self.closed_nodes, self.total_nodes)

    @property
    def input_controllability(self) -> float:
        return _ratio(self.controllable_nodes, self.total_nodes)

    @property
    def predicate_normalization(self) -> float:
        return _ratio(self.normalized_predicates, self.total_predicates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "closed_nodes": self.closed_nodes,
            "partial_nodes": self.partial_nodes,
            "open_nodes": self.open_nodes,
            "controllable_nodes": self.controllable_nodes,
            "source_closure": self.source_closure,
            "input_controllability": self.input_controllability,
            "predicate_normalization": self.predicate_normalization,
            "root_histogram": dict(sorted(self.root_histogram.items())),
            "reason_histogram": dict(sorted(self.reason_histogram.items())),
            "note": (
                "source_closure counts any legal root; input_controllability "
                "counts only roots a test case can set"
            ),
        }


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def measure(
    analyses: list[NodeAnalysis], records: list[BranchRecord]
) -> ClosureMetrics:
    m = ClosureMetrics(total_nodes=len(analyses))
    controllable_ids: set[str] = set()
    for a in analyses:
        if a.closed:
            m.closed_nodes += 1
        elif a.partial:
            m.partial_nodes += 1
        else:
            m.open_nodes += 1
        for r in a.roots:
            m.root_histogram[r] = m.root_histogram.get(r, 0) + 1
        for reason in a.reasons:
            m.reason_histogram[reason] = m.reason_histogram.get(reason, 0) + 1
    for rec in records:
        m.total_predicates += 1
        if rec.status == "extracted":
            m.normalized_predicates += 1
        if rec.input_controllable:
            controllable_ids.add(rec.branch_id)
    m.controllable_nodes = len(controllable_ids)
    return m
