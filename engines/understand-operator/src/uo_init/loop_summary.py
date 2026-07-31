# -*- coding: utf-8 -*-
"""How many times a counted loop can run.

Only loops whose init, step and bound are all read as constants get a number.
Everything else reports None, and a caller with None must not proceed: this
feeds a proof that a container stays under some size, and a trip count guessed
one too high is an unsound bound that would let a real branch be folded away.

Deliberately not a general induction-variable analysis. There is no widening,
no interval domain and no handling of a bound that changes inside the loop —
those belong to an abstract interpreter, and the stopping line for this work is
bounded loops with constant bounds.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from uo_init.cpp_expr import parse_expr
from uo_init.expr_ir import Bin, Const, Ref, Un

#: Comparisons that bound a counted loop, paired with the step sign they need.
#: `!=` is absent on purpose: `i != n` only terminates if the step divides the
#: distance exactly, and proving that is a different question.
_ASCENDING = {"<", "<="}
_DESCENDING = {">", ">="}
#: Bounds that are reached rather than passed, so the final value counts.
_INCLUSIVE = {"<=", ">="}


@dataclass(frozen=True)
class LoopBound:
    """What we could establish about one loop's iteration count."""

    #: Iterations the loop runs at most. None means not established.
    max_trip: int | None
    #: True when the count is exact rather than an upper bound. Currently the
    #: same thing for the shapes we read, but consumers of a bound and
    #: consumers of a count are different, and conflating them once the two
    #: diverge would be silent.
    exact: bool = False
    #: Why no number, for diagnosis. Empty when one was established.
    reason: str = ""

    def __bool__(self) -> bool:
        return self.max_trip is not None


def _as_int(node: Any, constants: dict[str, int]) -> int | None:
    """An integer value for a bound expression, or None.

    Named constants resolve through `constants`; a name that is not there is
    not a number, however plausible it looks.
    """
    if isinstance(node, Const):
        # `True`/`False` are ints in Python. A loop bounded by a bool is not a
        # shape we read, and silently treating it as 0/1 would invent a count.
        if isinstance(node.value, bool) or not isinstance(node.value, int):
            return None
        return node.value
    if isinstance(node, Ref):
        return constants.get(node.symbol)
    return None


def loop_bound(node: Any, constants: dict[str, int] | None = None) -> LoopBound:
    """Iteration bound for a `CtrlNode` describing a counted loop.

    `node.init_value` and `node.step` come off the AST; the bound is parsed
    from `node.condition`, which is normalised source text, using the same
    parser the rest of the derivation uses rather than a regex.
    """
    consts = constants or {}
    if getattr(node, "kind", "") != "for":
        return LoopBound(None, reason=f"not_a_for_loop:{getattr(node, 'kind', '?')}")
    init = getattr(node, "init_value", None)
    step = getattr(node, "step", None)
    if init is None:
        return LoopBound(None, reason="no_initial_value")
    if not step:
        return LoopBound(None, reason="no_step" if step is None else "zero_step")

    induction = getattr(node, "induction_vars", ()) or ()
    condition = (getattr(node, "condition", "") or "").strip()
    if not condition:
        return LoopBound(None, reason="no_condition")
    try:
        tree = parse_expr(condition)
    except Exception:
        return LoopBound(None, reason="condition_unparsed")
    if not isinstance(tree, Bin) or tree.op not in (_ASCENDING | _DESCENDING):
        return LoopBound(None, reason=f"condition_not_a_bound:{condition}")

    # The induction variable must be the side being compared, and the loop we
    # are counting must be the one that moves it. A condition on some other
    # variable says nothing about how often this loop runs.
    left, right = tree.left, tree.right
    op = tree.op
    if isinstance(left, Ref) and left.symbol in induction:
        bound_node = right
    elif isinstance(right, Ref) and right.symbol in induction:
        # `N > i` is `i < N`.
        bound_node = left
        op = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}[op]
    else:
        return LoopBound(None, reason=f"condition_not_on_induction_var:{condition}")

    bound = _as_int(bound_node, consts)
    if bound is None:
        return LoopBound(None, reason=f"bound_not_constant:{condition}")

    if step > 0 and op not in _ASCENDING:
        return LoopBound(None, reason="step_and_comparison_disagree")
    if step < 0 and op not in _DESCENDING:
        return LoopBound(None, reason="step_and_comparison_disagree")

    span = (bound - init) if step > 0 else (init - bound)
    if op in _INCLUSIVE:
        span += 1
    if span <= 0:
        return LoopBound(0, exact=True)
    return LoopBound(math.ceil(span / abs(step)), exact=True)


# --- container identity across functions ----------------------------------
#
# A container is filled in one function and read in another, both through
# reference parameters, so "every change to this container" is not a question
# about one function. Following that chain is what makes a size bound possible;
# following it incompletely is what would make the bound wrong.

#: Methods that read a container without changing it.
_READONLY_METHODS = frozenset(
    {
        "back", "front", "at", "size", "empty", "capacity", "data", "max_size",
        "begin", "end", "cbegin", "cend", "rbegin", "rend", "crbegin", "crend",
    }
)
#: Methods that change it in ways the walk records as write events.
_MODELLED_MUTATORS = frozenset(
    {
        "push_back", "emplace_back", "clear", "pop_back", "erase", "insert",
        "resize", "assign", "swap", "reserve", "emplace",
    }
)
#: Declared types that start out holding nothing. `reserve` changes capacity,
#: not size, so it does not belong here or in the disqualifying set.
_EMPTY_ON_DEFAULT_CONSTRUCTION = ("vector", "deque", "list", "set", "map", "unordered_")

#: Callees that cannot change how many elements their argument holds.
#: `operator[]` hands back one element, and a container constructor builds a
#: new object out of the old one; neither can resize what it was given. Moving
#: from the argument can, and is ruled out separately.
_SIZE_PRESERVING_CALLS = frozenset(
    {
        "operator[]", "at",
        "vector", "deque", "list", "set", "map", "array", "string",
        "pair", "make_pair", "tuple", "make_tuple",
    }
)
_MOVE_CALL = re.compile(r"\bmove\s*\(")


@dataclass(frozen=True)
class ContainerInstance:
    """One container object, and every mutation that can reach it.

    `reason` non-empty means the chain could not be followed to the end, and
    the instance must not be used for a bound: a partial event list looks
    exactly like a container that is mutated less than it really is.
    """

    root_function: str
    name: str
    events: tuple[Any, ...] = ()
    #: Whether it provably holds nothing before the first recorded mutation.
    starts_empty: bool = False
    #: Functions the chain passed through, for diagnosis.
    functions: tuple[str, ...] = ()
    reason: str = ""

    def __bool__(self) -> bool:
        return not self.reason


def _bare(actual: str) -> str:
    """An argument's variable name, if the argument is just a variable."""
    text = (actual or "").strip()
    while text.startswith(("&", "*")):
        text = text[1:].strip()
    return text


def _only_reaches_a_part(arg: str, var: str) -> bool:
    """Whether `arg` mentions `var` only to reach inside it.

    `v[i]`, `v.first`, `v.begin()` all hand over an element, a member or an
    iterator. None of them is the container, and none can change how many
    elements it holds — that needs the container itself. `std::move(v)` and a
    bare `v` do reach the container, and neither passes this test.
    """
    for m in re.finditer(rf"\b{re.escape(var)}\b", arg or ""):
        rest = (arg[m.end() :]).lstrip()
        if not rest or rest[0] not in "[.":
            return False
    return True


def _starts_empty(ir: Any, function: str, name: str) -> bool:
    decl = ir.local_decl(name, function) if hasattr(ir, "local_decl") else None
    if decl is None or decl.init is not None:
        return False
    return any(t in (decl.type_text or "") for t in _EMPTY_ON_DEFAULT_CONSTRUCTION)


def _trace_container(ir: Any, function: str, name: str, max_depth: int) -> ContainerInstance:
    """Every mutation reaching the object `name` names in `function`.

    Refuses rather than under-reports. A call we cannot follow into, a method
    we have no rule for, or a use of the name that is not a whole argument all
    end the trace with a reason: any of them can change the container without
    leaving an event, and an event list that is missing those is not a smaller
    bound but a wrong one.
    """
    empty = _starts_empty(ir, function, name)
    events: list[Any] = []
    seen: set[tuple[str, str]] = set()
    work: list[tuple[str, str, int]] = [(function, name, 0)]
    visited_fns: list[str] = []
    while work:
        fn, var, depth = work.pop()
        if (fn, var) in seen:
            continue
        seen.add((fn, var))
        visited_fns.append(fn)
        if depth > max_depth:
            return ContainerInstance(
                function, name, reason=f"call_chain_deeper_than_{max_depth}"
            )
        events.extend(ir.container_events(var, fn))
        word = re.compile(rf"\b{re.escape(var)}\b")
        for site in ir.call_sites:
            if site.caller != fn:
                continue
            if _bare(getattr(site, "receiver", "") or "").split(".")[0] == var:
                if (
                    site.callee not in _READONLY_METHODS
                    and site.callee not in _MODELLED_MUTATORS
                ):
                    return ContainerInstance(
                        function, name, reason=f"unmodelled_method:{site.callee}"
                    )
                continue
            for i, arg in enumerate(site.args or ()):
                if not word.search(arg or ""):
                    continue
                if _only_reaches_a_part(arg, var):
                    continue
                if site.callee in _SIZE_PRESERVING_CALLS and not _MOVE_CALL.search(arg):
                    continue
                if _bare(arg) != var:
                    # The name appears inside a larger expression, so what is
                    # passed is not the container itself and we cannot say what
                    # the callee does with it.
                    return ContainerInstance(
                        function, name, reason=f"used_in_expression:{arg[:40]}"
                    )
                target = ir.summaries.get(site.callee)
                if target is None or i >= len(target.params):
                    return ContainerInstance(
                        function, name, reason=f"escapes_into:{site.callee}"
                    )
                work.append((site.callee, target.params[i], depth + 1))
    return ContainerInstance(
        root_function=function,
        name=name,
        events=tuple(sorted(events, key=lambda w: (w.file, w.line, w.column))),
        starts_empty=empty,
        functions=tuple(dict.fromkeys(visited_fns)),
    )


def resolve_param_container(
    ir: Any, function: str, param: str, *, max_depth: int = 6
) -> list[ContainerInstance]:
    """The container objects a reference parameter can name, one per call site.

    Returned as a list, not merged: two callers passing their own local vectors
    are two objects, and a bound holding for both is the maximum over them, not
    the sum. Merging would also make one caller's mutations look like they
    reached the other's container.

    An empty list means no call site was found, which is not the same as a
    container with no mutations and must not be read as one.
    """
    summary = ir.summaries.get(function)
    if summary is None or param not in (summary.params or []):
        return []
    idx = summary.params.index(param)
    out: list[ContainerInstance] = []
    for site in ir.call_sites:
        if site.callee != function:
            continue
        if idx >= len(site.args or ()):
            out.append(
                ContainerInstance(site.caller, param, reason="call_site_missing_argument")
            )
            continue
        actual = _bare(site.args[idx])
        if not actual or not actual.isidentifier():
            out.append(
                ContainerInstance(
                    site.caller, param, reason=f"argument_not_a_variable:{actual[:40]}"
                )
            )
            continue
        out.append(_trace_container(ir, site.caller, actual, max_depth))
    return out


# --- are two events mutually exclusive ------------------------------------
#
# One question, asked of the solver, rather than a stack of syntactic special
# cases. `if/else` and `x == A` versus `x == B` are both just conjunctions that
# turn out to be unsatisfiable, and keeping two sets of rules for them means
# each has to be extended separately every time a new shape appears.

_CMP_TO_IR = {"<": "lt", "<=": "le", ">": "gt", ">=": "ge", "==": "eq", "!=": "ne"}
_BOOL_TO_IR = {"&&": "and", "||": "or"}


@dataclass(frozen=True)
class Exclusion:
    """Whether two guarded events can both happen on one iteration."""

    exclusive: bool
    #: Why not, when they are not. Empty when they are.
    reason: str = ""
    #: Guards that went into the query, for diagnosis.
    checked: int = 0

    def __bool__(self) -> bool:
        return self.exclusive


class _Atoms:
    """Stable names for the leaves of a guard.

    The whole judgement rests on one thing: the same source expression must map
    to the same name in both guards, or `c` and `!c` become two free variables
    and nothing is ever unsatisfiable.

    Locals are qualified by function, members are not. Two functions each with
    their own `startSyncRound` are two variables; `fBaseParams.deterSparseType`
    read in two functions is one. Qualifying members too would be safe in the
    same direction as failing to prove exclusion, but it would lose the enum
    case entirely.
    """

    def __init__(
        self, members: frozenset[str], overrides: dict[str, str] | None = None
    ) -> None:
        self._members = members
        #: Source spellings that stand for a symbol the caller already has a
        #: meaning for — `v.size()` for a container whose size it has bounded.
        self._overrides = dict(overrides or {})
        self.names: dict[str, str] = {}

    def of(self, text: str, function: str) -> str:
        fixed = self._overrides.get(text)
        if fixed is not None:
            self.names[fixed] = text
            return fixed
        head = (text or "").split(".")[0].split("[")[0].split("(")[0].strip()
        if head in self._members or text.startswith("this"):
            name = text
        else:
            name = f"{function}::{text}"
        # Solver identifiers, not source text.
        ident = "G_" + re.sub(r"[^0-9A-Za-z_]", "_", name)
        self.names[ident] = name
        return ident


#: Arithmetic the IR can carry. Anything else collapses to an opaque atom.
_ARITH_TO_IR = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod"}


def _lower(
    node: Any, atoms: _Atoms, function: str, constants: dict[str, int] | None = None
) -> Any:
    """One guard expression as constraint IR.

    Anything with no counterpart in the IR becomes a single opaque variable
    rather than being dropped. Dropping it would weaken the conjunction, and a
    weaker conjunction is easier to satisfy — which is the direction that turns
    "cannot tell" into "not exclusive" quietly. As an opaque variable it still
    contradicts its own negation, which is the common case.
    """
    consts = constants or {}
    if isinstance(node, Const):
        if isinstance(node.value, bool):
            return {"op": "lit", "value": node.value}
        if isinstance(node.value, int):
            return node.value
        return {"var": atoms.of(str(node.value), function)}
    if isinstance(node, Ref):
        # A named constant left as a free variable can take any value, and a
        # comparison against it is then satisfiable no matter what — which
        # silently loses every bound stated in terms of one.
        if node.symbol in consts:
            return int(consts[node.symbol])
        return {"var": atoms.of(node.symbol, function)}
    if isinstance(node, Un):
        if node.op == "!":
            return {"op": "not", "arg": _as_bool(_lower(node.arg, atoms, function, consts))}
        if node.op == "-":
            inner = _lower(node.arg, atoms, function, consts)
            if isinstance(inner, int) and not isinstance(inner, bool):
                return -inner
            return {"op": "sub", "args": [0, inner]}
    if isinstance(node, Bin):
        if node.op in _CMP_TO_IR:
            return {
                "op": _CMP_TO_IR[node.op],
                "lhs": _lower(node.left, atoms, function, consts),
                "rhs": _lower(node.right, atoms, function, consts),
            }
        if node.op in _BOOL_TO_IR:
            return {
                "op": _BOOL_TO_IR[node.op],
                "args": [
                    _as_bool(_lower(node.left, atoms, function, consts)),
                    _as_bool(_lower(node.right, atoms, function, consts)),
                ],
            }
        if node.op in _ARITH_TO_IR:
            return {
                "op": _ARITH_TO_IR[node.op],
                "args": [
                    _lower(node.left, atoms, function, consts),
                    _lower(node.right, atoms, function, consts),
                ],
            }
    return {"var": atoms.of(_render(node), function)}


def _render(node: Any) -> str:
    """A stable spelling for a subtree we do not lower, so it names one atom.

    Member accesses are rebuilt as `a.b.c` rather than printed as the nested
    Call nodes the parser produces. The printed form starts with `Call(`, which
    made the member test below look at the wrong head and qualify
    `fBaseParams.deterSparseType` per function — so the same member read in two
    functions became two variables and could never contradict itself.
    """
    from uo_init.expr_ir import Call
    from uo_init.source_resolver import dotted_path

    path = dotted_path(node)
    if path:
        return path
    if isinstance(node, Call):
        # `v.size()` parses as `size(v)`, not as a member access, so it needs
        # its own spelling — and a readable one, because callers name atoms by
        # it to give them a meaning (`size(syncRounds)` -> a bounded count).
        name = node.func[len("field:") :] if node.func.startswith("field:") else node.func
        return f"{name}({', '.join(_render(a) for a in node.args)})"
    if isinstance(node, Ref):
        return node.symbol
    if isinstance(node, Const):
        return str(node.value)
    return re.sub(r"\s+", "", str(node))


def _as_bool(ir: Any) -> dict[str, Any]:
    """Read a value in a boolean position the way C does."""
    if isinstance(ir, dict) and ir.get("op") in (
        set(_CMP_TO_IR.values()) | {"and", "or", "not"}
    ):
        return ir
    if isinstance(ir, int) and not isinstance(ir, bool):
        return {"op": "ne", "lhs": ir, "rhs": 0}
    return {"op": "ne", "lhs": ir, "rhs": 0}


def _text_to_ir(
    text: str, atoms: _Atoms, function: str, constants: dict[str, int] | None = None
) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        # An opaque guard (a macro that did not expand) says nothing, and
        # inventing an atom for it would let two unrelated opaque guards look
        # like the same condition.
        return None
    try:
        tree = parse_expr(text)
    except Exception:
        return {"op": "ne", "lhs": {"var": atoms.of(text, function)}, "rhs": 0}
    return _as_bool(_lower(tree, atoms, function, constants))


def _guard_ir(cond: Any, atoms: _Atoms, function: str) -> dict[str, Any] | None:
    ir = _text_to_ir(getattr(cond, "text", ""), atoms, function)
    if ir is None:
        return None
    if getattr(cond, "negated", False):
        ir = {"op": "not", "arg": ir}
    return ir


def guards_exclusive(
    conds_a: Any,
    conds_b: Any,
    *,
    function_a: str = "",
    function_b: str = "",
    members: Any = (),
    timeout_ms: int = 2000,
) -> Exclusion:
    """Whether two guard sets can hold at once, decided by the solver.

    Only `unsat` counts as exclusive. `sat`, `unknown`, a timeout and a
    compilation failure all mean the same thing here — we did not establish
    it — and each returns not-exclusive, because claiming exclusion we cannot
    show is what would let a real pair of appends be counted as one.
    """
    atoms = _Atoms(frozenset(members or ()))
    args: list[dict[str, Any]] = []
    for cond in conds_a or ():
        ir = _guard_ir(cond, atoms, function_a)
        if ir is not None:
            args.append(ir)
    for cond in conds_b or ():
        ir = _guard_ir(cond, atoms, function_b)
        if ir is not None:
            args.append(ir)
    if not args:
        return Exclusion(False, reason="no_readable_guards")

    try:
        from acp_common.z3_backend import SolveConfig, Z3Backend
    except ImportError as exc:  # pragma: no cover - solver always present
        return Exclusion(False, reason=f"solver_unavailable:{exc}")

    variables = [{"id": name, "type": "int"} for name in sorted(atoms.names)]
    try:
        backend = Z3Backend(
            {"variables": variables, "constraints": []},
            SolveConfig(timeout_ms=timeout_ms),
        )
        expr = args[0] if len(args) == 1 else {"op": "and", "args": args}
        result = backend.solve_expr(expr, label="event_exclusion")
    except Exception as exc:
        return Exclusion(False, reason=f"solver_error:{type(exc).__name__}")

    status = str((result or {}).get("status") or "")
    if status == "unsat":
        return Exclusion(True, checked=len(args))
    detail = (result or {}).get("reason") or ""
    return Exclusion(
        False,
        reason=f"not_proven:{status}" + (f":{detail[:80]}" if status == "error" else ""),
        checked=len(args),
    )


# --- how many elements can these containers hold between them --------------

#: Loop statements, as they appear in `PathCond.kind`.
_LOOP_KINDS = frozenset({"for", "while", "do", "cxx_for_range"})


@dataclass(frozen=True)
class CardinalityBound:
    """An upper bound on the combined element count of some containers.

    `bound` is on the *sum*. Separate per-container bounds would be a much
    weaker statement: two containers each under 36 only gives 72 between them,
    which is exactly the fact that fails to settle `a.size() + b.size() > 36`.
    """

    containers: tuple[str, ...]
    bound: int | None = None
    #: The loops the appends sit in, as (file, line, trip), for the record.
    loops: tuple[tuple[str, int, int], ...] = ()
    reason: str = ""

    def __bool__(self) -> bool:
        return self.bound is not None


def _enclosing_loops(event: Any) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            (pc.file, pc.line)
            for pc in getattr(event, "path_conditions", ()) or ()
            if getattr(pc, "kind", "") in _LOOP_KINDS
        )
    )


def _all_pairwise_exclusive(events: list[Any], members: Any) -> bool:
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            a, b = events[i], events[j]
            if not guards_exclusive(
                a.path_conditions,
                b.path_conditions,
                function_a=a.function,
                function_b=b.function,
                members=members,
            ):
                return False
    return True


def cardinality_bound(
    ir: Any,
    function: str,
    params: list[str] | tuple[str, ...],
    *,
    constants: dict[str, int] | None = None,
) -> CardinalityBound:
    """Largest combined size the containers behind `params` can reach.

    Everything has to line up: each container traced to its declaration, each
    provably empty to begin with, every recorded change an append, and every
    loop around those appends counted. A gap in any of them ends with a reason
    and no number, because a bound derived from an incomplete picture is not a
    loose bound — it is a wrong one, and it would be used to delete a branch.
    """
    names = tuple(params)
    members = getattr(ir, "class_fields", None) or frozenset()

    # One entry per call site of the consumer. Two callers passing their own
    # locals are two situations, and the bound has to hold in both, so they are
    # maximised over rather than added.
    per_site: dict[str, list[ContainerInstance]] = {}
    for param in names:
        found = resolve_param_container(ir, function, param)
        if not found:
            return CardinalityBound(names, reason=f"no_call_site_for:{param}")
        for inst in found:
            if not inst:
                return CardinalityBound(
                    names, reason=f"{param}:{inst.reason}"
                )
            if not inst.starts_empty:
                return CardinalityBound(
                    names, reason=f"{param}:not_known_to_start_empty"
                )
            per_site.setdefault(f"{inst.root_function}", []).append(inst)

    if len(per_site) == 0:
        return CardinalityBound(names, reason="no_container_instances")
    for site, insts in per_site.items():
        if len(insts) != len(names):
            # One of the parameters did not reach this caller, so we cannot say
            # what the other containers there are being summed with.
            return CardinalityBound(
                names, reason=f"incomplete_container_set_at:{site}"
            )

    worst = 0
    seen_loops: list[tuple[str, int, int]] = []
    for site, insts in per_site.items():
        events = [e for inst in insts for e in inst.events]
        non_append = {
            getattr(e, "kind", "assign") for e in events
        } - {"append"}
        if non_append:
            # `clear` only shrinks, but `resize` and whole-container assignment
            # can grow past anything the appends account for.
            return CardinalityBound(
                names, reason=f"{site}:non_append_mutation:{sorted(non_append)}"
            )

        groups: dict[tuple[tuple[str, int], ...], list[Any]] = {}
        for e in events:
            groups.setdefault(_enclosing_loops(e), []).append(e)

        total = 0
        for loops, evs in groups.items():
            trip = 1
            for file, line in loops:
                node = ir.loop_at(file, line)
                if node is None:
                    return CardinalityBound(
                        names, reason=f"loop_statement_not_found:{file}:{line}"
                    )
                bound = loop_bound(node, constants)
                if not bound:
                    return CardinalityBound(
                        names, reason=f"loop_not_counted:{file}:{line}:{bound.reason}"
                    )
                trip *= bound.max_trip
                seen_loops.append((file, line, bound.max_trip))
            # Appends that cannot both run on one iteration contribute one
            # element per iteration between them, not one each.
            if len(evs) > 1 and not _all_pairwise_exclusive(evs, members):
                trip *= len(evs)
            total += trip
            worst = max(worst, total)

    return CardinalityBound(names, bound=worst, loops=tuple(dict.fromkeys(seen_loops)))


# --- is a guard's value already settled ------------------------------------

_SIZE_READ = re.compile(r"\b(\w+)\s*\.\s*size\s*\(\s*\)")


@dataclass(frozen=True)
class GuardTruth:
    """Whether a guard's value is fixed by what we know, before any input."""

    always_true: bool = False
    always_false: bool = False
    #: The bound that settled it, for the record.
    detail: str = ""

    @property
    def settled(self) -> bool:
        return self.always_true or self.always_false


def _solve(expr: dict[str, Any], variables: list[dict[str, Any]], timeout_ms: int) -> str:
    try:
        from acp_common.z3_backend import SolveConfig, Z3Backend

        backend = Z3Backend(
            {"variables": variables, "constraints": []}, SolveConfig(timeout_ms=timeout_ms)
        )
        return str(backend.solve_expr(expr, label="guard_truth").get("status") or "")
    except Exception:
        return "error"


def guard_truth(
    ir: Any,
    text: str,
    scope: str,
    *,
    constants: dict[str, int] | None = None,
    timeout_ms: int = 2000,
) -> GuardTruth:
    """Whether container size bounds alone decide this guard.

    `syncRounds.size() + syncRoundRanges.size() > CORE_LIST_NUM` is false on
    every run, because those two vectors are filled from opposite sides of one
    `if` inside a 36-iteration loop. Left unsettled, each `size()` becomes a
    free variable and the branch behind it stays alive; settled, both variables
    and the branch go away together.

    Only sizes are looked at, and only when the guard mentions one. Everything
    else returns unsettled without troubling the solver.
    """
    names = [
        n
        for n in dict.fromkeys(_SIZE_READ.findall(text or ""))
        if n in ((getattr(ir.summaries.get(scope, None), "params", None)) or [])
    ]
    if not names:
        return GuardTruth()
    bound = cardinality_bound(ir, scope, names, constants=constants)
    if not bound:
        return GuardTruth()

    card = {f"size({n})": f"CARD_{n}" for n in names}
    atoms = _Atoms(frozenset(getattr(ir, "class_fields", None) or ()), overrides=card)
    guard = _text_to_ir(text, atoms, scope, constants)
    if guard is None:
        return GuardTruth()

    cards = [{"var": v} for v in card.values()]
    facts = [{"op": "ge", "lhs": c, "rhs": 0} for c in cards]
    total = cards[0] if len(cards) == 1 else {"op": "add", "args": cards}
    facts.append({"op": "le", "lhs": total, "rhs": int(bound.bound)})

    variables = [{"id": name, "type": "int"} for name in sorted(atoms.names)]
    detail = f"{'+'.join(sorted(card.values()))}<={bound.bound}"
    if _solve({"op": "and", "args": [*facts, guard]}, variables, timeout_ms) == "unsat":
        return GuardTruth(always_false=True, detail=detail)
    negated = {"op": "and", "args": [*facts, {"op": "not", "arg": guard}]}
    if _solve(negated, variables, timeout_ms) == "unsat":
        return GuardTruth(always_true=True, detail=detail)
    return GuardTruth()
