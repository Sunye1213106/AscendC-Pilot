# -*- coding: utf-8 -*-
"""Evaluate a dimension's tree forwards, on concrete inputs, without a solver.

Asking a solver "can these 19 dimensions hold at once" hands it trees full of
integer division and modulo — the undecidable fragment — and it answers by
timing out. Walking forwards has none of that: once the leaves hold numbers,
`d % 16` and `CeilDiv(s2, s2Inner)` are arithmetic. The compound comparisons
that stall the solver only exist in the symbolic world.

The inputs need not be enumerated over the integers either. Each dimension
only ever asks a finite set of "is it?" questions, and every value on the same
side of all of them gives the same answer, so a few representatives per
variable cover every distinction the operator can make. What comes out is the
equivalence classes of the input space, evaluated once each.
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from typing import Any, Iterable

__all__ = [
    "Unknown",
    "ValueTree",
    "Premises",
    "samples",
    "domains_of",
    "domain_for",
    "enumerate_cells",
    "possible_values",
]

_CMP = ("eq", "ne", "lt", "le", "gt", "ge")

#: Stands for "a value no threshold names", so that "none of the above" stays
#: reachable for a variable only ever compared against labels. An ordinary
#: string on purpose: equality against it has to answer (it equals no label),
#: and ordering against it has to refuse, which is what any label does.
OTHER = "__other__"

#: `VAR_SHAPE_QUERY_D2` is axis 2 of the tensor `VAR_SHAPE_QUERY`.
_AXIS_SUFFIX = re.compile(r"_D\d+$")


class Unknown(Exception):
    """The tree asked something this evaluator cannot answer concretely."""


class ZeroDenominator(Unknown):
    """A denominator evaluated to zero, and the subtree that did it.

    Not a gap in the evaluator: it is the operator not coming back. The input
    is illegal, whatever the stated premises failed to say about it.
    """

    def __init__(self, node: Any) -> None:
        super().__init__("division by zero")
        self.node = node


class ValueTree:
    """One derived value, with `$ref` nodes resolved on the way in.

    Named for what it holds rather than for `Expr`, which in this package is
    the symbolic tree the deriver builds. This one is the serialized form that
    comes back out of a field's `value_expr`.
    """

    def __init__(self, blob: Any) -> None:
        if isinstance(blob, dict) and blob.get("$dag"):
            self.defs = blob.get("defs") or {}
            self.root = blob.get("root")
        else:
            self.defs = {}
            self.root = blob

    def deref(self, node: Any) -> Any:
        seen = 0
        while isinstance(node, dict) and "$ref" in node:
            node = self.defs.get(node["$ref"])
            seen += 1
            if seen > 1000:
                raise Unknown("ref cycle")
        return node

    # -- collection --------------------------------------------------------
    def cuts(self) -> tuple[dict[str, set], set[str]]:
        """Thresholds each variable is compared against, and every variable."""
        cuts: dict[str, set] = defaultdict(set)
        seen_vars: set[str] = set()
        seen: set[int] = set()

        def walk(node: Any) -> None:
            node = self.deref(node)
            if isinstance(node, list):
                for x in node:
                    walk(x)
                return
            if not isinstance(node, dict) or id(node) in seen:
                return
            seen.add(id(node))
            name = node.get("var")
            if isinstance(name, str):
                seen_vars.add(name)
                op = node.get("op")
                if op in _CMP:
                    value = node.get("value")
                    if not isinstance(value, (dict, list)):
                        cuts[name].add(value)
                elif op in ("in", "not_in"):
                    for value in node.get("values") or ():
                        if not isinstance(value, (dict, list)):
                            cuts[name].add(value)
            for v in node.values():
                walk(v)

        walk(self.root)
        return dict(cuts), seen_vars

    def variables(self) -> set[str]:
        return self.cuts()[1]

    def vars_under(self, node: Any) -> set[str]:
        """Variables reachable from one node, `$ref`s followed as usual."""
        found: set[str] = set()
        seen: set[int] = set()

        def walk(n: Any) -> None:
            n = self.deref(n)
            if isinstance(n, list):
                for x in n:
                    walk(x)
                return
            if not isinstance(n, dict) or id(n) in seen:
                return
            seen.add(id(n))
            name = n.get("var")
            if isinstance(name, str):
                found.add(name)
            for v in n.values():
                walk(v)

        walk(node)
        return found

    def divisors(self) -> set[str]:
        """Variables whose being zero makes some denominator zero.

        Zero there is a division by zero, which the operator does not come
        back from, so that input yields no key and declining to draw it
        cannot lose a reachable one. Worth doing because it is most of what
        the harness was throwing away: with zero among the candidates, 62% of
        draws died on some divisor or other before the dimension was reached.

        A product counts the same way, factor by factor: `a / (b * c)` divides
        by zero whenever `b` is zero, whatever `c` is. Most real denominators
        are shaped like that -- an inner length times a ratio -- which is why
        stopping at the bare variable still lost half the draws.

        Anything else stops the walk. Under `a / (b - c)` no single value of
        `b` is ruled out, and dropping one would be excluding an input on no
        evidence.
        """
        found: set[str] = set()
        seen: set[int] = set()

        def zeroing(node: Any) -> set[str]:
            """Variables whose being zero makes this subtree zero."""
            node = self.deref(node)
            if not isinstance(node, dict):
                return set()
            op = node.get("op")
            if op is None:
                got = node.get("var")
                return {got} if isinstance(got, str) else set()
            if op == "mul":
                out: set[str] = set()
                for arg in node.get("args") or ():
                    out |= zeroing(arg)
                return out
            return set()

        def walk(node: Any) -> None:
            node = self.deref(node)
            if isinstance(node, list):
                for x in node:
                    walk(x)
                return
            if not isinstance(node, dict) or id(node) in seen:
                return
            seen.add(id(node))
            if node.get("op") in ("div", "mod"):
                for arg in (node.get("args") or ())[1:]:
                    found.update(zeroing(arg))
            for v in node.values():
                walk(v)

        walk(self.root)
        return found

    # -- evaluation --------------------------------------------------------
    def value(self, env: dict[str, Any]) -> Any:
        return self._eval(self.root, env)

    def _eval(self, node: Any, env: dict[str, Any]) -> Any:
        node = self.deref(node)
        if isinstance(node, (int, float, str, bool)) or node is None:
            return node
        if not isinstance(node, dict):
            raise Unknown(f"node {type(node).__name__}")
        if "lit" in node:
            return node["lit"]
        op = node.get("op")
        if op == "lit":
            return node.get("value")
        if op is None:
            if "var" in node:
                return self._read(node["var"], env)
            raise Unknown("node without op")
        if op == "if_then_else":
            cond = self._eval(node.get("condition"), env)
            return self._eval(node.get("then") if cond else node.get("else"), env)
        if op in _CMP:
            if "var" in node:
                left: Any = self._read(node["var"], env)
                right: Any = node.get("value")
            else:
                left = self._eval(node.get("lhs"), env)
                right = self._eval(node.get("rhs"), env)
            return _compare(op, left, right)
        if op in ("in", "not_in"):
            left = self._read(node["var"], env)
            members = [self._eval(v, env) for v in node.get("values") or ()]
            return (left in members) if op == "in" else (left not in members)
        if op in ("and", "or"):
            args = [self._eval(a, env) for a in node.get("args") or ()]
            return all(args) if op == "and" else any(args)
        if op == "not":
            return not self._eval(node.get("arg"), env)
        if op in ("add", "sub", "mul", "div", "mod"):
            raw = list(node.get("args") or ())
            args = [self._eval(a, env) for a in raw]
            if op in ("div", "mod"):
                # Say which denominator it was. The caller can then redraw the
                # handful of variables feeding it instead of the whole input,
                # which is the difference between finding a legal input and
                # not: the relation that was broken -- a size over a head
                # count -- involves two or three variables out of fifty.
                for src, got in zip(raw[1:], args[1:]):
                    if got == 0:
                        raise ZeroDenominator(src)
            return _arith(op, args)
        if op == "neg":
            return -self._eval(node.get("arg"), env)
        raise Unknown(f"op {op}")

    def _read(self, name: str, env: dict[str, Any]) -> Any:
        if name not in env:
            raise Unknown(f"unbound {name}")
        return env[name]


def _compare(op: str, a: Any, b: Any) -> bool:
    if op == "eq":
        return a == b
    if op == "ne":
        return a != b
    if isinstance(a, str) or isinstance(b, str):
        # Ordering two labels is not a question about the operator.
        raise Unknown(f"ordered compare on {a!r}")
    if op == "lt":
        return a < b
    if op == "le":
        return a <= b
    if op == "gt":
        return a > b
    return a >= b


def _arith(op: str, args: list[Any]) -> Any:
    if any(isinstance(x, str) for x in args):
        raise Unknown("arithmetic on a label")
    out = args[0]
    for x in args[1:]:
        if op == "add":
            out = out + x
        elif op == "sub":
            out = out - x
        elif op == "mul":
            out = out * x
        elif op == "div":
            if x == 0:
                raise Unknown("division by zero")
            out = out // x
        else:
            if x == 0:
                raise Unknown("modulo by zero")
            out = out % x
    return out


def samples(
    thresholds: Iterable[Any],
    domain: Any = None,
    constants: dict[str, int] | None = None,
) -> list[Any]:
    """Representative values: one per region the thresholds cut out.

    Comparisons only see which side of each threshold a value falls on, so a
    handful of points per variable covers every distinction the operator can
    make. Two ways to get this wrong, and they are not symmetric: too few
    points misses reachable keys, while points the operator could never be
    given make unreachable keys look reachable. So the regions are intersected
    with what the variable model says the input can be.
    """
    thresholds = set(thresholds)
    declared = set(getattr(domain, "values", None) or ())
    lo = getattr(domain, "lo", None)
    hi = getattr(domain, "hi", None)

    if declared:
        # A closed enum is already a list of regions — but the model spells a
        # dtype `DT_BF16` while the tiling code compares against 27. Comparing
        # the two forms is silently always false, which collapses the whole
        # dimension onto one branch, so the enum is put in the form the code
        # actually uses.
        wants_int = any(
            isinstance(t, int) and not isinstance(t, bool) for t in thresholds
        )
        if wants_int and constants and all(isinstance(v, str) for v in declared):
            named = [constants[v] for v in declared if v in constants]
            if len(named) == len(declared):
                return sorted(named)
        return sorted(declared, key=str)

    labels = sorted({t for t in thresholds if isinstance(t, str)})
    if labels:
        return labels + [OTHER]

    nulls = [None] if any(t is None for t in thresholds) else []
    bools = {t for t in thresholds if isinstance(t, bool)}
    numbers = sorted(
        {t for t in thresholds if isinstance(t, int) and not isinstance(t, bool)}
    )
    if bools and not numbers:
        return [False, True]

    out: set[Any] = set()
    if not numbers:
        # Nothing compares against this one, but it still reaches the key
        # through arithmetic: a head count divides, a length is ceil-divided
        # by a block size. Two points cannot separate those. Drawn from
        # {0, 1} every length is degenerate, every ratio lands in the same
        # branch, and half the draws put a zero under a division and throw
        # the whole point away — which is how a harness ends up unable to
        # move any dimension with any variable. Spread over magnitudes.
        out.update((0, 1, 2, 8, 64, 512))
    else:
        for t in numbers:
            out.update((t - 1, t, t + 1))
        out.add(max(numbers) + 64)
    if lo is not None:
        out = {x for x in out if x >= lo}
        out.add(lo)
    if hi is not None:
        out = {x for x in out if x <= hi}
        out.add(hi)
    return nulls + sorted(out)


def domains_of(var_model: Any) -> tuple[dict[str, Any], dict[str, int]]:
    """What each input may be, and the integers the code's names stand for."""
    out: dict[str, Any] = {}
    for vid, var in (getattr(var_model, "variables", None) or {}).items():
        domain = getattr(var, "domain", None)
        if domain is not None:
            out[vid] = domain
    constants = {
        k: v
        for k, v in (getattr(var_model, "named_constants", None) or {}).items()
        if isinstance(v, int) and not isinstance(v, bool)
    }
    return out, constants


def domain_for(vid: str, domains: dict[str, Any]) -> Any:
    """A per-axis variable inherits the tensor's domain: `query_d2` is a length.

    Naming each axis separately is what stopped `d` and `s1` from colliding,
    but the model still only knows the tensor. Until the axes are registered
    there too, the tensor's domain is the right thing to fall back on.
    """
    got = domains.get(vid)
    if got is not None:
        return got
    return domains.get(_AXIS_SUFFIX.sub("", vid))


def _refuses(tree: ValueTree, env: dict[str, Any]) -> bool:
    """Whether this premise turns the input down.

    One it cannot evaluate is not a refusal: excluding an input on no
    evidence is the direction that loses reachable keys.
    """
    try:
        return not tree.value(env)
    except Unknown:
        return False


class Premises:
    """Input legality conditions, as trees to test a candidate input against.

    An operator states what it accepts by rejecting the rest, and a run that
    was rejected produces no key at all. So a cell that fails any of these is
    not a cell the operator can be in, and whatever the dimensions evaluate to
    there was never reachable.
    """

    def __init__(self, blobs: Iterable[dict[str, Any]]) -> None:
        blobs = list(blobs)
        self.trees = [
            ValueTree(p["expr"]) for p in blobs if p.get("usable") and p.get("expr")
        ]
        self.dropped = [p for p in blobs if not p.get("usable")]
        self.vars: set[str] = set()
        self.cuts: dict[str, set] = defaultdict(set)
        #: Premises naming one variable only, which therefore decide it
        #: without needing to know anything else.
        self._alone: dict[str, list[ValueTree]] = defaultdict(list)
        for t in self.trees:
            cuts, names = t.cuts()
            self.vars |= names
            for k, v in cuts.items():
                self.cuts[k] |= v
            if len(names) == 1:
                self._alone[next(iter(names))].append(t)

    def keeps(self, var: str, values: list[Any]) -> list[Any]:
        """Candidate values with the ones already ruled out dropped.

        Drawing each variable independently and testing the premises
        afterwards spends most of the draws on inputs the operator refuses
        outright — one dtype premise alone threw away 43% of them, and what
        survives is too thin to tell any two inputs apart. A premise naming
        this variable and nothing else can be applied while the values are
        being chosen.

        Dropping every value would leave the axis empty and take the whole
        dimension with it, so that is read as the premise being about
        something this evaluator cannot see, and the values stand.
        """
        trees = self._alone.get(var)
        if not trees:
            return values
        keep = []
        for value in values:
            env = {var: value}
            if not any(_refuses(t, env) for t in trees):
                keep.append(value)
        return keep or values

    def rejects(self, env: dict[str, Any]) -> bool:
        """True when this input is one the operator refuses.

        A premise that cannot be evaluated here is skipped rather than
        assumed: it would exclude an input on no evidence, and excluding is
        the direction that loses reachable keys.
        """
        return any(_refuses(t, env) for t in self.trees)


def _axes(
    tree: ValueTree,
    domains: dict[str, Any],
    constants: dict[str, int] | None,
    premises: Premises | None,
) -> list[tuple[str, list[Any]]]:
    cuts, all_vars = tree.cuts()
    if premises is not None:
        # A premise splits the input space too, and only on the variables this
        # dimension reads: a rejection of one dtype matters to a dimension
        # that reads that dtype and to no other.
        for v in all_vars & premises.vars:
            cuts.setdefault(v, set()).update(premises.cuts.get(v, set()))
    divisors = tree.divisors()
    out = []
    for v in sorted(all_vars):
        vals = samples(cuts.get(v, set()), domain_for(v, domains), constants)
        if v in divisors:
            vals = [x for x in vals if x != 0] or vals
        if premises is not None:
            vals = premises.keeps(v, vals)
        out.append((v, vals))
    return out


def enumerate_cells(
    blob: Any,
    *,
    cap: int = 2_000_000,
    domains: dict[str, Any] | None = None,
    constants: dict[str, int] | None = None,
    premises: Premises | None = None,
) -> dict[str, Any]:
    """Every value one derived expression can take, with a witness for each.

    A witness is the point that produced the value, so a caller never has to
    take the verdict on trust: the input is there to re-run.
    """
    domains = domains or {}
    tree = ValueTree(blob)
    axes = _axes(tree, domains, constants, premises)
    total = 1
    for _, vals in axes:
        total *= len(vals)
    if total > cap:
        return {"vars": len(axes), "cells": total, "skipped": True}

    reached: dict[Any, dict[str, Any]] = {}
    unknown = 0
    refused = 0
    for combo in itertools.product(*[vals for _, vals in axes]):
        env = {v: x for (v, _), x in zip(axes, combo)}
        if premises is not None and premises.rejects(env):
            refused += 1
            continue
        try:
            got = tree.value(env)
        except Unknown:
            unknown += 1
            continue
        if not isinstance(got, (int, str, bool)):
            unknown += 1
            continue
        reached.setdefault(got, env)
    return {
        "vars": len(axes),
        "cells": total,
        "values": reached,
        "unknown": unknown,
        "refused": refused,
        "skipped": False,
    }


def reaching_inputs(
    tree: ValueTree,
    target: Any,
    axes: dict[str, list[Any]],
    *,
    keep: int = 24,
) -> list[dict[str, Any]]:
    """Partial inputs that steer the tree towards `target`.

    Drawing at random reaches whatever the code does on most inputs and never
    the rest: a branch guarded by three conditions at once is not going to
    come up by chance in a space this wide. So instead of waiting for the
    input, read it off the tree — walk down picking the arm that leads to the
    value wanted and write down what each condition on the way needs.

    What comes back constrains only the variables the path had an opinion
    about, and it is a guess, not a solution: conditions this cannot invert
    are left alone, so the caller must still evaluate and check. Being wrong
    costs a draw; being right reaches a value nothing else would.
    """

    def merge(a: list[dict], b: list[dict]) -> list[dict]:
        out = []
        for x in a:
            for y in b:
                if any(k in x and x[k] != v for k, v in y.items()):
                    continue  # the two arms want different things here
                out.append({**x, **y})
                if len(out) >= keep:
                    return out
        return out

    def pick(var: str, ok) -> list[dict]:
        got = [v for v in axes.get(var, ()) if _quietly(ok, v)]
        return [{var: v} for v in got[:keep]]

    def satisfy(node: Any, want: bool) -> list[dict]:
        node = tree.deref(node)
        if not isinstance(node, dict):
            return [{}]
        op = node.get("op")
        if op == "not":
            args = node.get("args") or []
            return satisfy(args[0], not want) if args else [{}]
        if op in ("and", "or"):
            args = [a for a in (node.get("args") or [])]
            # Every clause must hold for an `and` to hold, and one failing
            # clause is enough to break it. `or` is the same the other way.
            if want == (op == "and"):
                out: list[dict] = [{}]
                for a in args:
                    out = merge(out, satisfy(a, want))
                    if not out:
                        return []
                return out
            out = []
            for a in args:
                out.extend(satisfy(a, want))
            return out[:keep]
        if op in _CMP:
            if "var" in node and not isinstance(node.get("value"), dict):
                left, right = node["var"], node.get("value")
            else:
                lhs, rhs = tree.deref(node.get("lhs")), tree.deref(node.get("rhs"))
                left = lhs.get("var") if isinstance(lhs, dict) else None
                right = rhs.get("lit") if isinstance(rhs, dict) and "lit" in rhs else rhs
            if not isinstance(left, str) or isinstance(right, dict):
                return [{}]
            return pick(left, lambda v: _compare(op, v, right) == want)
        if op in ("in", "not_in"):
            var, vals = node.get("var"), node.get("values") or []
            if not isinstance(var, str):
                return [{}]
            inside = want == (op == "in")
            return pick(var, lambda v: (v in vals) == inside)
        return [{}]

    def solve(node: Any, want: Any, depth: int) -> list[dict]:
        node = tree.deref(node)
        if depth > 24:
            return [{}]
        if not isinstance(node, dict):
            return [{}] if node == want else []
        if "lit" in node:
            return [{}] if node["lit"] == want else []
        op = node.get("op")
        if op is None and isinstance(node.get("var"), str):
            return pick(node["var"], lambda v: v == want)
        if op == "if_then_else":
            out = merge(satisfy(node.get("condition"), True),
                        solve(node.get("then"), want, depth + 1))
            out.extend(merge(satisfy(node.get("condition"), False),
                             solve(node.get("else"), want, depth + 1)))
            return out[:keep]
        if isinstance(want, bool) or want in (0, 1):
            return satisfy(node, bool(want))
        return [{}]

    return [w for w in solve(tree.root, target, 0) if w][:keep]


def _quietly(ok, value) -> bool:
    try:
        return bool(ok(value))
    except Unknown:
        return False


def possible_values(
    blob: Any,
    env: dict[str, Any],
    *,
    free: Iterable[str],
    domains: dict[str, Any] | None = None,
    constants: dict[str, int] | None = None,
    cap: int = 4096,
) -> set[Any] | None:
    """What the expression could evaluate to at `env`, over its free variables.

    An expression that still carries free variables has no single value at an
    input point, but it does have a set of them — one per assignment to the
    variables nobody could pin down. That set is a fact about the source: a
    claim that the field is something else at this point contradicts it.

    Returns None when the set cannot be pinned down — too many combinations,
    or the tree asks something unevaluable on every one of them. None means
    "no opinion", never "empty".
    """
    tree = ValueTree(blob)
    domains = domains or {}
    cuts, _ = tree.cuts()
    axes = [
        (v, samples(cuts.get(v, set()), domain_for(v, domains), constants))
        for v in sorted(set(free))
    ]
    total = 1
    for _, vals in axes:
        total *= len(vals)
    if total > cap:
        return None

    out: set[Any] = set()
    for combo in itertools.product(*[vals for _, vals in axes]):
        point = dict(env)
        point.update({v: x for (v, _), x in zip(axes, combo)})
        try:
            got = tree.value(point)
        except Unknown:
            continue
        if isinstance(got, (int, str, bool)):
            out.add(got)
    return out or None
