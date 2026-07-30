# -*- coding: utf-8 -*-
"""Derive each TilingKey field back to a guarded expression over input roots.

The bind layer says *which* host expression lands in each key slot. That is not
yet a condition: `static_cast<uint8_t>(splitAxis)` tells a test generator
nothing. This module rewrites every slot into an expression tree whose leaves
are input roots, by repeatedly substituting the guarded assignments that define
each intermediate name:

    IsDrop <- dropValue
           <- fBaseParams.keepProb < 1 ? ENABLE : DISABLE
           <- Ite(lt(VAR_ATTR_KEEP_PROB, 1), 1, 0)

Nothing here is operator-specific: the substitution set comes from the Host IR
(field writes and guarded local writes) and the leaf classification comes from
`SourceResolver`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from uo_init.clang_walk import RETURN_SLOT
from uo_init.cpp_expr import parse_expr
from uo_init.expr_ir import Bin, Call, Const, Expr, Ite, Ref, Select, Un, Unknown
from uo_init.kb_model import Domain
from uo_init.predicate import (
    ARITH_OPS,
    BOOL_OPS,
    CMP_OPS,
    NormalizeError,
    PredicateNormalizer,
    REASON_OPAQUE,
    _as_operand,
    _leaf_text,
    collect_vars,
    rewrite_strcmp_cmp,
)
from uo_init.source_resolver import dotted_path
from uo_init.variable_model import VarSpec

STATUS_DERIVED = "derived"
STATUS_PARTIAL = "partial"
STATUS_UNRESOLVED = "unresolved"

# Roots that say *where in the schedule* we are, not *what the input was*.
# `coreIdx`/`blockIdx`/loop counters are traversal position: a branch on them
# is taken on some iteration regardless of the input, so pinning them would
# wrongly rule keys out. They become unconstrained variables instead.
#
# This is deliberately narrow. A quantity that merely *looks* scheduling-ish —
# tail-core count, tail block size, `CeilDiv(s1, aicNum)` — resolves to
# INPUT_SHAPE / PLATFORM_CORE_COUNT and stays a real constraint.
SCHEDULING_ROOTS = frozenset(
    {"LOOP_DERIVED", "LOOP_INDUCTION", "KERNEL_BUILTIN", "EXECUTION_ROLE"}
)

# Guard text / leaf patterns that are schedule simulation — soft immediately
# instead of expanding into huge UNMAPPED trees.
_SCHED_SOFT_RE = re.compile(
    r"syncRound|currentSum|maxBlockNumPerCore|totalRound|coreIdx|blockIdx|"
    r"invalidS1Array|actualS1Outer|actualS2Outer|prefix0Max|prefix1Max|prefix2Max|"
    r"CheckExceedL2Cache|CaclePerCore|GetSparseUnpad|__reached_|"
    r"ret\s*!=\s*ge::GRAPH_SUCCESS|GRAPH_SUCCESS",
    re.I,
)

_PLATFORM_CORE_CALLS = frozenset(
    {"GetCoreNumAic", "GetCoreNumAiv", "GetCoreNum", "GetL2Size"}
)

REASON_NO_DEFINITION = "NO_DEFINITION"
REASON_DEPTH = "EXPANSION_DEPTH_EXCEEDED"
REASON_BUDGET = "EXPANSION_BUDGET_EXCEEDED"
REASON_CYCLE = "CYCLIC_DEFINITION"
REASON_AMBIGUOUS_RETURN = "AMBIGUOUS_RETURN"

# Casts and identity wrappers carry no value of their own.
_CAST_CALLS = frozenset(
    {
        "static_cast",
        "const_cast",
        "reinterpret_cast",
        "dynamic_cast",
        "int",
        "bool",
        "float",
        "double",
        "size_t",
        "int8_t",
        "uint8_t",
        "int16_t",
        "uint16_t",
        "int32_t",
        "uint32_t",
        "int64_t",
        "uint64_t",
    }
)

# Termination comes from cycle detection plus the node budget; depth only keeps
# the Python stack from overflowing, so it can be generous.
MAX_DEPTH = 160
MAX_NODES = 400000

# A path condition that cannot act as a value guard: loop headers say "this
# write happened on some iteration", and truncated text cannot be re-parsed.
_NON_GUARD_RE = re.compile(r"^\s*(?:while|for|do|switch|cxx_for_range)\b")

# How many *distinct* constants a multi-return helper must yield before its
# returns are inlined. Two-valued helpers are normally status codes
# (`GRAPH_FAILED`/`GRAPH_SUCCESS`) — inlining them pulls whole validation
# bodies into a guard for no gain, which is what exhausts `MAX_NODES`. Three
# or more constants means the helper maps its inputs onto a fixed set of
# buckets, which is what a key dimension *is*. Boolean predicates
# (`true`/`false`) are the one two-valued exception: they *are* the bucket
# choice, and their bodies are the input conditions we need.
_MIN_CLASSIFIER_VALUES = 3
_BOOL_CONST_FORMS = frozenset({"true", "false", "True", "False", "0", "1"})


def _is_bool_classifier(forms: list[str]) -> bool:
    return len(set(forms)) == 2 and set(forms) <= _BOOL_CONST_FORMS


@dataclass
class DefSite:
    """One assignment that can define a name, with the guards reaching it."""

    rhs: str
    guards: tuple[str, ...] = ()
    file: str = ""
    line: int = 0
    function: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rhs": self.rhs,
            "guards": list(self.guards),
            "file": self.file,
            "line": self.line,
            "function": self.function,
        }


@dataclass
class KeyFieldDerivation:
    name: str
    index: int
    host_expr: str
    expanded: str = ""
    value_expr: dict[str, Any] | None = None
    value_table: list[dict[str, Any]] = field(default_factory=list)
    value_leaves: list[str] = field(default_factory=list)
    input_roots: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    def_sites: list[DefSite] = field(default_factory=list)
    unresolved: list[dict[str, str]] = field(default_factory=list)
    scheduling: dict[str, str] = field(default_factory=dict)
    undecided: dict[str, str] = field(default_factory=dict)
    status: str = STATUS_UNRESOLVED
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "index": self.index,
            "host_expr": self.host_expr,
            "expanded": self.expanded,
            "value_expr": self.value_expr,
            "value_table": list(self.value_table),
            "value_leaves": list(self.value_leaves),
            "input_roots": list(self.input_roots),
            "variables": list(self.variables),
            "def_sites": [d.to_dict() for d in self.def_sites],
            "unresolved": list(self.unresolved),
            "scheduling": dict(self.scheduling),
            "undecided": dict(self.undecided),
            "status": self.status,
            "note": self.note,
        }


def strip_casts(text: str) -> str:
    """`static_cast<uint8_t>(splitAxis)` -> `splitAxis`."""
    prev = None
    cur = (text or "").strip()
    pat = re.compile(
        r"^(?:" + "|".join(sorted(_CAST_CALLS, key=len, reverse=True)) + r")\s*"
        r"(?:<[^<>]*>)?\s*\((.*)\)$",
        re.DOTALL,
    )
    while cur != prev:
        prev = cur
        m = pat.match(cur)
        if m and _balanced(m.group(1)):
            cur = m.group(1).strip()
    return cur


def _balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _children(e: Expr) -> tuple[Expr, ...]:
    if isinstance(e, Un):
        return (e.arg,)
    if isinstance(e, Bin):
        return (e.left, e.right)
    if isinstance(e, Ite):
        return (e.cond, e.then, e.else_)
    if isinstance(e, Select):
        return (e.array, e.index)
    if isinstance(e, Call):
        return tuple(e.args)
    return ()


def _walk_dag(root: Expr):
    """Yield each distinct node once. A substituted tree is a DAG; walking it
    as a tree costs the unfolded size, which is exponential in practice."""
    seen: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        yield node
        stack.extend(_children(node))


def _has_reason(root: Expr, reason: str) -> bool:
    return any(isinstance(n, Unknown) and n.reason == reason for n in _walk_dag(root))


def _dag_size(root: Expr) -> int:
    return sum(1 for _ in _walk_dag(root))


def _collect_vars_dag(node: Any, seen: set[int] | None = None) -> set[str]:
    """`collect_vars` over a shared SMT-lite structure.

    Normalisation memoises by node identity, so the result is a DAG of shared
    dicts; the plain recursive walk revisits shared branches and degenerates to
    the unfolded size.
    """
    seen = set() if seen is None else seen
    out: set[str] = set()
    if id(node) in seen:
        return out
    seen.add(id(node))
    if isinstance(node, dict):
        if isinstance(node.get("var"), str):
            out.add(node["var"])
        for value in node.values():
            out |= _collect_vars_dag(value, seen)
    elif isinstance(node, list):
        for item in node:
            out |= _collect_vars_dag(item, seen)
    return out


def _pretty(e: Expr) -> str:
    if isinstance(e, Const):
        return repr(e.value)
    if isinstance(e, Ref):
        return e.symbol
    if isinstance(e, Unknown):
        return f"<?{e.reason}>"
    if isinstance(e, Un):
        return f"{e.op}({_pretty(e.arg)})"
    if isinstance(e, Bin):
        return f"({_pretty(e.left)} {e.op} {_pretty(e.right)})"
    if isinstance(e, Ite):
        return f"({_pretty(e.cond)} ? {_pretty(e.then)} : {_pretty(e.else_)})"
    if isinstance(e, Select):
        return f"{_pretty(e.array)}[{_pretty(e.index)}]"
    if isinstance(e, Call):
        name = e.func[len("field:") :] if e.func.startswith("field:") else e.func
        return f"{name}({', '.join(_pretty(a) for a in e.args)})"
    return str(e)


# A node worth naming: shared, and big enough that repeating it costs more than
# the binding does.
_SHARE_MIN_SIZE = 6


def _pretty_dag(root: Expr) -> str:
    """Render sharing explicitly, as `let $n = ...` bindings over a body.

    `_pretty` alone unfolds the DAG and produces hundreds of megabytes for a
    field like `IsTndSwizzle`, which makes the result unreadable and unusable
    as a debugging artefact.
    """
    refs: dict[int, int] = {}
    order: list[Expr] = []

    def count(node: Expr) -> None:
        refs[id(node)] = refs.get(id(node), 0) + 1
        if refs[id(node)] > 1:
            return
        for ch in _children(node):
            count(ch)
        order.append(node)

    count(root)

    size: dict[int, int] = {}
    for node in order:
        size[id(node)] = 1 + sum(size.get(id(c), 1) for c in _children(node))

    names: dict[int, str] = {}
    for node in order:
        if (
            refs.get(id(node), 0) > 1
            and size.get(id(node), 1) >= _SHARE_MIN_SIZE
            and _children(node)
        ):
            names[id(node)] = f"${len(names) + 1}"

    def render(node: Expr, *, top: bool = False) -> str:
        if not top and id(node) in names:
            return names[id(node)]
        if isinstance(node, Const):
            return repr(node.value)
        if isinstance(node, Ref):
            return node.symbol
        if isinstance(node, Unknown):
            return f"<?{node.reason}>"
        if isinstance(node, Un):
            return f"{node.op}({render(node.arg)})"
        if isinstance(node, Bin):
            return f"({render(node.left)} {node.op} {render(node.right)})"
        if isinstance(node, Ite):
            return f"({render(node.cond)} ? {render(node.then)} : {render(node.else_)})"
        if isinstance(node, Select):
            return f"{render(node.array)}[{render(node.index)}]"
        if isinstance(node, Call):
            fname = (
                node.func[len("field:") :]
                if node.func.startswith("field:")
                else node.func
            )
            return f"{fname}({', '.join(render(a) for a in node.args)})"
        return str(node)

    lines = [
        f"let {names[id(node)]} = {render(node, top=True)}"
        for node in order
        if id(node) in names
    ]
    lines.append(render(root, top=True) if id(root) in names else render(root))
    return "\n".join(lines)


# A *named* constant, as opposed to any old SCREAMING_CASE identifier. Axis
# names in tiling code are short and upper-case — `S1`, `S2`, `D`, `B`, `N2` —
# and they are ordinary input-derived locals. Admitting them would let a helper
# that returns computed values masquerade as a classifier, which is exactly the
# blow-up this gate exists to prevent. A real named constant is scoped
# (`SparseType::DENSE`), or underscored (`GRAPH_FAILED`), or `k`-prefixed.
_NAMED_CONST_RE = re.compile(r"^(?:[A-Z][A-Z0-9]*_[A-Z0-9_]*|k[A-Z]\w*)$")


def _is_constant(e: Expr) -> bool:
    """A literal, a named constant, or a tuple built only out of those."""
    if isinstance(e, Const):
        return True
    if isinstance(e, Un) and e.op in ("-", "+", "~"):
        return _is_constant(e.arg)
    if isinstance(e, Bin) and e.op in ARITH_OPS:
        # `MAX_CORE - 1` reads as a constant, so treat it as one.
        return _is_constant(e.left) and _is_constant(e.right)
    if isinstance(e, Ref):
        if e.symbol in ("true", "false"):
            return True
        head, _, tail = e.symbol.rpartition("::")
        # A scoped member is a constant when the member is not lower-case:
        # `SparseType::DENSE`, `Mode::kSmall`.
        if head:
            return bool(tail) and not tail[:1].islower()
        return bool(_NAMED_CONST_RE.match(tail))
    if isinstance(e, Call):
        name = e.func[len("field:") :] if e.func.startswith("field:") else e.func
        if name.split("::")[-1] in _TUPLE_BUILDERS:
            return bool(e.args) and all(_is_constant(a) for a in e.args)
    return False


def value_leaves(root: Expr) -> set[str]:
    """Constants the field can actually evaluate to.

    Only the *value* position counts, so the walk follows `Ite` arms and never
    descends into a guard. A constant inside a condition is a comparison
    operand: `d > NUM128` does not make `NUM128` a value `DTemplateNum` can
    take, and `layoutType == INPUT_FORMAT_TND` does not make the format enum a
    value of `IsTnd`.

    Walking the whole tree instead — which is what a plain `_walk_dag` over
    every `Ite` does — makes every dimension that shares a sub-DAG report the
    union of its neighbours' constants. `SplitAxis` and `IsTnd` both expand
    `SetSplitAxis`/`DoSparse`, and under the whole-tree rule both reported the
    same 20 leaves, so a domain check on them could not fail.

    An empty result is meaningful, not a collapse: a dimension defined by a
    bare predicate has no `Ite` at all and its domain is the declared `{0,1}`.
    """
    vals: set[str] = set()
    seen: set[int] = set()
    stack: list[Expr] = [root]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if _is_constant(node):
            vals.add(_pretty(node))
            continue
        if isinstance(node, Ite):
            stack.append(node.then)
            stack.append(node.else_)
    return vals


def smt_value_leaves(node: Any) -> set[str]:
    """Value-position constants of an SMT-lite `value_expr`.

    Bare boolean key fields (`layoutType == TND`) expand to a comparison with
    no `Ite`, so `value_leaves(expanded)` is empty; the normalizer then wraps
    them as `if_then_else(cond, 1, 0)`. Those 0/1 arms must still count.
    """
    vals: set[str] = set()

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            if n.get("op") == "if_then_else":
                for side in (n.get("then"), n.get("else")):
                    if isinstance(side, (int, bool, str)):
                        vals.add(str(side))
                    else:
                        walk(side)
                return
            if "lit" in n and len(n) == 1:
                vals.add(str(n["lit"]))
                return
            for child in n.values():
                walk(child)
        elif isinstance(n, list):
            for child in n:
                walk(child)

    walk(node)
    return vals


def _constant_form(text: str) -> str | None:
    """Canonical text of a constant return, or None if it is not constant."""
    try:
        tree = parse_expr(strip_casts(text))
    except Exception:  # noqa: BLE001 - parser failure means "not recognised"
        return None
    return _pretty(tree) if _is_constant(tree) else None


def _usable_guard(text: str) -> bool:
    t = (text or "").strip()
    if not t or "..." in t:
        return False
    return not _NON_GUARD_RE.match(t.lstrip("!("))


def _conjoin_text(guards) -> str:
    parts = [g for g in guards if _usable_guard(g)]
    if not parts:
        return ""
    return " && ".join(f"({p})" for p in parts)


def _loop_scoped_only(sites: list[DefSite]) -> bool:
    """True when every definition of a name sits under a loop or switch head.

    Such a name takes a different value on each iteration, so no single
    assignment defines it. Treating the loop head as "no guard" would promote
    the initialiser to an unconditional write: a `for (i = 0; ...)` index then
    folds to the constant `0`, turning `i == 0` into a tautology and every
    `i != 0` branch into dead code — which silently deletes real definitions.
    """
    return bool(sites) and all(s.guards and not _conjoin_text(s.guards) for s in sites)




class KeyFieldDeriver:
    """Expands host encode expressions down to input roots."""

    def __init__(self, *, host_ir, resolver, var_model, max_helper_guards: int = 4):
        self.ir = host_ir
        self.resolver = resolver
        self.model = var_model
        self.max_helper_guards = max_helper_guards
        self._nodes = 0
        self._cache: dict[tuple[str, str], Expr] = {}
        self._stack: set[tuple[str, str]] = set()
        self._scoped: dict[str, Any] = {}
        self.cycles: set[str] = set()
        # (id(node), scope) -> (node, expansion). The node is kept alive so its
        # id cannot be recycled onto a different object.
        self._ememo: dict[tuple[int, str], tuple[Expr, Expr]] = {}

    # -- definition lookup -------------------------------------------------
    def _field_defs(self, path: str) -> list[DefSite]:
        tail = path.rsplit(".", 1)[-1]
        by_tail = self.ir.writes_by_tail().get(tail, [])
        exact = [w for w in by_tail if w.path == path or w.path.endswith("." + path)]
        pool = exact or [
            w for w in by_tail if w.path.rsplit(".", 1)[0] == path.rsplit(".", 1)[0]
        ]
        return [
            DefSite(
                rhs=w.rhs,
                guards=tuple(w.guards()),
                file=w.file,
                line=w.line,
                function=w.function,
            )
            for w in sorted(pool, key=lambda w: (w.file, w.line))
            if w.rhs.strip()
        ]

    def _local_defs(self, name: str, fn: str) -> list[DefSite]:
        writes = self.ir.local_writes_in(fn).get(name, [])
        return [
            DefSite(
                rhs=w.rhs,
                guards=tuple(w.guards()),
                file=w.file,
                line=w.line,
                function=w.function,
            )
            for w in sorted(writes, key=lambda w: (w.file, w.line))
            if w.rhs.strip() and w.rhs.strip() != name
        ]

    def _defs_for(self, name: str, fn: str) -> list[DefSite]:
        return [d for d in self._all_defs_for(name, fn) if "..." not in d.rhs]

    def _all_defs_for(self, name: str, fn: str) -> list[DefSite]:
        if "." in name:
            return self._field_defs(name)
        local = self._local_defs(name, fn)
        if local:
            return local
        # Declared without a guarded write in this scope: fall back to the
        # function summary, which has the RHS but no path conditions.
        defs = self.ir.defs_by_function().get(fn, {}).get(name, [])
        sites = [
            DefSite(rhs=r, function=fn) for r in defs if r.strip() and r.strip() != name
        ]
        if sites:
            return sites
        # A bare identifier naming a data member of the tiling class.
        if name in getattr(self.ir, "class_fields", ()):  # pragma: no branch
            for owner in ("fBaseParams", "tilingData"):
                got = self._field_defs(f"{owner}.{name}")
                if got:
                    return got
        return self._unique_foreign_defs(name, fn)

    def _unique_foreign_defs(self, name: str, fn: str) -> list[DefSite]:
        """A local defined in a different function than the one being expanded.

        Guard chains reach across helpers, so the scope recorded on a write is
        often not the scope we are expanding in. Accepting the definition only
        when exactly one function declares the name keeps this from confusing
        two unrelated locals that happen to share a name.
        """
        if not name or name == RETURN_SLOT:
            return []
        owners = [
            other
            for other in self.ir.summaries
            if other != fn and self.ir.local_writes_in(other).get(name)
        ]
        if len(owners) != 1:
            return []
        return self._local_defs(name, owners[0])

    def _return_defs(self, fname: str, args: list[Expr]) -> tuple[list[DefSite], str]:
        """Definitions contributed by a callee's return statements.

        Only *small* helpers are inlined. A predicate helper like
        `DoBn2s2Sparse()` computes its answer with a per-core loop; inlining
        its body drags loop accumulators into a guard that is, at the call
        site, a plain function of the inputs. Left as a call it is classified
        by `SourceResolver`, which reports its input roots without unfolding
        the arithmetic that produced them.
        """
        short = fname.split("::")[-1]
        summary = self.ir.summaries.get(short)
        if summary is None or not summary.returns:
            return [], ""
        # An unsubstituted formal would be expanded in the callee's scope and
        # could bind to an unrelated local of the same name.
        if len(args) < len(summary.params):
            return [], "ARITY_MISMATCH"
        subst: dict[str, str] = {}
        for pname, actual in zip(summary.params, args):
            # The substituted text is re-parsed, so it has to be plain C++ —
            # no `let` sharing available. Refuse actuals whose flat form would
            # be enormous rather than paying to render them.
            if _dag_size(actual) > 64:
                return [], "ACTUAL_TOO_LARGE"
            txt = _pretty(actual).lstrip("&").strip()
            if txt:
                subst[pname] = txt
        # Ahead of the size gate on purpose. Guard count is a proxy for "how
        # much body would we drag in"; all-constant returns is a direct
        # statement that the helper *selects* rather than *computes*, so there
        # is no body to drag in and the proxy has nothing left to protect.
        if len(summary.returns) > 1:
            classified = self._classifier_defs(short, subst)
            if classified is not None:
                return classified, ""
        if len(summary.guards) > self.max_helper_guards:
            return [], "HELPER_TOO_LARGE"
        rewritten = [_substitute_names(r, subst) for r in summary.returns]
        note = REASON_AMBIGUOUS_RETURN if len(rewritten) > 1 else ""
        return [DefSite(rhs=r, function=short) for r in rewritten], note

    def _classifier_defs(self, short: str, subst: dict[str, str]) -> list[DefSite] | None:
        """Guarded returns of a helper that classifies its inputs into buckets.

        `summary.returns` is an unordered set of return expressions with no path
        conditions, so a multi-return helper is normally left as an opaque call.
        For a classifier that is fatal rather than conservative: the *whole
        point* of `GetS1S2TemplateType` is that it maps dtype and shape onto one
        of four `(s1, s2)` template sizes, and a key dimension reads that result
        directly. Left opaque, the field either fails or — worse — resolves
        through the helper's first return and silently becomes a constant.

        `RETURN_SLOT` carries each return as a guarded write with its full
        if/else-if path condition, which is exactly the chain we need. Returns
        are early exits, so the *first* matching guard wins; `_chain` is
        last-wins, hence the reversal.
        """
        slot = self.ir.local_writes_in(short).get(RETURN_SLOT, ())
        # Need at least two returns to be a classifier; the distinct-value
        # threshold below is the real gate.
        if len(slot) < 2:
            return None
        forms = [_constant_form(w.rhs) for w in slot]
        if any(f is None for f in forms):
            return None
        n_distinct = len(set(forms))
        if n_distinct < 2:
            return None
        if n_distinct < _MIN_CLASSIFIER_VALUES and not _is_bool_classifier(forms):
            return None
        bare = 0
        for w in slot:
            guards = w.guards()
            if not guards:
                bare += 1
            elif any(not _usable_guard(g) for g in guards):
                # A return reached from inside a loop has no value guard, so the
                # chain would silently lose a case.
                return None
        # Exactly one unguarded fallthrough is the normal `return default;` at
        # the end. More than one means we cannot order them faithfully.
        if bare > 1:
            return None
        return [
            DefSite(
                rhs=_substitute_names(w.rhs, subst),
                guards=tuple(_substitute_names(g, subst) for g in w.guards()),
                file=w.file,
                line=w.line,
                function=short,
            )
            for w in reversed(list(slot))
        ]

    # -- expansion ---------------------------------------------------------
    def _chain(self, sites: list[DefSite], fn: str, depth: int) -> Expr:
        """Sequential assignment semantics: a later write wins where its guard holds.

        An unguarded write only overrides prior writes from the *same* function.
        Without that, a fallthrough assignment in `DoSparse` (empty usable
        guards) would last-wins-erase `SetSplitAxis`'s `BN2S2` from another TU,
        collapsing a three-valued enum to two. Cross-function unguarded writes
        become soft alternatives under a reachability tag instead.
        """
        result: Expr | None = None
        result_fn: str | None = None
        for site in sites:
            scope = site.function or fn
            value = self._expand_text(site.rhs, scope, depth + 1)
            guard_text = _conjoin_text(site.guards)
            if not guard_text:
                if result is None or scope == result_fn:
                    result = value
                    result_fn = scope
                else:
                    result = Ite(Ref(f"__reached_{scope}"), value, result)
                continue
            cond = self._expand_text(guard_text, scope, depth + 1)
            # An if/else-if chain with no unguarded write falls through to the
            # declared default, which for tiling structs and enums is zero.
            fallthrough = result if result is not None else Const(0)
            result = Ite(cond, value, fallthrough)
            result_fn = scope
        return result if result is not None else Unknown(REASON_NO_DEFINITION)

    def _expand_text(self, text: str, fn: str, depth: int) -> Expr:
        if not text or not text.strip():
            return Unknown(REASON_NO_DEFINITION)
        try:
            tree = parse_expr(strip_casts(text))
        except Exception:  # noqa: BLE001 - parser failure is a real outcome
            return Unknown("PARSE_FAILED")
        return self._expand(tree, fn, depth)

    def _expand(self, e: Expr, fn: str, depth: int) -> Expr:
        # Substitution turns a tree into a DAG: the layout ternary that defines
        # b/n2/s1/s2 is reached from dozens of places. Returning the *same*
        # object for the same (node, scope) keeps it shared, so the cost is the
        # number of distinct nodes rather than the size of the unfolded tree.
        memo_key = (id(e), fn)
        hit = self._ememo.get(memo_key)
        if hit is not None:
            return hit[1]
        out = self._expand_uncached(e, fn, depth)
        self._ememo[memo_key] = (e, out)
        return out

    def _expand_uncached(self, e: Expr, fn: str, depth: int) -> Expr:
        self._nodes += 1
        if self._nodes > MAX_NODES:
            return Unknown(REASON_BUDGET)
        # Depth is only a guard against exhausting the Python stack; termination
        # comes from `_stack` (cycles) and `_nodes` (breadth).
        if depth > MAX_DEPTH:
            return Unknown(REASON_DEPTH)

        if isinstance(e, (Const, Unknown)):
            return e
        if isinstance(e, Un):
            arg = self._expand(e.arg, fn, depth)
            if e.op in ("!", "not") and isinstance(arg, Const):
                return Const(not bool(arg.value))
            return Un(e.op, arg)
        if isinstance(e, Bin):
            rewritten = rewrite_strcmp_cmp(e)
            if rewritten is not e:
                return self._expand(rewritten, fn, depth)
            # Locked platform: GetPlatformInfo(...) == None is never true.
            if self._is_platform_null_cmp(e):
                return Const(e.op in ("!=",))
            # Legal tiling path: `ret != GRAPH_SUCCESS` never holds on a key that
            # reached GetTilingKey. Softening it to a free bool collapses value
            # arms behind the soft guard; folding it here keeps the then-arm.
            folded = self._fold_graph_success_cmp(e)
            if folded is not None:
                return folded
            # Named-constant classifier boundary: `layoutType == INPUT_FORMAT_TND`
            # (and peers) must not chase every write of the left-hand field
            # through DoSparse / SetSplitAxis. That chase is what pulled
            # PLATFORM_CORE_COUNT into IsTnd's roots.
            bounded = self._expand_named_const_cmp(e, fn, depth)
            if bounded is not None:
                return bounded
            return Bin(
                e.op,
                self._expand(e.left, fn, depth),
                self._expand(e.right, fn, depth),
            )
        if isinstance(e, Ite):
            cond = self._expand(e.cond, fn, depth)
            then = self._expand(e.then, fn, depth)
            else_ = self._expand(e.else_, fn, depth)
            if isinstance(cond, Const):
                return then if cond.value else else_
            if (
                isinstance(then, Const)
                and isinstance(else_, Const)
                and then.value == else_.value
            ):
                return then
            return Ite(cond, then, else_)
        if isinstance(e, Select):
            # Keep the container surface symbolic. Expanding the array through
            # write defs replaces a vector with one `push_back` element and
            # loses the name `_container_element` needs for provenance.
            return Select(
                self._expand_container_surface(e.array, fn, depth),
                self._expand(e.index, fn, depth),
            )
        if isinstance(e, Ref):
            return self._expand_name(e.symbol, e, fn, depth)
        if isinstance(e, Call):
            return self._expand_call(e, fn, depth)
        return e

    def _fold_graph_success_cmp(self, e: Bin) -> Expr | None:
        """`ret != ge::GRAPH_SUCCESS` → False on the legal encode path."""
        if e.op not in ("!=", "=="):
            return None

        def _is_graph_success(side: Expr) -> bool:
            text = _pretty(side) if not isinstance(side, Ref) else side.symbol
            return bool(re.search(r"(?:ge::)?GRAPH_SUCCESS\b", str(text or "")))

        def _is_ret(side: Expr) -> bool:
            if isinstance(side, Ref):
                return side.symbol.split("::")[-1] == "ret"
            return False

        if _is_ret(e.left) and _is_graph_success(e.right):
            return Const(False if e.op == "!=" else True)
        if _is_ret(e.right) and _is_graph_success(e.left):
            return Const(False if e.op == "!=" else True)
        return None

    def _expand_named_const_cmp(self, e: Bin, fn: str, depth: int) -> Expr | None:
        """Keep field-vs-enum comparisons shallow.

        When exactly one side is already a named constant / constexpr, the
        other side is a classifier operand: expand casts only, do not substitute
        every guarded write of the field. Full substitution is still used for
        arithmetic and for non-constant comparisons (e.g. `d > s1`).
        """
        if e.op not in CMP_OPS:
            return None
        left_const = _is_constant(e.left)
        right_const = _is_constant(e.right)
        if left_const == right_const:
            return None
        if left_const:
            return Bin(
                e.op,
                self._expand(e.left, fn, depth),
                self._expand_surface(e.right, fn, depth),
            )
        return Bin(
            e.op,
            self._expand_surface(e.left, fn, depth),
            self._expand(e.right, fn, depth),
        )

    def _expand_surface(self, e: Expr, fn: str, depth: int) -> Expr:
        """Expand casts / strcmp rewrites, but leave names as resolver leaves."""
        if isinstance(e, (Const, Unknown, Ref)):
            return e
        if isinstance(e, Un):
            return Un(e.op, self._expand_surface(e.arg, fn, depth))
        if isinstance(e, Call):
            name = e.func[len("field:") :] if e.func.startswith("field:") else e.func
            short = name.split("::")[-1]
            if short in _CAST_CALLS and len(e.args) == 1:
                return self._expand_surface(e.args[0], fn, depth)
            # Keep accessor calls intact so the resolver can classify them.
            return Call(
                e.func,
                tuple(self._expand_surface(a, fn, depth) for a in e.args),
            )
        if isinstance(e, Bin):
            rewritten = rewrite_strcmp_cmp(e)
            if rewritten is not e:
                return self._expand_surface(rewritten, fn, depth)
            return Bin(
                e.op,
                self._expand_surface(e.left, fn, depth),
                self._expand_surface(e.right, fn, depth),
            )
        if isinstance(e, Select):
            return Select(
                self._expand_surface(e.array, fn, depth),
                self._expand_surface(e.index, fn, depth),
            )
        if isinstance(e, Ite):
            return Ite(
                self._expand_surface(e.cond, fn, depth),
                self._expand_surface(e.then, fn, depth),
                self._expand_surface(e.else_, fn, depth),
            )
        return e

    def _expand_container_surface(self, e: Expr, fn: str, depth: int) -> Expr:
        """Peel casts / nested selects without substituting container writes."""
        self._nodes += 1
        if self._nodes > MAX_NODES or depth > MAX_DEPTH:
            return Unknown(REASON_BUDGET if self._nodes > MAX_NODES else REASON_DEPTH)
        if isinstance(e, (Const, Unknown, Ref)):
            return e
        if isinstance(e, Select):
            return Select(
                self._expand_container_surface(e.array, fn, depth + 1),
                self._expand(e.index, fn, depth + 1),
            )
        if isinstance(e, Call):
            name = e.func[len("field:") :] if e.func.startswith("field:") else e.func
            short = name.split("::")[-1]
            if name in _CAST_CALLS and len(e.args) == 1:
                return self._expand_container_surface(e.args[0], fn, depth + 1)
            if short in _CONTAINER_OPS:
                return e
            if e.func.startswith("field:") or dotted_path(e) is not None:
                if not e.args:
                    return e
                head = self._expand_container_surface(e.args[0], fn, depth + 1)
                tail = tuple(self._expand(a, fn, depth + 1) for a in e.args[1:])
                return Call(e.func, (head,) + tail)
            return e
        if isinstance(e, Un):
            return Un(e.op, self._expand_container_surface(e.arg, fn, depth + 1))
        if isinstance(e, Ite):
            return Ite(
                self._expand(e.cond, fn, depth + 1),
                self._expand_container_surface(e.then, fn, depth + 1),
                self._expand_container_surface(e.else_, fn, depth + 1),
            )
        if isinstance(e, Bin):
            return Bin(
                e.op,
                self._expand_container_surface(e.left, fn, depth + 1),
                self._expand_container_surface(e.right, fn, depth + 1),
            )
        return e

    def _expand_call(self, e: Call, fn: str, depth: int) -> Expr:
        name = e.func[len("field:") :] if e.func.startswith("field:") else e.func
        short = name.split("::")[-1]
        if name in _CAST_CALLS and len(e.args) == 1:
            return self._expand(e.args[0], fn, depth)
        # Locked SKU: fold platform core / L2 queries to INI constants.
        folded = self._platform_const_call(short)
        if folded is not None:
            return folded
        # A whole-container reduction / element accessor is named by its
        # container. Expanding the iterator arguments substitutes the container
        # for the element written by one `push_back`, which loses the name.
        if short in _CONTAINER_OPS:
            return e
        slot = _projection_index(name)
        if slot is not None and len(e.args) == 1:
            projected = _project(slot, self._expand(e.args[0], fn, depth))
            if projected is not None:
                return projected
        path = dotted_path(e)
        if path is not None:
            return self._expand_name(path, e, fn, depth)
        # Two calls to the same helper with different actuals are different
        # expansions, so the recursion key has to carry the arguments.
        key = (fn, f"{name}({','.join(_pretty_dag(a) for a in e.args)})")
        if key not in self._stack:
            sites, note = self._return_defs(name, list(e.args))
            if sites and not note:
                self._stack.add(key)
                try:
                    return self._chain(sites, fn, depth)
                finally:
                    self._stack.discard(key)
        return Call(e.func, tuple(self._expand(a, fn, depth) for a in e.args))

    def _platform_const_call(self, short: str) -> Const | None:
        prof = getattr(self.model, "platform_profile", None)
        if prof is None:
            return None
        if short == "GetCoreNumAic" or short == "GetCoreNum":
            return Const(int(prof.aic_num))
        if short == "GetCoreNumAiv":
            return Const(int(prof.vector_core_cnt))
        if short == "GetL2Size":
            return Const(int(prof.l2_size))
        return None

    def _is_platform_null_cmp(self, e: Bin) -> bool:
        if getattr(self.model, "platform_profile", None) is None:
            return False
        if e.op not in ("==", "!="):
            return False

        def _is_null(x: Expr) -> bool:
            if isinstance(x, Const) and x.value in (None, "nullptr", "NULL", 0, "0"):
                return True
            if isinstance(x, Ref) and x.symbol in ("nullptr", "NULL", "None"):
                return True
            return False

        def _is_plat(x: Expr) -> bool:
            if isinstance(x, Call):
                name = x.func[len("field:") :] if x.func.startswith("field:") else x.func
                return name.split("::")[-1] in (
                    "GetPlatformInfo",
                    "GetPlatformInfoPtr",
                    "GetAscendcPlatform",
                )
            return False

        return (_is_plat(e.left) and _is_null(e.right)) or (
            _is_plat(e.right) and _is_null(e.left)
        )

    def _canonical_name(self, name: str, fn: str) -> str:
        """Map a bare tiling member to its `fBaseParams.*` / `tilingData.*` path.

        `_defs_for("splitAxis")` already returns the field writes, but the
        expand stack keyed only on the bare name. A nested
        `fBaseParams.splitAxis` then rebuilt the whole chain and cycled through
        `bn2S2RouteLimit`, leaving opaque Refs in the guards. Canonicalizing
        puts both spellings on the same frame.
        """
        if not name or "." in name:
            return name
        if name not in getattr(self.ir, "class_fields", ()):
            return name
        # Prefer a local definition in this scope when it exists — that is a
        # real alias (`auto splitAxis = fBaseParams.splitAxis`), not the field.
        if self._local_defs(name, fn):
            return name
        for owner in ("fBaseParams", "tilingData"):
            if self._field_defs(f"{owner}.{name}"):
                return f"{owner}.{name}"
        return name

    def _expand_name(self, name: str, original: Expr, fn: str, depth: int) -> Expr:
        """Substitute a name by its definitions, all the way to input roots.

        Stopping at the first name the resolver can already classify would
        collapse exactly the branch structure this module exists to recover:
        `fBaseParams.splitAxis` resolves to INPUT_SHAPE, but *which* shape
        predicate selects each value is only visible in its guarded writes.
        """
        leaf = original if isinstance(original, Ref) else Ref(name)
        canon = self._canonical_name(name, fn)
        key = (fn, canon)
        if key in self._stack or any(n == canon for _s, n in self._stack):
            self.cycles.add(canon)
            return leaf
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        # Same host state under another caller scope.
        for (scope2, other), got in self._cache.items():
            if other == canon and scope2 != fn:
                self._cache[key] = got
                return got
        sites = self._defs_for(name, fn)
        if not sites and canon != name:
            sites = self._defs_for(canon, fn)
        if not sites:
            return leaf
        # A for-init like `i = 0` carries only a discarded `for(...)` guard. If
        # we chained it, the empty usable-guard set would promote that write to
        # an unconditional definition and fold `i` to `0`. Leave the name as a
        # leaf so the resolver can classify it as LOOP_INDUCTION / scheduling.
        if _loop_scoped_only(sites):
            self._cache[key] = leaf
            return leaf
        self._stack.add(key)
        try:
            out = self._chain(sites, fn, depth)
        finally:
            self._stack.discard(key)
        # A depth-truncated result is an artefact of *where* the name was first
        # reached, not a property of the name. Caching it would poison every
        # later, shallower use.
        if not _has_reason(out, REASON_DEPTH):
            self._cache[key] = out
        return out

    def _scope(self, fn: str):
        if fn not in self._scoped:
            self._scoped[fn] = self.resolver._in_function(fn) if fn else self.resolver
        return self._scoped[fn]

    # -- entry point -------------------------------------------------------
    def derive(self, *, dim_name: str, index: int, host_expr: str, function: str):
        self._nodes = 0
        self.cycles = set()
        expanded = self._expand_text(host_expr, function, 0)
        out = KeyFieldDerivation(
            name=dim_name,
            index=index,
            host_expr=host_expr,
            expanded=_pretty_dag(expanded),
            def_sites=self._defs_for(strip_casts(host_expr), function),
        )
        norm = _ValueNormalizer(self._scope(function), self.model)
        try:
            out.value_expr = norm.value(expanded)
        except NormalizeError as exc:
            out.unresolved.append({"text": exc.detail, "reason": exc.reason})
        leaves = value_leaves(expanded)
        if out.value_expr is not None:
            leaves |= smt_value_leaves(out.value_expr)
        out.value_leaves = sorted(leaves)
        out.scheduling = dict(norm.scheduling)
        out.undecided = dict(norm.undecided)
        for reason in sorted(set(_collect_unknowns(expanded))):
            out.unresolved.append({"text": "", "reason": reason})
        if self.cycles:
            out.note = f"{REASON_CYCLE}: " + ",".join(sorted(self.cycles)[:6])
        if out.value_expr is not None:
            out.variables = sorted(_collect_vars_dag(out.value_expr))
            # Roots must come from variables that survived into value_expr.
            # Accumulating every leaf the normalizer touched while walking
            # softened guards (GetCoreNumAic, …) is how PLATFORM_CORE_COUNT
            # landed on IsTnd even though its SMT form is a single SCHED bool.
            out.input_roots = sorted(
                {
                    norm.roots[v]
                    for v in out.variables
                    if v in norm.roots and not v.startswith(("VAR_SCHED_", "VAR_UNDECIDED_"))
                }
            )
        # Softening an undecidable guard is an over-approximation, and a field
        # whose *every* guard was softened carries no input constraint at all —
        # calling that "derived" would hand the test generator a dimension it
        # believes is decided when nothing decides it. A field that folded to a
        # genuine constant has no undecided guards and is unaffected.
        #
        # Do NOT harvest roots from the full expanded DAG when value_expr
        # already exists: that reintroduces the platform/scheduling leaves the
        # projection above just removed.
        if out.undecided and not out.input_roots and out.value_expr is None:
            harvested = self._harvest_input_roots(expanded)
            if harvested:
                out.input_roots = sorted(harvested)
                out.status = STATUS_DERIVED
            else:
                out.note = "; ".join(filter(None, [out.note, "ALL_GUARDS_SOFTENED"]))
                out.status = STATUS_PARTIAL
        elif out.value_expr is not None and not out.unresolved:
            out.status = STATUS_DERIVED
        elif out.value_expr is not None or out.variables:
            out.status = STATUS_PARTIAL
        else:
            out.status = STATUS_UNRESOLVED
        return out

    def _harvest_input_roots(self, exp: Expr) -> set[str]:
        """Recover input roots from the expanded DAG when SMT soft-only."""
        from uo_init.source_resolver import LEGAL_ROOTS

        roots: set[str] = set()
        stack = [exp]
        seen: set[int] = set()
        while stack:
            n = stack.pop()
            if id(n) in seen:
                continue
            seen.add(id(n))
            if isinstance(n, (Bin,)):
                stack.extend([n.left, n.right])
            elif isinstance(n, Un):
                stack.append(n.arg)
            elif isinstance(n, Ite):
                stack.extend([n.cond, n.then, n.else_])
            elif isinstance(n, Call):
                stack.extend(n.args)
                text = _pretty_dag(n)[:200]
                res = self.resolver.resolve(text)
                for a in res.atoms:
                    if a.root in LEGAL_ROOTS and a.root not in (
                        "CONSTANT",
                        "EXTERNAL",
                        "LOOP_DERIVED",
                        "LOOP_INDUCTION",
                        "KERNEL_BUILTIN",
                    ):
                        roots.add(a.root)
            elif isinstance(n, Select):
                stack.extend([n.array, n.index])
            elif isinstance(n, Ref):
                res = self.resolver.resolve(n.symbol)
                for a in res.atoms:
                    if a.root in LEGAL_ROOTS and a.root not in (
                        "CONSTANT",
                        "EXTERNAL",
                        "LOOP_DERIVED",
                        "LOOP_INDUCTION",
                        "KERNEL_BUILTIN",
                    ):
                        roots.add(a.root)
        return roots


def _deref(e: Expr) -> Expr:
    """`*p` / `&x` carry the value of what they point at."""
    while isinstance(e, Un) and e.op in ("*", "&"):
        e = e.arg
    return e


# Whole-container reductions: no closed form over the elements, but the result
# is decided by whatever input fills the container.
_REDUCTIONS = {
    "max_element": "max",
    "min_element": "min",
    "accumulate": "sum",
    "reduce": "sum",
}

# Element / length accessors over the same containers. Kept opaque through
# expand (like reductions) so the container name survives into normalize.
_ELEMENT_ACCESSORS = {
    "back": "back",
    "front": "front",
    "at": "elem",
    "size": "size",
    "empty": "empty",
}

_CONTAINER_OPS = {**_REDUCTIONS, **_ELEMENT_ACCESSORS}

# Accessor names that must not become the variable slug — they collide across
# every tensor that resolves through the same GetData/GetDim chase.
_GENERIC_ACCESSORS = frozenset(
    {
        "GetData",
        "GetDim",
        "GetDimNum",
        "GetStorageShape",
        "GetOriginShape",
        "size",
        "data",
        "begin",
        "end",
    }
)

_ITERATOR_METHODS = ("begin", "end", "cbegin", "cend", "rbegin", "rend", "data")

_TUPLE_BUILDERS = ("tie", "make_tuple", "make_pair", "__init_list")
_GET_RE = re.compile(r"^get<(\d+)>$")
_PAIR_SLOTS = {"first": 0, "second": 1}


def _projection_index(func: str) -> int | None:
    short = (func[len("field:") :] if func.startswith("field:") else func).split("::")[-1]
    m = _GET_RE.match(short)
    return int(m.group(1)) if m else _PAIR_SLOTS.get(short)


def _project(index: int, expr: Expr) -> Expr | None:
    """Take one component out of a tuple, distributing over branches.

    `GetS1S2TemplateType` returns a different `make_pair` per dtype, so after
    inlining, `.second` is applied to an `Ite` chain rather than to a pair.
    Without pushing the projection into the branches the whole chain stays
    opaque and the field cannot be derived.
    """
    expr = _deref(expr)
    if isinstance(expr, Ite):
        then = _project(index, expr.then)
        other = _project(index, expr.else_)
        if then is None or other is None:
            return None
        return Ite(expr.cond, then, other)
    if isinstance(expr, Call):
        builder = (
            expr.func[len("field:") :]
            if expr.func.startswith("field:")
            else expr.func
        )
        if builder.split("::")[-1] in _TUPLE_BUILDERS and index < len(expr.args):
            return expr.args[index]
    return None


def _tuple_element(short: str, args: list[Expr]) -> Expr | None:
    """`std::get<1>(std::tie(a, b, c))` -> `b`.

    The tuple is built and indexed in the same expression, so the element is
    known statically; leaving the call opaque loses a plain value.
    """
    m = _GET_RE.match(short)
    if m is None or len(args) != 1:
        return None
    tup = _deref(args[0])
    if not isinstance(tup, Call):
        return None
    builder = tup.func[len("field:") :] if tup.func.startswith("field:") else tup.func
    if builder.split("::")[-1] not in _TUPLE_BUILDERS:
        return None
    index = int(m.group(1))
    return tup.args[index] if index < len(tup.args) else None


def _container_of(arg: Expr) -> str:
    """`fBaseParams.actualSeqQlen.begin()` -> `fBaseParams.actualSeqQlen`.

    The iterator method parses as a plain call wrapping the container rather
    than as a member access, so unwrap it before asking for the dotted path.
    Nested selects (`a[i][j]`) peel down to the outermost container name.
    """
    arg = _deref(arg)
    while isinstance(arg, Select):
        arg = _deref(arg.array)
    if isinstance(arg, Call):
        short = arg.func[len("field:") :] if arg.func.startswith("field:") else arg.func
        if short.split("::")[-1] in _ITERATOR_METHODS and len(arg.args) == 1:
            arg = arg.args[0]
    path = dotted_path(arg)
    if not path:
        if isinstance(arg, Ref):
            return arg.symbol
        return ""
    head, _, tail = path.rpartition(".")
    return head if head and tail in _ITERATOR_METHODS else path


# A member name is not a name in scope. Substituting a formal called `d` into
# `params.d > d` has to leave the member alone, or the guard silently becomes
# `params.64 > 64`.
_NAME_RE = re.compile(r"(?<![.\w])(?<!->)(?<!::)([A-Za-z_]\w*)\b")


def _substitute_names(text: str, subst: dict[str, str]) -> str:
    if not subst:
        return text
    return _NAME_RE.sub(lambda m: subst.get(m.group(1), m.group(1)), text)


def _collect_unknowns(e: Expr) -> list[str]:
    return [n.reason for n in _walk_dag(e) if isinstance(n, Unknown)]


class _ValueNormalizer(PredicateNormalizer):
    """PredicateNormalizer extended with a value-producing entry point.

    A key field is an integer, not a predicate, so `Ite` has to survive into the
    SMT as `if_then_else` at value level rather than being coerced to a bool.
    """

    def __init__(self, resolver, model) -> None:
        super().__init__(resolver, model)
        self.roots: dict[str, str] = {}
        self.scheduling: dict[str, str] = {}
        self.undecided: dict[str, str] = {}
        # The expanded expression is a DAG. Normalising it as a tree costs the
        # unfolded size, so each (node, position) is lowered exactly once and
        # the resulting SMT-lite object is shared by every reference to it.
        self._memo: dict[tuple[int, str], tuple[Expr, dict[str, Any]]] = {}

    def _lower(self, expr: Expr, position: str, fn) -> dict[str, Any]:
        key = (id(expr), position)
        hit = self._memo.get(key)
        if hit is not None:
            return hit[1]
        out = fn(expr)
        self._memo[key] = (expr, out)
        return out

    def _guard(self, cond: Expr) -> dict[str, Any]:
        return self._lower(cond, "guard", self._guard_uncached)

    def _guard_uncached(self, cond: Expr) -> dict[str, Any]:
        """A guard position, which is allowed to be undecidable.

        A guard only selects *which* assignment applies. When it cannot be
        reduced to inputs — a loop accumulator, a helper we do not model — the
        honest statement is "either branch may apply", not "this whole field is
        underivable". It becomes a free boolean so the solver explores both
        sides, and the drop is recorded so the over-approximation is auditable.
        Value positions get no such licence: there a failure is a real failure.
        """
        cond = rewrite_strcmp_cmp(_deref(cond))
        # Decompose first: in `shapeOk && loopAccumulator > n` only the second
        # conjunct is undecidable, and collapsing the pair would throw away a
        # real input constraint.
        if isinstance(cond, Bin) and cond.op in BOOL_OPS:
            return {
                "op": BOOL_OPS[cond.op],
                "args": [self._guard(cond.left), self._guard(cond.right)],
            }
        if isinstance(cond, Un) and cond.op in ("!", "not"):
            return {"op": "not", "arg": self._guard(cond.arg)}
        # Schedule / GRAPH_SUCCESS / reachability — soft without expanding.
        soft = self._sched_soft_guard(cond)
        if soft is not None:
            return soft
        try:
            return self._bool(cond)
        except NormalizeError as exc:
            from uo_init.ids import hash12

            # Must stay DAG-aware: `_pretty` here unfolds the whole guard and
            # costs more than the derivation it is reporting on.
            text = _pretty_dag(cond)
            var_id = f"VAR_UNDECIDED_{hash12(text)}"
            if self.model.get(var_id) is None:
                self.model.add(
                    VarSpec(
                        var_id=var_id,
                        name=var_id,
                        value_type="bool",
                        domain=Domain(
                            var_id=var_id,
                            value_type="bool",
                            completeness="open",
                            source="undecidable_guard",
                        ),
                        origin="UNDECIDED_GUARD",
                        description=f"{exc.reason}: {text[:160]}",
                    )
                )
            self.undecided[var_id] = f"{exc.reason}: {text[:160]}"
            return {"op": "eq", "var": var_id, "value": True}

    def _sched_soft_guard(self, cond: Expr) -> dict[str, Any] | None:
        """Mark known scheduling/reachability guards without expanding them."""
        from uo_init.ids import hash12

        text = _pretty_dag(cond)
        if not _SCHED_SOFT_RE.search(text):
            return None
        # Only soft when the *dominant* theme is schedule — keep mixed input
        # guards going through normal _bool so layout/shape conjuncts survive.
        if re.search(
            r"GetAttr|GetDim|GetDataType|hasRope|QUERY_ROPE|keepProb|layoutType|"
            r"INPUT_FORMAT|splitAxis|isBn2|deterSparse|queryType",
            text,
        ) and not re.search(r"__reached_|syncRound|currentSum|CheckExceedL2", text):
            return None
        var_id = f"VAR_SCHED_{hash12(text)[:12]}"
        if self.model.get(var_id) is None:
            self.model.add(
                VarSpec(
                    var_id=var_id,
                    name=var_id,
                    value_type="bool",
                    domain=Domain(
                        var_id=var_id,
                        value_type="bool",
                        completeness="open",
                        source="scheduling_guard",
                    ),
                    origin="SCHED_SOFT",
                    description=f"scheduling/reachability soft: {text[:120]}",
                )
            )
        self.scheduling[var_id] = "SCHED_SOFT"
        self.undecided[var_id] = f"SCHED_SOFT: {text[:160]}"
        return {"op": "eq", "var": var_id, "value": True}

    def _leaf(self, expr: Expr) -> dict[str, Any]:
        expr = _deref(expr)
        if isinstance(expr, Select):
            elem = self._container_element(expr.array, kind="elem")
            if elem is not None:
                return elem
            raise NormalizeError(REASON_OPAQUE, "array_subscript")
        text = _leaf_text(expr)
        lit = self._named_lit(text)
        if lit is not None:
            return {"lit": lit}
        sched = self._scheduling_leaf(expr)
        if sched is not None:
            return sched
        out = super()._leaf(expr)
        if "lit" in out and isinstance(out["lit"], str):
            named = self._named_lit(out["lit"])
            if named is not None:
                return {"lit": named}
        if "var" in out and out.get("root"):
            self.roots[out["var"]] = out["root"]
        return out

    def _named_lit(self, symbol: str | None) -> int | None:
        if not symbol:
            return None
        lookup = getattr(self.model, "lookup_constant", None)
        if lookup is None:
            return None
        return lookup(symbol)

    def _container_element(
        self, container_expr: Expr, *, kind: str = "elem"
    ) -> dict[str, Any] | None:
        """One element / length of an input-backed container as a free variable.

        Same provenance story as `_container_reduction`: the concrete index is
        often a scheduling position, but the *value* still comes from the input
        that fills the container.
        """
        container = _container_of(container_expr)
        if not container:
            path = dotted_path(_deref(container_expr))
            container = path or ""
        if not container:
            return None
        res = self.resolver.resolve(container)
        atoms = [a for a in res.atoms if a.root and a.root != "CONSTANT"]
        if not atoms:
            return None
        from uo_init.ids import slug

        atom = atoms[0]
        # Resolver often chases a container to a generic accessor (`GetData`,
        # `GetDim`). Slugging that collapses every tensor into one variable.
        # Prefer the container surface name for identity.
        raw_sym = atom.symbol or ""
        if raw_sym in _GENERIC_ACCESSORS or not raw_sym:
            label = container
        else:
            label = raw_sym
        var_id = f"VAR_ELEM_{kind.upper()}_{slug(label)}"
        value_type = "bool" if kind == "empty" else "int"
        if self.model.get(var_id) is None:
            self.model.add(
                VarSpec(
                    var_id=var_id,
                    name=f"{kind}({container})",
                    value_type=value_type,
                    domain=Domain(
                        var_id=var_id,
                        value_type=value_type,
                        lo=None if value_type == "bool" else 0,
                        completeness="open",
                        source="container_element",
                    ),
                    origin=atom.root,
                    description=f"{kind} of {container}; decided by its input",
                )
            )
        self.model.declare_on_demand(var_id, atom.root)
        self.roots[var_id] = atom.root
        return {"var": var_id, "root": atom.root}

    def _container_reduction(self, short: str, args: list[Expr]) -> dict[str, Any] | None:
        """`*std::max_element(v.begin(), v.end())` as one input-derived value.

        A whole-container reduction has no closed form over the elements, but it
        is still a function of the input that fills the container: under TND,
        `s1` is the largest entry of `actualSeqQlen`, which comes straight from
        the optional sequence-length tensor. Modelling it as a variable that
        inherits the container's root keeps the input provenance, where failing
        the call would drop the field entirely.
        """
        kind = _REDUCTIONS.get(short) or _ELEMENT_ACCESSORS.get(short)
        if kind is None or not args:
            return None
        if short in _ELEMENT_ACCESSORS:
            return self._container_element(args[0], kind=kind)
        container = _container_of(args[0])
        if not container:
            return None
        res = self.resolver.resolve(container)
        atoms = [a for a in res.atoms if a.root and a.root != "CONSTANT"]
        if not atoms:
            return None
        from uo_init.ids import slug

        atom = atoms[0]
        raw_sym = atom.symbol or ""
        label = (
            container
            if (raw_sym in _GENERIC_ACCESSORS or not raw_sym)
            else raw_sym
        )
        var_id = f"VAR_REDUCE_{kind.upper()}_{slug(label)}"
        if self.model.get(var_id) is None:
            self.model.add(
                VarSpec(
                    var_id=var_id,
                    name=f"{kind}({container})",
                    value_type="int",
                    domain=Domain(
                        var_id=var_id,
                        value_type="int",
                        lo=0,
                        completeness="open",
                        source="container_reduction",
                    ),
                    origin=atom.root,
                    description=f"{kind} over {container}; decided by its input",
                )
            )
        self.model.declare_on_demand(var_id, atom.root)
        self.roots[var_id] = atom.root
        return {"var": var_id, "root": atom.root}

    def _scheduling_leaf(self, expr: Expr) -> dict[str, Any] | None:
        """Turn a traversal-position leaf into an unconstrained variable.

        Left to the base normalizer these raise UNMAPPED_LEAF, because
        `var_id_for` has no id for them, and one loop counter deep inside a
        guard would sink the whole field.
        """
        from uo_init.ids import slug

        text = _leaf_text(expr)
        if not text:
            return None
        res = self.resolver.resolve(text)
        atoms = [a for a in res.atoms if a.root and a.root != "CONSTANT"]
        if not atoms or atoms[0].root not in SCHEDULING_ROOTS:
            return None
        atom = atoms[0]
        var_id = f"VAR_SCHED_{slug(atom.symbol or text)}"
        if self.model.get(var_id) is None:
            self.model.add(
                VarSpec(
                    var_id=var_id,
                    name=atom.symbol or text,
                    value_type="int",
                    domain=Domain(
                        var_id=var_id,
                        value_type="int",
                        lo=0,
                        completeness="open",
                        source="scheduling_position",
                    ),
                    origin=atom.root,
                    description="traversal position; unconstrained by input",
                )
            )
        self.scheduling[var_id] = atom.root
        return {"var": var_id, "root": atom.root}

    def _bool(self, expr: Expr) -> dict[str, Any]:
        expr = _deref(expr)
        if isinstance(expr, Select):
            leaf = self._container_element(expr.array, kind="elem")
            if leaf is not None:
                return self._truthy(leaf)
            raise NormalizeError(REASON_OPAQUE, "array_subscript")
        return self._lower(expr, "bool", lambda e: super(_ValueNormalizer, self)._bool(_deref(e)))

    def _value(self, expr: Expr) -> dict[str, Any]:
        return self._lower(expr, "value", self._value_uncached)

    def _value_uncached(self, expr: Expr) -> dict[str, Any]:
        """Value position, with `Ite` kept as a value rather than coerced to bool."""
        expr = _deref(expr)
        if isinstance(expr, Unknown):
            raise NormalizeError(expr.reason, "")
        if isinstance(expr, Select):
            elem = self._container_element(expr.array, kind="elem")
            if elem is not None:
                return elem
            raise NormalizeError(REASON_OPAQUE, "array_subscript")
        if isinstance(expr, Call):
            helper = self._pure_helper(expr)
            if helper is not None:
                return helper
        if isinstance(expr, Ite):
            return {
                "op": "if_then_else",
                "condition": self._guard(expr.cond),
                "then": _as_operand(self._value(expr.then)),
                "else": _as_operand(self._value(expr.else_)),
            }
        # A boolean-valued key field is `predicate ? 1 : 0`, so its predicate
        # sits in a *selection* position exactly like a def-site guard, and gets
        # the same licence: `_guard` decomposes the conjunction and softens only
        # the conjuncts it cannot reduce. Routing it through `_bool` instead
        # made one unreducible conjunct — a loop accumulator, a helper we do not
        # model — sink the whole field, even though the other conjuncts were
        # perfectly good input constraints.
        if isinstance(expr, Un) and expr.op in ("!", "not"):
            return {
                "op": "if_then_else",
                "condition": self._guard(expr.arg),
                "then": 0,
                "else": 1,
            }
        if isinstance(expr, Bin) and (expr.op in CMP_OPS or expr.op in BOOL_OPS):
            return {
                "op": "if_then_else",
                "condition": self._guard(expr),
                "then": 1,
                "else": 0,
            }
        return super()._value(expr)

    def _pure_helper(self, e: Call) -> dict[str, Any] | None:
        """Arithmetic helpers that have an exact integer lowering.

        `std::max(a, b)` reaches the base normalizer as an opaque call and the
        resolver splits it into two atoms, so it fails as a leaf even though
        both arguments resolve perfectly well.
        """
        name = e.func[len("field:") :] if e.func.startswith("field:") else e.func
        short = name.split("::")[-1]
        args = list(e.args)
        reduced = self._container_reduction(short, args)
        if reduced is not None:
            return reduced
        picked = _tuple_element(short, args)
        if picked is not None:
            return self._value(picked)
        # `std::max({a, b, c})` is one initialiser-list argument, not three.
        if (
            len(args) == 1
            and isinstance(args[0], Call)
            and args[0].func == "__init_list"
        ):
            args = list(args[0].args)
        if short in ("max", "min") and len(args) >= 2:
            op = "gt" if short == "max" else "lt"
            acc = self._value(args[0])
            for nxt in args[1:]:
                cur = self._value(nxt)
                acc = {
                    "op": "if_then_else",
                    "condition": {
                        "op": op,
                        "lhs": _as_operand(acc),
                        "rhs": _as_operand(cur),
                    },
                    "then": _as_operand(acc),
                    "else": _as_operand(cur),
                }
            return acc
        if short == "abs" and len(args) == 1:
            inner = self._value(args[0])
            return {
                "op": "if_then_else",
                "condition": {"op": "ge", "lhs": _as_operand(inner), "rhs": 0},
                "then": _as_operand(inner),
                "else": {"op": "sub", "args": [0, _as_operand(inner)]},
            }
        if short in ("CeilDiv", "CeilDivision", "CeilDivideBy") and len(args) == 2:
            num, den = self._value(args[0]), self._value(args[1])
            return {
                "op": "div",
                "args": [
                    {"op": "sub", "args": [
                        {"op": "add", "args": [_as_operand(num), _as_operand(den)]}, 1
                    ]},
                    _as_operand(den),
                ],
            }
        if short in ("AlignUp", "AlignTo") and len(args) == 2:
            val, align = self._value(args[0]), self._value(args[1])
            return {
                "op": "mul",
                "args": [
                    {"op": "div", "args": [
                        {"op": "sub", "args": [
                            {"op": "add", "args": [_as_operand(val), _as_operand(align)]}, 1
                        ]},
                        _as_operand(align),
                    ]},
                    _as_operand(align),
                ],
            }
        if short == "AlignDown" and len(args) == 2:
            val, align = self._value(args[0]), self._value(args[1])
            return {
                "op": "mul",
                "args": [
                    {"op": "div", "args": [_as_operand(val), _as_operand(align)]},
                    _as_operand(align),
                ],
            }
        return None

    def value(self, e: Expr) -> dict[str, Any]:
        return self._value(e)
