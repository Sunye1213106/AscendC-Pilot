# -*- coding: utf-8 -*-
"""Single-pass clang AST walk producing control nodes, path conditions and writes.

This is the precise-IR backend shared by BranchInventory (step 1), Host IR
(step 2) and the path-condition collector (step 6). Text/regex scanning is kept
only as an explicit fallback for files that cannot be parsed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from uo_init.build_context import BuildContext

try:
    from clang import cindex
except ImportError:  # pragma: no cover
    cindex = None  # type: ignore


FOREIGN_MARKERS = ("cann-asc-devkit", "/_cann/", "cann-metadef", "bisheng")

# Guard expressions are read back as text and re-parsed; 48 tokens truncated
# real conditions mid-expression and produced spurious parse failures.
COND_TOKENS = 200
# Initialisers, assignments and return expressions are chased transitively, so
# truncating them silently poisons every guard downstream.
EXPR_TOKENS = 256

CONTROL_KINDS: dict[str, str] = {
    "IF_STMT": "if",
    "SWITCH_STMT": "switch",
    "FOR_STMT": "for",
    "CXX_FOR_RANGE_STMT": "cxx_for_range",
    "WHILE_STMT": "while",
    "DO_STMT": "do",
    "CONDITIONAL_OPERATOR": "ternary",
}


@dataclass(frozen=True)
class PathCond:
    """One guard on the way from function entry to a node."""

    text: str
    negated: bool
    file: str
    line: int
    #: What kind of statement put this guard on the path — `if`, `ternary`,
    #: `switch`, a loop (`for` / `while` / `do` / `cxx_for_range`),
    #: `guard_clause` for the negation implied by an earlier `if (c) return;`,
    #: or `bailout` for the same when that return reports the call was rejected.
    #: Loop and switch guards also spell their kind into `text`, but only as
    #: text: this is what lets a reader tell them apart without parsing it out.
    kind: str = "if"

    def pretty(self) -> str:
        text = self.text or "<macro-expanded>"
        return f"!({text})" if self.negated else text

    @property
    def is_opaque(self) -> bool:
        """True when the guard came from a macro expansion with no readable text."""
        return not self.text.strip()

    @property
    def is_decision(self) -> bool:
        """True when this guard splits paths two ways, so its negation is the
        other way and the two together cover everything.

        A loop guard says "on some iteration" and a `switch` case is one of
        many with no promise of a `default`, so neither can be paired with a
        negation that way. A `bailout` splits nothing either: the other way
        does not reach here at all, which is why it is a premise of the whole
        run rather than a condition on one write. See `is_bailout`.
        """
        return self.kind in ("if", "ternary", "guard_clause")

    @property
    def is_bailout(self) -> bool:
        """True when this guard holds on every run that produces a key.

        `if (dtype is one we reject) { return GRAPH_FAILED; }` does not make the
        statements after it conditional in any useful sense: the other branch
        never reaches key encoding, so on every run there *is* a key for, the
        negation simply holds. Hanging it on the writes that follow says the
        wrong thing twice over — those writes look partial, which mints an
        initial value for a run that cannot happen, and the condition itself,
        which is the operator's own definition of a legal input, ends up buried
        inside one field instead of constraining the inputs everywhere.
        """
        return self.kind == "bailout"

    @property
    def records_what_follows(self) -> bool:
        """True when everything further down this path was also recorded.

        False for `guard_clause`, which is the negation implied by an
        `if (c) { return; } else if (…) { … }`: only `c` gets negated onto the
        path, never the chain's own conditions, so the recorded guard is weaker
        than the truth and running out of the path proves nothing. The same
        `if` without an else chain records `!c` in full and is not marked.
        """
        return self.kind != "guard_clause"


@dataclass
class CtrlNode:
    id: str
    kind: str
    file: str
    line: int
    column: int = 0
    snippet: str = ""
    condition: str = ""
    function: str = ""
    universe: str = "PRODUCTION"
    path_conditions: tuple[PathCond, ...] = ()
    induction_vars: tuple[str, ...] = ()
    #: Loop initial value and per-iteration delta, when both are read straight
    #: off the AST. Neither appears in `condition`, and `snippet` is truncated,
    #: so a trip count has no other honest source. `None` means the loop was
    #: not one of the shapes we read, and callers must not guess from text.
    init_value: int | None = None
    step: int | None = None


@dataclass
class WriteRecord:
    path: str
    line: int
    rhs: str
    file: str
    function: str = ""
    path_conditions: tuple[PathCond, ...] = ()
    #: How the write changes the destination. Consumers that chase a value need
    #: `assign` / `replace` (the RHS *is* the new value) apart from `append`
    #: (the RHS is one element, and the container's value is the whole
    #: sequence), and both apart from `opaque` — a change we recognised but
    #: cannot describe. Without the distinction, `size(v)` resolves to the value
    #: of whichever element was pushed last, and a `clear()` we failed to model
    #: is indistinguishable from no write at all.
    kind: str = "assign"
    #: Same reason `CallSite` carries one: ordering a write against a read on
    #: the same line needs the column. Deciding whether a `push_back` is the
    #: last change before a `back()` is exactly that question.
    column: int = 0


@dataclass(frozen=True)
class CallSite:
    """One call, with the guards that have to hold to reach it.

    A write inside a helper is only reached if the helper is called, and only
    on the paths where the call is. Without the guards here, an unguarded
    write in another function has to be modelled as "may or may not happen" —
    a free boolean the solver reads as either way.
    """

    caller: str
    callee: str
    file: str
    line: int
    args: tuple[str, ...] = ()
    path_conditions: tuple[PathCond, ...] = ()
    #: For a C++ member call, the object it was called on. Not derivable from
    #: `args`: clang does not put the receiver among a member call's arguments,
    #: so without this `v.clear()` records as `callee='clear', args=()` and
    #: there is no way to learn which container was emptied.
    receiver: str = ""
    #: One line can hold several calls on the same container —
    #: `prefix0.push_back(x)` and `prefix0.back()` share a line in FAG. Ordering
    #: them needs the column; the line alone cannot say which ran first.
    column: int = 0


#: Methods that add to a container. The argument is one element, never the
#: container's new value — see `WriteRecord.kind`.
_CONTAINER_APPENDERS = frozenset(
    {
        "push_back",
        "emplace_back",
        "push_front",
        "emplace_front",
        "emplace",
        "insert",
        "append",
    }
)

#: Methods that change a container's length without naming the new contents.
#: They used to leave no trace at all, which made "the container held still"
#: indistinguishable from "we did not look". Recorded with an empty RHS and
#: `kind` from `_MUTATOR_KINDS` so the change is at least *visible*.
_CONTAINER_SHRINKERS = frozenset({"clear", "pop_back", "pop_front", "erase", "resize"})

#: Methods that replace a container's contents wholesale.
_CONTAINER_REPLACERS = frozenset({"assign", "swap"})

_MUTATOR_KINDS = {
    **{m: "append" for m in _CONTAINER_APPENDERS},
    **{m: "shrink" for m in _CONTAINER_SHRINKERS},
    **{m: "replace" for m in _CONTAINER_REPLACERS},
}

_CONTAINER_MUTATORS = frozenset(_MUTATOR_KINDS)


@dataclass(frozen=True)
class FieldDecl:
    """A data member's declaration and whatever it initialises itself to.

    `init` is `None` when the member has no in-class initialiser at all — its
    value before the first write is then indeterminate, which is a stronger
    statement than "we did not look". A member missing from the table entirely
    is the "did not look" case.
    """

    host: str
    name: str
    init: str | None
    file: str
    line: int


@dataclass(frozen=True)
class LocalDecl:
    """A local variable's declaration, whether or not it initialises anything.

    Declarations with no initialiser are recorded too, and that is the point:
    `std::vector<T> v;` writes nothing, so it leaves no write event, yet
    "declared here and default-constructed" is a fact — and an empty container
    at the top of a function is exactly the premise a size bound rests on.
    Absent an entry, the variable was never declared in a function we walked,
    which is a weaker statement than "declared with no initialiser".

    Kept apart from `local_writes` on purpose: a declaration without a value is
    not an assignment, and feeding it to the definition chains as one would put
    an empty right-hand side where a value is expected.
    """

    name: str
    function: str
    type_text: str
    init: str | None
    file: str
    line: int
    column: int = 0


@dataclass
class FuncRecord:
    name: str
    file: str
    line: int
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    guards: list[str] = field(default_factory=list)
    locals: dict[str, str] = field(default_factory=dict)
    params: list[str] = field(default_factory=list)
    # non-const ref/pointer formals that the callee may write through
    out_params: list[str] = field(default_factory=list)
    # (callee name, positional actual-argument sources) for every call made here
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    returns: list[str] = field(default_factory=list)
    # local_name → RHS of the *last* assignment (last write wins)
    assigns: dict[str, str] = field(default_factory=dict)
    # container path → every element appended to it, in order. Deliberately not
    # in `assigns`: an element is not the container's value.
    appends: dict[str, list[str]] = field(default_factory=dict)
    # local_name → every RHS seen in order (init + assigns); enables cycle-safe chase
    assign_lists: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class WalkResult:
    path: str
    controls: list[CtrlNode] = field(default_factory=list)
    writes: list[WriteRecord] = field(default_factory=list)
    # Assignments to plain locals, kept with their path conditions. `writes`
    # only holds field paths, but a key field is often encoded straight from a
    # local (`GET_TPL_TILING_KEY(..., splitAxis, ...)`), and without the guards
    # there is no condition left to derive.
    local_writes: list[WriteRecord] = field(default_factory=list)
    #: Every call with its guards, so "was this function reached" is a real
    #: condition rather than an unknown.
    call_sites: list[CallSite] = field(default_factory=list)
    functions: dict[str, FuncRecord] = field(default_factory=dict)
    diagnostics: list[tuple[int, str, str]] = field(default_factory=list)
    macro_idioms: int = 0
    # data members declared by the tiling classes in this TU: a bare identifier
    # naming one of these is really `this->name`
    class_fields: set[str] = field(default_factory=set)
    #: (declaring struct, member) -> its declaration. Keyed on the struct too
    #: because member names collide freely: `b` is declared by six different
    #: structs here, and the generated tiling-data ones all say `= 0`. Reading a
    #: bare name would turn "cannot prove" into "proved to be zero".
    field_decls: dict[tuple[str, str], FieldDecl] = field(default_factory=dict)
    #: Local declarations, including the ones that initialise nothing.
    local_decls: list[LocalDecl] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for sev, _, _ in self.diagnostics if sev >= 3)

    def count_by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for n in self.controls:
            out[n.kind] = out.get(n.kind, 0) + 1
        return out

    def count_by_file(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for n in self.controls:
            out[n.file] = out.get(n.file, 0) + 1
        return out


def _require_clang():
    if cindex is None:  # pragma: no cover
        raise RuntimeError("libclang not installed")


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def _tokens(cursor, limit: int = 64) -> list[str]:
    out: list[str] = []
    try:
        for t in cursor.get_tokens():
            # Comments between operands are trivia, not expression tokens.
            # Keeping them makes a valid guard such as ``a || // why\n b``
            # look like it references the prose in the comment.
            if getattr(getattr(t, "kind", None), "name", "") == "COMMENT":
                continue
            if len(out) >= limit:
                out.append("...")
                break
            out.append(t.spelling)
    except Exception:
        return []
    return out


_SPACE_AROUND_OP = (
    (re.compile(r"\s*\.\s*"), "."),
    (re.compile(r"\s*->\s*"), "->"),
    (re.compile(r"\s*::\s*"), "::"),
    (re.compile(r"\s*<\s*"), "<"),
    (re.compile(r"\s*>\s*"), ">"),
    (re.compile(r"\s*\(\s*"), "("),
    (re.compile(r"\s*\)\s*"), ")"),
    (re.compile(r"\s*,\s*"), ", "),
    (re.compile(r"\s*;\s*"), ";"),
    (re.compile(r"\s+"), " "),
)


def normalize_expr_text(text: str) -> str:
    """Collapse libclang token spacing so `a . b` becomes chaseable `a.b`."""
    t = (text or "").strip()
    if not t:
        return t
    for pat, repl in _SPACE_AROUND_OP:
        t = pat.sub(repl, t)
    return t.strip()


def _text_of(cursor, limit: int = 64) -> str:
    return normalize_expr_text(" ".join(_tokens(cursor, limit)))


# Synthetic local that carries a function's return value, so a multi-branch
# helper reads back as a guarded assignment chain.
RETURN_SLOT = "__return__"

_COMPOUND_OPS = ("<<=", ">>=", "+=", "-=", "*=", "/=", "%=", "|=", "&=", "^=")


def _compound_op(cursor) -> str:
    """`+=` for a compound assignment, `""` for a plain one.

    The operand cursors of `a += b` are just `a` and `b`, so reading the second
    child as the RHS silently turns an accumulation into an overwrite. The
    operator only survives in the token stream.
    """
    if cursor.kind.name != "COMPOUND_ASSIGNMENT_OPERATOR":
        return ""
    for tok in _tokens(cursor, EXPR_TOKENS):
        if tok in _COMPOUND_OPS:
            return tok
    return ""


def _is_constexpr_if(cursor) -> bool:
    toks = _tokens(cursor, 3)
    return len(toks) >= 2 and toks[0] == "if" and toks[1] == "constexpr"


def _is_do_while_zero(children: list) -> bool:
    """`do { ... } while (0)`: the statement-macro idiom, not a loop.

    An empty condition extent means the whole do-stmt came from a macro
    expansion whose tokens live in another TU position; in Ascend C host code
    those are always the OP_LOG* / OP_CHECK statement macros.
    """
    if not children:
        return False
    cond = _text_of(children[-1], 4).replace(" ", "")
    return cond in ("0", "(0)", "false", "")


def _file_of(cursor) -> str | None:
    try:
        f = cursor.location.file
    except Exception:
        return None
    return _norm(f.name) if f is not None else None


def _in_scope(
    file: str | None, needle: str, op_root: str = "", scope=None
) -> bool:
    """True when a cursor belongs to the operator under analysis.

    A scanned scope answers this directly and is preferred, because it was
    built from the include graph: it holds the shared headers a domain keeps
    beside its operators, which carry no operator name. Judging those by name
    drops them, and what they define then reads as undefined rather than as
    missing input.

    The filename needle and the operator root remain for callers that have no
    scan to hand.
    """
    if file is None:
        return False
    if any(m in file for m in FOREIGN_MARKERS):
        return False
    if scope is not None:
        return scope.contains(file)
    if needle:
        return needle in file
    if op_root:
        return file.startswith(op_root)
    return True


def _base_class(cursor):
    """The class a `CXX_BASE_SPECIFIER` names, or None."""
    for get in (cursor.get_definition, lambda: cursor.type.get_declaration()):
        try:
            decl = get()
        except Exception:  # noqa: BLE001 - binding raises on unresolved types
            continue
        if decl is not None and decl.location.file is not None:
            return decl
    return None


def _framework_headers(cursor, needle: str, op_root: str = "", scope=None) -> set[str]:
    """Files holding the base classes this operator's tiling classes derive from.

    A tiling class inheriting `TilingBaseClass` hands the framework the say in
    when its hooks run, and the base class is where that decision is written
    down — one template method calling the hooks in order. Scoped out by
    filename, those calls vanish and every hook becomes a function nothing
    appears to call, which reads downstream as "this may not run at all".

    Derived from the inheritance edges rather than from a path, so it holds for
    any operator on any base class. Bases inside the operator are already
    visible and are followed but not returned.
    """
    if cindex is None:
        return set()
    out: set[str] = set()
    seen: set[str] = set()

    def _specifiers(node, only_in_scope: bool):
        found = []
        stack = list(node.get_children())
        while stack:
            child = stack.pop()
            try:
                kind = child.kind.name
            except Exception:  # noqa: BLE001 - a cursor libclang cannot describe
                continue
            where = _file_of(child)
            if where is None:
                continue
            if only_in_scope and not _in_scope(where, needle, op_root, scope):
                continue
            if kind == "CXX_BASE_SPECIFIER":
                found.append(child)
            else:
                stack.extend(child.get_children())
        return found

    pending = _specifiers(cursor, only_in_scope=True)
    while pending:
        base = _base_class(pending.pop())
        if base is None:
            continue
        key = f"{base.get_usr()}"
        if key in seen:
            continue
        seen.add(key)
        where = _file_of(base)
        if where is None or any(m in where for m in FOREIGN_MARKERS):
            continue
        if not _in_scope(where, needle, op_root, scope):
            out.add(where)
        # A base may itself derive from the class holding the hooks.
        pending.extend(_specifiers(base, only_in_scope=False))
    return out


def _is_out_param(cursor) -> bool:
    """True when a parameter is a non-const reference or pointer (writable out)."""
    if cindex is None:
        return False
    try:
        t = cursor.type
        if t is None:
            return False
        if t.kind == cindex.TypeKind.LVALUEREFERENCE:
            pointee = t.get_pointee()
            return pointee is not None and not pointee.is_const_qualified()
        if t.kind == cindex.TypeKind.POINTER:
            pointee = t.get_pointee()
            return pointee is not None and not pointee.is_const_qualified()
    except Exception:
        return False
    return False


def _receiver_path(cursor, method: str) -> str:
    """The object a member call was made on, as a dotted path.

    Clang does not list the receiver among a member call's arguments, so this
    reads it off the callee child: a member call's first child is a
    MemberRefExpr whose own base is the object.

    A free function has no receiver and has to come back empty. That is why
    only two shapes are accepted — the MemberRefExpr above, and a member
    reference already flattened into the path text so that it ends in the
    method name. Accepting any dotted path from the first child would report
    `std::max(a.b, c)` as a call on `a.b`, because the namespace refs are
    skipped and the next child is an argument.
    """
    for ch in cursor.get_children():
        kn = ch.kind.name
        if kn == "MEMBER_REF_EXPR" and (ch.spelling or "") == method:
            bases = list(ch.get_children())
            return member_path(bases[0]) if bases else ""
        if kn in ("MEMBER_REF_EXPR", "DECL_REF_EXPR", "UNEXPOSED_EXPR"):
            cand = member_path(ch)
            if cand.endswith("." + method):
                return cand[: -(len(method) + 1)]
            return ""
    return ""


def _host_field_allowed(file: str | None, side: str) -> bool:
    """Host analysis must ignore kernel-header FIELD_DECL pollution."""
    if side != "host":
        return True
    if not file:
        return False
    f = file.replace("\\", "/")
    if "/op_kernel/" in f:
        return False
    if any(m in f for m in FOREIGN_MARKERS):
        return False
    return True


def classify_universe(node: CtrlNode, *, op_root: str = "") -> str:
    """Assign an analysis universe from evidence, not a blanket default."""
    text = f"{node.snippet} {node.condition}"
    if not text.strip():
        # No readable tokens at this location: the construct lives inside a
        # macro body defined outside the operator, and clang attributes the
        # expansion to the use site. It is not operator-authored control flow.
        return "LIBRARY_INTERNAL"
    if any(
        marker in text
        for marker in (
            "OP_LOGE",
            "OP_CHECK",
            "OPS_CHECK",
            "OP_TILING_CHECK",
            "GRAPH_FAILED",
            "GRAPH_SUCCESS",
            "ASSERT",
            "OP_LOGE_IF",
            "CheckLogLevel",
            "DLOG_ERROR",
            "DLOG_WARN",
            "DLOG_INFO",
            "DLOG_DEBUG",
        )
    ):
        return "VALIDATION_ONLY"
    if node.kind == "if_constexpr":
        # folded away only once instantiated; still PRODUCTION at inventory time
        return "PRODUCTION"
    if op_root and not node.file.startswith(_norm(op_root)):
        return "LIBRARY_INTERNAL"
    return "PRODUCTION"


class _Walker:
    def __init__(
        self,
        needle: str = "",
        op_root: str = "",
        collect_writes: bool = True,
        *,
        side: str = "host",
        frame_files: frozenset[str] = frozenset(),
        scope=None,
        logs_rejections: bool = False,
    ):
        self.needle = needle
        self.op_root = _norm(op_root) if op_root else ""
        self.frame_files = frame_files
        self.scope = scope
        self.logs_rejections = logs_rejections
        self.collect_writes = collect_writes
        self.side = side
        self.controls: list[CtrlNode] = []
        self.writes: list[WriteRecord] = []
        self.local_writes: list[WriteRecord] = []
        self.call_sites: list[CallSite] = []
        self.functions: dict[str, FuncRecord] = {}
        self.class_fields: set[str] = set()
        self.field_decls: dict[tuple[str, str], FieldDecl] = {}
        self.local_decls: list[LocalDecl] = []
        self.macro_idioms = 0
        self._ordinal: dict[tuple[str, int, str], int] = {}
        # induction variables of every loop currently enclosing the cursor
        self._loop_vars: tuple[str, ...] = ()

    # -- helpers -----------------------------------------------------------
    def _in_scope(self, file: str | None) -> bool:
        return _in_scope(file, self.needle, self.op_root, self.scope)

    def _in_frame(self, file: str | None) -> bool:
        """Scope for who-calls-whom, which reaches one step past the operator.

        The base class that calls this operator's hooks is not part of the
        operator and none of its state should be, but the order it calls them
        in is the only record of when they run. So its functions and its calls
        are read, and nothing else — writes, fields and control nodes all stay
        on the strict test.
        """
        if file is None:
            return False
        return self._in_scope(file) or file in self.frame_files

    def _stable_id(self, file: str, line: int, col: int, kind: str) -> str:
        key = (file, line, kind)
        n = self._ordinal.get(key, 0)
        self._ordinal[key] = n + 1
        return f"{file}:{line}:{col}:{kind}:{n}"

    def _record_field_decl(self, cursor, file: str) -> None:
        """Record a data member's in-class initialiser, or its absence."""
        parent = cursor.semantic_parent
        host = (parent.spelling if parent is not None else "") or ""
        if not host:
            # An anonymous struct or union. Without a name for the declaring type
            # there is no key that tells its members apart from anyone else's.
            return
        init: str | None = None
        children = [
            c
            for c in cursor.get_children()
            if c.kind.name not in ("TYPE_REF", "TEMPLATE_REF", "NAMESPACE_REF")
        ]
        if children:
            text = _text_of(children[-1], EXPR_TOKENS)
            if text.startswith("{") and text.endswith("}"):
                text = text[1:-1].strip()
            init = text or None
        self.field_decls.setdefault(
            (host, cursor.spelling),
            FieldDecl(
                host=host,
                name=cursor.spelling,
                init=init,
                file=file,
                line=cursor.location.line,
            ),
        )

    def _record_var_decl(self, cursor, func: str, stack=()) -> None:
        if not func or func not in self.functions:
            return
        file = _file_of(cursor)
        if not self._in_scope(file):
            return
        children = list(cursor.get_children())
        init = children[-1] if children else None
        # A trailing type reference is the declared type, not a value: these are
        # the declarations that initialise nothing.
        if init is not None and (
            init.kind.name in ("TYPE_REF", "TEMPLATE_REF", "NAMESPACE_REF")
            or _is_default_construction(init)
        ):
            init = None
        text = _text_of(init, EXPR_TOKENS) if init is not None else ""
        if text.startswith("{") and text.endswith("}"):
            text = text[1:-1].strip()  # brace initialisation: `int64_t m{expr}`
        if cursor.spelling:
            self.local_decls.append(
                LocalDecl(
                    name=cursor.spelling,
                    function=func,
                    type_text=(cursor.type.spelling if cursor.type else "") or "",
                    init=text or None,
                    file=file,
                    line=cursor.location.line,
                    column=cursor.location.column,
                )
            )
        if text:
            fr = self.functions[func]
            fr.locals.setdefault(cursor.spelling, text)
            hist = fr.assign_lists.setdefault(cursor.spelling, [])
            if text not in hist:
                hist.append(text)
            self._record_local_write(
                cursor.spelling, text, cursor, file, func, stack
            )

    def _record_local_write(
        self, name, rhs, cursor, file, func, stack, kind: str = "assign"
    ) -> None:
        # A write that names its new value is worthless without the value, so
        # those are still dropped. A length change has no value to name, and
        # dropping it would hide the change itself.
        if not (name and file):
            return
        if kind in ("assign", "append") and (not rhs or rhs == name):
            return
        self.local_writes.append(
            WriteRecord(
                path=name,
                line=cursor.location.line,
                column=cursor.location.column,
                rhs=rhs,
                file=file,
                function=func,
                path_conditions=tuple(stack),
                kind=kind,
            )
        )

    def _record_return(self, cursor, func: str, stack=()) -> None:
        """Return expressions let a call to this function resolve to its sources.

        A helper that returns a different value per branch carries its whole
        meaning in *which* branch returns what, so the return is also recorded
        as a guarded write to a synthetic slot. Keeping only the bare list of
        return texts makes such a helper look ambiguous instead of conditional.
        """
        if not func or func not in self.functions:
            return
        children = list(cursor.get_children())
        if not children:
            return
        text = _text_of(children[0], EXPR_TOKENS)
        if not text:
            return
        if text not in self.functions[func].returns:
            self.functions[func].returns.append(text)
        file = _file_of(cursor)
        if self._in_scope(file):
            self._record_local_write(RETURN_SLOT, text, cursor, file, func, stack)

    def _record_call(self, cursor, func: str, stack=()) -> None:
        """Remember the actual arguments so callee parameters can be resolved."""
        if not func or func not in self.functions:
            return
        file = _file_of(cursor)
        if not self._in_frame(file):
            return
        callee = cursor.spelling
        if not callee:
            return
        try:
            args = tuple(_text_of(a, EXPR_TOKENS) for a in cursor.get_arguments())
        except Exception:
            return
        if any(args):
            self.functions[func].calls.append((callee, args))
        # Recorded for every call, including argument-less ones: reachability
        # is about whether the call happens, not about what is passed. The
        # receiver matters for the same reason — `v.clear()` passes nothing and
        # changes everything.
        self.call_sites.append(
            CallSite(
                caller=func,
                callee=callee,
                file=file,
                line=cursor.location.line,
                args=args,
                path_conditions=tuple(stack),
                # Not gated on a member-call cursor kind: this libclang reports
                # `v.clear()` as a plain CALL_EXPR and has no
                # CXX_MEMBER_CALL_EXPR in `CursorKind` at all, so gating on it
                # left every receiver empty. `_receiver_path` returns "" for a
                # free function, which is the only distinction needed.
                receiver=_receiver_path(cursor, callee),
                column=cursor.location.column,
            )
        )

    def _record_control(
        self,
        cursor,
        kind: str,
        cond_text: str,
        stack,
        func: str,
        cond_cursor=None,
        induction_vars: tuple[str, ...] = (),
        init_value: int | None = None,
        step: int | None = None,
    ):
        file = _file_of(cursor)
        if not self._in_scope(file):
            return
        assert file is not None
        if func and func in self.functions:
            fr = self.functions[func]
            if cond_text and cond_text not in fr.guards:
                fr.guards.append(cond_text)
            if cond_cursor is not None:
                for p in collect_member_paths(cond_cursor):
                    if p not in fr.reads:
                        fr.reads.append(p)
        loc = cursor.location
        node = CtrlNode(
            id=self._stable_id(file, loc.line, loc.column, kind),
            kind=kind,
            file=file,
            line=loc.line,
            column=loc.column,
            snippet=_text_of(cursor, 16),
            condition=cond_text,
            function=func,
            path_conditions=tuple(stack),
            # a nested branch can also be guarded by any enclosing loop variable
            induction_vars=tuple(dict.fromkeys(induction_vars + self._loop_vars)),
            init_value=init_value,
            step=step,
        )
        node.universe = classify_universe(node, op_root=self.op_root)
        self.controls.append(node)

    def _record_tie_unpack(self, lhs, rhs_text: str, func: str) -> bool:
        """`std::tie(a, b, std::ignore) = tup` → per-element assigns via __tuple_elem.

        Returns True when the LHS was a tie/unpack and has been handled.
        """
        if not func or func not in self.functions or not rhs_text:
            return False
        # Unwrap UnexposedExpr layers down to the real CallExpr.
        cur = lhs
        for _ in range(6):
            if cur.kind.name in ("CALL_EXPR", "CXX_OPERATOR_CALL_EXPR"):
                break
            kids = list(cur.get_children())
            if len(kids) == 1:
                cur = kids[0]
                continue
            # Prefer a CallExpr child if several
            calls = [k for k in kids if k.kind.name in ("CALL_EXPR", "CXX_OPERATOR_CALL_EXPR")]
            if len(calls) == 1:
                cur = calls[0]
                continue
            break
        lhs = cur
        spelling = (lhs.spelling or "").split("::")[-1]
        toks = _text_of(lhs, 16)
        if spelling not in ("tie", "make_tuple", "forward_as_tuple"):
            if "tie(" in toks.replace(" ", "") or "tie (" in toks:
                spelling = "tie"
            else:
                return False
        try:
            args = list(lhs.get_arguments())
        except Exception:
            args = []
        if not args:
            for ch in lhs.get_children():
                kn = ch.kind.name
                if kn == "DECL_REF_EXPR" and (ch.spelling or "") not in (
                    "tie",
                    "make_tuple",
                ):
                    args.append(ch)
                elif kn == "UNEXPOSED_EXPR":
                    sub = list(ch.get_children())
                    if sub and sub[0].kind.name == "DECL_REF_EXPR":
                        if (sub[0].spelling or "") not in ("tie", "make_tuple"):
                            args.append(sub[0])
        if not args:
            return False
        fr = self.functions[func]
        idx = 0
        recorded = 0
        for arg in args:
            cur = arg
            guard = 0
            while cur is not None and cur.kind.name == "UNEXPOSED_EXPR" and guard < 4:
                kids = list(cur.get_children())
                cur = kids[0] if kids else None
                guard += 1
            if cur is None:
                idx += 1
                continue
            name = cur.spelling or ""
            if not name or name in ("ignore", "tie", "make_tuple") or name.endswith(
                "ignore"
            ):
                idx += 1
                continue
            if cur.kind.name not in ("DECL_REF_EXPR", "MEMBER_REF_EXPR"):
                idx += 1
                continue
            get_rhs = f"__tuple_elem({idx}, {rhs_text})"
            fr.assigns[name] = get_rhs
            hist = fr.assign_lists.setdefault(name, [])
            if get_rhs not in hist:
                hist.append(get_rhs)
            recorded += 1
            idx += 1
        return recorded > 0

    def _record_write(self, cursor, stack, func: str):
        file = _file_of(cursor)
        if not self._in_scope(file):
            return
        children = list(cursor.get_children())
        if not children:
            return
        lhs = children[0]
        rhs = ""
        if len(children) > 1:
            rhs = _text_of(children[1], EXPR_TOKENS)
        # std::tie / structured unpack into locals
        if rhs and self._record_tie_unpack(lhs, rhs, func):
            return
        op = _compound_op(cursor)
        if op and rhs:
            lhs_text = _text_of(lhs, EXPR_TOKENS) or member_path(lhs)
            if lhs_text:
                rhs = f"{lhs_text} {op[:-1]} ({rhs})"
        path = member_path(lhs)
        if path.count(".") < 1:
            # `x = expr` on a plain local: not a tiling-data write, but it is the
            # only definition of names that were declared without an initialiser
            if path and func and func in self.functions and len(children) > 1:
                if rhs and rhs != path:
                    # last write wins
                    fr = self.functions[func]
                    fr.assigns[path] = rhs
                    hist = fr.assign_lists.setdefault(path, [])
                    if rhs not in hist:
                        hist.append(rhs)
                    self._record_local_write(path, rhs, cursor, file, func, stack)
            return
        assert file is not None
        rec = WriteRecord(
            path=path,
            line=cursor.location.line,
            column=cursor.location.column,
            rhs=rhs,
            file=file,
            function=func,
            path_conditions=tuple(stack),
        )
        self.writes.append(rec)
        if func and func in self.functions:
            fr = self.functions[func]
            if path not in fr.writes:
                fr.writes.append(path)
            if len(children) > 1:
                for p in collect_member_paths(children[1]):
                    if p not in fr.reads:
                        fr.reads.append(p)

    def _record_container_write(self, cursor, stack, func: str) -> None:
        """A container mutation → WriteEvent on the container path.

        Appends carry the pushed element as the RHS. Length changes
        (`clear` / `pop_back` / `erase` / `resize`) and wholesale replacements
        (`assign` / `swap`) carry no readable new value, and are recorded with an
        empty RHS purely so that "the container changed here" is visible: a
        `clear()` that leaves no trace is indistinguishable from no write, and
        anything reasoning about `back(v)` would then be reasoning about a write
        sequence it cannot see.
        """
        if not func or func not in self.functions:
            return
        file = _file_of(cursor)
        if not self._in_scope(file):
            return
        method = cursor.spelling or ""
        kind = _MUTATOR_KINDS.get(method)
        if kind is None:
            return
        try:
            args = list(cursor.get_arguments())
        except Exception:
            return
        if kind == "append" and not args:
            return
        path = _receiver_path(cursor, method)
        if not path:
            return
        rhs = _text_of(args[0], EXPR_TOKENS) if kind == "append" and args else ""
        if kind == "append" and not rhs:
            return
        assert file is not None
        fr = self.functions[func]
        if rhs:
            # Local containers are SSA state too. Recording their inserted value
            # lets ``items.size()/find()/empty()`` and out-parameter containers
            # resolve back to the source of their elements.
            #
            # Kept apart from `assigns` on purpose. An appended element is not
            # the container's value, and while it lived in `assigns` the
            # container's *definition* was whichever element was pushed last —
            # `assigns['slicePrefix1'] == 'R1'`. Every consumer of
            # `defs_by_function()` would then resolve `size(v)` or `v` itself to
            # one element's value.
            hist = fr.appends.setdefault(path, [])
            if rhs not in hist:
                hist.append(rhs)
        if path.count(".") < 1:
            # A bare name is a function-local `std::set`/`vector`, not tiling
            # data — `_record_write` already draws that line for `=`. Without
            # it here, `scratch.insert(x)` became an ownerless WriteRecord that
            # tail-matching could then attribute to a real tiling field.
            self._record_local_write(path, rhs, cursor, file, func, stack, kind=kind)
            return
        self.writes.append(
            WriteRecord(
                path=path,
                line=cursor.location.line,
                column=cursor.location.column,
                rhs=rhs,
                file=file,
                function=func,
                path_conditions=tuple(stack),
                kind=kind,
            )
        )
        if path not in fr.writes:
            fr.writes.append(path)

    # -- traversal ---------------------------------------------------------
    def walk(self, cursor, stack: list[PathCond], func: str) -> None:
        kind_name = cursor.kind.name

        if kind_name in ("CXX_METHOD", "FUNCTION_DECL", "FUNCTION_TEMPLATE", "CONSTRUCTOR"):
            if cursor.is_definition():
                file = _file_of(cursor)
                if self._in_frame(file):
                    assert file is not None
                    name = cursor.spelling or func
                    rec = self.functions.setdefault(
                        name,
                        FuncRecord(name=name, file=file, line=cursor.location.line),
                    )
                    for ch in cursor.get_children():
                        if ch.kind.name == "PARM_DECL" and ch.spelling:
                            if ch.spelling not in rec.params:
                                rec.params.append(ch.spelling)
                            if _is_out_param(ch) and ch.spelling not in rec.out_params:
                                rec.out_params.append(ch.spelling)
                    func = name
                    stack = []

        if kind_name == "COMPOUND_STMT":
            # Statements in a block are siblings in the AST, so a guard clause
            # (`if (cond) { ...; return; }`) leaves no trace on what follows it —
            # yet everything after it runs only when `!cond`. Without that,
            # `x = A;` inside the guard and a later unguarded `x = B;` look like
            # plain last-wins and `x` collapses to the constant `B`.
            implied: list[PathCond] = []
            for ch in cursor.get_children():
                self.walk(ch, stack + implied, func)
                implied.extend(_guard_clause_negations(ch, self.logs_rejections))
            return

        if kind_name == "IF_STMT":
            self._walk_if(cursor, stack, func)
            return
        if kind_name == "CONDITIONAL_OPERATOR":
            self._walk_ternary(cursor, stack, func)
            return
        if kind_name == "SWITCH_STMT":
            self._walk_switch(cursor, stack, func)
            return
        if kind_name in ("FOR_STMT", "WHILE_STMT", "DO_STMT", "CXX_FOR_RANGE_STMT"):
            self._walk_loop(cursor, stack, func, CONTROL_KINDS[kind_name])
            return
        if kind_name == "FIELD_DECL":
            file = _file_of(cursor)
            if (
                cursor.spelling
                and self._in_scope(file)
                and _host_field_allowed(file, self.side)
            ):
                self.class_fields.add(cursor.spelling)
                self._record_field_decl(cursor, file)
        elif kind_name == "VAR_DECL":
            self._record_var_decl(cursor, func, stack)
        # `CXX_MEMBER_CALL_EXPR` is not a kind this libclang has — `v.clear()`
        # arrives as a plain CALL_EXPR, and `CursorKind` has no such member at
        # all. Kept for bindings that do expose it; do not read it as evidence
        # that member calls are dispatched separately here.
        elif kind_name in ("CALL_EXPR", "CXX_MEMBER_CALL_EXPR"):
            self._record_call(cursor, func, stack)
            if self.collect_writes:
                self._record_container_write(cursor, stack, func)
                if (cursor.spelling or "") == "operator=":
                    self._record_operator_assign(cursor, stack, func)
        elif kind_name == "RETURN_STMT":
            self._record_return(cursor, func, stack)
        if self.collect_writes and kind_name in (
            "BINARY_OPERATOR",
            "COMPOUND_ASSIGNMENT_OPERATOR",
        ):
            toks = _tokens(cursor, 96)
            if "=" in toks or any(t in toks for t in ("+=", "-=", "*=", "/=", "|=", "&=")):
                self._record_write(cursor, stack, func)

        for ch in cursor.get_children():
            self.walk(ch, stack, func)

    def _record_operator_assign(self, cursor, stack, func: str) -> None:
        """`std::tie(a,b) = tup` is a CALL_EXPR to operator=, not BINARY_OPERATOR."""
        children = list(cursor.get_children())
        if len(children) < 2:
            return
        # Typical shape: [lhs, operator=-ref, rhs] or [lhs, rhs]
        candidates = [
            c
            for c in children
            if not (
                (c.spelling or "") == "operator="
                or (
                    c.kind.name == "UNEXPOSED_EXPR"
                    and (c.spelling or "") == "operator="
                )
            )
        ]
        if len(candidates) >= 2:
            lhs, rhs = candidates[0], candidates[-1]
        elif len(children) >= 3:
            lhs, rhs = children[0], children[-1]
        else:
            return
        rhs_text = _text_of(rhs, EXPR_TOKENS)
        if self._record_tie_unpack(lhs, rhs_text, func):
            return
        path = member_path(lhs)
        if (
            not path
            or path in ("tie", "make_tuple", "forward_as_tuple")
            or func not in self.functions
            or not rhs_text
            or rhs_text == path
        ):
            return
        fr = self.functions[func]
        # Plain `local = expr` via overloaded operator= — rare for ints
        if path.count(".") < 1:
            fr.assigns[path] = rhs_text
            hist = fr.assign_lists.setdefault(path, [])
            if rhs_text not in hist:
                hist.append(rhs_text)
            return
        # `a.b = expr` where `b`'s type overloads operator= (a container, a
        # string, a struct with a user-defined assignment). This used to be
        # dropped outright: it survived only in `FuncSummary.calls`, which no
        # write-chasing consumer reads. Anything following the write history of
        # `a.b` was therefore reading a sequence with entries missing, and would
        # report a value the source had already overwritten.
        file = _file_of(cursor)
        if not self._in_scope(file):
            return
        assert file is not None
        self.writes.append(
            WriteRecord(
                path=path,
                line=cursor.location.line,
                column=cursor.location.column,
                rhs=rhs_text,
                file=file,
                function=func,
                path_conditions=tuple(stack),
                kind="replace",
            )
        )
        if path not in fr.writes:
            fr.writes.append(path)

    def _cond_and_branches(self, cursor):
        children = list(cursor.get_children())
        cond = children[0] if children else None
        rest = children[1:]
        return cond, rest

    def _walk_if(self, cursor, stack, func):
        kind = "if_constexpr" if _is_constexpr_if(cursor) else "if"
        cond, rest = self._cond_and_branches(cursor)
        cond_text = _text_of(cond, COND_TOKENS) if cond is not None else ""
        self._record_control(cursor, kind, cond_text, stack, func, cond_cursor=cond)

        file = _file_of(cursor) or ""
        line = cursor.location.line
        if cond is not None:
            self.walk(cond, stack, func)
        then_stmt = rest[0] if rest else None
        else_stmt = rest[1] if len(rest) > 1 else None
        if then_stmt is not None:
            self.walk(
                then_stmt,
                stack + [PathCond(cond_text, False, file, line)],
                func,
            )
        if else_stmt is not None:
            self.walk(
                else_stmt,
                stack + [PathCond(cond_text, True, file, line)],
                func,
            )

    def _walk_ternary(self, cursor, stack, func):
        cond, rest = self._cond_and_branches(cursor)
        cond_text = _text_of(cond, COND_TOKENS) if cond is not None else ""
        self._record_control(cursor, "ternary", cond_text, stack, func, cond_cursor=cond)
        file = _file_of(cursor) or ""
        line = cursor.location.line
        if cond is not None:
            self.walk(cond, stack, func)
        if rest:
            self.walk(
                rest[0],
                stack + [PathCond(cond_text, False, file, line, kind="ternary")],
                func,
            )
        if len(rest) > 1:
            self.walk(
                rest[1],
                stack + [PathCond(cond_text, True, file, line, kind="ternary")],
                func,
            )

    def _walk_switch(self, cursor, stack, func):
        cond, rest = self._cond_and_branches(cursor)
        cond_text = _text_of(cond, COND_TOKENS) if cond is not None else ""
        self._record_control(cursor, "switch", cond_text, stack, func, cond_cursor=cond)
        file = _file_of(cursor) or ""
        line = cursor.location.line
        if cond is not None:
            self.walk(cond, stack, func)
        for body in rest:
            self.walk(
                body,
                stack
                + [PathCond(f"switch({cond_text})", False, file, line, kind="switch")],
                func,
            )

    def _walk_loop(self, cursor, stack, func, kind):
        children = list(cursor.get_children())
        if kind == "do" and _is_do_while_zero(children):
            # `do { ... } while (0)` is the statement-macro idiom (OP_LOGD etc.),
            # not a branch: the body executes exactly once. Recurse without
            # recording a control node or a guard.
            if self._in_scope(_file_of(cursor)):
                self.macro_idioms += 1
            for ch in children:
                self.walk(ch, stack, func)
            return
        cond_cursor, induction, init_value, step = _loop_header(children, kind)
        cond_text = _text_of(cond_cursor, COND_TOKENS) if cond_cursor is not None else _text_of(cursor, 24)
        self._record_control(
            cursor,
            kind,
            cond_text,
            stack,
            func,
            cond_cursor=cond_cursor,
            induction_vars=induction,
            init_value=init_value,
            step=step,
        )
        file = _file_of(cursor) or ""
        line = cursor.location.line
        outer = self._loop_vars
        self._loop_vars = tuple(dict.fromkeys(outer + induction))
        try:
            for ch in children:
                self.walk(
                    ch,
                    stack
                    + [PathCond(f"{kind}({cond_text})", False, file, line, kind=kind)],
                    func,
                )
        finally:
            self._loop_vars = outer


_EXIT_KINDS = frozenset(
    {"RETURN_STMT", "BREAK_STMT", "CONTINUE_STMT", "GOTO_STMT", "CXX_THROW_EXPR"}
)

# Returns that report the call was rejected. Which inputs an operator accepts is
# stated nowhere else -- there is no separate legality model -- so these bail-outs
# *are* the definition, and their negation is what holds on everything after them.
# FAG rejects HIFLOAT8 this way; without the negation the analysis believes a
# HIFLOAT8 query reaches key encoding and reports an output dtype the kernel never
# declared.
_ERROR_EXIT_RE = re.compile(r"GRAPH_FAILED|PARAM_INVALID|GRAPH_PARAM|FAILED\b")

# The same bail-out written the other common way. `if (ret != GRAPH_SUCCESS)
# { return ret; }` forwards the status it just tested rather than naming a
# failure code, so the statement carries no word `_ERROR_EXIT_RE` can see --
# but a branch guarded by "the status is not success" is the failure path
# whatever it returns. Reading it as normal flow hangs "every check so far
# passed" on the rest of the function, and a value only ever assigned after
# such a check then looks like it might never be assigned at all.
_STATUS_FAILURE_RE = re.compile(
    r"!=\s*(?:\w+\s*::\s*)?\w*SUCCESS\b|\w*SUCCESS\s*!="
)

# A third way, and the one the user-facing API layer uses. A checker there
# returns `false` or a forwarded status, so the return statement names no
# failure at all -- what marks the branch as a refusal is that it logs an error
# on the way out. `LOGE` is how every layer of this stack spells that.
_ERROR_LOG_RE = re.compile(r"\w*LOGE\b")


def _refuses(then, exit_stmt, by_log: bool) -> bool:
    """Whether this branch is rejecting the input rather than handling a case.

    `by_log` is off for tiling, where a bare `return false` is ordinary control
    flow, and on for the API layer, where it is the house style for refusal.
    Reading tiling that way would turn every early return into a premise about
    the input, which is how a legal input gets excluded.
    """
    if exit_stmt is None:
        return False
    if _ERROR_EXIT_RE.search(" ".join(_tokens(exit_stmt, 64))):
        return True
    return by_log and bool(_ERROR_LOG_RE.search(" ".join(_tokens(then, 256))))


def _exit_statement(stmt):
    """The statement that unconditionally leaves this block, if there is one."""
    kind = stmt.kind.name
    if kind in _EXIT_KINDS:
        return stmt
    if kind == "COMPOUND_STMT":
        children = list(stmt.get_children())
        return _exit_statement(children[-1]) if children else None
    return None


def _else_if_chain(stmt):
    """An `if / else if / …` chain as its links, plus whatever trails it.

    Each link is the condition and the branch it guards; the trailing part is
    the final plain `else`, or None when the chain ends without one.
    """
    links = []
    node = stmt
    while node is not None and node.kind.name == "IF_STMT":
        children = list(node.get_children())
        if len(children) < 2:
            break
        links.append((children[0], children[1]))
        node = children[2] if len(children) > 2 else None
    return links, node


def _exits_inside(body, by_log: bool = False) -> list[PathCond]:
    """Guards one level in that leave the function, as negations."""
    kind = body.kind.name if body is not None else ""
    stmts = list(body.get_children()) if kind == "COMPOUND_STMT" else [body]
    out: list[PathCond] = []
    for s in stmts:
        if s is not None and s.kind.name == "IF_STMT":
            out.extend(_guard_clause_negations(s, by_log))
    return out


def _implied_by_nested_guards(stmt, links, by_log: bool = False) -> list[PathCond]:
    """What an `if` whose branch only *sometimes* leaves still tells us.

    `if (A) { … if (B) return X; }` does not stop the code after it, so the
    negation of B is not on that path outright — but reaching there under A
    does mean B was false. Recorded as `A implies !B`, which is weaker than
    `!B` and holds either way.

    Worth recording because this is the shape an operator's alternate exit
    takes: a whole separate encoding for the degenerate case, guarded by an
    arch test. Dropping it entirely, as reading only unconditional exits did,
    left the main path free to claim the degenerate case's own key -- and the
    keys built from that combination are ones no run produces.

    Recorded as a bail-out, which is what it is from where the key is built:
    the branch that leaves encodes its own key somewhere else, so every run
    that reaches *this* encoding satisfies the implication. Hanging it on the
    writes instead would make them look conditional and mint an initial value
    for a run that does not happen.
    """
    file = _file_of(stmt) or ""
    out: list[PathCond] = []
    for cond, body in links:
        outer = _text_of(cond, COND_TOKENS)
        if not outer:
            continue
        for inner in _exits_inside(body, by_log):
            if inner.is_opaque:
                continue
            out.append(
                PathCond(
                    f"!({outer}) || {inner.pretty()}",
                    False,
                    file,
                    cond.location.line,
                    kind="bailout",
                )
            )
    return out


def _guard_clause_negations(stmt, by_log: bool = False) -> list[PathCond]:
    """The conditions that hold for whatever follows this `if`.

    An if/else already walks both polarities inside the branches, but a
    statement *after* `if (c) { return; } else { ... }` only runs when the
    else was taken — i.e. under `!c`. Without recording that, a later
    unguarded write looks unconditional and wipes earlier definitions
    (FAG's `DoSparse` overwriting `SplitAxisEnum::BN2S2` is exactly this).

    When every branch of an `else if` chain leaves, reaching the statement
    after it means no condition in the chain held — all of them, not just the
    first. Recording only the first understates the path, and the trailing
    `return` of a function written that way then looks like a case the earlier
    branches might not have covered, which mints an initial value for a member
    the code always sets.
    """
    if stmt.kind.name != "IF_STMT":
        return []
    links, tail = _else_if_chain(stmt)
    if not links:
        return []
    if _exit_statement(links[0][1]) is None:
        return _implied_by_nested_guards(stmt, links, by_log)

    exits = [_exit_statement(then) for _, then in links]
    if (
        all(e is not None for e in exits)
        and tail is not None
        and _exit_statement(tail) is not None
    ):
        # Every way through leaves: nothing after the chain runs at all.
        return []

    file = _file_of(stmt) or ""
    texts = [_text_of(cond, COND_TOKENS) for cond, _ in links]
    lines = [cond.location.line for cond, _ in links]
    # `if (ret != GRAPH_SUCCESS) { return ret; }` is a bail-out too, but `ret`
    # names no input: the condition that really failed is inside the callee,
    # and negating this text would only add an opaque variable.
    opaque = [bool(t) and bool(_STATUS_FAILURE_RE.search(t)) for t in texts]
    rejects = [_refuses(then, e, by_log) for (_, then), e in zip(links, exits)]

    whole_chain = (
        len(links) > 1
        and all(e is not None for e in exits)
        and all(texts)
        and not any(rejects)
        and not any(opaque)
    )
    if whole_chain:
        return [
            PathCond(text, True, file, line, kind="if")
            for text, line in zip(texts, lines)
        ]

    # Otherwise only the first condition is known to hold, and with a chain
    # behind it that is weaker than the truth — `guard_clause` marks that, see
    # `PathCond.records_what_follows`.
    if not texts[0] or opaque[0]:
        return []
    if rejects[0]:
        return [PathCond(texts[0], True, file, lines[0], kind="bailout")]
    trailing = len(links) > 1 or tail is not None
    return [
        PathCond(
            texts[0],
            True,
            file,
            lines[0],
            kind="guard_clause" if trailing else "if",
        )
    ]


#: Wrappers libclang inserts between a declaration and its literal initialiser.
#: `unsigned int i = 0` arrives as UNEXPOSED_EXPR because 0 needs converting.
_LITERAL_WRAPPERS = frozenset(
    {"UNEXPOSED_EXPR", "CSTYLE_CAST_EXPR", "CXX_STATIC_CAST_EXPR", "PAREN_EXPR"}
)


def _is_default_construction(node) -> bool:
    """Whether this node is an implicit default constructor rather than a value.

    `std::vector<T> v;` has no initialiser, but libclang still hangs a
    `CALL_EXPR` off the declaration for the implicit default constructor. It
    has no children and its extent covers only the declarator, so reading its
    tokens gives back the variable's own name — which is how
    `std::vector<...> syncRounds;` was recorded as initialised to
    `syncRounds`. A constructor with arguments (`std::vector<int> v(n)`) has
    children, and is a real initialiser.
    """
    return node.kind.name == "CALL_EXPR" and not list(node.get_children())


def _int_literal(cursor) -> int | None:
    """The integer this expression is, or None if it is not plainly one."""
    if cursor is None:
        return None
    name = cursor.kind.name
    if name == "INTEGER_LITERAL":
        toks = [t.spelling for t in cursor.get_tokens()]
        if not toks:
            return None
        # Suffixed literals (`0u`, `36UL`) still name one integer.
        text = toks[0].rstrip("uUlL")
        try:
            return int(text, 0)
        except ValueError:
            return None
    if name in _LITERAL_WRAPPERS:
        kids = list(cursor.get_children())
        return _int_literal(kids[0]) if len(kids) == 1 else None
    if name == "UNARY_OPERATOR":
        kids = list(cursor.get_children())
        toks = [t.spelling for t in cursor.get_tokens()]
        if len(kids) == 1 and toks and toks[0] == "-":
            inner = _int_literal(kids[0])
            return None if inner is None else -inner
    return None


def _loop_step(cursor) -> int | None:
    """Per-iteration delta of a loop's increment clause, if it is a constant.

    Only `i++` / `i--` / `i += k` / `i -= k` are read. The `++i` and `i++`
    forms differ in token order, so the operator is looked for anywhere in the
    clause rather than at a fixed position.
    """
    if cursor is None:
        return None
    toks = [t.spelling for t in cursor.get_tokens()]
    name = cursor.kind.name
    if name == "UNARY_OPERATOR":
        if "++" in toks:
            return 1
        if "--" in toks:
            return -1
        return None
    if name == "COMPOUND_ASSIGNMENT_OPERATOR":
        kids = list(cursor.get_children())
        if len(kids) != 2:
            return None
        amount = _int_literal(kids[1])
        if amount is None:
            return None
        if "+=" in toks:
            return amount
        if "-=" in toks:
            return -amount
    return None


def _loop_header(children: list, kind: str):
    """Split a loop's children into (condition, induction names, init, step).

    `for (int i = 0; i < N; ++i)` yields cond=`i < N` and induction=('i',), so
    the guard resolves against the loop variable instead of being reported as
    an unmapped symbol.

    libclang omits absent header clauses rather than leaving a hole, so a
    `for` has four children only when all three clauses are written. `init`
    and `step` are therefore read only from that shape; anything else reports
    None instead of a value inferred from position.
    """
    if not children:
        return None, (), None, None
    header = children[:-1]
    induction: list[str] = []
    for h in header:
        if h.kind.name == "DECL_STMT":
            for d in h.get_children():
                if d.kind.name == "VAR_DECL" and d.spelling:
                    induction.append(d.spelling)
        elif h.kind.name == "VAR_DECL" and h.spelling:
            # CXX_FOR_RANGE_STMT commonly exposes `for (auto x : xs)` as a
            # VAR_DECL directly, not wrapped in DECL_STMT.
            induction.append(h.spelling)
    if kind == "while":
        return (header[0] if header else None), (), None, None
    if kind == "do":
        return (children[-1] if len(children) > 1 else None), (), None, None
    if kind == "for":
        if len(header) == 3:
            init_c, cond_c, step_c = header
            # Positional, and only here: with all three clauses present the
            # middle one is the condition by construction. Scanning for the
            # first BINARY_OPERATOR instead would pick up an assignment-style
            # init (`for (i = 0; ...)`), which libclang also reports as a
            # BINARY_OPERATOR, and report `i = 0` as the loop condition.
            init_value = None
            if init_c.kind.name == "DECL_STMT":
                decls = [
                    d for d in init_c.get_children() if d.kind.name == "VAR_DECL"
                ]
                # Two induction variables and one increment clause is a shape
                # whose trip count we have not established; say so.
                if len(decls) == 1:
                    kids = list(decls[0].get_children())
                    init_value = _int_literal(kids[-1]) if kids else None
            return cond_c, tuple(induction), init_value, _loop_step(step_c)
        for h in header:
            if h.kind.name in ("BINARY_OPERATOR", "CXX_BOOL_LITERAL_EXPR", "UNEXPOSED_EXPR"):
                return h, tuple(induction), None, None
        return None, tuple(induction), None, None
    # range-for: `for (auto x : range)`
    return None, tuple(induction), None, None


def collect_member_paths(cursor, limit: int = 256) -> list[str]:
    """All nested field paths read inside a subtree (RHS or guard condition)."""
    out: list[str] = []
    stack = [cursor]
    seen = 0
    while stack and seen < limit:
        cur = stack.pop()
        seen += 1
        if cur.kind.name == "MEMBER_REF_EXPR":
            p = member_path(cur)
            if p.count(".") >= 1 and p not in out:
                out.append(p)
            continue
        stack.extend(cur.get_children())
    return out


def member_path(n) -> str:
    """Full nested field path, e.g. `this.fBaseParams.isNzOut` (never flattened)."""
    parts: list[str] = []
    cur = n
    guard = 0
    while cur is not None and guard < 64:
        guard += 1
        k = cur.kind.name
        if k == "MEMBER_REF_EXPR":
            parts.append(cur.spelling)
            ch = list(cur.get_children())
            cur = ch[0] if ch else None
            if cur is None:
                parts.append("this")
        elif k == "DECL_REF_EXPR":
            parts.append(cur.spelling)
            cur = None
        elif k == "CXX_THIS_EXPR":
            parts.append("this")
            cur = None
        elif k == "ARRAY_SUBSCRIPT_EXPR":
            ch = list(cur.get_children())
            cur = ch[0] if ch else None
        else:
            ch = list(cur.get_children())
            cur = ch[0] if ch else None
    return ".".join(reversed([p for p in parts if p]))


def walk_file(
    path: str | Path,
    ctx: BuildContext,
    *,
    side: str = "host",
    dtype_variant: str | None = "DT_FLOAT16",
    op_needle: str = "",
    collect_writes: bool = True,
    scope=None,
    logs_rejections: bool = False,
) -> WalkResult:
    """Parse one TU and extract control nodes / writes / function summaries.

    `logs_rejections` says this file refuses input by logging an error on the
    way out rather than by returning a named failure code. True for the API
    layer, false for tiling. See `_refuses`.
    """
    import time as _time

    from uo_init.timing import log as _tlog, phase_budget_s

    _require_clang()
    path = str(path)
    name = Path(path).name
    t_all = _time.perf_counter()
    args = (
        ctx.host_args()
        if side == "host"
        else ctx.kernel_args(dtype_variant=dtype_variant)
    )
    idx = cindex.Index.create()
    t0 = _time.perf_counter()
    tu = idx.parse(path, args=args, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
    t_parse = _time.perf_counter() - t0
    diags = [
        (int(d.severity), _norm(d.location.file.name) if d.location.file else "?", d.spelling)
        for d in tu.diagnostics
    ]
    op_root = ctx.op_dir or ""
    t0 = _time.perf_counter()
    frame_files = frozenset(
        _framework_headers(tu.cursor, op_needle, op_root, scope)
    )
    t_frame = _time.perf_counter() - t0
    w = _Walker(
        op_needle,
        op_root=op_root,
        collect_writes=collect_writes,
        side=side,
        frame_files=frame_files,
        scope=scope,
        logs_rejections=logs_rejections,
    )
    t0 = _time.perf_counter()
    for child in tu.cursor.get_children():
        w.walk(child, [], "")
    t_walk = _time.perf_counter() - t0
    t_total = _time.perf_counter() - t_all
    budget = phase_budget_s()
    flag = " SLOW" if t_total > budget else ""
    _tlog(
        f"{t_total:7.3f}s{flag}  walk_file  file={name} side={side} "
        f"parse={t_parse:.3f}s frame={t_frame:.3f}s ast_walk={t_walk:.3f}s "
        f"controls={len(w.controls)} writes={len(w.writes)} "
        f"calls={len(w.call_sites)} diags={len(diags)} frames={len(frame_files)}"
    )
    return WalkResult(
        path=_norm(path),
        controls=w.controls,
        writes=w.writes,
        local_writes=w.local_writes,
        call_sites=w.call_sites,
        functions=w.functions,
        diagnostics=diags,
        macro_idioms=w.macro_idioms,
        class_fields=w.class_fields,
        field_decls=w.field_decls,
        local_decls=w.local_decls,
    )
