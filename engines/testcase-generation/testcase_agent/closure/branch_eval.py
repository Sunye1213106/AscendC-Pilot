# -*- coding: utf-8 -*-
"""Evaluate a kernel branch condition against one observed TilingData.

The point is to say, without a device, which way each steerable branch went for
a case the host really tilinged. Three kinds of symbol appear in these
conditions and each is resolved from a different place:

  * tiling data access   -> the decoded bytes
  * TilingKey parameter  -> the key's decoded dimensions
  * anything else        -> UNKNOWN, and the branch is reported as undecided

UNKNOWN is a first-class answer. Guessing a value here would invent coverage:
a branch reported TRUE that the kernel never took is worse than one reported
undecided, because only the second sends anybody to look.
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from typing import Any

#: `<name>` reads as "the value is not known", distinct from any real value.
UNKNOWN = object()

TD_ACCESS = re.compile(
    r"\b(?:this\s*->\s*)?\w*[Tt]iling\w*\s*(?:->|\.)\s*"
    r"(\w+)(?:\s*\.\s*(\w+))?\s*(\[\s*[^\]]+\s*\])?")

#: Enum spellings the conditions compare against, resolved from the operator's
#: own constants rather than assumed. Filled by the caller from UO.
EnumTable = dict[str, int]


@dataclass
class Env:
    """Everything a condition can be resolved against."""

    #: leaf field path -> value, or list of values for an array
    fields: dict[str, Any] = field(default_factory=dict)
    #: TilingKey dimension name -> int
    dims: dict[str, int] = field(default_factory=dict)
    #: kernel parameter name (IS_TND) -> TilingKey dimension name (IsTnd)
    param_to_dim: dict[str, str] = field(default_factory=dict)
    #: named constants (BN2S2, DETER_BAND, VEC_CORE_NUM_64, ...)
    enums: EnumTable = field(default_factory=dict)
    #: symbols deliberately left unknown, recorded for reporting
    unknown: set[str] = field(default_factory=set)
    #: How many cores the host asked for. A condition comparing the core index
    #: against a field is decided per core, exactly like an indexed array, and
    #: without this it reads as undecided even though every value it depends on
    #: is known.
    block_num: int = 0
    #: Kernel member -> the C++ expression that defines it, as UO recorded the
    #: write. A condition on `isDropBoolMode` is really a condition on the
    #: tiling data that member was computed from, so resolving it here is what
    #: turns an undecided branch into a decided one. Only unguarded writes
    #: belong in this map: a write under `if constexpr (IS_TND)` is not the
    #: definition for a key where IS_TND is false.
    derived: dict[str, str] = field(default_factory=dict)
    #: Field -> the one value it can hold under this key, from a proved lemma.
    #: Reading a pinned field is not a dependency on the case: the key already
    #: fixed it, so a condition over pinned fields and key dimensions decides
    #: the same way for every case under the key. A lemma that is wrong makes
    #: this claim wrongly, which is why `check_pinned` re-tests every one of
    #: them against every observation before any of it is believed.
    pinned: dict[str, Any] = field(default_factory=dict)


@dataclass
class Outcome:
    """What one branch did, and why that is or is not known."""

    value: bool | None          # None == undecided
    detail: str = ""
    unknown_symbols: tuple[str, ...] = ()
    #: For a condition indexed by core or loop counter: the set of results over
    #: every legal index. A branch both taken and not taken across cores is
    #: covered both ways by a single case, which is why this is kept apart from
    #: a single boolean.
    per_index: tuple[bool, ...] = ()
    #: True when the value was reached without reading any tiling data, i.e. it
    #: follows from the TilingKey alone. Then the *other* outcome is not merely
    #: unobserved -- no input can produce it under this key, because the
    #: condition folded at compile time. That is an exclusion, and telling it
    #: apart from an unmet target is the difference between a closed ledger and
    #: one carrying debt nobody can ever pay.
    key_determined: bool = False

    @property
    def both_ways(self) -> bool:
        return len(set(self.per_index)) > 1


_BIN = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.LShift: operator.lshift,
    ast.RShift: operator.rshift, ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_, ast.BitXor: operator.xor,
}
_CMP = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
}


#: Prefix for a flattened tiling-data access. A member path has to become one
#: identifier before `ast.parse` sees it, or `a->b.c` arrives as an attribute
#: chain and every condition that reads a field is reported undecided.
TD_PREFIX = "__td__"


def flat_name(struct: str, field_name: str = "") -> str:
    return TD_PREFIX + (f"{struct}__{field_name}" if field_name else struct)


def _flatten_td(cond: str) -> str:
    def sub(m: re.Match) -> str:
        a, b = m.group(1), m.group(2)
        return flat_name(a, b or "")
    return TD_ACCESS_PATH.sub(sub, cond)


#: The access itself, without the trailing subscript: the subscript is an
#: expression the evaluator still has to walk.
TD_ACCESS_PATH = re.compile(
    r"\b(?:this\s*->\s*)?\w*[Tt]iling\w*\w*\s*(?:->|\.)\s*"
    r"(\w+)(?:\s*\.\s*(\w+))?")


def _to_python(cond: str) -> str:
    """Rewrite a C++ condition into something `ast.parse` accepts.

    Only the surface differs -- `&&`, `!`, casts, `::`, member paths -- so this
    is a rename, not a translation. Anything it cannot rename stays as an
    identifier and the evaluator reports it unknown rather than mis-parsing it.
    """
    s = _balanced_prefix(cond)
    s = re.sub(r"static_cast\s*<[^>]*>\s*", "", s)
    s = re.sub(r"\breinterpret_cast\s*<[^>]*>\s*", "", s)
    # IsSameType<T1, float>::value -> a single identifier the caller can bind
    s = re.sub(r"\bIsSameType\s*<\s*(\w+)\s*,\s*([\w:]+)\s*>\s*::\s*value",
               r"__is_same_\1_\2", s)
    s = _flatten_td(s)
    # `this->x` is just `x` here; any other arrow becomes one name so the
    # subscript around it still parses.
    s = re.sub(r"\bthis\s*->\s*", "", s)
    s = re.sub(r"\b(\w+)\s*->\s*(\w+)", r"\1__\2", s)
    s = re.sub(r"\b(\w+)\s*::\s*(\w+)", r"\1__\2", s)
    s = s.replace("&&", " and ").replace("||", " or ")
    s = re.sub(r"!(?!=)", " not ", s)
    s = s.replace("true", "True").replace("false", "False")
    # A leading `not ` from `!cond` leaves whitespace `ast.parse` reads as an
    # indent, which reported a readable condition as unparseable.
    return s.strip()


def _balanced_prefix(cond: str) -> str:
    """The longest prefix with balanced brackets.

    A macro-expanded guard arrives with the macro body trailing after the
    condition -- `sinkOptional){ op.SyncALLCores(); ...` -- so the text has to
    be cut back to the condition itself before anything tries to parse it.
    """
    depth = 0
    for i, ch in enumerate(cond):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            if depth == 0:
                return cond[:i]
            depth -= 1
        elif ch in "{;" and depth == 0:
            return cond[:i]
    return cond


class _Eval(ast.NodeVisitor):
    def __init__(self, env: Env, index: int | None = None,
                 index_names: tuple[str, ...] = (),
                 resolving: frozenset[str] = frozenset()):
        self.env = env
        self.index = index
        self.index_names = index_names
        #: Members currently being resolved, so a self-referential write
        #: (`x = x || ...`) stops instead of recursing.
        self.resolving = resolving
        self.unknown: set[str] = set()
        #: Tiling data the value actually depended on. Empty means the result
        #: came from the key alone and therefore holds for every case under it.
        self.touched_td: set[str] = set()

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        return node.value

    def visit_BoolOp(self, node):
        """Short-circuit for real, not just in the result.

        Evaluating the remaining operands anyway would still return the right
        answer, but it records a dependency on tiling data the condition never
        actually read -- and that dependency is what decides whether the
        opposite outcome is impossible or merely unobserved.
        """
        decisive = isinstance(node.op, ast.Or)
        before = set(self.touched_td)
        saw_unknown = False
        for v in node.values:
            mark = set(self.touched_td)
            got = self.visit(v)
            if got is UNKNOWN:
                saw_unknown = True
                continue
            if _truthy(got) is decisive:
                # This operand alone settles the expression. If it needed no
                # tiling data, neither does the result -- whatever the operands
                # before it happened to read cannot change the answer, so their
                # reads are not a dependency of it.
                if self.touched_td == mark:
                    self.touched_td = before
                return decisive
        return UNKNOWN if saw_unknown else (not decisive)

    def visit_UnaryOp(self, node):
        v = self.visit(node.operand)
        if v is UNKNOWN:
            return UNKNOWN
        if isinstance(node.op, ast.Not):
            return not _truthy(v)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return +v
        if isinstance(node.op, ast.Invert):
            return ~v
        return UNKNOWN

    def visit_BinOp(self, node):
        a, b = self.visit(node.left), self.visit(node.right)
        if a is UNKNOWN or b is UNKNOWN:
            return UNKNOWN
        fn = _BIN.get(type(node.op))
        try:
            return fn(a, b) if fn else UNKNOWN
        except Exception:  # noqa: BLE001 - a division by a decoded zero
            return UNKNOWN

    def visit_Compare(self, node):
        left = self.visit(node.left)
        for op, comp in zip(node.ops, node.comparators):
            right = self.visit(comp)
            if left is UNKNOWN or right is UNKNOWN:
                return UNKNOWN
            fn = _CMP.get(type(op))
            if fn is None:
                return UNKNOWN
            try:
                if not fn(_num(left), _num(right)):
                    return False
            except Exception:  # noqa: BLE001
                return UNKNOWN
            left = right
        return True

    def visit_IfExp(self, node):
        t = self.visit(node.test)
        if t is UNKNOWN:
            return UNKNOWN
        return self.visit(node.body if _truthy(t) else node.orelse)

    def visit_Call(self, node):
        # The deterministic-mode predicates are macros over one argument.
        name = getattr(node.func, "id", "")
        args = [self.visit(a) for a in node.args]
        if name in self.env.enums and len(args) == 1:
            return UNKNOWN
        fn = _MACROS.get(name)
        if fn and len(args) == 1 and args[0] is not UNKNOWN:
            return fn(_num(args[0]))
        self.unknown.add(name or "<call>")
        return UNKNOWN

    def visit_Subscript(self, node):
        base = self.visit(node.value)
        if base is UNKNOWN:
            return UNKNOWN
        idx = self.visit(node.slice)
        if not isinstance(base, (list, tuple)):
            return UNKNOWN
        if idx is UNKNOWN:
            if self.index is None:
                return UNKNOWN
            idx = self.index
        try:
            return base[int(idx)]
        except Exception:  # noqa: BLE001 - an index past the array
            return UNKNOWN

    def visit_Attribute(self, node):
        return UNKNOWN

    def visit_Name(self, node):
        n = node.id
        env = self.env
        # A lemma names the field; the condition may name it through its struct
        # (`__td__preTilingData__hasInvalidCol`). Compare on the leaf so a rule
        # does not have to know which struct carries the field.
        pin = _leaf_of(n)
        if pin in env.pinned:
            return env.pinned[pin]
        if n in env.pinned:
            return env.pinned[n]
        if n in env.fields:
            self.touched_td.add(n)
            return env.fields[n]
        # Decoded maps often supply only the leaf; conditions flatten through
        # the struct path. Leaf lookup keeps Env construction operator-agnostic.
        if pin != n and pin in env.fields:
            self.touched_td.add(pin)
            return env.fields[pin]
        if n in env.dims:
            return env.dims[n]
        if n in env.param_to_dim:
            d = env.param_to_dim[n]
            if d in env.dims:
                return env.dims[d]
        if n in env.enums:
            return env.enums[n]
        if n in self.index_names:
            return self.index if self.index is not None else UNKNOWN
        if n in env.derived and n not in self.resolving:
            sub = _Eval(env, index=self.index, index_names=self.index_names,
                        resolving=self.resolving | {n})
            try:
                tree = ast.parse(_to_python(env.derived[n]), mode="eval")
            except SyntaxError:
                self.unknown.add(n)
                return UNKNOWN
            v = sub.visit(tree)
            self.unknown |= sub.unknown
            self.touched_td |= sub.touched_td
            if v is not UNKNOWN:
                return v
            return UNKNOWN
        self.unknown.add(n)
        return UNKNOWN

    def generic_visit(self, node):
        self.unknown.add(type(node).__name__)
        return UNKNOWN


#: `IS_DETER_OLD(x)` / `IS_DETER_NEW(x)` over the DeterSparseType enum. Kept as
#: a table because they are macros: no declaration carries their body into the
#: AST, and the values they test are the enum UO already records.
_MACROS = {
    "IS_DETER_OLD": lambda v: int(v) == 1,
    "IS_DETER_NEW": lambda v: int(v) in (2, 3, 4),
    "IS_DETER": lambda v: int(v) != 0,
}


def _truthy(v: Any) -> bool:
    return bool(v) if not isinstance(v, (list, tuple)) else bool(len(v))


def _num(v: Any) -> Any:
    return int(v) if isinstance(v, bool) else v


def _leaf_of(name: str) -> str:
    """The field name inside a flattened access, or the name unchanged."""
    if name.startswith(TD_PREFIX):
        return name[len(TD_PREFIX):].rsplit("__", 1)[-1]
    return name


def _names_index(cond_py: str, index_names: tuple[str, ...]) -> bool:
    idents = set(re.findall(r"\b[A-Za-z_]\w*\b", cond_py))
    return bool(idents & set(index_names))


def _array_len(env: Env, cond_py: str) -> int:
    """Longest array the condition indexes, so per-index evaluation knows how
    many indices to try."""
    best = 0
    for name, val in env.fields.items():
        if isinstance(val, (list, tuple)) and name in cond_py:
            best = max(best, len(val))
    return best


def evaluate(condition: str, env: Env, *,
             index_names: tuple[str, ...] = ("cBlockIdx", "vBlockIdx", "blockIdx",
                                             "m_blockIdx", "i", "loopIdx", "bIdx",
                                             "taskId", "blockInnerIdx",
                                             "nextValidBlockInnerIdx",
                                             "bandLoopIdx")) -> Outcome:
    """Decide a branch condition against one observed TilingData."""
    py = _to_python(condition)
    try:
        tree = ast.parse(py, mode="eval")
    except SyntaxError as exc:
        return Outcome(None, detail=f"unparsed: {exc.msg}")

    n = _array_len(env, py)
    if n <= 1 and env.block_num > 1 and _names_index(py, index_names):
        n = env.block_num
    if n > 1:
        results: list[bool] = []
        unknown: set[str] = set()
        touched: set[str] = set()
        for i in range(n):
            ev = _Eval(env, index=i, index_names=index_names)
            v = ev.visit(tree)
            unknown |= ev.unknown
            touched |= ev.touched_td
            if v is not UNKNOWN:
                results.append(_truthy(v))
        if results:
            uniform = len(set(results)) == 1
            return Outcome(
                value=(results[0] if uniform else None),
                detail=("uniform" if uniform
                        else f"varies over {len(results)} indices"),
                unknown_symbols=tuple(sorted(unknown)),
                per_index=tuple(results),
                key_determined=bool(uniform and not touched and not unknown),
            )
        return Outcome(None, detail="array indexed but nothing decided",
                       unknown_symbols=tuple(sorted(unknown)))

    ev = _Eval(env, index=None, index_names=index_names)
    v = ev.visit(tree)
    if v is UNKNOWN:
        return Outcome(None, detail="undecided",
                       unknown_symbols=tuple(sorted(ev.unknown)))
    return Outcome(_truthy(v), detail="decided",
                   unknown_symbols=tuple(sorted(ev.unknown)),
                   key_determined=bool(not ev.touched_td and not ev.unknown))
