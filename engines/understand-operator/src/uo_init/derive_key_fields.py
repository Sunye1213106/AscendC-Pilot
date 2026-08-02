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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from uo_init.clang_walk import RETURN_SLOT
from uo_init.cpp_expr import parse_expr
from uo_init.expr_ir import Bin, Call, Const, Expr, Ite, Ref, Select, Un, Unknown
from uo_init.kb_model import CONTROLLABLE_ROOTS, PLATFORM_LOCKED_ROOTS, Domain
from uo_init.loop_summary import guard_truth
from uo_init.predicate import (
    ARITH_OPS,
    BOOL_OPS,
    CMP_OPS,
    NormalizeError,
    PredicateNormalizer,
    REASON_OPAQUE,
    REASON_UNMAPPED_LEAF,
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

# How faithful the derived expression is to the source, which `status` alone
# cannot say: "derived" covers both a field pinned exactly to its inputs and one
# whose guards were all replaced by free booleans. A test generator treating the
# second as decided will believe it controls a dimension that nothing controls.
EX_EXACT = "exact"
EX_CONSTANT = "constant"
EX_OVERAPPROX = "overapproximated"
EX_PARTIAL = "partial"
EX_UNRESOLVED = "unresolved"

# Variables the derivation invents when it cannot decide something. Each one
# widens the field's condition, so their presence in `value_expr` is exactly
# what separates `exact` from `overapproximated`:
#   VAR_UNDECIDED_  a guard that failed to normalize
#   VAR_SCHED_      a guard on schedule position rather than on the input
#   VAR_REACHED_    "did control actually reach this function"
#   VAR_INIT_       "no guard matched, so the field kept its default"
#   VAR_LOOPELEM_   an element of a container built inside a loop
LOOPELEM_PREFIX = "VAR_LOOPELEM_"

OVERAPPROX_PREFIXES = (
    "VAR_UNDECIDED_",
    "VAR_SCHED_",
    "VAR_REACHED_",
    "VAR_INIT_",
    LOOPELEM_PREFIX,
)


def is_overapprox_var(var_id: str) -> bool:
    return str(var_id).startswith(OVERAPPROX_PREFIXES)


def classify_exactness(
    *,
    value_expr: dict[str, Any] | None,
    variables: list[str],
    unresolved: list[dict[str, str]],
    implicit_defaults: list[dict[str, Any]] | None = None,
) -> tuple[str, list[str]]:
    """Grade a derivation and list the variables standing in for what it lost."""
    if value_expr is None:
        return EX_UNRESOLVED, []
    free = sorted({v for v in variables if is_overapprox_var(v)})
    if unresolved:
        return EX_PARTIAL, free
    if free:
        return EX_OVERAPPROX, free
    if implicit_defaults:
        # The chain rested on a default nobody read. Each such site mints a
        # VAR_INIT_ variable, so this is normally already covered by `free` --
        # unless simplification dropped the branch it sat on. Grading on the
        # record as well means no route back to "exact" survives the
        # assumption, whatever the expression ends up looking like.
        return EX_OVERAPPROX, free
    if not variables:
        return EX_CONSTANT, []
    return EX_EXACT, []


#: `status` is the coarse view older consumers read; keep it a projection of
#: exactness so the two can never disagree.
_STATUS_OF_EXACTNESS = {
    EX_EXACT: STATUS_DERIVED,
    EX_CONSTANT: STATUS_DERIVED,
    EX_OVERAPPROX: STATUS_PARTIAL,
    EX_PARTIAL: STATUS_PARTIAL,
    EX_UNRESOLVED: STATUS_UNRESOLVED,
}


def status_of_exactness(exactness: str) -> str:
    return _STATUS_OF_EXACTNESS.get(exactness, STATUS_UNRESOLVED)

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

# Synthetic marker `_chain` emits for a cross-function unguarded write: "this
# assignment applies if control reached that function at all". It is not a
# source-level name, so it can be recognized by spelling.
REACHED_PREFIX = "__reached_"


def _is_true(e: Expr) -> bool:
    return isinstance(e, Const) and e.value is True

# Roots that carry no constraint on the input and so cannot pin a key down:
# traversal position, and leaves the resolver could only call constant or
# external. Everything else in LEGAL_ROOTS — shapes, dtypes, formats,
# attributes, platform facts — is a real constraint and must survive.
_UNCONSTRAINING_ROOTS = SCHEDULING_ROOTS | {"CONSTANT", "EXTERNAL"}

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

# How far to follow a classifier operand's writes before giving up on it. This
# bounds the *cost* of the attempt only — whether the result is used is decided
# by `_reduces_to_inputs`, not by size. Wide enough that no expansion which does
# reduce has been seen to hit it (the largest, IsAttenMask, is ~40 nodes),
# narrow enough that a runaway one stops in well under a second rather than
# grinding to the global budget, which took 185s for IsBn2MultiBlk.
CLASSIFIER_PROBE_NODES = 4000

# Roots a generated case can pin down: knobs plus everything fixed by the CANN
# profile. A classifier operand that still reaches anything else after expansion
# has not been reduced to an input condition.
_DRIVABLE_ROOTS = CONTROLLABLE_ROOTS | PLATFORM_LOCKED_ROOTS

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
    #: The same guards before `pretty()` flattened negation into `!(…)` text.
    #: Needed to tell the two branches of one `if` apart, which is what decides
    #: whether a chain of writes leaves any path falling through to the default.
    #: Empty for def sites that do not come from a recorded write.
    conds: tuple[Any, ...] = ()
    #: Position of every loop header this write sits under, as `(file, line)`.
    #: Taken before `_decisive_conds` drops loop guards, because ordering a
    #: write against a read needs to know they share an iteration: inside one
    #: loop a write below a read still runs before it on the next pass round.
    loops: tuple[tuple[str, int], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rhs": self.rhs,
            "guards": list(self.guards),
            "file": self.file,
            "line": self.line,
            "function": self.function,
        }


def _decisive_conds(w) -> tuple[Any, ...]:
    """A write's guards, keeping only those that decide a branch.

    A macro-expanded guard has no readable text, and a loop or `switch` guard is
    not a two-way decision (see `PathCond.is_decision`), so neither can be
    reasoned about as "this path or the other". Both are dropped rather than
    treated as decisions, which makes the coverage test below give up instead of
    concluding wrongly.
    """
    return tuple(
        pc for pc in getattr(w, "path_conditions", ()) if not pc.is_opaque and _decides(pc)
    )


def _loops_of(w) -> tuple[tuple[str, int], ...]:
    """Where the loops are that this write sits inside."""
    return tuple(
        (pc.file, pc.line)
        for pc in getattr(w, "path_conditions", ())
        if getattr(pc, "kind", "") in _LOOP_COND_KINDS
    )


def _decides(pc) -> bool:
    if "kind" in getattr(pc, "__dict__", {}):
        return pc.is_decision
    # A guard with no `kind` comes either from the text backend or from a cached
    # extraction predating the field. Both spell a loop or `switch` into the
    # text, which is what this used to read before `kind` existed.
    return not _NON_GUARD_RE.match(pc.text or "")


def _same_decision(a, b) -> bool:
    return (a.file, a.line, a.text) == (b.file, b.line, b.text)


def _paths_are_covered(paths: list[tuple[Any, ...]]) -> bool:
    """Do these guarded writes leave no path falling through to the default?

    This is what tells `if (A) x=1; else if (B) x=2; else x=3;` — exhaustive,
    nothing assumed — apart from `if (A) x=1;`, where the source really does
    leave `x` at whatever it was declared as.

    An unguarded write among them is *not* taken as covering the rest. Inside a
    function it would, but whether it runs at all depends on the function being
    called, and which write wins depends on the order `_chain_sites` folds them
    in. That decision stays there.
    """
    if not paths or any(len(p) == 0 for p in paths):
        return False
    return _covers(paths)


def _records_rest(paths: list[tuple[Any, ...]]) -> bool:
    """Do the guards leading into these paths record what follows them?

    Asked per side of a decision, not per decision: a `guard_clause` is always
    the negated side, so the two sides can differ.
    """
    return all(getattr(p[0], "records_what_follows", True) for p in paths)


def _covers(paths: list[tuple[Any, ...]], trusted: bool = True) -> bool:
    """Recursively: from this point on, is every continuation written?

    At each point every path must be deciding the same condition, and both of
    its branches must in turn be covered. A path that has run out means this
    side of the decision is written outright. Paths that disagree about which
    condition comes next cannot be folded this way, and the answer is no: an
    unproven assumption reported as one is the safe direction.

    `trusted` says whether the guard leading into these paths records what
    follows it. When it does not (see `PathCond.records_what_follows`) a path
    running out is not evidence of an unconditional write — the rest of its
    guards were never written down. Without this, a `return` after
    `if (c) return;` looks unconditional and stops this decision's two sides
    from being checked at all.
    """
    if not paths:
        return False
    if any(len(p) == 0 for p in paths):
        return trusted
    head = paths[0][0]
    if not all(_same_decision(p[0], head) for p in paths):
        return False
    pos = [p for p in paths if not p[0].negated]
    neg = [p for p in paths if p[0].negated]
    return _covers([p[1:] for p in pos], _records_rest(pos)) and _covers(
        [p[1:] for p in neg], _records_rest(neg)
    )


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
    #: var_id -> the symbol resolution stopped on, for guards whose text is far
    #: too large to read the failure out of.
    blocked_on: dict[str, str] = field(default_factory=dict)
    #: var_id -> the function the variable was read in. Two same-named
    #: containers in different functions share guard text, so evidence lookup
    #: needs this to cite the right one.
    var_scope: dict[str, str] = field(default_factory=dict)
    #: var_id -> declared type, for the variables this derivation minted. The
    #: parent process re-declares them and cannot otherwise know.
    var_types: dict[str, str] = field(default_factory=dict)
    status: str = STATUS_UNRESOLVED
    exactness: str = EX_UNRESOLVED
    free_vars: list[str] = field(default_factory=list)
    implicit_defaults: list[dict[str, Any]] = field(default_factory=list)
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
            "blocked_on": dict(self.blocked_on),
            "var_scope": dict(self.var_scope),
            "var_types": dict(self.var_types),
            "status": self.status,
            "exactness": self.exactness,
            "free_vars": list(self.free_vars),
            "implicit_defaults": list(self.implicit_defaults),
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


def collect_vars_dag(node: Any) -> set[str]:
    """Public view of `_collect_vars_dag`, for consumers outside derivation."""
    return _collect_vars_dag(node)


def truth_probe_var(node: Any) -> str | None:
    """The variable a "this guard held" probe tests, or None if not a probe.

    `PredicateNormalizer._truthy` renders the probe by the variable's type: a
    bool becomes `var == True`, an int becomes `var != 0` (C's implicit
    truthiness). Both mean the same thing, so both are substitutable.
    """
    var = node.get("var")
    if not isinstance(var, str):
        return None
    op = node.get("op")
    value = node.get("value")
    if op == "eq" and value is True:
        return var
    if op == "ne" and not isinstance(value, bool) and value == 0:
        return var
    return None


def substitute_vars(node: Any, replacements: dict[str, Any]) -> Any:
    """Rewrite truth probes of the given variables into real conditions.

    A softened guard enters `value_expr` as `{"op": "eq", "var": VAR_UNDECIDED_x,
    "value": True}`. When something later establishes what that guard actually
    tested, substituting the condition back in is what removes the
    over-approximation. Dropping the guard *record* alone would only hide it:
    the free variable would still be in the expression a solver sees, but
    nothing would remain to say what it stood for.

    Only the `eq/True` shape used to be matched, so every int-typed variable —
    which is all of the loop-element cuts — was skipped in silence: the guard
    got struck from the record while its variable stayed in the expression,
    exactly the failure the paragraph above describes. Callers should still
    verify the substitution landed; see `apply_bindings_to_derivation`.

    Structure-sharing is preserved — a normalized expression is a DAG, and
    rebuilding it as a tree unfolds to the size the sharing exists to avoid.
    """
    if not replacements:
        return node
    memo: dict[int, Any] = {}

    def rewrite(n: Any) -> Any:
        if isinstance(n, (str, int, float, bool)) or n is None:
            return n
        hit = memo.get(id(n))
        if hit is not None:
            return hit
        out: Any
        if isinstance(n, dict):
            probe = truth_probe_var(n)
            if probe is not None and probe in replacements:
                out = replacements[probe]
            else:
                out = {k: rewrite(v) for k, v in n.items()}
        elif isinstance(n, list):
            out = [rewrite(item) for item in n]
        else:
            out = n
        memo[id(n)] = out
        return out

    return rewrite(node)


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


# Normalisation memoises by node identity (`_ValueNormalizer._lower`), so a
# `value_expr` is a DAG: one sub-expression object is reachable by many paths.
# JSON and YAML have no notion of sharing, so a plain dump writes it once per
# path — the unfolded tree, which is the cost the sharing exists to avoid. One
# FAG field reached ~10MB that way and the full report ran out of memory.
_DAG_MARK = "$dag"
_DAG_REF = "$ref"

# Under this, the unfolded form is still small enough to read, and a legible
# artifact is worth more than the bytes.
DAG_ENVELOPE_MIN_NODES = 4000


def _is_expr_container(node: Any) -> bool:
    return isinstance(node, (dict, list))


def _smt_children(node: Any) -> list[Any]:
    if isinstance(node, dict):
        return [v for v in node.values() if _is_expr_container(v)]
    if isinstance(node, list):
        return [v for v in node if _is_expr_container(v)]
    return []


def _dag_postorder(root: Any) -> tuple[list[Any], dict[int, int]]:
    """Distinct containers of `root`, children before parents, plus in-degree.

    Iterative because a derived expression nests deeper than the default
    recursion limit, and counted per DAG edge rather than per path so the walk
    stays linear in the shared structure.
    """
    order: list[Any] = []
    refs: dict[int, int] = {}
    seen: set[int] = set()
    stack: list[tuple[Any, bool]] = [(root, False)]
    while stack:
        node, done = stack.pop()
        if not _is_expr_container(node):
            continue
        if done:
            order.append(node)
            continue
        refs[id(node)] = refs.get(id(node), 0) + 1
        if id(node) in seen:
            continue
        seen.add(id(node))
        stack.append((node, True))
        for child in _smt_children(node):
            stack.append((child, False))
    return order, refs


def _dag_sizes(order: list[Any]) -> dict[int, int]:
    """Unfolded size per node, as a proxy for what dumping it would cost."""
    size: dict[int, int] = {}
    for node in order:
        size[id(node)] = len(node) + sum(
            size.get(id(child), 0) for child in _smt_children(node)
        )
    return size


def expr_tree_size(root: Any) -> int:
    """Size `root` would have written out as a tree.

    Computed over the DAG, so asking the question does not cost what the answer
    is there to warn about.
    """
    if not _is_expr_container(root):
        return 1
    order, _ = _dag_postorder(root)
    return _dag_sizes(order).get(id(root), 1)


def encode_expr_dag(node: Any, *, min_tree_nodes: int = DAG_ENVELOPE_MIN_NODES) -> Any:
    """Make sharing explicit, so a dump costs the DAG and not the unfolded tree.

    Small expressions pass through unchanged: every reader already accepts the
    plain form, and keeping the artifact legible is worth more than the bytes.
    Above the threshold the result is `{"$dag": 1, "root": …, "defs": {…}}`
    with `{"$ref": name}` standing in for each shared sub-expression.

    A reader that skips `decode_expr_dag` sees a dict that is plainly not an
    expression, rather than a subtly truncated one.
    """
    if not _is_expr_container(node):
        return node
    order, refs = _dag_postorder(node)
    size = _dag_sizes(order)
    if size.get(id(node), 0) <= min_tree_nodes:
        return node

    names: dict[int, str] = {}
    built: dict[int, Any] = {}
    defs: dict[str, Any] = {}

    def emit(value: Any) -> Any:
        if not _is_expr_container(value):
            return value
        name = names.get(id(value))
        return {_DAG_REF: name} if name else built[id(value)]

    for n in order:
        if isinstance(n, dict):
            body: Any = {k: emit(v) for k, v in n.items()}
        else:
            body = [emit(v) for v in n]
        built[id(n)] = body
        # Naming a node costs a definition plus one reference per use, so it
        # only pays off for shared nodes big enough to beat repeating them.
        if refs.get(id(n), 0) > 1 and size.get(id(n), 0) >= _SHARE_MIN_SIZE:
            name = f"n{len(defs) + 1}"
            names[id(n)] = name
            defs[name] = body

    return {
        _DAG_MARK: 1,
        "nodes": len(order),
        "tree_nodes": size.get(id(node), 0),
        "root": emit(node),
        "defs": defs,
    }


def decode_expr_dag(node: Any) -> Any:
    """Inverse of `encode_expr_dag`; a plain expression passes straight through.

    Sharing is rebuilt, not merely the shape: a consumer that walked the
    restored form as a tree would pay exactly the cost the envelope avoids.
    """
    if not (isinstance(node, dict) and _DAG_MARK in node):
        return node
    defs = node.get("defs") or {}
    # Iterative on purpose. Only nodes big and shared enough earn a definition,
    # so what stays inline is one deep spine, and these run to tens of
    # thousands of levels. Recursing needs the limit raised past what the C
    # stack can carry, and that does not raise a Python error -- the process
    # dies with no traceback.
    done: dict[int, Any] = {}
    # (node, are its children ready yet)
    stack: list[tuple[Any, bool]] = [(node.get("root"), False)]
    while stack:
        value, expanded = stack.pop()
        vid = id(value)
        if vid in done:
            continue
        if not isinstance(value, (dict, list)):
            done[vid] = value
            continue
        ref = value.get(_DAG_REF) if isinstance(value, dict) else None
        if isinstance(ref, str):
            if ref not in defs:
                raise ValueError(f"expression DAG references undefined node {ref!r}")
            body = defs[ref]
            if id(body) in done:
                # Every reference to a definition yields the same object, which
                # is the sharing the envelope exists to restore.
                done[vid] = done[id(body)]
            else:
                stack.append((value, True))
                stack.append((body, False))
            continue
        if not expanded:
            stack.append((value, True))
            for child in value.values() if isinstance(value, dict) else value:
                stack.append((child, False))
            continue
        if isinstance(value, dict):
            done[vid] = {k: done[id(v)] for k, v in value.items()}
        else:
            done[vid] = [done[id(v)] for v in value]
    return done[id(node.get("root"))]


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

    Shared sub-expressions are visited once. The result is a set either way, so
    this is purely about not paying the unfolded size of the DAG.
    """
    vals: set[str] = set()
    seen: set[int] = set()

    def walk(n: Any) -> None:
        if _is_expr_container(n):
            if id(n) in seen:
                return
            seen.add(id(n))
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
        #: `(function, name, versions in scope, writes in view) -> expansion`.
        #: The last part is empty unless a write was dropped as not yet run;
        #: without it two reads of one name at different points in a function
        #: would share an entry. See `_visible_defs`.
        self._cache: dict[tuple[str, str, tuple, tuple], Expr] = {}
        self._stack: set[tuple[str, str]] = set()
        #: Names whose chain is currently being built. Cycle detection has to
        #: key on identity alone — unlike the cache, which also keys on the
        #: part-built values in scope — or a name re-entered under a different
        #: context would not be recognised as recursion.
        self._active: set[str] = set()
        self._scoped: dict[str, Any] = {}
        #: Variable being chained -> value of its writes so far, so that a
        #: self-referencing RHS reads the previous version instead of looking
        #: like a cycle. See `_chain`.
        self._prev_version: dict[str, Expr] = {}
        #: Names whose previous version was read while building the expansion
        #: currently in progress, so a result that depended on someone else's
        #: half-built value can be kept out of the cache.
        self._prev_read: set[str] = set()
        #: The write whose right-hand side is being expanded, which is where
        #: the names inside it are being read. See `_visible_defs`.
        self._read_at: DefSite | None = None
        #: `(name, sites)` pairs already being re-expanded at an earlier
        #: program point, so that re-entry cannot descend forever.
        self._earlier_frames: set[tuple[Any, ...]] = set()
        #: function -> entered at most once per run. See `_runs_once`.
        self._runs_once_cache: dict[str, bool] = {}
        #: read site -> the line it happens at in each enclosing function.
        self._read_line_cache: dict[tuple[str, int, str], dict] = {}
        #: (read site, name) -> reaching the read forces one of its writes.
        #: Each miss costs a solver call, and the same question is asked once
        #: per field whose derivation passes through the name.
        self._read_cover_cache: dict[tuple[str, int, str, str], bool] = {}
        #: Functions whose reachability condition is being built, to stop
        #: recursion in the call graph.
        self._reach_stack: set[str] = set()
        self._reach_cache: dict[str, Expr] = {}
        #: The function the key is encoded in, and every function that call
        #: sits inside. Reaching the encoding means those ran, which is the
        #: only ground on which "always reached" is a fact. See `_encode_path`.
        self._encode_fn: str = ""
        self._encode_path_cache: set[str] | None = None
        self.cycles: set[str] = set()
        #: Sites where an if/else-if chain was closed with an assumed zero
        #: default. See `_chain`.
        self.implicit_zero: list[dict[str, Any]] = []
        self._implicit_seen: set[tuple[str, str, int]] = set()
        #: field path → whether its writes re-read it. See
        #: `_writes_are_self_routing`.
        self._self_routing: dict[str, bool] = {}
        #: (guard text, function) → whether its value is already settled. Kept
        #: across dimensions: the same guard is chained once per field that
        #: passes through it, and each answer costs two solver calls.
        self._guard_truth_cache: dict[tuple[str, str], Any] = {}
        #: Tightened node budget while probing a classifier operand; `None`
        #: means the global `MAX_NODES` applies.
        self._node_ceiling: int | None = None
        #: Fields whose expansion did not reduce to inputs. Kept across
        #: dimensions: it is a property of the field's writes, not of the read.
        self._rejected: set[str] = set()
        # (id(node), scope) -> (node, expansion). The node is kept alive so its
        # id cannot be recycled onto a different object.
        self._ememo: dict[tuple[int, str], tuple[Expr, Expr]] = {}

    # -- definition lookup -------------------------------------------------
    def _field_defs(self, path: str) -> list[DefSite]:
        tail = path.rsplit(".", 1)[-1]
        by_tail = self.ir.writes_by_tail().get(tail, [])
        exact = [w for w in by_tail if w.path == path or w.path.endswith("." + path)]
        exact += self._alias_writes(path, tail, exact)
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
                conds=_decisive_conds(w),
                loops=_loops_of(w),
            )
            for w in sorted(pool, key=lambda w: (w.file, w.line))
            if w.rhs.strip()
        ]

    def _alias_writes(self, path: str, tail: str, already: list) -> list:
        """Writes reaching `path` through a reference parameter.

        `SetSplitAxis(ctx, FuzzyBaseInfoParamsRegbase& fBaseParams)` records
        `fBaseParams.splitAxis`, which the suffix match above cannot relate to
        `this.fBaseParams.splitAxis`. Take those writes only when the parameter
        provably receives that member at every call site, so a helper handed a
        different object of the same type stays out.
        """
        target = path[len("this.") :] if path.startswith("this.") else path
        member, _, rest = target.partition(".")
        if not rest:
            # A one-segment path has no member prefix to bind against, and the
            # parameter name would be matched against the field name itself.
            return []
        seen = {(w.file, w.line, w.path) for w in already}
        out = []
        for w in self.ir.writes_by_tail().get(tail, []):
            head = w.path.split(".", 1)[0]
            if head in ("this", "") or w.path != f"{head}.{rest}":
                continue
            if (w.file, w.line, w.path) in seen:
                continue
            if self.ir.param_bound_member(w.function, head) == member:
                out.append(w)
        return out

    def _local_defs(self, name: str, fn: str) -> list[DefSite]:
        writes = self.ir.local_writes_in(fn).get(name, [])
        return [
            DefSite(
                rhs=w.rhs,
                guards=tuple(w.guards()),
                file=w.file,
                line=w.line,
                function=w.function,
                conds=_decisive_conds(w),
                loops=_loops_of(w),
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
        out_param = self._out_param_defs(name, fn)
        if out_param:
            return out_param
        return self._unique_foreign_defs(name, fn)

    def _out_param_defs(self, name: str, fn: str) -> list[DefSite]:
        """A local the callee writes through a reference parameter.

        `CalcleActualToken(fBaseParams, i, s1Token, s2Token)` leaves no write
        to `s2Token` in this function at all — the assignments are to the
        formal, inside the callee. The whole guarded chain is taken, not the
        last assignment alone: these functions typically set a default and
        then refine it, so the last write is often `x = f(x)` and on its own
        says nothing about what `x` was.
        """
        caller = self.ir.summaries.get(fn)
        if caller is None:
            return []
        found: list[tuple[str, str]] = []
        for callee, args in caller.calls:
            target = self.ir.summaries.get(callee)
            if target is None or not target.out_params:
                continue
            outs = set(target.out_params)
            for pname, actual in zip(target.params, args):
                if pname not in outs:
                    continue
                if (actual or "").lstrip("&").strip() != name:
                    continue
                if (callee, pname) not in found:
                    found.append((callee, pname))
        # Written through two different callees: which one ran last is a
        # question about order this does not answer, so it stays unresolved
        # rather than picking one.
        if len(found) != 1:
            return []
        callee, pname = found[0]
        return self._local_defs(pname, callee)

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
                # The guards are renamed into the caller's names above; the
                # conditions are not, because nothing reads their text — only
                # which decision each one is, to tell an exhaustive chain of
                # returns from one that falls through to a default.
                conds=_decisive_conds(w),
            )
            for w in reversed(list(slot))
        ]

    # -- expansion ---------------------------------------------------------
    def _chain(
        self,
        sites: list[DefSite],
        fn: str,
        depth: int,
        *,
        defining: str = "",
        pool: list[DefSite] | None = None,
    ) -> Expr:
        """Sequential assignment semantics: a later write wins where its guard holds.

        An unguarded write only overrides prior writes from the *same* function.
        Without that, a fallthrough assignment in `DoSparse` (empty usable
        guards) would last-wins-erase `SetSplitAxis`'s `BN2S2` from another TU,
        collapsing a three-valued enum to two. Cross-function unguarded writes
        become soft alternatives under a reachability tag instead.

        `defining` names the variable these sites write, which is what makes
        `x = f(x)` readable: sites are in source order, so when the RHS of one
        mentions the variable, it means the value built by the sites before it
        — exactly what `result` holds at that point.
        """
        result: Expr | None = None
        result_fn: str | None = None
        ident = self._ident(defining, fn) if defining else ""
        outer = self._prev_version.pop(ident, None) if ident else None
        try:
            return self._chain_sites(sites, fn, depth, defining, pool or sites, ident)
        finally:
            if ident:
                if outer is None:
                    self._prev_version.pop(ident, None)
                else:
                    self._prev_version[ident] = outer

    def _chain_sites(
        self,
        sites: list[DefSite],
        fn: str,
        depth: int,
        defining: str,
        pool: list[DefSite],
        ident: str = "",
    ) -> Expr:
        result: Expr | None = None
        result_fn: str | None = None
        # When the writes cover every path, the fall-through below is dead code
        # and there is nothing being assumed about the declaration.
        #
        # Judged on `pool` -- every write to the name -- while the value below
        # is built from `sites`, the ones that have run by this read. The two
        # differ where a name is read between its writes, and asking coverage
        # of the shorter list gets the wrong answer: reading `n2` inside the
        # branch that just set it leaves the other branch's write out of view,
        # which looks like a path with no value and mints an initial-value
        # variable for a path that cannot happen.
        #
        # Coverage is a property of one function's writes: two functions each
        # writing one side of the same condition look exhaustive together, but
        # either can be called alone. Asked per function rather than only when
        # there is exactly one, because a write somewhere else does not unmake
        # the coverage here. `fBaseParams.b` is assigned on all five layout
        # branches of `GetShapeAttrsInfo` — the fifth a plain `else` — and once
        # more in `DoOpTiling`; letting that sixth write veto the judgement
        # minted a free variable for a path the five branches leave no room
        # for, and it went on to block five dimensions.
        # Coverage inside a function says its writes leave no path through it
        # without a value. For a member that is only half the story: a run that
        # never enters the function still reads whatever it held before, so the
        # function has to be one that always runs. A local needs no such
        # premise — a run that skips the function neither writes it nor has
        # anywhere to read it from.
        covered_in = {
            name: _paths_are_covered(
                [s.conds for s in pool if (s.function or fn) == name]
            )
            and (self._is_local_of(defining, name) or self._always_runs(name, depth))
            for name in {s.function or fn for s in pool}
        }
        for site in sites:
            scope = site.function or fn
            guards = self._live_guards(site.guards, scope)
            if guards is None:
                # A guard proved false on every run: this write cannot happen,
                # and keeping it would put a branch in the expression that the
                # operator never takes — along with the free variables its
                # condition mentions.
                continue
            if defining:
                # Read by `_expand_name` when the RHS or guard names the
                # variable being defined. Absent for the first site: a
                # self-reference there is a read before any write, which is
                # a genuine unknown rather than a previous version.
                if result is None:
                    self._prev_version.pop(ident or defining, None)
                else:
                    self._prev_version[ident or defining] = result
            value = self._expand_at(site, site.rhs, scope, depth + 1)
            guard_text = _conjoin_text(guards)
            if guard_text and result is None and self._is_declaration_site(
                defining, site, scope
            ):
                # Guards on a declaration say which block it is in, not which
                # runs give it a value. See `_is_declaration_site`.
                guard_text = ""
            if not guard_text:
                if result is None or scope == result_fn:
                    result = value
                    result_fn = scope
                else:
                    result = Ite(self._reached(scope, depth), value, result)
                continue
            cond = self._expand_at(site, guard_text, scope, depth + 1)
            # An if/else-if chain with no unguarded write falls through to the
            # declared default, which for tiling structs and enums is zero.
            #
            # That default is an assumption about a declaration we have not
            # read, so it is recorded rather than taken silently: if the field
            # is initialised to anything else, every key derived through this
            # branch is wrong, and nothing else would show it.
            declared = None
            assumed: Expr | None = None
            if (
                result is None
                and not covered_in.get(scope, False)
                and not self._read_forces_a_write(pool, defining)
            ):
                declared = self._declared_default(defining, scope, depth)
                if declared is None:
                    assumed = self._init_var(defining, scope, site)
                    # One site, one assumption. A site can be chained more than
                    # once — different callers, different cache contexts — and
                    # counting it each time would report the number of visits
                    # rather than the number of things assumed.
                    site_key = (scope, site.file, site.line)
                    if site_key not in self._implicit_seen:
                        self._implicit_seen.add(site_key)
                        self.implicit_zero.append(
                            {
                                "function": scope,
                                "file": site.file,
                                "line": site.line,
                                "guard": guard_text[:120],
                                "field": defining,
                                "variable": assumed.symbol,
                            }
                        )
            if result is not None:
                fallthrough = result
            elif declared is not None:
                fallthrough = declared
            else:
                fallthrough = assumed if assumed is not None else Const(0)
            result = Ite(cond, value, fallthrough)
            result_fn = scope
        return result if result is not None else Unknown(REASON_NO_DEFINITION)

    def _read_forces_a_write(self, pool: list[DefSite], defining: str) -> bool:
        """Can this read be reached at all without one of the writes running?

        Writes can look partial and still leave nothing to assume, because
        where a name is *read* is a condition too. `fBaseParams.bandIdx` is
        written only when an attention mask is present and read only under the
        same test, so the two together admit no run that reads it unwritten --
        and the free variable minted for that run went on to block five
        dimensions.

        Asked of the solver rather than by comparing guard text: the read's
        condition and the writes' rarely match word for word, and only the
        `unsat` answer is used, so a query that fails to prove anything leaves
        the assumption exactly where it was.
        """
        read = self._read_at
        if read is None or not read.conds or not pool:
            return False
        key = (read.file, read.line, read.function, defining)
        hit = self._read_cover_cache.get(key)
        if hit is None:
            from uo_init.loop_summary import guards_cover

            hit = bool(
                guards_cover(
                    read.conds,
                    [(s.conds, s.function or read.function) for s in pool],
                    read_function=read.function,
                    members=getattr(self.ir, "class_fields", ()) or (),
                )
            )
            self._read_cover_cache[key] = hit
        return hit

    def _live_guards(self, guards: tuple[str, ...], scope: str) -> tuple[str, ...] | None:
        """`guards` without the ones already decided, or None if none can hold.

        A guard whose value is fixed before any input is not a condition, and
        writing it into the expression costs a branch plus a free variable for
        everything it mentions. `syncRounds.size() + syncRoundRanges.size() >
        CORE_LIST_NUM` is the case this exists for: both vectors are filled
        from opposite sides of one `if` inside a 36-iteration loop, so the sum
        never exceeds 36 and the early return behind it is unreachable.
        """
        out: list[str] = []
        for text in guards:
            truth = self._guard_truth(text, scope)
            if truth.always_false:
                return None
            if truth.always_true:
                continue
            out.append(text)
        return tuple(out)

    def _guard_truth(self, text: str, scope: str):
        key = (text, scope)
        hit = self._guard_truth_cache.get(key)
        if hit is None:
            hit = guard_truth(
                self.ir, text, scope, constants=self._int_named_constants()
            )
            self._guard_truth_cache[key] = hit
        return hit

    def _int_named_constants(self) -> dict[str, int]:
        cached = getattr(self, "_int_consts", None)
        if cached is None:
            named = getattr(self.model, "named_constants", None) or {}
            cached = {k: v for k, v in named.items() if isinstance(v, int)}
            self._int_consts = cached
        return cached

    def _init_var(self, defining: str, scope: str, site: DefSite) -> Ref:
        """A free variable for the value a field holds before any write.

        The chain ends at a guard that may not hold and no declaration could be
        read, so the value on that path is whatever the field was initialised
        to — which is unknown. Closing with `Const(0)` states a default nobody
        read: sound only if it happens to be right, and when it is wrong the
        solver rules out keys the operator does produce. An unconstrained
        variable says the same thing honestly, and `classify_exactness` sees it
        by its prefix and stops calling such a field exact.
        """
        from uo_init.ids import hash12

        text = f"{scope}:{defining}:{site.file}:{site.line}"
        var_id = f"VAR_INIT_{hash12(text)[:12]}"
        if self.model is not None and self.model.get(var_id) is None:
            self.model.add(
                VarSpec(
                    var_id=var_id,
                    name=var_id,
                    value_type="int",
                    domain=Domain(
                        var_id=var_id,
                        value_type="int",
                        completeness="open",
                        source="init_unknown",
                    ),
                    origin="INIT_UNKNOWN",
                    description=f"value of {defining} before any write ({site.file}:{site.line})",
                )
            )
        return Ref(var_id)

    def _always_runs(self, scope: str, depth: int) -> bool:
        """Does `scope` run on every path that reaches the key encoding?"""
        reached = self._reached(scope, depth)
        return isinstance(reached, Const) and reached.value is True

    def _is_local_of(self, defining: str, scope: str) -> bool:
        """Is `defining` a variable local to `scope`?

        Unlike `_is_declaration_site` this asks nothing about an initialiser.
        The question here is lifetime, not value: a local does not outlive the
        call, so a run that never enters the function has nowhere to read it
        from and coverage inside the function is the whole story.
        """
        if not defining or "." in defining or self.ir is None:
            return False
        find = getattr(self.ir, "local_decl", None)
        if find is None:
            return False
        return bool(find(defining, scope) or find(defining, scope.split("::")[-1]))

    def _is_declaration_site(self, defining: str, site: DefSite, scope: str) -> bool:
        """Is this write the declaration of a local, initialiser and all?

        Such a write has already run wherever the variable can be read. C++
        scoping is the whole argument: a read of a block-scoped local sits
        inside the block that declares it and after the declaration, so the
        guards on the declaration are conditions on reaching the block, not
        conditions on the variable having a value. Reading them as the latter
        asks what `seqQShapeSize` holds when the layout is not TND — a block it
        is not declared in, where no read of it exists — and answers with a
        free variable that then keeps five dimensions off `exact`.

        Requires an initialiser. `int64_t x;` followed by a guarded assignment
        really can be read before anything writes it, and that indeterminate
        value is exactly what the chain's fall-through is for.

        Members, parameters and out parameters are all excluded by asking for a
        local declaration: each of those outlives the writes seen here, so a
        read before them is a real path.
        """
        if not defining or "." in defining or self.ir is None:
            return False
        find = getattr(self.ir, "local_decl", None)
        if find is None:
            return False
        decl = find(defining, scope) or find(defining, scope.split("::")[-1])
        if decl is None or not (decl.init or "").strip():
            return False
        # The chain can hold several writes to one local; only the declaration
        # itself carries this argument.
        return decl.line == site.line and (not site.file or decl.file == site.file)

    def _declared_default(self, defining: str, scope: str, depth: int) -> Expr | None:
        """What the declaration initialises `defining` to, if that is knowable.

        Closing a chain with `Const(0)` asserts a default nobody read, and for
        `dTemplateType` (declared `NUM64`) or `s1TemplateType` (`NUM128`) that
        assertion is simply false — a solver would then accept keys where the
        field is 0, which the operator cannot produce.

        Returns None when the answer is not known, which keeps the assumption
        and its record. Three separate reasons for that, all left alone on
        purpose: no declaration was found, the member declares no initialiser
        at all (its value really is indeterminate before the first write), or
        the initialiser does not reduce to a constant.
        """
        if not defining or self.ir is None:
            return None
        decl = self.ir.field_decl(defining)
        if decl is None or decl.init is None:
            return None
        try:
            expanded = self._expand_text(decl.init, scope, depth + 1)
        except Exception:  # noqa: BLE001 - an unreadable initialiser is "unknown"
            return None
        return expanded if _is_constant(expanded) else None

    def _note_root(self, fn: str) -> None:
        """Record the function the current question is asked in."""
        if fn == self._encode_fn:
            return
        self._encode_fn = fn
        self._encode_path_cache = None
        self._reach_cache.clear()

    def _encode_path(self) -> set[str]:
        """Functions a run must have entered to reach the key encoding.

        Every field's value is asked for at one program point: where the key
        is built. So the function holding that point ran, and so did every
        function that lies on all the ways of getting there — the dominators
        of the encoding in the call graph.

        Following single callers upward only finds a prefix of that set. The
        framework's driver calls the encoding once for real and once more to
        log it, and with two call sites the climb stopped immediately, leaving
        the driver and every hook it calls looking like they might not run.

        Entries are the functions nothing calls, restricted to those that can
        reach the encoding at all; the hundreds of registry accessors with no
        callers are not ways into this question. Edges the walk missed split
        the entries and shrink the answer, which is the safe direction: a
        function left out is merely one we decline to assume ran.
        """
        if self._encode_path_cache is not None:
            return self._encode_path_cache
        encode = self._encode_fn.split("::")[-1] if self._encode_fn else ""
        if not encode:
            self._encode_path_cache = set()
            return self._encode_path_cache

        preds: dict[str, set[str]] = {}
        nodes = {encode}
        queue = [encode]
        while queue:
            fn = queue.pop()
            up: set[str] = set()
            for site in self._calls_to(fn):
                caller = str(getattr(site, "caller", "") or "").split("::")[-1]
                if not caller or caller == fn:
                    continue
                up.add(caller)
                if caller not in nodes:
                    nodes.add(caller)
                    queue.append(caller)
            preds[fn] = up

        roots = {fn for fn in nodes if not preds.get(fn)}
        if not roots:
            # Every way in is itself called: the graph closed into a cycle and
            # there is no entry to start the argument from.
            self._encode_path_cache = {encode}
            return self._encode_path_cache

        dom: dict[str, set[str]] = {fn: set(nodes) for fn in nodes}
        for root in roots:
            dom[root] = {root}
        changed = True
        while changed:
            changed = False
            for fn in nodes:
                if fn in roots:
                    continue
                ps = preds.get(fn) or set()
                if not ps:
                    continue
                merged = set(nodes)
                for p in ps:
                    merged &= dom[p]
                merged.add(fn)
                if merged != dom[fn]:
                    dom[fn] = merged
                    changed = True
        self._encode_path_cache = dom[encode]
        return self._encode_path_cache

    def _reached(self, scope: str, depth: int) -> Expr:
        """When does `scope` run? The disjunction over its call sites.

        A write with no guard of its own still only happens if its function is
        called, and only on the paths the call is on. Those guards are
        recorded, so this is an ordinary condition on the input; the
        `__reached_` placeholder it replaces was a free boolean that let a
        solver have the write both ways.

        `Const(True)` is only ever emitted where it is a fact rather than a
        guess, and there is exactly one such ground: the derivation answers
        "what do the fields hold when a key is encoded", so every function the
        encoding sits inside has run in any run that reaches the question.
        `_encode_path` is that set. A function outside it with no recorded call
        site is not a framework entry — it is a function whose callers the walk
        never saw, and claiming it always runs lets an unguarded write in it
        erase what earlier writes left. That is a claim about control flow with
        nothing behind it, and the erased value is exactly what makes a
        satisfiable key look unreachable.
        """
        short = scope.split("::")[-1]
        if short in self._reach_stack:
            # Recursion, direct or mutual: no finite condition to build here.
            return Ref(f"{REACHED_PREFIX}{scope}")
        # Whether a function runs is a property of the call graph, not of the
        # expansion that asked. Recomputing it per ask walks every path to the
        # entry point again, and rebuilds nodes the DAG is meant to share.
        hit = self._reach_cache.get(short)
        if hit is not None:
            return hit
        sites = self.ir.calls_to(short) if hasattr(self.ir, "calls_to") else []
        if not sites:
            out: Expr = (
                Const(True)
                if short in self._encode_path()
                else Ref(f"{REACHED_PREFIX}{scope}")
            )
            self._reach_cache[short] = out
            return out
        self._reach_stack.add(short)
        try:
            terms: list[Expr] = []
            for site in sites:
                # A bailout is not a condition on this call, it is a condition
                # on the run existing at all: `if (ret != SUCCESS) return ret;`
                # before the call means every run that got past it — every run
                # that reaches the encoding — took the call. Carried here it
                # reads as "this hook may not have run", which is how a driver
                # that calls its hooks in a fixed order ends up looking
                # optional. The condition is not lost; it is a premise on the
                # inputs, collected by `legality_premises`.
                conds = tuple(
                    c
                    for c in getattr(site, "path_conditions", ())
                    if not getattr(c, "is_bailout", False)
                )
                guard_text = _conjoin_text(
                    tuple(c.pretty() for c in conds if not c.is_opaque)
                )
                # Resolve caller reachability first: when the caller is a
                # framework entry (Const True) and this call is unguarded, the
                # whole term collapses without expanding any path text.
                up = self._reached(site.caller, depth + 1)
                if not guard_text:
                    term = up
                elif _is_true(up):
                    term = self._expand_text(guard_text, site.caller, depth + 1)
                else:
                    here = self._expand_text(guard_text, site.caller, depth + 1)
                    term = Bin("&&", up, here)
                if any(getattr(c, "is_opaque", False) for c in conds):
                    # A condition nobody could read is still a condition.
                    # Dropped, this call site reads as easier to reach than it
                    # is, and "reached" is what decides whether an unguarded
                    # write here overwrites the value already there.
                    unread = Ref(
                        f"{REACHED_PREFIX}{site.caller}@"
                        f"{getattr(site, 'line', 0)}"
                    )
                    term = unread if _is_true(term) else Bin("&&", term, unread)
                if _is_true(term):
                    self._reach_cache[short] = Const(True)
                    return Const(True)
                terms.append(term)
        finally:
            self._reach_stack.discard(short)
        out = terms[0]
        for t in terms[1:]:
            out = Bin("||", out, t)
        self._reach_cache[short] = out
        return out

    def _expand_at(self, site: DefSite, text: str, fn: str, depth: int) -> Expr:
        """Expand `text` knowing it is read at `site`.

        Which writes to that name are in view depends on where it is read;
        see `_visible_defs`.
        """
        outer = self._read_at
        self._read_at = site
        try:
            return self._expand_text(text, fn, depth)
        finally:
            self._read_at = outer

    def _calls_to(self, fn: str) -> list[Any]:
        find = getattr(self.ir, "calls_to", None) if self.ir is not None else None
        return list(find(fn)) if find and fn else []

    def _runs_once(self, fn: str) -> bool:
        """Is `fn` entered at most once per run?

        Asked before a caller's line number is allowed to order anything. A
        function entered twice has already run once by the second entry, so a
        write below the first call sits above the second, and comparing lines
        would rule out a write that did happen.
        """
        hit = self._runs_once_cache.get(fn)
        if hit is not None:
            return hit
        # Pessimistic while recursing: mutual recursion means many entries.
        self._runs_once_cache[fn] = False
        calls = self._calls_to(fn)
        if not calls:
            out = True  # never called from within: an entry point
        elif len(calls) > 1:
            out = False
        else:
            site = calls[0]
            out = not _under_loop(
                getattr(site, "path_conditions", ())
            ) and self._runs_once(getattr(site, "caller", ""))
        self._runs_once_cache[fn] = out
        return out

    def _read_lines(self, read: DefSite) -> dict[tuple[str, str], int]:
        """Where this read happens, expressed in each function it happens in.

        A read inside a helper happens, as far as the caller is concerned, at
        the call: by the line below it the helper has returned. That is the
        only way to order `CalcleDeterParam`'s read of `isDeterministic`
        against `DoSparse`'s write of it — same file, different functions, and
        the write is below the call that does the reading.

        Climbs only while each step is a single call outside any loop into a
        caller that itself runs once. Any of those failing and the climb stops:
        with two ways in, or a second visit, an earlier pass could have done
        the write already.
        """
        key = (read.file, read.line, read.function)
        hit = self._read_line_cache.get(key)
        if hit is not None:
            return hit
        out: dict[tuple[str, str], int] = {}
        fn = read.function
        if fn and read.file and read.line:
            out[(read.file, fn)] = read.line
            while True:
                calls = self._calls_to(fn)
                if len(calls) != 1:
                    break
                site = calls[0]
                caller = getattr(site, "caller", "")
                if not caller or _under_loop(getattr(site, "path_conditions", ())):
                    break
                if not self._runs_once(caller):
                    break
                where = (getattr(site, "file", ""), caller)
                if not where[0] or where in out:
                    break
                out[where] = getattr(site, "line", 0)
                fn = caller
        self._read_line_cache[key] = out
        return out

    def _runs_before(self, site: DefSite, read: DefSite) -> bool:
        """Could `site` have run before control reached `read`?

        Only says no when it can point at the reason: the write is below the
        point the read happens, in a function the read happens inside. A write
        anywhere else -- off the path in, or with no position -- is kept,
        because call order is not line order.

        Sharing a loop is the exception that makes this more than a line
        comparison. A write below a read inside one loop still runs before it,
        on the pass round after. Only a loop enclosing *both* does that; a loop
        holding just the write runs to completion before the read.
        """
        if not (site.file and site.line):
            return True
        at = self._read_lines(read).get((site.file, site.function or ""))
        if at is None:
            return True
        if site.line <= at:
            return True
        return bool(set(site.loops) & set(read.loops))

    def _visible_defs(self, sites: list[DefSite]) -> list[DefSite]:
        """Of `sites`, the writes that could have run by the current read.

        This is what tells a save/modify/restore apart from a cycle. A member
        is stashed in a local, changed under a condition, then restored from
        the local. Expanding the local reads the member, whose last write
        reads the local -- around it goes. But the stash sits *above* both the
        change and the restore, so where the local is read from, neither has
        run, and what remains is an ordinary value.

        Dropping a write is a claim about order, so `_runs_before` only makes
        it with a reason. Falls back to the whole pool when nothing is left:
        a read before every write reads the declaration, which the chain's
        fall-through already handles, and answering `leaf` here instead would
        lose the declared value.
        """
        if self._read_at is None:
            return sites
        kept = [s for s in sites if self._runs_before(s, self._read_at)]
        return kept or sites

    def _expand_text(self, text: str, fn: str, depth: int) -> Expr:
        if depth == 0:
            # The outermost ask names the function the question is posed in,
            # and a question posed there is a run that got there. `_reached`
            # needs that to tell a function it can prove ran from one whose
            # callers it merely never saw.
            self._note_root(fn)
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
        if self._nodes > (self._node_ceiling or MAX_NODES):
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
            #
            # The subscript stays shallow for a different reason: nothing here
            # ever consumes its value. A `Select` is replaced wholesale by
            # `_element_or_cut`, so the index only ever serves to say *which*
            # element was read — and for that it has to keep the shape it had in
            # the source. Expanded, a subscript picks up whatever guards its
            # definition sat under (`SetSparseParams(...)`, `platformInfoPtr ==
            # None`), so the same `parseInfo[i]` renders differently on
            # different expansion paths and splits into a dozen variables that
            # the source has no counterpart for.
            return Select(
                self._expand_container_surface(e.array, fn, depth),
                self._expand_surface(e.index, fn, depth),
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
        """Expand a field-vs-enum comparison as deep as the field allows.

        When exactly one side is a named constant / constexpr, the other side is
        a classifier operand. Substituting its guarded writes is what recovers
        the input condition selecting each value — without it the field stays a
        surface leaf, the resolver classifies it as host state, and the
        dimension comes out `exact` yet undrivable. That is how IsPse and
        IsAttenMask ended up rooted in TILING_DATA despite each having exactly
        two writes guarded by an input shape.

        A self-routing field is the exception; see `_writes_are_self_routing`.
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
                self._expand_operand(e.right, fn, depth),
            )
        return Bin(
            e.op,
            self._expand_operand(e.left, fn, depth),
            self._expand(e.right, fn, depth),
        )

    def _expand_operand(self, e: Expr, fn: str, depth: int) -> Expr:
        """Substitute a classifier operand only if doing so reduces it to inputs.

        Expanding is worth it when the field's guarded writes *are* the input
        condition — `pseOptional` becomes a test on the pse shape, and the
        dimension turns drivable. It is not worth it when the writes are guarded
        by other host fields, because then expansion drags in their chains too:
        the operand comes back with host state and free variables still in it,
        the dimension is no better driven than before, and the expression grew by
        two orders of magnitude. Measured on FAG: IsPse 335 chars and fully
        input-rooted, versus IsNEqual 25220 chars with 8 roots including
        TILING_DATA, and IsBn2MultiBlk exhausting the node budget outright.

        So the expansion is attempted and kept only if it reduced. Rejecting it
        restores exactly the previous behaviour, which is the safe direction —
        the field stays a surface leaf classified as host state.
        """
        name = self._classifier_operand(e, fn)
        if name is None or self._writes_are_self_routing(name, fn):
            return self._expand_surface(e, fn, depth)
        # Probing the same field twice is pure waste: rejecting an expansion
        # rolls back the caches that would have remembered it, so without this
        # the attempt is repeated at every occurrence. Keyed on the field alone
        # rather than the reading scope — a field that will not reduce to inputs
        # in one caller almost never does in another, and being wrong here only
        # means falling back to the surface leaf, which is where we started.
        if name in self._rejected:
            return self._expand_surface(e, fn, depth)
        state = self._snapshot()
        ceiling = self._node_ceiling
        self._node_ceiling = min(
            ceiling or MAX_NODES, self._nodes + CLASSIFIER_PROBE_NODES
        )
        try:
            deep = self._expand(e, fn, depth)
        finally:
            self._node_ceiling = ceiling
        if self._reduces_to_inputs(deep, fn):
            return deep
        self._rejected.add(name)
        self._restore(state)
        return self._expand_surface(e, fn, depth)

    def _snapshot(self) -> tuple:
        """State a rejected expansion has to give back.

        A truncated expansion must not stay in the caches: every later use of
        that name would read the truncation. `implicit_zero` matters for the
        same reason — those are assumptions recorded about branches that are no
        longer in the tree.

        `_nodes` is part of it because the global budget pays for the tree that
        is kept, not for attempts that were thrown away. Leaving the probes
        charged to it exhausted the budget on SplitAxis and turned a field that
        derives fine into `unresolved`.
        """
        return (
            self._nodes,
            dict(self._cache),
            dict(self._ememo),
            list(self.implicit_zero),
            set(self._implicit_seen),
            set(self.cycles),
        )

    def _restore(self, state: tuple) -> None:
        nodes, cache, ememo, zeros, seen, cycles = state
        self._nodes = nodes
        self._cache = cache
        self._ememo = ememo
        self.implicit_zero = zeros
        self._implicit_seen = seen
        self.cycles = cycles

    def _reduces_to_inputs(self, e: Expr, fn: str) -> bool:
        """Is every name left in `e` something a test case can set?

        Truncated or cyclic expansions fail here too: an operand carrying
        `Unknown` is strictly worse than the surface leaf it replaced.
        """
        names: set[tuple[str, str]] = set()
        for node in _walk_dag(e):
            if isinstance(node, Unknown):
                return False
            if isinstance(node, Ref):
                names.add((node.symbol, node.scope or fn))
            elif isinstance(node, Call):
                path = dotted_path(node)
                if path is not None:
                    names.add((path, fn))
        for name, scope in names:
            res = self._scope(scope).resolve(name)
            if not res.closed or not res.roots:
                return False
            if any(r not in _DRIVABLE_ROOTS for r in res.roots):
                return False
        return True

    def _classifier_operand(self, e: Expr, fn: str) -> str | None:
        """The path of the field side of a comparison, if this side is one."""
        if isinstance(e, Ref):
            name: str | None = e.symbol
        elif isinstance(e, Call):
            name = dotted_path(e)
        else:
            name = None
        return self._canonical_name(name, fn) if name else None

    def _writes_are_self_routing(self, path: str, fn: str) -> bool:
        """Does any write of `path` read `path` itself, in its value or guard?

        `layoutType = isAllSame ? TND : layoutType`, under a guard that itself
        tests `layoutType == TND`, is a field the host *routes*: a value is set
        from the inputs and later rewritten along some paths. Its writes cannot
        be chained into one value. Chaining a prefix of them reports a value the
        later rewrites contradict — the failure direction that matters, since a
        dimension would be called drivable on a value the host does not produce.
        Chaining all of them re-reads the field inside its own guards, which for
        `layoutType` is 8 writes under 18 guards, ~43k characters, and a
        MemoryError in normalization.

        An ordinary classifier field — `pseOptional`, `attenMaskOptional` — has
        no such write, and its chain is exactly its input condition.
        """
        cached = self._self_routing.get(path)
        if cached is not None:
            return cached
        tail = path.rsplit(".", 1)[-1]
        pat = re.compile(rf"\b{re.escape(tail)}\b")
        out = False
        # Guard against a field whose own expansion asks this question again.
        self._self_routing[path] = True
        for site in self._all_defs_for(path, fn):
            if pat.search(site.rhs) or any(pat.search(g) for g in site.guards):
                out = True
                break
        self._self_routing[path] = out
        return out

    def _expand_surface(self, e: Expr, fn: str, depth: int) -> Expr:
        """Expand casts / strcmp rewrites, but leave names as resolver leaves."""
        if isinstance(e, Ref):
            return replace(e, scope=fn)
        if isinstance(e, (Const, Unknown)):
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
        if isinstance(e, (Const, Unknown)):
            return e
        if isinstance(e, Ref):
            # Tag the scope, exactly as `_expand_surface` does for ordinary
            # names. A container reached through `Select` is usually a local of
            # another function; untagged, `_container_element` resolves it in
            # the encode function, finds no binding, and an element that really
            # is input-backed (`qValue[i]`, i.e.
            # `actualSeqQlenTensor->GetData<int64_t>()`) degrades into an
            # over-approximation.
            return replace(e, scope=fn)
        if isinstance(e, Select):
            # Shallow index for the same reason as the main path above.
            return Select(
                self._expand_container_surface(e.array, fn, depth + 1),
                self._expand_surface(e.index, fn, depth + 1),
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
            if short == "back":
                pushed = self._last_push_dominates_back(e, fn)
                if pushed is not None:
                    return self._expand(pushed, fn, depth + 1)
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

    def _last_push_dominates_back(self, e: Call, fn: str) -> Expr | None:
        """`v.push_back(x); … v.back()` is `x`, when nothing can intervene.

        Not a closed form over the container — the exact opposite. When the
        last thing that happened to `v` before this read was appending `x`, the
        read *is* `x`, and treating it as an unknown throws away a value the
        source states outright. In FAG this is `slicePrefix1`: sliced, then
        appended `R1` unconditionally, then read back on the next line.

        The expression IR carries no source position, so the read locates
        itself through `sole_member_read`: one `back()` on this container in
        this function, or nothing. Every condition below is a way for the
        rewrite to be wrong, so failing any of them returns None and the caller
        keeps its over-approximation.

        Members are excluded outright. `deterPrefixData.prefix1` is appended to
        in six functions and any callee can reach it through `this`, so
        "nothing intervened" is not decidable from one function's events.
        """
        if len(e.args) != 1 or not fn:
            return None
        ir = getattr(self, "ir", None)
        if ir is None:
            return None
        container = _container_of(e.args[0]) or dotted_path(_deref(e.args[0])) or ""
        if not container or "." in container:
            return None
        read = ir.sole_member_read(fn, container, "back")
        if read is None:
            return None
        here = (read.file, read.line, read.column)
        events = [
            w
            for w in ir.container_events(container, fn)
            if (w.file, w.line, w.column) < here
        ]
        if not events:
            return None
        last = events[-1]
        if last.kind != "append" or not (last.rhs or "").strip():
            return None
        # A push inside a loop appends once per iteration, so which element is
        # last depends on the trip count; a read inside a loop sees a different
        # container on the second pass. Either way program order across the
        # back edge is not the textual order.
        if _under_loop(last.path_conditions) or _under_loop(read.path_conditions):
            return None
        # The push has to happen on every path reaching the read. It does when
        # the read's guards imply the push's — every guard on the push is also
        # on the read — which is what dominance means here without a CFG.
        # Demanding the push be unconditional instead would reject the case
        # this exists for: in FAG both sit inside the same `deterSparseType ==
        # DETER_BAND` block, so both carry that guard.
        if not _cond_keys(last.path_conditions) <= _cond_keys(read.path_conditions):
            return None
        # A `guard_clause` records less than the truth (see `PathCond`), so a
        # push carrying one may have conditions the comparison above never saw.
        if not all(pc.records_what_follows for pc in last.path_conditions):
            return None
        if self._container_may_escape(container, fn, last, read):
            return None
        return parse_expr(strip_casts(last.rhs))

    def _container_may_escape(self, container: str, fn: str, last, read) -> bool:
        """Whether anything between the push and the read could change `container`.

        `container_events` only knows the mutations we model. A call taking the
        container by reference, or a method we have no rule for, can change the
        last element without leaving a write event — so the absence of an event
        is not evidence here, and any such call in the window is disqualifying.
        """
        ir = getattr(self, "ir", None)
        if ir is None:
            return True
        lo = (last.file, last.line, last.column)
        hi = (read.file, read.line, read.column)
        word = re.compile(rf"\b{re.escape(container)}\b")
        for s in ir.call_sites:
            if s.caller != fn:
                continue
            at = (s.file, s.line, getattr(s, "column", 0))
            if not (lo < at < hi):
                continue
            recv = (getattr(s, "receiver", "") or "").split(".")[0]
            if recv == container and s.callee not in _READONLY_CONTAINER_METHODS:
                return True
            if any(word.search(a or "") for a in s.args):
                return True
        return False

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

    def _sites_for(self, name: str, canon: str, fn: str) -> list[DefSite]:
        sites = self._defs_for(name, fn)
        if not sites and canon != name:
            sites = self._defs_for(canon, fn)
        return sites

    def _expand_name(self, name: str, original: Expr, fn: str, depth: int) -> Expr:
        """Substitute a name by its definitions, all the way to input roots.

        Stopping at the first name the resolver can already classify would
        collapse exactly the branch structure this module exists to recover:
        `fBaseParams.splitAxis` resolves to INPUT_SHAPE, but *which* shape
        predicate selects each value is only visible in its guarded writes.
        """
        # Every `return leaf` below hands back a name we could not expand. It
        # has to carry the function it was read in, or the normalizer will look
        # for it in the encode function and not find it.
        leaf = Ref(name, scope=fn) if not isinstance(original, Ref) else replace(original, scope=fn)
        canon = self._canonical_name(name, fn)
        # Expanding inside another name's chain can read that name's previous
        # version, so the result is only valid under the same set of
        # part-built values. Keying on them keeps such results cached — and
        # therefore structurally shared — instead of rebuilt at every use,
        # which is what turns the expression DAG back into a tree.
        # Most expansions do not read anyone else's part-built value, and those
        # are valid everywhere — they go in the context-free slot so all uses
        # share one object. Only an expansion that actually read an enclosing
        # name's previous version is stored against that context.
        # Which writes could have run by the time this read happens. Taken
        # before the cache is consulted, because two reads of one name at
        # different points in a function are two different values and must not
        # share an entry. Almost always this is every write there is -- only a
        # write below the read in the same function drops out -- so the tag is
        # empty and the cache behaves as it did.
        pool = self._sites_for(name, canon, fn)
        sites = self._visible_defs(pool)
        tag = () if len(sites) == len(pool) else tuple((s.file, s.line) for s in sites)
        generic = (fn, canon, (), tag)
        key = (fn, canon, self._version_context(), tag)
        ident = self._ident(canon, fn)
        if ident in self._active:
            # `x = f(x)` is not a cycle. Sites are chained in source order, so
            # the name on the right of the one being expanded refers to the
            # value the earlier sites produced. Treating it as a cycle used to
            # abandon the whole guard, and 24 of the remaining dropped guards
            # were nothing more than ordinary sequential assignment.
            prev = self._prev_version.get(ident)
            if prev is not None:
                self._prev_read.add(ident)
                return prev
            # Re-entering with fewer writes in view is not recursion: it is the
            # same name earlier in the function, where the writes that close
            # the loop have not run. See `_visible_defs`.
            frame = (ident, tag)
            if tag and sites and frame not in self._earlier_frames:
                self._earlier_frames.add(frame)
                try:
                    # Deliberately not cached: it holds at this read, no other.
                    return self._chain(sites, fn, depth, defining=canon, pool=pool)
                finally:
                    self._earlier_frames.discard(frame)
            self.cycles.add(canon)
            return leaf
        cached = self._cache.get(generic)
        if cached is None and key != generic:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        # Same host state under another caller scope -- true of a member, which
        # is one variable however many functions touch it. A local is a
        # different variable in every function that declares one, so reusing
        # another scope's result here would answer with an unrelated
        # expression. See `_ident`.
        if "." in canon:
            for (scope2, other, ctx2, tag2), got in self._cache.items():
                if other == canon and scope2 != fn and ctx2 == () and tag2 == tag:
                    self._cache[generic] = got
                    return got
        if not sites:
            return leaf
        # A for-init like `i = 0` carries only a discarded `for(...)` guard. If
        # we chained it, the empty usable-guard set would promote that write to
        # an unconditional definition and fold `i` to `0`. Leave the name as a
        # leaf so the resolver can classify it as LOOP_INDUCTION / scheduling.
        if _loop_scoped_only(sites):
            self._cache[generic] = leaf
            return leaf
        self._active.add(ident)
        outer_reads = self._prev_read
        self._prev_read = set()
        try:
            out = self._chain(sites, fn, depth, defining=canon, pool=pool)
            reads = self._prev_read
        finally:
            self._active.discard(ident)
            # Anything this expansion read of an *enclosing* name still makes
            # the caller's result context-dependent, so it propagates up.
            self._prev_read = outer_reads | (self._prev_read - {ident})
        # A depth-truncated result is an artefact of *where* the name was first
        # reached, not a property of the name. Caching it would poison every
        # later, shallower use.
        #
        # Reading an enclosing name's previous version makes a result
        # context-dependent for the same reason: it is that name's value
        # partway through its own chain, and reusing it elsewhere would
        # substitute a half-built value for the finished one. Reading *this*
        # name's own previous version is not context-dependent — it is what
        # `x = f(x)` means, and the chain that produced it is self-contained.
        if not _has_reason(out, REASON_DEPTH):
            # Self-contained results are valid anywhere and go in the shared
            # slot; a result that leaned on an enclosing chain is only valid
            # under the same one.
            self._cache[generic if not (reads - {ident}) else key] = out
        return out

    def _ident(self, name: str, fn: str) -> str:
        """What counts as "the same variable" for cycles and previous versions.

        A member is one variable wherever it is read, which is why its writes
        are gathered from the whole program. A local is not: 183 local names in
        FAG are spelled the same in more than one function, `s1Inner`,
        `s2Inner` and `blockOuter` among them. Their writes are already kept
        apart — `_all_defs_for` asks `_local_defs(name, fn)` — but the
        bookkeeping around them was keyed on the bare name, so one function's
        half-built value could be handed to another function's variable. That
        is not an over-approximation: it is a wrong equality, and a wrong
        equality is what makes a satisfiable key look unreachable.
        """
        return name if "." in name else f"{fn}::{name}"

    def _version_context(self) -> tuple[tuple[str, int], ...]:
        """Identity of the part-built values an expansion could read.

        Two expansions of the same name are interchangeable only if the
        previous versions visible to them are the same objects; identity is
        enough because these are memoised nodes of one DAG.
        """
        if not self._prev_version:
            return ()
        return tuple(sorted((n, id(v)) for n, v in self._prev_version.items()))

    def _scope(self, fn: str):
        if fn not in self._scoped:
            self._scoped[fn] = self.resolver._in_function(fn) if fn else self.resolver
        return self._scoped[fn]

    # -- entry point -------------------------------------------------------
    def derive(self, *, dim_name: str, index: int, host_expr: str, function: str):
        self._nodes = 0
        self.cycles = set()
        self.implicit_zero = []
        self._implicit_seen = set()
        expanded = self._expand_text(host_expr, function, 0)
        out = KeyFieldDerivation(
            name=dim_name,
            index=index,
            host_expr=host_expr,
            expanded=_pretty_dag(expanded),
            def_sites=self._defs_for(strip_casts(host_expr), function),
        )
        norm = _ValueNormalizer(
            self._scope(function),
            self.model,
            scope_for=self._scope,
            host_ir=self.ir,
        )
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
        out.blocked_on = dict(norm.blocked_on)
        out.var_scope = dict(norm.var_scope)
        out.var_types = dict(norm.var_types)
        out.implicit_defaults = list(self.implicit_zero)
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
        # Grade the result by what actually survived into `value_expr`, and let
        # `status` follow from that. The previous rule had an escape hatch: when
        # every guard had been softened it went looking for input roots in the
        # *unexpanded* DAG and, on finding any, called the field "derived" —
        # reporting a dimension as decided on the strength of names that no
        # longer appeared in the expression the solver would be given.
        out.exactness, out.free_vars = classify_exactness(
            value_expr=out.value_expr,
            variables=out.variables,
            unresolved=out.unresolved,
            implicit_defaults=out.implicit_defaults,
        )
        out.status = status_of_exactness(out.exactness)
        if out.exactness == EX_OVERAPPROX and not out.input_roots:
            out.note = "; ".join(filter(None, [out.note, "ALL_GUARDS_SOFTENED"]))
        return out


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

#: Container methods that cannot change the last element. Anything else called
#: on a container — including a method we simply have no rule for — has to
#: count as a possible change; see `_container_may_escape`.
_READONLY_CONTAINER_METHODS = frozenset(
    {
        "back",
        "front",
        "at",
        "size",
        "empty",
        "capacity",
        "begin",
        "end",
        "cbegin",
        "cend",
        "rbegin",
        "rend",
        "crbegin",
        "crend",
        "data",
        "max_size",
    }
)

#: Loop statement kinds as they appear in `PathCond.kind`.
_LOOP_COND_KINDS = frozenset({"for", "while", "do", "cxx_for_range"})


def _under_loop(conds: Iterable[Any]) -> bool:
    return any(getattr(pc, "kind", "") in _LOOP_COND_KINDS for pc in conds or ())


def _cond_keys(conds: Iterable[Any]) -> set[tuple[Any, ...]]:
    """Path conditions as a comparable set, to ask whether one guards implies another.

    Keyed on the statement's own position as well as its text, so two distinct
    `if` statements testing the same thing are not treated as one guard.
    """
    return {
        (pc.text, pc.negated, pc.file, pc.line) for pc in conds or ()
    }

# Accesses whose index we never resolved, so the variable stands for *some*
# element rather than a particular one. `back` / `front` / `size` / `empty` and
# the reductions are not here: those name one value of the container *while the
# container holds still* — see `_summary_identity_is_merged` for the case where
# it does not. `first` / `second` arrive as slot names from `_element_member`,
# and they are index-free for the same reason `elem` is — the slot is known,
# the index is not.
INDEX_FREE_KINDS = frozenset({"elem", "first", "second"})

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


def _slot_short(func: str) -> str:
    """Accessor name without the `field:` tag or a namespace qualifier."""
    bare = func[len("field:") :] if func.startswith("field:") else func
    return bare.split("::")[-1]


def _projection_index(func: str) -> int | None:
    short = _slot_short(func)
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

    Pretty-print / re-parse also loses the `field:` tag the member parser
    emits, so `actualSeqQlen(fBaseParams)` must be recognised as the same
    surface as `field:actualSeqQlen(fBaseParams)` — otherwise every
    `actualSeqQlen(fBaseParams)[i]` Select fails `_container_element` even
    though the dotted member form resolves to INPUT_VALUE.
    """
    arg = _deref(arg)
    while isinstance(arg, Select):
        arg = _deref(arg.array)
    arg = _normalize_member_calls(arg)
    if isinstance(arg, Call):
        short = arg.func[len("field:") :] if arg.func.startswith("field:") else arg.func
        if short.split("::")[-1] in _ITERATOR_METHODS and len(arg.args) == 1:
            arg = _normalize_member_calls(_deref(arg.args[0]))
    path = dotted_path(arg)
    if not path:
        if isinstance(arg, Ref):
            return arg.symbol
        return ""
    head, _, tail = path.rpartition(".")
    return head if head and tail in _ITERATOR_METHODS else path


def _scope_under(expr: Expr) -> str:
    """Function the first scoped name under `expr` was read in.

    Part of a loop-local variable's identity: the same container name is a
    local of several functions here, and equating them would constrain
    unrelated code to agree.
    """
    for node in _walk_dag(expr):
        if isinstance(node, Ref) and getattr(node, "scope", ""):
            return node.scope
    return ""


def _subscript_chain(expr: Select) -> list[Expr]:
    """Every subscript of a nested `Select`, outermost first.

    `_container_of` deliberately peels all of them off — it answers "which
    container is this", and the input root lives on the base name. Identity of
    one *element* needs the opposite: `a[b][0][SUM_ALL]` and
    `a[b-1][0][SUM_ALL]` are different values, and keying them on the innermost
    subscript alone equates them — a false equality, since these are prefix sums
    whose neighbours are never equal.
    """
    indices: list[Expr] = []
    cur: Expr = expr
    while isinstance(cur, Select):
        indices.append(cur.index)
        cur = _deref(cur.array)
    indices.reverse()
    return indices


# camelCase identifier: tiling struct members (`actualSeqQlen`), not helpers
# (`CeilDiv`, `GetDim`) or free functions that happen to take one argument.
_MEMBER_LIKE_RE = re.compile(r"^[a-z][A-Za-z0-9]*$")


def _normalize_member_calls(arg: Expr) -> Expr:
    """Rewrite call-style member access back to the parser's `field:` form.

    Only unary calls whose callee looks like a data-member name are rewritten.
    Known casts, container ops, and iterators are left alone so `size(v)` /
    `begin(v)` keep their real meaning.
    """
    arg = _deref(arg)
    seen: set[int] = set()
    while isinstance(arg, Call) and id(arg) not in seen:
        seen.add(id(arg))
        if arg.func.startswith("field:"):
            break
        if len(arg.args) != 1:
            break
        short = arg.func.split("::")[-1]
        if (
            short in _ITERATOR_METHODS
            or short in _CONTAINER_OPS
            or short in _CAST_CALLS
            or short in _PLATFORM_CORE_CALLS
            or not _MEMBER_LIKE_RE.match(short)
        ):
            break
        arg = Call(f"field:{short}", arg.args)
    return arg


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

    def __init__(self, resolver, model, scope_for=None, host_ir=None) -> None:
        super().__init__(resolver, model)
        #: Consulted only to ask whether a container is written between reads,
        #: which decides whether one variable may stand for `back(v)` at all of
        #: them. Absent, every container summary is isolated — the safe side.
        self.ir = host_ir
        #: Maps a function name to a resolver scoped to it. Expansion inlines
        #: across functions, so leaves reach here carrying the scope they were
        #: read in; without this they would all be resolved against the encode
        #: function, where another function's locals simply do not exist.
        self._scope_for = scope_for
        self.roots: dict[str, str] = {}
        self.scheduling: dict[str, str] = {}
        self.undecided: dict[str, str] = {}
        #: var_id -> the single symbol that defeated resolution, as opposed to
        #: the full guard text in `undecided`.
        self.blocked_on: dict[str, str] = {}
        #: var_id -> the function it was read in, so evidence lookup can be
        #: confined to that function instead of matching guard text globally.
        self.var_scope: dict[str, str] = {}
        #: var_id -> the type it was declared with. Minting happens in a
        #: derivation worker, whose model the parent never sees, so the parent
        #: re-declares from the record that comes back. Without the type there
        #: it has to guess from the name, and `VAR_SCHED_` covers both a
        #: softened guard (bool) and a traversal position like `coreIdx` (int).
        #: Guessing bool for the latter makes `coreIdx == 36` fail to compile
        #: and takes every dimension down with it.
        self.var_types: dict[str, str] = {}
        # The expanded expression is a DAG. Normalising it as a tree costs the
        # unfolded size, so each (node, position) is lowered exactly once and
        # the resulting SMT-lite object is shared by every reference to it.
        self._memo: dict[tuple[int, str], tuple[Expr, dict[str, Any]]] = {}

    def _resolver_for(self, expr: Expr):
        """Resolver for the function this expression was read in.

        Only `Ref` carries a scope, and an accessor chain reaches here as a
        `Call` whose stamp sits on the receiver underneath it. Reading the
        scope off the node alone therefore resolved every
        `shape->GetStorageShape().GetDimNum()` against the encode function,
        where the local naming the tensor does not exist: the operand stayed
        unknown, the accessor's own name stood in for it, and every rank in the
        operator collapsed onto one variable — forcing unrelated tensors to
        have equal rank and inventing unreachable keys from it.

        Chains that name their operand inline (`GetInputShape(QUERY_IDX)->...`)
        survived the wrong scope, which is why only the ones routed through a
        local were affected.
        """
        scope = getattr(expr, "scope", "") or _scope_under(expr)
        if scope and self._scope_for is not None:
            return self._scope_for(scope)
        return self.resolver

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
            # The guard text is the whole condition; `detail` is the one symbol
            # inside it that could not be resolved. Without it, a 900-character
            # guard tells you it failed but not on what, and every diagnosis
            # starts by re-deriving to find out.
            if exc.detail:
                self.blocked_on[var_id] = str(exc.detail)
            return {"op": "eq", "var": var_id, "value": True}

    def _guard_leaf_roots(self, cond: Expr) -> tuple[set[str], bool, bool]:
        """Roots of this guard's leaves, plus reached / unresolved flags.

        Resolving leaf by leaf rather than rendering the guard and resolving
        the text: a substituted guard is a DAG whose printed form runs to
        megabytes, and the print alone costs more than the derivation.

        Leaves must be resolved in the function they were read in (`Ref.scope`):
        a layout / rope local defined in `GetShapeAttrsInfo` has no binding in
        the encode-function resolver, and classifying it from there makes every
        such guard look "unconstrained" — then softens it as schedule.
        """
        roots: set[str] = set()
        reached = False
        unresolved = False
        for node in _walk_dag(cond):
            if isinstance(node, Ref):
                if node.symbol.startswith(REACHED_PREFIX):
                    reached = True
                    continue
                symbol = node.symbol
                resolver = self._resolver_for(node)
            elif isinstance(node, Call):
                # Arguments are separate nodes in the walk, so the callee name
                # is all this node contributes.
                symbol = (
                    node.func[len("field:") :]
                    if node.func.startswith("field:")
                    else node.func
                )
                # Same scope rule as for `Ref`: a member tail (`field:isNzOut`)
                # or a helper name is looked up among the locals and fields of
                # the function that read it, and the encode function is not it.
                resolver = self._resolver_for(node)
            else:
                continue
            got = False
            for atom in resolver.resolve(symbol).atoms:
                if atom.root:
                    roots.add(atom.root)
                    got = True
            if not got:
                # A leaf we cannot classify. Silence here used to let a sibling
                # CONSTANT (MULT_BASE, CORE_LIST_NUM) alone push the whole
                # guard into SCHED_SOFT — which is how `bTail % MULT_BASE == 1`
                # and `size(syncRounds) > CORE_LIST_NUM` were mislabelled.
                unresolved = True
        return roots, reached, unresolved

    def _sched_soft_guard(self, cond: Expr) -> dict[str, Any] | None:
        """Soften a guard only when nothing about the input decides it.

        The rule used to be a regex over the guard text, listing identifiers
        lifted from one operator's source (`invalidS1Array`, `prefix0Max`,
        `CaclePerCore`) plus a second regex exempting the mixed guards the
        first over-caught. That is unusable twice over: on any other operator
        the first list matches nothing and every schedule guard becomes an
        UNMAPPED blocker, while on this one it swallowed layout comparisons and
        discarded real input constraints.

        Classify the leaves instead. A guard is schedule iff every root it
        reaches is a traversal position — one leaf backed by a shape, dtype,
        format or attribute makes it an input constraint no matter what it is
        named, and it goes through normal normalization.

        Unresolved leaves are *not* schedule: they are modelling gaps. Softening
        them hid `N12`/`bTail`/`size(syncRounds)` as VAR_SCHED when the truth
        was "we failed to bind an input-derived local".
        """
        roots, reached, unresolved = self._guard_leaf_roots(cond)
        constraining = roots - _UNCONSTRAINING_ROOTS
        if constraining:
            return None
        if reached:
            # Distinct from schedule position: this says control-flow analysis
            # could not tell whether the writing function runs, which call-graph
            # slicing can settle. Keeping it separate stops a modelling gap from
            # hiding among the guards we soften deliberately.
            return self._soft_var(cond, prefix="VAR_REACHED", origin="REACHED_SOFT")
        # Soften only when a leaf is *actually* a traversal position. A guard
        # whose only "roots" are CONSTANT / EXTERNAL used to land here too —
        # that is how `N12 > 0` (SCREAMING_CASE false-positive) and
        # `bTail % MULT_BASE == 1` (unresolved local + named constant) were
        # labelled schedule. Those are modelling gaps; report them as UNDECIDED.
        if unresolved or not (roots & SCHEDULING_ROOTS):
            return None
        return self._soft_var(cond, prefix="VAR_SCHED", origin="SCHED_SOFT")

    def _soft_var(self, cond: Expr, *, prefix: str, origin: str) -> dict[str, Any]:
        from uo_init.ids import hash12

        text = _pretty_dag(cond)
        var_id = f"{prefix}_{hash12(text)[:12]}"
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
                        source=origin.lower(),
                    ),
                    origin=origin,
                    description=f"{origin}: {text[:120]}",
                )
            )
        self.scheduling[var_id] = origin
        self.undecided[var_id] = f"{origin}: {text[:160]}"
        self.var_types[var_id] = "bool"
        return {"op": "eq", "var": var_id, "value": True}

    def _leaf(self, expr: Expr) -> dict[str, Any]:
        expr = _deref(expr)
        if isinstance(expr, Ref) and expr.symbol.startswith(OVERAPPROX_PREFIXES):
            # Minted by the derivation, not read from the source, so the
            # resolver has no root for it and must not be asked for one.
            return {"var": expr.symbol}
        if isinstance(expr, Select):
            elem = self._element_or_cut(expr)
            if elem is not None:
                return elem
            raise NormalizeError(REASON_OPAQUE, "array_subscript")
        member = self._element_member(expr)
        if member is not None:
            return member
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
            # Only reject the SCREAMING_CASE false positives that look like
            # short locals (`N12`, `N11`): letters + digits, no underscore.
            # Broader rejection of every unresolved string lit also killed
            # dtype / layout enum names (`FLOAT16`, `SBH`) and dropped CLOSED.
            if re.fullmatch(r"[A-Z]+\d+", out["lit"]):
                raise NormalizeError(REASON_UNMAPPED_LEAF, out["lit"])
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

    def _summary_identity_is_merged(
        self, container: str, kind: str, scope: str
    ) -> bool:
        """Whether one variable may stand for this summary at every read point.

        `back(v)` names one value of `v` only while `v` holds still. In FAG it
        often does not: `deterPrefixData.prefix1` is pushed to in six functions,
        and `prefix1.back()` is read both before and after those pushes. One
        variable for all of those reads asserts an equality the source does not
        provide, and the way that fails is by *inventing* an unsatisfiable key —
        the one direction the design forbids. So the identity is merged (the
        variable stands for *some* value, and cross-read equalities are dropped)
        whenever program order cannot rule the interleaving out.

        Order cannot be recovered when the reading function also writes the
        container, or when writes are spread over several functions: writes
        carry a line number, reads do not. A container filled in exactly one
        function and read in others — `actualSeqQlen`, filled in
        `GetShapeAttrsInfo` and reduced later — keeps a shared identity, which
        is what lets `max(actualSeqQlen)` agree across the five dimensions
        that read it.
        """
        if kind in INDEX_FREE_KINDS:
            return True
        ir = getattr(self, "ir", None)
        if ir is None:
            return True
        writers = ir.container_writers(container)
        return len(writers) > 1 or (bool(scope) and scope in writers)

    def _container_element(
        self, container_expr: Expr, *, kind: str = "elem"
    ) -> dict[str, Any] | None:
        """One element / length of an input-backed container as a free variable.

        Same provenance story as `_container_reduction`: the concrete index is
        often a scheduling position, but the *value* still comes from the input
        that fills the container.

        The container name must be resolved in the function it was read in.
        Cross-function expansion leaves `qValue` / `actualSeqQlen` tagged with
        e.g. `GetShapeAttrsInfo`; looking them up in the encode-function
        resolver returns nothing, and every `Select` then becomes an
        `array_subscript` undecided — even when the binding exists in scope.
        """
        container = _container_of(container_expr)
        if not container:
            path = dotted_path(_deref(container_expr))
            container = path or ""
        if not container:
            return None
        res = self._resolver_for(container_expr).resolve(container)
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
        merged = self._summary_identity_is_merged(
            container, kind, _scope_under(container_expr)
        )
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
                    identity_merged=merged,
                )
            )
        if merged:
            self.model.mark_identity_merged(var_id)
        self.model.declare_on_demand(var_id, atom.root)
        self.roots[var_id] = atom.root
        return {"var": var_id, "root": atom.root}

    def _loop_element_var(self, expr: Select, *, slot: str = "") -> dict[str, Any] | None:
        """A loop-local container element, as one named over-approximation.

        `_container_element` needs a container backed by an input to name the
        element after. A vector filled inside a loop and read at the induction
        variable has no such root, and no closed form over its elements: what
        the loop establishes is a quantified statement, which this analysis
        does not compute.

        Failing here costs far more than the subscript. The `NormalizeError`
        reaches `_guard_uncached`, which replaces *the whole guard* with a
        single free boolean — and an expanded guard is the conjunction of every
        source guard on the path, so one unresolved subscript also throws away
        the layout / platform / attribute constraints standing beside it.
        Cutting at the subscript keeps those and confines the
        over-approximation to the element that earned it.

        Identity is `(scope, container, index, slot)`. Reads of the same element
        in the same function stay one variable, so the guard cannot be satisfied
        two contradictory ways; a same-named container in another function is
        not silently equated with this one.
        """
        container = _container_of(expr.array) or dotted_path(_deref(expr.array)) or ""
        if not container:
            return None
        subscripts = "".join(f"[{_pretty_dag(i)}]" for i in _subscript_chain(expr))
        surface = f"{container}{subscripts}" + (f".{slot}" if slot else "")
        out = self._loop_local_var(
            surface=surface,
            label=f"{container}_{slot}" if slot else container,
            scope=_scope_under(expr.array),
            what=f"{slot or 'element'} of loop-local {container}",
        )
        self.blocked_on[out["var"]] = f"{container}[]" + (f".{slot}" if slot else "")
        return out

    def _loop_reduction_var(self, container_expr: Expr, kind: str) -> dict[str, Any] | None:
        """A whole-container summary of a loop-local container.

        `_container_reduction` can only name a summary after the input that
        fills the container. `syncRounds` / `slicePrefix1` are built inside a
        loop and have no such root, and returning `None` there costs the whole
        guard — `size(syncRounds) + size(syncRoundRanges) > CORE_LIST_NUM`
        collapsed along with every layout and platform constraint beside it.

        Same trade already made for elements and for tuple slots: confine the
        over-approximation to the summary that earned it. Identity is
        `(scope, container, kind)`, so `size(v)` read twice is one variable
        while `size(v)` and `back(v)` stay apart.
        """
        container = (
            _container_of(container_expr) or dotted_path(_deref(container_expr)) or ""
        )
        if not container:
            return None
        surface = f"{kind}({container})"
        out = self._loop_local_var(
            surface=surface,
            label=f"{kind}_{container}",
            scope=_scope_under(container_expr),
            what=f"{kind} of loop-local {container}",
        )
        self.blocked_on[out["var"]] = surface
        return out

    def _loop_local_var(
        self, *, surface: str, label: str, scope: str, what: str
    ) -> dict[str, Any]:
        """Register one loop-local unknown, element and summary alike."""
        from uo_init.ids import hash12, slug

        var_id = f"{LOOPELEM_PREFIX}{slug(label)}_{hash12(f'{scope}|{surface}')}"
        if self.model.get(var_id) is None:
            self.model.add(
                VarSpec(
                    var_id=var_id,
                    name=surface[:80],
                    # Left as an unbounded int rather than a bool: the element
                    # type is exactly what we could not resolve, and `_truthy`
                    # reads a non-zero int as true either way.
                    value_type="int",
                    domain=Domain(
                        var_id=var_id,
                        value_type="int",
                        completeness="open",
                        source="loop_local_element",
                    ),
                    origin="LOOP_ELEMENT",
                    description=what + (f" in {scope}" if scope else ""),
                    # One id per read site, but the index within the container
                    # is exactly what is unknown, so two dimensions reading it
                    # need not mean the same element.
                    identity_merged=True,
                )
            )
        self.model.mark_identity_merged(var_id)
        self.undecided[var_id] = f"LOOP_ELEMENT: {surface[:160]}"
        self.var_types[var_id] = "int"
        # Two same-named containers in different functions are different
        # variables here, but their guard *text* is identical, so evidence
        # lookup by text alone cites whichever it finds first. The two
        # `invalidS1Array[j]` were both reported at the normal-path line even
        # though one of them lives in the varlen path, in a different
        # coordinate domain. Recording the scope is what lets the lookup be
        # restricted to the function the variable actually came from.
        if scope:
            self.var_scope[var_id] = scope
        return {"var": var_id}

    def _element_or_cut(self, expr: Select, *, slot: str = "") -> dict[str, Any] | None:
        """An input-backed element if there is one, else a loop-local cut."""
        elem = self._container_element(expr.array, kind=slot or "elem")
        if elem is not None:
            return elem
        return self._loop_element_var(expr, slot=slot)

    def _element_member(self, expr: Expr) -> dict[str, Any] | None:
        """A tuple slot of a container element, cut like the element itself.

        `_element_or_cut` is only reached for a bare `Select`, and
        `s1ValidIdx[i].second` is a `Call` wrapping one, so it used to miss
        every cut and fall through to the text path — where `dotted_path`
        cannot render a subscript, the leaf arrives as `second(?)`, and an
        unmapped call takes the whole guard down with it.

        Only what earlier stages could not see through gets here: `_expand_call`
        already projects a slot out of a tuple it can reach (`make_pair`, an
        `Ite` over them). A subscript is not such a tuple — what the container
        holds is decided inside the loop that filled it.

        The slot belongs to the variable's identity. `.first` and `.second` of
        one element are different values, and naming them alike would let the
        solver equate a sequence-length bound with the index it is paired with.
        """
        if not isinstance(expr, Call) or len(expr.args) != 1:
            return None
        if _projection_index(expr.func) is None:
            return None
        base = _deref(expr.args[0])
        if not isinstance(base, Select):
            return None
        return self._element_or_cut(base, slot=_slot_short(expr.func))

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
            elem = self._container_element(args[0], kind=kind)
            return elem if elem is not None else self._loop_reduction_var(args[0], kind)
        container = _container_of(args[0])
        if not container:
            return None
        res = self._resolver_for(args[0]).resolve(container)
        atoms = [a for a in res.atoms if a.root and a.root != "CONSTANT"]
        if not atoms:
            return self._loop_reduction_var(args[0], kind)
        from uo_init.ids import slug

        atom = atoms[0]
        raw_sym = atom.symbol or ""
        label = (
            container
            if (raw_sym in _GENERIC_ACCESSORS or not raw_sym)
            else raw_sym
        )
        var_id = f"VAR_REDUCE_{kind.upper()}_{slug(label)}"
        merged = self._summary_identity_is_merged(
            container, kind, _scope_under(args[0])
        )
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
                    identity_merged=merged,
                )
            )
        if merged:
            self.model.mark_identity_merged(var_id)
        self.model.declare_on_demand(var_id, atom.root)
        self.roots[var_id] = atom.root
        return {"var": var_id, "root": atom.root}

    def _scheduling_leaf(self, expr: Expr) -> dict[str, Any] | None:
        """Turn a traversal-position leaf into an unconstrained variable.

        Left to the base normalizer these raise UNMAPPED_LEAF, because
        `var_id_for` has no id for them, and one loop counter deep inside a
        guard would sink the whole field.

        Recorded in `undecided` as well as `scheduling`: a key field whose
        *value* depends on the core index is not decided by the input, and
        that has to be as visible as a softened guard. It was only in
        `scheduling`, which nothing downstream reads, so these leaves reached
        `value_expr` with no record explaining them.

        Scoped, like every other local. Two functions each greedily packing
        blocks onto cores both call their counter `coreIdx`; naming the
        variable after the symbol alone made them one, which asserts the two
        counts are equal. That narrows the feasible set rather than widening
        it — the one direction an over-approximation must never take, and
        enough on its own to rule out keys that are reachable.
        """
        from uo_init.ids import hash12, slug

        text = _leaf_text(expr)
        if not text:
            return None
        scope = getattr(expr, "scope", "") or _scope_under(expr)
        res = self._resolver_for(expr).resolve(text)
        atoms = [a for a in res.atoms if a.root and a.root != "CONSTANT"]
        if not atoms or atoms[0].root not in SCHEDULING_ROOTS:
            return None
        atom = atoms[0]
        var_id = f"VAR_SCHED_{slug(atom.symbol or text)}"
        if scope:
            var_id = f"{var_id}_{hash12(scope)}"
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
                    description="traversal position; unconstrained by input"
                    + (f" in {scope}" if scope else ""),
                )
            )
        self.scheduling[var_id] = atom.root
        self.undecided[var_id] = f"{atom.root}: {atom.symbol or text}"
        # A position, not a predicate: `coreIdx` gets compared with the core
        # count, so it has to come back as the int it was declared as.
        self.var_types[var_id] = "int"
        if scope:
            self.var_scope[var_id] = scope
        return {"var": var_id, "root": atom.root}

    def _bool(self, expr: Expr) -> dict[str, Any]:
        expr = _deref(expr)
        if isinstance(expr, Select):
            leaf = self._element_or_cut(expr)
            if leaf is not None:
                return self._truthy(leaf)
            raise NormalizeError(REASON_OPAQUE, "array_subscript")
        member = self._element_member(expr)
        if member is not None:
            return self._truthy(member)
        return self._lower(expr, "bool", lambda e: super(_ValueNormalizer, self)._bool(_deref(e)))

    def _value(self, expr: Expr) -> dict[str, Any]:
        return self._lower(expr, "value", self._value_uncached)

    def _value_uncached(self, expr: Expr) -> dict[str, Any]:
        """Value position, with `Ite` kept as a value rather than coerced to bool."""
        expr = _deref(expr)
        if isinstance(expr, Unknown):
            raise NormalizeError(expr.reason, "")
        if isinstance(expr, Select):
            elem = self._element_or_cut(expr)
            if elem is not None:
                return elem
            raise NormalizeError(REASON_OPAQUE, "array_subscript")
        if isinstance(expr, Call):
            helper = self._pure_helper(expr)
            if helper is not None:
                return helper
            member = self._element_member(expr)
            if member is not None:
                return member
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
