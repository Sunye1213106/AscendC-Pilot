"""Align KB branch conditions to CSV/KEY via AST → simplify → atom bind."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .atom_bind import BindContext, bind_atoms, csv_var, substitute_norm_expr
from .condition_ast import try_parse_condition
from .condition_simplify import simplify_and_atomize
from .expr_bind import collect_var_ids_from_expr


RUNTIME_SOURCES = {"TilingDataField", "KernelVariable", "KernelDerivedField"}


def _var_id(name: str) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(name)).strip("_").upper()
    return text if text.startswith("VAR_") else f"VAR_{text or 'UNKNOWN'}"


def _derived(var_id: str, var_type: str, domain: Any, expr: dict[str, Any], description: str) -> dict[str, Any]:
    return {
        "id": var_id,
        "type": var_type,
        "domain": domain,
        "expr": {"op": "derived", "var": var_id, "expr": expr},
        "description": description,
        "source_refs": [{"path": "branch_align", "rationale": description}],
    }


def _ite(condition: dict[str, Any], then_value: Any, else_value: Any) -> dict[str, Any]:
    return {"op": "if_then_else", "condition": condition, "then": then_value, "else": else_value}


def align_branches(
    branches_doc: dict[str, Any],
    snapshot: dict[str, Any] | None = None,
    *,
    csv_columns: list[str] | None = None,
    lexicon: dict[str, Any] | None = None,
    op_name: str = "",
    shape_closure: set[str] | None = None,
) -> dict[str, Any]:
    """Return branch_mappings, abstract_branches, alignment_report, extra stub derived vars."""
    ctx = BindContext(
        snapshot,
        csv_columns=csv_columns or [],
        lexicon=lexicon,
        op_name=op_name,
        shape_closure=shape_closure,
    )
    mappings: list[dict[str, Any]] = []
    abstract: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    source_stats: dict[str, Counter[str]] = {}
    stub_vars: dict[str, dict[str, Any]] = {}
    free_csv_vars: dict[str, dict[str, Any]] = {}

    for branch in _iter_items(branches_doc.get("branches")):
        branch_id = str(branch.get("id") or "")
        if not branch_id:
            continue
        var_id = _var_id(branch_id)
        condition = str(branch.get("condition") or "")
        source = str(branch.get("determinant_source") or "")
        base = {
            "branch_ref": branch_id,
            "var": var_id,
            "condition": condition,
            "determinant_source": source,
            "file_path": branch.get("file_path", ""),
            "start_line": branch.get("start_line"),
        }
        source_stats.setdefault(source or "Unknown", Counter())

        healed = _heal_parens(condition)
        parsed = simplify_and_atomize(healed)
        if parsed.get("status") != "ok":
            # Fallback: try original without heal, then legacy single-token path via bind of raw ident
            parsed2 = simplify_and_atomize(condition) if healed != condition else parsed
            if parsed2.get("status") != "ok":
                reason = "PARSE_FAIL"
                abstract.append(
                    {
                        **base,
                        "abstract_only": True,
                        "reason": reason,
                        "parse_error": parsed.get("error") or parsed2.get("error"),
                        "unbound_atoms": [],
                    }
                )
                reason_counts[reason] += 1
                source_stats[source or "Unknown"]["abstract"] += 1
                source_stats[source or "Unknown"][reason] += 1
                continue
            parsed = parsed2

        atoms = parsed.get("atoms") or []
        bindings = bind_atoms(atoms, ctx)
        unbound = [b for b in bindings if b.get("status") != "bound"]
        if unbound:
            reasons = sorted({str(b.get("reason") or "UNBOUND_ATOM") for b in unbound})
            primary = reasons[0]
            abstract.append(
                {
                    **base,
                    "abstract_only": True,
                    "reason": primary,
                    "reasons": reasons,
                    "unbound_atoms": unbound,
                    "atom_bindings": bindings,
                    "norm_expr": parsed.get("norm_expr"),
                }
            )
            reason_counts[primary] += 1
            source_stats[source or "Unknown"]["abstract"] += 1
            source_stats[source or "Unknown"][primary] += 1
            continue

        expr = substitute_norm_expr(parsed.get("norm_expr"), bindings)
        if not expr:
            abstract.append(
                {
                    **base,
                    "abstract_only": True,
                    "reason": "SUBSTITUTE_FAIL",
                    "atom_bindings": bindings,
                }
            )
            reason_counts["SUBSTITUTE_FAIL"] += 1
            source_stats[source or "Unknown"]["abstract"] += 1
            continue

        lexicon_key_ids = {
            str(item.get("id") or "")
            for item in (ctx.lexicon.get("key_derivations") or [])
            if isinstance(item, dict) and item.get("id") and isinstance(item.get("expr"), dict)
        }
        missing_keys = sorted(
            vid for vid in collect_var_ids_from_expr(expr) if vid.startswith("VAR_KEY_") and vid not in lexicon_key_ids
        )
        if missing_keys:
            reason = "KEY_DERIVATION_MISSING"
            abstract.append(
                {
                    **base,
                    "abstract_only": True,
                    "reason": reason,
                    "missing_key_vars": missing_keys,
                    "atom_bindings": bindings,
                    "norm_expr": parsed.get("norm_expr"),
                    "hint": "add key_derivations for these VAR_KEY_* in realization/binding_lexicon.yaml",
                }
            )
            reason_counts[reason] += 1
            source_stats[source or "Unknown"]["abstract"] += 1
            source_stats[source or "Unknown"][reason] += 1
            continue

        # Collect KVAR stubs only (KEY must come from lexicon.key_derivations — never constant-0).
        for binding in bindings:
            target = binding.get("target") or {}
            _collect_stub_vars(target, stub_vars, free_kvar_ids=set(ctx.free_kvar_specs))
            _collect_free_csv_vars(target, free_csv_vars, ctx)

        mappings.append(
            {
                **base,
                "abstract_only": False,
                "atom_bindings": bindings,
                "norm_expr": parsed.get("norm_expr"),
                "derived_variable": _derived(
                    var_id,
                    "bool",
                    [False, True],
                    expr,
                    "aligned kernel branch condition",
                ),
            }
        )
        reason_counts["bound"] += 1
        source_stats[source or "Unknown"]["mapped"] += 1

    report = build_alignment_report(
        mappings,
        abstract,
        reason_counts=reason_counts,
        source_stats=source_stats,
    )
    return {
        "branch_mappings": mappings,
        "abstract_branches": abstract,
        "alignment_report": report,
        "stub_derived_variables": list(stub_vars.values()),
        "free_csv_variables": list(free_csv_vars.values()),
        "free_variables": list(ctx.free_kvar_specs.values()),
    }


def build_alignment_report(
    mappings: list[dict[str, Any]],
    abstract: list[dict[str, Any]],
    *,
    reason_counts: Counter[str] | None = None,
    source_stats: dict[str, Counter[str]] | None = None,
) -> dict[str, Any]:
    reason_counts = reason_counts or Counter()
    source_stats = source_stats or {}
    by_source: dict[str, Any] = {}
    for source, counter in source_stats.items():
        mapped = int(counter.get("mapped", 0))
        abstract_n = int(counter.get("abstract", 0))
        total = mapped + abstract_n
        by_source[source] = {
            "mapped": mapped,
            "abstract": abstract_n,
            "total": total,
            "bound_rate": (mapped / total) if total else 0.0,
            "reasons": {k: v for k, v in counter.items() if k not in {"mapped", "abstract"}},
        }
    runtime = {k: v for k, v in by_source.items() if k in RUNTIME_SOURCES}
    return {
        "version": 1,
        "totals": {
            "mapped": len(mappings),
            "abstract": len(abstract),
            "total": len(mappings) + len(abstract),
            "bound_rate": (len(mappings) / (len(mappings) + len(abstract))) if (mappings or abstract) else 0.0,
        },
        "reason_counts": dict(reason_counts),
        "by_determinant_source": by_source,
        "runtime_sources": runtime,
        "parse_fail": int(reason_counts.get("PARSE_FAIL", 0)),
    }


def try_parse_healed(condition: str) -> tuple[dict[str, Any] | None, str]:
    healed = _heal_parens(condition)
    return try_parse_condition(healed)


def _heal_parens(text: str) -> str:
    """Append missing ')' for truncated KB conditions when clearly unbalanced."""
    s = str(text or "").rstrip()
    if not s:
        return s
    opens = s.count("(")
    closes = s.count(")")
    if opens <= closes:
        return s
    # Only heal when trailing looks truncated (ends mid-ident or after &&/||/!)
    if s.endswith(("&&", "||", "!", ",", "->", ".")) or s[-1].isalnum() or s.endswith("_"):
        return s + (")" * (opens - closes))
    return s + (")" * (opens - closes))


def _collect_stub_vars(expr: Any, stub_vars: dict[str, dict[str, Any]], *, free_kvar_ids: set[str] | None = None) -> None:
    if not isinstance(expr, dict):
        return
    free_kvar_ids = free_kvar_ids or set()
    var = expr.get("var")
    # VAR_KEY_* stubs removed: without lexicon.key_derivations the branch is KEY_DERIVATION_MISSING.
    if isinstance(var, str) and var.startswith("VAR_KVAR_") and var not in stub_vars and var not in free_kvar_ids:
        stub_vars[var] = _derived(
            var,
            "int",
            [0, 1],
            _ite({"op": "ge", "var": csv_var("B"), "value": 0}, 0, 0),
            f"stub kvar {var} (default 0; refine via /tg-csv-contract)",
        )
    for key in ("arg", "lhs", "rhs", "condition", "then", "else", "expr"):
        child = expr.get(key)
        if isinstance(child, dict):
            _collect_stub_vars(child, stub_vars, free_kvar_ids=free_kvar_ids)
    for child in expr.get("args") or []:
        _collect_stub_vars(child, stub_vars, free_kvar_ids=free_kvar_ids)


def _collect_free_csv_vars(expr: Any, free_csv_vars: dict[str, dict[str, Any]], ctx: BindContext) -> None:
    """Register free CSV solver vars referenced by bound exprs (from UO set_by.csv + consumer evidence)."""
    for var_id in collect_var_ids_from_expr(expr):
        if not var_id.startswith("VAR_CSV_") or var_id in free_csv_vars:
            continue
        column = var_id[len("VAR_CSV_") :]
        # Do not invent CSV columns: require consumer schema evidence when columns are known.
        if ctx.csv_columns and column not in ctx.csv_columns:
            continue
        # Prefer domain from kvar that maps to this column.
        domain: list[Any] = [0, 1, 2, 4, 8, 16, 32, 64, 128, 256]
        for kvar in ctx.kvar_by_name.values():
            if not isinstance(kvar, dict):
                continue
            set_by = kvar.get("set_by") if isinstance(kvar.get("set_by"), dict) else {}
            if str(set_by.get("csv") or "") == column:
                values = kvar.get("domain")
                if isinstance(values, list) and values:
                    ints = []
                    for item in values:
                        try:
                            ints.append(int(item))
                        except (TypeError, ValueError):
                            continue
                    if ints:
                        domain = sorted(dict.fromkeys(ints))
                break
        free_csv_vars[var_id] = {
            "id": var_id,
            "column": column,
            "type": "int",
            "domain": domain,
            "default": domain[0],
            "free": True,
            "source_refs": [{"path": "branch_align.free_csv", "column": column}],
        }


def _iter_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [{"id": str(key), **item} if isinstance(item, dict) else {"id": str(key), "value": item} for key, item in sorted(value.items())]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []
