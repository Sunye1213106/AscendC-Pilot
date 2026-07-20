"""Simplify condition AST and extract atomic predicates."""

from __future__ import annotations

from typing import Any

from .condition_ast import ParseError, try_parse_condition

ARITH_OPS = {"add", "sub", "mul", "div", "mod"}
CMP_OPS = {"eq", "ne", "lt", "le", "gt", "ge"}


def simplify_and_atomize(condition: str) -> dict[str, Any]:
    """Return {status, ast, norm_expr, atoms, error}."""
    ast, err = try_parse_condition(condition)
    if ast is None:
        return {"status": "parse_fail", "ast": None, "norm_expr": None, "atoms": [], "error": err or "PARSE_FAIL"}
    try:
        simplified = simplify_ast(ast)
        atoms = extract_atoms(simplified)
        norm = ast_to_norm_expr(simplified)
        return {"status": "ok", "ast": simplified, "norm_expr": norm, "atoms": atoms, "error": ""}
    except Exception as exc:  # noqa: BLE001 — surface as parse/simplify failure
        return {"status": "parse_fail", "ast": ast, "norm_expr": None, "atoms": [], "error": str(exc)}


def simplify_ast(node: dict[str, Any]) -> dict[str, Any]:
    op = str(node.get("op") or "")
    if op == "wrap":
        return simplify_ast(node["arg"])
    if op == "not":
        inner = simplify_ast(node["arg"])
        if inner.get("op") == "not":
            return simplify_ast(inner["arg"])
        if inner.get("op") == "and":
            return {"op": "or", "args": [simplify_ast({"op": "not", "arg": a}) for a in inner.get("args") or []]}
        if inner.get("op") == "or":
            return {"op": "and", "args": [simplify_ast({"op": "not", "arg": a}) for a in inner.get("args") or []]}
        return {"op": "not", "arg": inner}
    if op in {"and", "or"}:
        args = [simplify_ast(a) for a in node.get("args") or []]
        flat: list[dict[str, Any]] = []
        for a in args:
            if a.get("op") == op:
                flat.extend(a.get("args") or [])
            else:
                flat.append(a)
        uniq: list[dict[str, Any]] = []
        seen: set[str] = set()
        for a in flat:
            key = repr(a)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(a)
        if len(uniq) == 1:
            return uniq[0]
        return {"op": op, "args": uniq}
    if op in CMP_OPS:
        return {"op": op, "lhs": _simp_value(node.get("lhs")), "rhs": _simp_value(node.get("rhs"))}
    if op in ARITH_OPS:
        return {"op": op, "args": [_simp_value(a) for a in node.get("args") or []]}
    if op == "call":
        return {"op": "call", "name": node.get("name"), "args": [_simp_value(a) for a in node.get("args") or []]}
    if op == "name":
        return {"op": "name", "name": str(node.get("name") or "")}
    if op == "lit":
        return {"op": "lit", "value": node.get("value")}
    raise ParseError(f"unsupported ast op in simplify: {op}")


def extract_atoms(node: dict[str, Any]) -> list[dict[str, Any]]:
    atoms: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(n: dict[str, Any]) -> None:
        op = str(n.get("op") or "")
        if op in {"and", "or"}:
            for a in n.get("args") or []:
                visit(a)
            return
        if op == "not":
            inner = n.get("arg") or {}
            if str(inner.get("op") or "") in {"and", "or", "not"}:
                visit(inner)
                return
            # Keep leaf atom id without leading !; negation lives in norm_expr structure.
            atom = _atom_from_node(inner, negated=False)
            _add(atom)
            return
        atom = _atom_from_node(n, negated=False)
        _add(atom)

    def _add(atom: dict[str, Any] | None) -> None:
        if not atom:
            return
        key = atom["id"]
        if key in seen:
            return
        seen.add(key)
        atoms.append(atom)

    visit(node)
    return atoms


def ast_to_norm_expr(node: dict[str, Any]) -> dict[str, Any]:
    """Convert simplified AST to constraint-IR shaped bool expr using atom placeholders."""
    op = str(node.get("op") or "")
    if op == "and":
        return {"op": "and", "args": [ast_to_norm_expr(a) for a in node.get("args") or []]}
    if op == "or":
        return {"op": "or", "args": [ast_to_norm_expr(a) for a in node.get("args") or []]}
    if op == "not":
        inner = node.get("arg") or {}
        if str(inner.get("op") or "") not in {"and", "or", "not"}:
            atom = _atom_from_node(inner, negated=False)
            return {"op": "not", "arg": {"op": "atom", "id": atom["id"]}}
        return {"op": "not", "arg": ast_to_norm_expr(inner)}
    atom = _atom_from_node(node, negated=False)
    return {"op": "atom", "id": atom["id"]}


def _atom_from_node(node: dict[str, Any], *, negated: bool) -> dict[str, Any]:
    op = str(node.get("op") or "")
    if op == "name":
        name = str(node.get("name") or "")
        aid = name  # negation handled by outer not in norm_expr
        return {
            "id": aid,
            "kind": "ident",
            "raw": f"!{name}" if negated else name,
            "name": name,
            "negated": negated,
            "lhs": name,
            "cmp": None,
            "rhs": None,
            "lhs_ast": {"op": "name", "name": name},
            "rhs_ast": None,
        }
    if op in CMP_OPS:
        lhs_ast = node.get("lhs") if isinstance(node.get("lhs"), dict) else {"op": "lit", "value": node.get("lhs")}
        rhs_ast = node.get("rhs") if isinstance(node.get("rhs"), dict) else {"op": "lit", "value": node.get("rhs")}
        lhs = _leaf_str(lhs_ast)
        rhs = _leaf_str(rhs_ast)
        raw = f"{lhs} {op} {rhs}"
        aid = raw
        return {
            "id": aid,
            "kind": "cmp",
            "raw": f"!({raw})" if negated else raw,
            "name": lhs,
            "negated": negated,
            "lhs": lhs,
            "cmp": op,
            "rhs": _leaf_value(rhs_ast),
            "rhs_raw": rhs,
            "lhs_ast": lhs_ast,
            "rhs_ast": rhs_ast,
        }
    if op == "call":
        name = str(node.get("name") or "call")
        args = ",".join(_leaf_str(a) for a in node.get("args") or [])
        raw = f"{name}({args})"
        if "IsSameType" in name and "float" in name:
            aid = "IsSameType_float"
        elif "IsSameType" in name and ("bfloat16" in name.lower() or "bf16" in name.lower()):
            aid = "IsSameType_bf16"
        elif "IsSameType" in name and ("half" in name.lower() or "float16" in name.lower()):
            aid = "IsSameType_fp16"
        else:
            aid = raw
        return {
            "id": aid,
            "kind": "call",
            "raw": f"!{aid}" if negated else aid,
            "name": name,
            "negated": negated,
            "lhs": name,
            "cmp": None,
            "rhs": None,
            "lhs_ast": None,
            "rhs_ast": None,
        }
    if op == "lit":
        aid = f"lit:{node.get('value')}"
        return {"id": aid, "kind": "lit", "raw": aid, "name": aid, "negated": negated, "lhs": None, "cmp": None, "rhs": node.get("value")}
    raise ParseError(f"cannot atomize op={op}")


def _simp_value(node: Any) -> dict[str, Any]:
    if not isinstance(node, dict):
        return {"op": "lit", "value": node}
    op = str(node.get("op") or "")
    if op in {"wrap", "not", "and", "or"}:
        return simplify_ast(node)
    if op in ARITH_OPS:
        return {"op": op, "args": [_simp_value(a) for a in node.get("args") or []]}
    if op in CMP_OPS:
        return simplify_ast(node)
    return node


def _leaf_str(node: Any) -> str:
    if not isinstance(node, dict):
        return str(node)
    op = node.get("op")
    if op == "name":
        return str(node.get("name") or "")
    if op == "lit":
        return str(node.get("value"))
    if op == "call":
        args = ",".join(_leaf_str(a) for a in node.get("args") or [])
        return f"{node.get('name')}({args})"
    if op in ARITH_OPS:
        sym = {"add": "+", "sub": "-", "mul": "*", "div": "/", "mod": "%"}[op]
        parts = [_leaf_str(a) for a in node.get("args") or []]
        return f"({sym.join(parts)})" if len(parts) > 1 else (parts[0] if parts else op)
    return repr(node)


def _leaf_value(node: Any) -> Any:
    if not isinstance(node, dict):
        return node
    if node.get("op") == "lit":
        return node.get("value")
    if node.get("op") == "name":
        return str(node.get("name") or "")
    return _leaf_str(node)
