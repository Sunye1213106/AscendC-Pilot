"""Bind value sub-expressions (names / arith) onto CSV/KEY/KVAR vars for finite predicate binding."""

from __future__ import annotations

import re
from typing import Any

from .atom_bind import (
    BindContext,
    UNBOUND_TEMPLATE_NAMES,
    csv_var,
    _extract_tdf_field,
    _is_loop_local,
    _is_platform,
    _lookup_key_token,
    _normalize_member,
    _strip_qualifiers,
)


class ExprBindError(RuntimeError):
    def __init__(self, reason: str, name: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.name = name


def bind_value_expr(node: Any, ctx: BindContext) -> dict[str, Any]:
    """Bind an AST value node to ConstraintIR value expr ({var}/lit/add/...)."""
    if not isinstance(node, dict):
        return {"op": "lit", "value": node} if False else _lit(node)
    op = str(node.get("op") or "")
    if op == "lit":
        return _lit(node.get("value"))
    if op == "name":
        return bind_name_to_value(str(node.get("name") or ""), ctx)
    if op in {"add", "sub", "mul", "div", "mod"}:
        return {"op": op, "args": [bind_value_expr(a, ctx) for a in node.get("args") or []]}
    if op == "call":
        # Treat call as named flag value 0/1 when it's an IS_* macro call
        name = str(node.get("name") or "")
        key_hit = _lookup_key_token(name, ctx)
        if key_hit:
            var_id, true_value = key_hit
            # value expr for use inside arith rarely; as bool leaf use var ref
            return {"var": var_id}
        raise ExprBindError("UNBOUND_CALL", name)
    if op == "wrap":
        return bind_value_expr(node.get("arg"), ctx)
    raise ExprBindError("UNBOUND_ATOM", op)


def bind_name_to_value(name: str, ctx: BindContext) -> dict[str, Any]:
    raw = str(name or "").strip()
    if not raw:
        raise ExprBindError("UNBOUND_ATOM", raw)
    if _is_platform(raw, ctx):
        raise ExprBindError("PLATFORM_MACRO", raw)
    if _is_loop_local(raw):
        raise ExprBindError("LOOP_LOCAL", raw)

    # Integer / named constants from UO/TG tables
    upper = raw.upper()
    if upper in ctx.arith_constants:
        return _lit(ctx.arith_constants[upper])
    if raw in ctx.arith_constants:
        return _lit(ctx.arith_constants[raw])

    # KEY / template flags → VAR_KEY_* (int 0/1)
    key_hit = _lookup_key_token(raw, ctx)
    if key_hit:
        var_id, _true = key_hit
        return {"var": var_id}

    # CSV field aliases (from binding_lexicon)
    alias = _normalize_member(raw)
    if alias in ctx.csv_field_aliases:
        column, _ = ctx.csv_field_aliases[alias]
        return {"var": csv_var(column)}

    # TilingData field
    tdf = _extract_tdf_field(raw)
    if tdf:
        leaf = tdf.split(".")[-1]
        if leaf in ctx.missing_tdf_producers or tdf in ctx.missing_tdf_producers:
            raise ExprBindError("NO_HOST_PRODUCER", raw)
        kvar = ctx.kvar_by_name.get(leaf) or ctx.kvar_by_name.get(leaf.upper())
        if kvar:
            return _kvar_value_ref(kvar, leaf, ctx)
        raise ExprBindError("NO_HOST_PRODUCER", raw)

    base = _strip_qualifiers(raw)
    if "::" in base:
        base = base.split("::")[-1]

    # Enum member literals from any kvar domain_entries (e.g. BN2 → 1)
    lit = ctx.enum_literal_values.get(raw) or ctx.enum_literal_values.get(upper)
    if lit is not None:
        return _lit(lit)

    # Layout / sparse-mode style tokens used as CSV string enum values
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", raw) and raw not in UNBOUND_TEMPLATE_NAMES:
        # Prefer symbolic string for CSV enums (BNGSD, RIGHT_DOWN_CAUSAL, ...)
        if any(
            raw in (kvar.get("domain") or []) or raw.upper() in {str(x).upper() for x in (kvar.get("domain") or [])}
            for kvar in ctx.kvar_by_name.values()
            if isinstance(kvar, dict)
        ):
            return _lit(raw)

    if base in UNBOUND_TEMPLATE_NAMES or base.upper() in UNBOUND_TEMPLATE_NAMES:
        # Still allow if kvar has set_by
        kvar = ctx.kvar_by_name.get(base) or ctx.kvar_by_name.get(base.upper())
        if kvar and isinstance(kvar.get("set_by"), dict) and (
            kvar["set_by"].get("csv") or kvar["set_by"].get("key") or kvar["set_by"].get("tiling")
        ):
            return _kvar_value_ref(kvar, base, ctx)
        raise ExprBindError("UNBOUND_TEMPLATE", raw)

    kvar = ctx.kvar_by_name.get(base) or ctx.kvar_by_name.get(base.upper()) or ctx.kvar_by_name.get(raw)
    if kvar:
        return _kvar_value_ref(kvar, base, ctx)

    # DT_* dtype enums as literals
    from .atom_bind import DTYPE_VALUES

    if raw in DTYPE_VALUES:
        return _lit(DTYPE_VALUES[raw])

    raise ExprBindError("UNBOUND_CMP", raw)


def _kvar_value_ref(kvar: dict[str, Any], name: str, ctx: BindContext) -> dict[str, Any]:
    set_by = kvar.get("set_by") if isinstance(kvar.get("set_by"), dict) else {}
    kvar_id = str(kvar.get("id") or "")
    classification = str(kvar.get("classification") or "").lower()
    if classification in {"loop_local", "platform"}:
        raise ExprBindError("LOOP_LOCAL" if classification == "loop_local" else "PLATFORM_MACRO", name)
    if set_by.get("csv"):
        column = str(set_by.get("csv"))
        if not ctx.csv_columns or column in ctx.csv_columns:
            return {"var": csv_var(column)}
        # UO set_by.csv without consumer evidence → CSV-free kvar (do not invent CSV column).
        var = f"VAR_{kvar_id}" if kvar_id and not kvar_id.startswith("VAR_") else (kvar_id or f"VAR_KVAR_{name.upper()}")
        domain = kvar.get("domain")
        ints: list[int] = []
        if isinstance(domain, list):
            for item in domain:
                try:
                    ints.append(int(item))
                except (TypeError, ValueError):
                    continue
        ctx.free_kvar_specs[var] = {
            "id": var,
            "type": "int",
            "domain": ints or [0, 1, 2, 4, 8, 16, 32, 64, 128, 256],
            "free": True,
            "source_refs": [{"path": "uo.set_by.csv_without_consumer", "kvar": kvar_id, "intended_csv": column}],
        }
        return {"var": var}
    if set_by.get("key"):
        key = str(set_by.get("key"))
        var = key if key.startswith("VAR_") else f"VAR_{key}" if key.startswith("KEY_") else f"VAR_KEY_{key.upper()}"
        return {"var": var}
    if set_by.get("tiling"):
        var = f"VAR_{kvar_id}" if kvar_id and not kvar_id.startswith("VAR_") else (kvar_id or f"VAR_KVAR_{name.upper()}")
        return {"var": var}
    if _is_loop_local(name):
        raise ExprBindError("LOOP_LOCAL", name)
    raise ExprBindError("UNBOUND_KVAR", name)


def bind_cmp_atom_to_ir(atom: dict[str, Any], ctx: BindContext) -> dict[str, Any]:
    """Bind a comparison atom (possibly with arith sides) to ConstraintIR bool expr."""
    cmp_op = str(atom.get("cmp") or "eq")
    lhs_ast = atom.get("lhs_ast")
    rhs_ast = atom.get("rhs_ast")
    if not isinstance(lhs_ast, dict):
        lhs_ast = {"op": "name", "name": str(atom.get("lhs") or "")}
    if not isinstance(rhs_ast, dict):
        rhs = atom.get("rhs")
        rhs_ast = rhs if isinstance(rhs, dict) else {"op": "lit", "value": rhs}
    lhs = bind_value_expr(lhs_ast, ctx)
    rhs = bind_value_expr(rhs_ast, ctx)
    # Prefer {op, var, value} when lhs is bare var and rhs is lit
    if "var" in lhs and len(lhs) == 1 and isinstance(rhs, dict) and rhs.get("op") == "lit":
        return {"op": cmp_op, "var": lhs["var"], "value": rhs.get("value")}
    return {"op": cmp_op, "lhs": lhs, "rhs": rhs}


def collect_var_ids_from_expr(expr: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(expr, dict):
        if "var" in expr and isinstance(expr.get("var"), str):
            out.add(str(expr["var"]))
        for key in ("arg", "lhs", "rhs", "condition", "then", "else", "expr"):
            if key in expr:
                out |= collect_var_ids_from_expr(expr[key])
        for child in expr.get("args") or []:
            out |= collect_var_ids_from_expr(child)
    return out


def _lit(value: Any) -> dict[str, Any]:
    return {"op": "lit", "value": value}
