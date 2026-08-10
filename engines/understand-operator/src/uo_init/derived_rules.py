# -*- coding: utf-8 -*-
"""Rules the solver proves for itself, rather than ones a reader wrote down.

A coverage run needs to know which TilingKeys it is allowed to give up on.
Those exclusions were being hand-written -- "NZ out needs 64 < D < 128", "swizzle
forces the BN2S2 split" -- each one a reading of the operator source that no
machine checked, in a list nobody could tell was complete.

But the same facts are already implied by the derivation: every dimension is an
expression over host state, so asking whether two dimension values can hold at
once is one UNSAT query against expressions that are already compiled. This
module asks all of them and writes down the contradictions.

Only UNSAT is used, which is the one direction the solver is trusted in: a
contradiction over sound expressions is a real exclusion, while SAT can come
from an over-approximated dimension admitting states the host never reaches.
So `unknown` never becomes a rule, and neither does a contradiction that leans
on symbols the derivation had to invent values for.

Two shapes come out:

- `value_unreachable` -- one dimension's value the expression cannot produce.
- `pair_exclusive` -- two values that cannot hold together.

and one read off the pair matrix rather than asked directly:

- `implication` -- `A=a` excludes every value of `B` but one, so `A=a` forces it.

Implications are the useful form for a reader ("IsNzOut=1 forces SplitAxis=0")
and the compact form for a searcher, but they are only as sound as the pairs
they summarise, so each one keeps the pairs it was folded from.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .key_reachability import R_UNREACHABLE, KeyVerdict

#: Rule kinds, narrowest first.
KIND_VALUE = "value_unreachable"
KIND_PAIR = "pair_exclusive"
KIND_IMPLICATION = "implication"

#: What produced a rule. The runtime side grades its own facts differently, so
#: the consumer can tell a proof from an observation; see the gate that reads
#: these back.
GRADE_SOLVER = "solver_derived"

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DerivedRule:
    """One exclusion, with the solver's own reason for it."""

    kind: str
    #: The values that cannot hold, as (dimension, value) pairs. For an
    #: implication this is the antecedent alone.
    excludes: tuple[tuple[str, Any], ...]
    #: Only for `implication`: what the antecedent leaves as the sole option.
    forces: tuple[str, Any] | None = None
    #: Labels of the assertions Z3 needed, straight from the unsat core. Reads
    #: as `asked:<dim>` for a value this query pinned and `derived:VAR_KEYDIM_*`
    #: for a dimension's definition.
    evidence: tuple[str, ...] = ()
    #: The pair rules an implication was folded from, so it can be rechecked
    #: without re-running the solver.
    folded_from: tuple[tuple[tuple[str, Any], ...], ...] = ()
    evidence_grade: str = GRADE_SOLVER

    @property
    def dims(self) -> tuple[str, ...]:
        named = [d for d, _ in self.excludes]
        if self.forces is not None:
            named.append(self.forces[0])
        return tuple(dict.fromkeys(named))

    def describe(self) -> str:
        """One line a reader can check against the operator source."""
        premise = " and ".join(f"{d}={v}" for d, v in self.excludes)
        if self.kind == KIND_VALUE:
            return f"{premise} is never produced"
        if self.kind == KIND_IMPLICATION and self.forces is not None:
            return f"{premise} forces {self.forces[0]}={self.forces[1]}"
        return f"{premise} cannot hold together"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "evidence_grade": self.evidence_grade,
            "statement": self.describe(),
            "excludes": [{"dim": d, "value": v} for d, v in self.excludes],
        }
        if self.forces is not None:
            out["forces"] = {"dim": self.forces[0], "value": self.forces[1]}
        if self.evidence:
            out["evidence"] = list(self.evidence)
        if self.folded_from:
            out["folded_from"] = [
                [{"dim": d, "value": v} for d, v in combo] for combo in self.folded_from
            ]
        return out


@dataclass
class RuleSet:
    """Every rule one solve pass produced, plus what it could not decide."""

    rules: list[DerivedRule] = field(default_factory=list)
    #: (dimension, value) pairs and pairs-of-pairs the solver gave up on. These
    #: are the gap: not excluded, not shown reachable.
    undecided: list[dict[str, Any]] = field(default_factory=list)
    #: Dimensions with no compiled expression, so nothing about them was asked.
    skipped: dict[str, str] = field(default_factory=dict)
    queries: int = 0
    #: Sub-counts, for telling a cheap pass from an exhaustive one.
    stats: dict[str, int] = field(default_factory=dict)

    def of_kind(self, kind: str) -> list[DerivedRule]:
        return [r for r in self.rules if r.kind == kind]

    def dead_values(self) -> set[tuple[str, Any]]:
        """(dimension, value) pairs proved unproducible on their own."""
        return {r.excludes[0] for r in self.rules if r.kind == KIND_VALUE}

    def to_dict(self, *, provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
        doc: dict[str, Any] = {"version": SCHEMA_VERSION}
        if provenance:
            doc.update(dict(provenance))
        doc["counts"] = {
            "rules": len(self.rules),
            KIND_VALUE: len(self.of_kind(KIND_VALUE)),
            KIND_PAIR: len(self.of_kind(KIND_PAIR)),
            KIND_IMPLICATION: len(self.of_kind(KIND_IMPLICATION)),
            "undecided": len(self.undecided),
            "queries": self.queries,
            **self.stats,
        }
        if self.skipped:
            doc["skipped_dimensions"] = dict(self.skipped)
        doc["rules"] = [r.to_dict() for r in self.rules]
        if self.undecided:
            doc["undecided"] = list(self.undecided)
        return doc


def source_hash(*payloads: bytes | str) -> str:
    """What the rules were derived from, so a stale file is detectable.

    A rule outlives the derivation that proved it only by accident; anything
    reading these back has to be able to tell that the expressions have since
    changed.
    """
    digest = hashlib.sha256()
    for item in payloads:
        digest.update(item.encode("utf-8") if isinstance(item, str) else item)
    return digest.hexdigest()


def _normalise(candidates: Mapping[str, Sequence[Any]]) -> dict[str, list[Any]]:
    """Candidate values as the solver wants them, order preserved."""
    from .key_reachability import _target_value

    out: dict[str, list[Any]] = {}
    for dim, raw in candidates.items():
        values: list[Any] = []
        for item in raw:
            value = _target_value(item)
            if value is None or value in values:
                continue
            values.append(value)
        if values:
            out[dim] = values
    return out


def derive_rules(
    reach: Any,
    candidates: Mapping[str, Sequence[Any]],
    *,
    pairs: bool = True,
    implications: bool = True,
    on_progress: Callable[[str, int, int], None] | None = None,
    pair_slice: tuple[int, int] | None = None,
) -> RuleSet:
    """Ask the solver for every exclusion among these candidate values.

    `candidates` is the declared value domain per dimension -- the template's,
    not this module's business to know. Dimensions absent from it, or with no
    compiled expression, are reported as skipped rather than assumed total.

    `pair_slice=(index, count)` runs only every `count`-th pair, so a full
    scan can be split across several cheap invocations instead of one long
    one; singles and implications always run whole (implications fold whatever
    this slice proved, and are only total on the last slice).
    """
    out = RuleSet()
    domains = _normalise(candidates)
    compiled = dict(getattr(reach, "_dims", {}) or {})
    # A dimension whose UNSAT the reachability layer refuses to trust cannot
    # yield a rule, however long the solver is given. Dropping it here is not
    # a shortcut in the answer, only in the bill: every query it would take
    # part in ends as `undecided` either way.
    unprovable = set(getattr(reach, "unprovable_dims", ()) or ())
    for dim in sorted(domains):
        if dim not in compiled:
            out.skipped[dim] = "no compiled expression"
        elif dim in unprovable:
            out.skipped[dim] = "under-approximated: UNSAT would not be trusted"
    live = {
        d: v for d, v in domains.items()
        if d in compiled and d not in unprovable
    }

    def ask(combo: dict[str, Any]) -> KeyVerdict:
        out.queries += 1
        return reach.joint_verdict(combo)

    # -- one dimension at a time -------------------------------------------
    # A value that cannot be produced on its own makes every pair containing it
    # vacuous, so this pass both yields the sharpest rules and prunes the next.
    dead: set[tuple[str, Any]] = set()
    singles = [(d, v) for d in sorted(live) for v in live[d]]
    for index, (dim, value) in enumerate(singles):
        if on_progress:
            on_progress(KIND_VALUE, index, len(singles))
        answer = ask({dim: value})
        if answer.status == R_UNREACHABLE:
            dead.add((dim, value))
            out.rules.append(
                DerivedRule(
                    kind=KIND_VALUE,
                    excludes=((dim, value),),
                    evidence=answer.unsat_core,
                )
            )
        elif answer.status != "reachable":
            out.undecided.append(
                {
                    "kind": KIND_VALUE,
                    "excludes": [{"dim": dim, "value": value}],
                    "status": answer.status,
                    "reason": answer.reason,
                }
            )
    out.stats["values_excluded"] = len(dead)

    if not pairs:
        return out

    # -- two at a time -----------------------------------------------------
    names = sorted(live)
    todo = [
        (a, va, b, vb)
        for i, a in enumerate(names)
        for b in names[i + 1 :]
        for va in live[a]
        if (a, va) not in dead
        for vb in live[b]
        if (b, vb) not in dead
    ]
    if pair_slice is not None:
        index0, count = pair_slice
        todo = todo[index0::count]
    exclusive: set[tuple[tuple[str, Any], tuple[str, Any]]] = set()
    for index, (a, va, b, vb) in enumerate(todo):
        if on_progress:
            on_progress(KIND_PAIR, index, len(todo))
        answer = ask({a: va, b: vb})
        if answer.status == R_UNREACHABLE:
            exclusive.add(((a, va), (b, vb)))
            out.rules.append(
                DerivedRule(
                    kind=KIND_PAIR,
                    excludes=((a, va), (b, vb)),
                    evidence=answer.unsat_core,
                )
            )
        elif answer.status != "reachable":
            out.undecided.append(
                {
                    "kind": KIND_PAIR,
                    "excludes": [{"dim": a, "value": va}, {"dim": b, "value": vb}],
                    "status": answer.status,
                    "reason": answer.reason,
                }
            )
    out.stats["pairs_excluded"] = len(exclusive)

    if implications:
        out.rules.extend(_fold_implications(live, dead, exclusive))
        out.stats["implications"] = len(out.of_kind(KIND_IMPLICATION))
    return out


def refute(
    rules: Iterable[DerivedRule], observations: Iterable[Mapping[str, Any]]
) -> list[tuple[DerivedRule, dict[str, Any]]]:
    """Rules a real run contradicts, each with the observation that did it.

    A derived rule is a claim that no host run produces something. One run that
    produces it settles the matter: the proof was wrong, whatever the solver
    said. That can only come from an expression that does not match the host --
    a derivation bug -- so this must never be resolved by dropping the
    observation.

    Cheap enough to run over a whole corpus, and it has to be: a wrong
    exclusion is invisible until something asks why a key was never searched
    for, and by then the answer is buried under thousands of skipped keys.
    """
    from .key_reachability import _target_value

    out: list[tuple[DerivedRule, dict[str, Any]]] = []
    rules = list(rules)
    if not rules:
        return out

    for row in observations:
        seen: dict[str, Any] = {}
        for dim, raw in row.items():
            value = _target_value(raw)
            if value is not None:
                seen[dim] = value
        if not seen:
            continue
        for rule in rules:
            if not all(d in seen for d in rule.dims):
                continue  # this run says nothing about the rule
            holds = all(seen[d] == v for d, v in rule.excludes)
            if not holds:
                continue
            if rule.kind == KIND_IMPLICATION and rule.forces is not None:
                dim, value = rule.forces
                if seen[dim] == value:
                    continue
            out.append((rule, {d: seen[d] for d in rule.dims}))

    # One counterexample per rule is enough to retract it; more is noise.
    first: dict[int, tuple[DerivedRule, dict[str, Any]]] = {}
    for rule, evidence in out:
        first.setdefault(id(rule), (rule, evidence))
    return list(first.values())


def _fold_implications(
    live: Mapping[str, Sequence[Any]],
    dead: Iterable[tuple[str, Any]],
    exclusive: Iterable[tuple[tuple[str, Any], tuple[str, Any]]],
) -> list[DerivedRule]:
    """Read `A=a forces B=b` off the pair matrix.

    If `A=a` is exclusive with every value `B` can take but one, then any run
    with `A=a` has `B` at that one -- which is the same content as the pairs,
    stated the way a reader and a searcher both want it. Folding needs the
    whole row to have been asked, so a pair the solver gave up on leaves the row
    alone rather than narrowing it on partial information.
    """
    dead = set(dead)
    blocked: dict[tuple[tuple[str, Any], str], set[Any]] = {}
    for (a, va), (b, vb) in exclusive:
        blocked.setdefault(((a, va), b), set()).add(vb)
        blocked.setdefault(((b, vb), a), set()).add(va)

    out: list[DerivedRule] = []
    for (premise, other), excluded in sorted(
        blocked.items(), key=lambda kv: (kv[0][0][0], str(kv[0][0][1]), kv[0][1])
    ):
        options = [v for v in live.get(other, ()) if (other, v) not in dead]
        left = [v for v in options if v not in excluded]
        if len(options) < 2 or len(left) != 1:
            continue
        out.append(
            DerivedRule(
                kind=KIND_IMPLICATION,
                excludes=(premise,),
                forces=(other, left[0]),
                folded_from=tuple(
                    (premise, (other, v)) for v in sorted(excluded, key=str)
                ),
            )
        )
    return out
