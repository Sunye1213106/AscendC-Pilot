# -*- coding: utf-8 -*-
"""Turn guard expressions into constraint-IR JSON.

`source_resolver` says where a guard comes from; `variable_model` names the
variables. This module rewrites the parsed expression tree so every leaf is
either a declared variable or a literal, and emits the operator set shared by
the downstream constraint consumers (`constraint_ir.SUPPORTED_EXPR_OPS`).

A predicate that cannot be fully normalized is *not* approximated. It is
returned with `status: unresolved` and the reason that stopped it, so the gap
shows up as one blocker instead of a plausible-looking wrong constraint.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from uo_init.cpp_expr import parse_expr
from uo_init.expr_ir import Bin, Call, Const, Expr, Ite, Ref, Select, Un, Unknown
from uo_init.ids import hash12
from uo_init.source_resolver import Atom, Resolution, SourceResolver, dotted_path

# C++ operator -> SMT-lite op. Anything absent is unsupported on purpose:
# bit twiddling has no faithful lowering to the integer theory TG solves in.
CMP_OPS = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}
BOOL_OPS = {"&&": "and", "||": "or", "and": "and", "or": "or"}
ARITH_OPS = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod"}
UNSUPPORTED_OPS = {"&", "|", "^", "<<", ">>", "~"}

STATUS_OK = "extracted"
STATUS_UNRESOLVED = "unresolved"

REASON_UNSUPPORTED_OP = "UNSUPPORTED_OPERATOR"
REASON_UNMAPPED_LEAF = "UNMAPPED_LEAF"
REASON_PARSE_FAILED = "PARSE_FAILED"
REASON_EMPTY = "NO_CONDITION_TEXT"
REASON_OPAQUE = "OPAQUE_EXPRESSION"

# Longest string literal still treated as an enum tag rather than free text.
# Layout and mode names ("TND", "BN2GS2D", "HIGH_PRECISION") sit well inside
# this; anything longer is a message or a path, and rewriting a comparison
# against it as an enum equality would invent a domain value.
_MAX_ENUM_LITERAL = 16


def _call_name(e: Expr) -> str:
    if not isinstance(e, Call):
        return ""
    name = e.func[len("field:") :] if e.func.startswith("field:") else e.func
    return name.split("::")[-1]


#: Marks a comparison whose value side was quoted in the source. It rides on
#: the comparison rather than on the literal because a bare `{"lit": ...}` is
#: matched by exact key set elsewhere, and an extra key there would look like a
#: different kind of node.
VALUE_KIND_STRING = "string_literal"


def _mark_literal(node: dict[str, Any], side: Expr) -> dict[str, Any]:
    if isinstance(side, Const) and side.string_literal and isinstance(side.value, str):
        node["value_kind"] = VALUE_KIND_STRING
    return node


def _string_lit(e: Expr) -> str | None:
    if not isinstance(e, Const):
        return None
    v = e.value
    if isinstance(v, str):
        return v.strip("'\"")
    return None


def rewrite_strcmp_cmp(expr: Expr) -> Expr:
    """`strcmp(layout, \"TND\") == 0` → `layout == \"TND\"` (INPUT_FORMAT/ATTR).

    Keeps the layout side as an expanded accessor so the resolver can map it to
    ATTRIBUTE / INPUT_FORMAT, and turns the strcmp result into a plain string
    equality the normalizer already handles.
    """
    if not isinstance(expr, Bin) or expr.op not in ("==", "!="):
        return expr
    left, right = expr.left, expr.right

    def _match(call: Expr, zero: Expr) -> Expr | None:
        if not isinstance(call, Call) or _call_name(call) != "strcmp":
            return None
        if not isinstance(zero, Const) or zero.value not in (0, "0", False):
            return None
        if len(call.args) < 2:
            return None
        a, b = call.args[0], call.args[1]
        sa, sb = _string_lit(a), _string_lit(b)
        if sb is not None and len(sb) <= _MAX_ENUM_LITERAL:
            return Bin(expr.op, a, Const(sb, string_literal=True))
        if sa is not None and len(sa) <= _MAX_ENUM_LITERAL:
            return Bin(expr.op, b, Const(sa, string_literal=True))
        return None

    got = _match(left, right) or _match(right, left)
    return got if got is not None else expr


class NormalizeError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}:{detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class NormalizedPredicate:
    condition: str
    smt: dict[str, Any] | None = None
    status: str = STATUS_OK
    reason: str = ""
    detail: str = ""
    variables: list[str] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and self.smt is not None

    @property
    def canonical(self) -> str:
        """Formatting-independent form, used as content-stable id material."""
        if self.smt is None:
            # Fall back to the raw text with whitespace collapsed: an
            # unresolved guard still needs a stable identity.
            return re.sub(r"\s+", " ", self.condition.strip())
        return json.dumps(self.smt, sort_keys=True, separators=(",", ":"))

    @property
    def digest(self) -> str:
        return hash12(self.canonical)

    def negated(self) -> "NormalizedPredicate":
        """The `else` side of the same branch."""
        if not self.ok:
            return NormalizedPredicate(
                condition=f"!({self.condition})",
                status=self.status,
                reason=self.reason,
                detail=self.detail,
                variables=list(self.variables),
                roots=list(self.roots),
            )
        return NormalizedPredicate(
            condition=f"!({self.condition})",
            smt={"op": "not", "arg": self.smt},
            variables=list(self.variables),
            roots=list(self.roots),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "condition": self.condition,
            "status": self.status,
            "variables": list(self.variables),
            "roots": list(self.roots),
        }
        if self.smt is not None:
            out["smt"] = self.smt
        if self.reason:
            out["unresolved_reason"] = self.reason
        if self.detail:
            out["unresolved_detail"] = self.detail
        return out


class PredicateNormalizer:
    """Rewrites one guard at a time; holds the resolver and variable model."""

    def __init__(self, resolver: SourceResolver, model) -> None:
        self.resolver = resolver
        self.model = model
        # Controllability re-normalizes the same path-condition strings on
        # every nested branch in a function; keep the rewrite.
        self._normalize_cache: dict[str, NormalizedPredicate] = {}

    def _resolver_for(self, expr: Expr) -> SourceResolver:
        """Which scope to read this leaf in. One resolver unless overridden."""
        del expr
        return self.resolver

    # -- leaves ------------------------------------------------------------
    def _leaf(self, expr: Expr) -> dict[str, Any]:
        """A symbol or accessor call becomes `{"var": VAR_...}`."""
        text = _leaf_text(expr)
        if not text:
            raise NormalizeError(REASON_OPAQUE, type(expr).__name__)
        res = self._resolver_for(expr).resolve(text)
        atoms = [a for a in res.atoms if a.root != "CONSTANT"]
        if not atoms:
            # The whole leaf folded to a constant, e.g. a scoped enum member.
            # `symbol` is the value it folded to; `text` is the name it was
            # written under, so reading `text` here spells the literal like an
            # identifier and everything downstream sees an unmodelled symbol.
            const = next((a for a in res.atoms if a.root == "CONSTANT"), None)
            if const is not None:
                return {"lit": _literal_of(const.symbol or const.text)}
            raise NormalizeError(REASON_UNMAPPED_LEAF, text[:80])
        if len(atoms) > 1:
            # A composite like `a * b` inside an accessor: the resolver split
            # it, so there is no single variable to name.
            raise NormalizeError(REASON_OPAQUE, text[:80])
        atom = atoms[0]
        if atom.root is None:
            raise NormalizeError(atom.reason or REASON_UNMAPPED_LEAF, atom.text[:80])
        var_id = self.model.var_id_for(
            atom.root, atom.symbol, atom.index, getattr(atom, "reads", None)
        )
        if not var_id:
            raise NormalizeError(REASON_UNMAPPED_LEAF, f"{atom.root}:{atom.symbol}"[:80])
        self.model.declare_on_demand(var_id, atom.root, atom.index)
        return {"var": var_id, "root": atom.root}

    def _value(self, expr: Expr) -> dict[str, Any]:
        """An operand position: literal, variable, or nested arithmetic."""
        if isinstance(expr, Const):
            return {"lit": expr.value}
        if isinstance(expr, Un) and expr.op == "-" and isinstance(expr.arg, Const):
            return {"lit": -expr.arg.value}
        if isinstance(expr, Bin) and expr.op in ARITH_OPS:
            return {
                "op": ARITH_OPS[expr.op],
                "args": [
                    _as_operand(self._value(expr.left)),
                    _as_operand(self._value(expr.right)),
                ],
            }
        if isinstance(expr, Bin) and expr.op in UNSUPPORTED_OPS:
            raise NormalizeError(REASON_UNSUPPORTED_OP, expr.op)
        return self._leaf(expr)

    # -- boolean structure -------------------------------------------------
    def _bool(self, expr: Expr) -> dict[str, Any]:
        expr = rewrite_strcmp_cmp(expr)
        if isinstance(expr, Unknown):
            raise NormalizeError(REASON_OPAQUE, expr.reason)
        if isinstance(expr, Const):
            return {"op": "lit", "value": bool(expr.value)}
        if isinstance(expr, Un):
            if expr.op in ("!", "not"):
                arg = self._bool(expr.arg)
                if isinstance(arg, dict) and arg.get("op") == "lit":
                    return {"op": "lit", "value": not bool(arg.get("value"))}
                return {"op": "not", "arg": arg}
            raise NormalizeError(REASON_UNSUPPORTED_OP, expr.op)
        if isinstance(expr, Bin):
            if expr.op in BOOL_OPS:
                return {
                    "op": BOOL_OPS[expr.op],
                    "args": [self._bool(expr.left), self._bool(expr.right)],
                }
            if expr.op in CMP_OPS:
                return self._compare(CMP_OPS[expr.op], expr.left, expr.right)
            if expr.op in UNSUPPORTED_OPS:
                raise NormalizeError(REASON_UNSUPPORTED_OP, expr.op)
            if expr.op in ARITH_OPS:
                # `if (a - b)` is C's implicit "!= 0".
                return self._compare("ne", expr, Const(0))
            raise NormalizeError(REASON_UNSUPPORTED_OP, expr.op)
        if isinstance(expr, Ite):
            return {
                "op": "if_then_else",
                "condition": self._bool(expr.cond),
                "then": self._bool(expr.then),
                "else": self._bool(expr.else_),
            }
        if isinstance(expr, Select):
            raise NormalizeError(REASON_OPAQUE, "array_subscript")
        # A bare symbol or accessor used as a condition tests truthiness.
        leaf = self._leaf(expr)
        return self._truthy(leaf)

    def _truthy(self, leaf: dict[str, Any]) -> dict[str, Any]:
        if "lit" in leaf:
            return {"op": "lit", "value": bool(leaf["lit"])}
        var_id = leaf["var"]
        spec = self.model.get(var_id)
        value: Any = True if (spec and spec.value_type == "bool") else 0
        op = "eq" if (spec and spec.value_type == "bool") else "ne"
        return {"op": op, "var": var_id, "value": value}

    def _compare(self, op: str, left: Expr, right: Expr) -> dict[str, Any]:
        lhs = self._value(left)
        rhs = self._value(right)
        nullness = self._null_comparison(op, lhs, rhs)
        if nullness is not None:
            return nullness
        # `{var, value}` is the shape the solver handles best; use it whenever
        # exactly one side is a plain variable and the other a literal.
        if "var" in lhs and "lit" in rhs:
            return _mark_literal({"op": op, "var": lhs["var"], "value": rhs["lit"]}, right)
        if "lit" in lhs and "var" in rhs:
            return _mark_literal(
                {"op": _flip(op), "var": rhs["var"], "value": lhs["lit"]}, left
            )
        return {"op": op, "lhs": _as_operand(lhs), "rhs": _as_operand(rhs)}

    def _null_comparison(
        self, op: str, lhs: dict[str, Any], rhs: dict[str, Any]
    ) -> dict[str, Any] | None:
        """`optional != nullptr` is a presence test, not an integer compare.

        Left as `value: None` it would reach the solver as an untyped null and
        make a bool variable unsatisfiable.
        """
        if op not in ("eq", "ne"):
            return None
        for var_side, lit_side in ((lhs, rhs), (rhs, lhs)):
            if "var" not in var_side or "lit" not in lit_side:
                continue
            if lit_side["lit"] is not None:
                continue
            spec = self.model.get(var_side["var"])
            if spec is not None and spec.value_type != "bool":
                return None
            return {"op": "eq", "var": var_side["var"], "value": op == "ne"}
        return None

    # -- entry point -------------------------------------------------------
    def normalize(self, condition: str) -> NormalizedPredicate:
        text = (condition or "").strip()
        if not text:
            return NormalizedPredicate(
                condition=condition or "", status=STATUS_UNRESOLVED, reason=REASON_EMPTY
            )
        hit = self._normalize_cache.get(text)
        if hit is not None:
            return hit
        try:
            tree = parse_expr(text)
        except Exception as exc:  # noqa: BLE001 - parser failure is a real outcome
            out = NormalizedPredicate(
                condition=text,
                status=STATUS_UNRESOLVED,
                reason=REASON_PARSE_FAILED,
                detail=str(exc)[:120],
            )
            self._normalize_cache[text] = out
            return out
        try:
            smt = self._bool(tree)
        except NormalizeError as exc:
            res = self.resolver.resolve(text)
            out = NormalizedPredicate(
                condition=text,
                status=STATUS_UNRESOLVED,
                reason=exc.reason,
                detail=exc.detail,
                roots=res.roots,
            )
            self._normalize_cache[text] = out
            return out
        res = self.resolver.resolve(text)
        out = NormalizedPredicate(
            condition=text,
            smt=smt,
            variables=sorted(collect_vars(smt)),
            roots=res.roots,
        )
        self._normalize_cache[text] = out
        return out


def _flip(op: str) -> str:
    return {"lt": "gt", "le": "ge", "gt": "lt", "ge": "le"}.get(op, op)


def _as_operand(node: dict[str, Any]) -> Any:
    """Render an operand for the `lhs`/`rhs` slots the solver expects."""
    if "lit" in node:
        return node["lit"]
    if "var" in node:
        return {"var": node["var"]}
    return node


def _literal_of(text: str) -> Any:
    raw = text.strip().strip("'\"")
    for cast in (int, float):
        try:
            return cast(raw, 0) if cast is int else cast(raw)
        except (TypeError, ValueError):
            continue
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    return raw


def _leaf_text(expr: Expr) -> str:
    if isinstance(expr, Ref):
        return expr.symbol
    if isinstance(expr, Call):
        path = dotted_path(expr)
        if path:
            return path
        args = ", ".join(_leaf_text(a) or "?" for a in expr.args)
        name = expr.func[len("field:") :] if expr.func.startswith("field:") else expr.func
        return f"{name}({args})"
    if isinstance(expr, Const):
        return repr(expr.value)
    return ""


def collect_vars(node: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        if isinstance(node.get("var"), str):
            out.add(node["var"])
        for value in node.values():
            out |= collect_vars(value)
    elif isinstance(node, list):
        for item in node:
            out |= collect_vars(item)
    return out


def normalize_many(
    conditions: list[str], resolver: SourceResolver, model
) -> list[NormalizedPredicate]:
    normalizer = PredicateNormalizer(resolver, model)
    return [normalizer.normalize(c) for c in conditions]


def conjoin(preds: list[NormalizedPredicate]) -> dict[str, Any] | None:
    """AND together the resolved predicates on a path.

    Unresolved members are dropped rather than failing the whole path: a path
    condition is a conjunction, so keeping the resolved part still yields a
    sound (if weaker) constraint. The caller records the dropped ones.
    """
    args = [p.smt for p in preds if p.ok and p.smt is not None]
    if not args:
        return None
    if len(args) == 1:
        return args[0]
    return {"op": "and", "args": args}
