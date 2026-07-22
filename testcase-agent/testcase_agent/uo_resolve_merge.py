"""Merge uo_query_resolve/*.yaml into binding_lexicon + domain symmetry checks."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .binding_lexicon import merge_lexicons, normalize_lexicon
from .io import read_yaml, write_yaml
from .realization_validation import _is_constant_fixed_expr
from .resolve_policy import (
    is_empty_allowlisted,
    is_fake_not_csv_excuse,
    is_legitimate_skip,
    require_chains_terminate_at_csv,
    require_high_only,
    require_no_nonempty_unresolved,
    require_no_placeholders,
    validate_resolved_doc,
    write_mid_symbol_queue,
)


PLACEHOLDER_STRINGS = {
    "deter_branch",
    "non_deter_branch",
    "already_bound_in_kb",
    "already_bound",
    "unknown",
    "unspecified",
    "todo",
    "placeholder",
}


class UoMergeError(RuntimeError):
    def __init__(self, message: str, *, ask: str = "uo_merge_required", report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.ask = ask
        self.report = report or {}


def merge_uo_resolve(out_root: Path, *, auto_fix_heuristics: bool = True) -> dict[str, Any]:
    """Merge KEY resolve YAMLs into lexicon; align domains; write uo_merge_report.yaml."""
    out_root = Path(out_root)
    realization = out_root / "realization"
    resolve_dir = realization / "uo_query_resolve"
    lexicon_path = realization / "binding_lexicon.yaml"
    map_path = realization / "realization_map.yaml"
    review_path = realization / "domain_review.yaml"
    hints_path = realization / "domain_hints.yaml"

    lexicon = normalize_lexicon(read_yaml(lexicon_path) if lexicon_path.is_file() else {})
    rmap = read_yaml(map_path) if map_path.is_file() else {}
    if not isinstance(rmap, dict):
        rmap = {}
    review = read_yaml(review_path) if review_path.is_file() else {}
    hints = read_yaml(hints_path) if hints_path.is_file() else {}

    domain_align = align_domains_from_review(rmap, review, hints if isinstance(hints, dict) else {})
    if domain_align["updated"] and map_path.parent.is_dir():
        write_yaml(map_path, rmap)

    domains = build_effective_domains(rmap, review, hints if isinstance(hints, dict) else {})

    resolved_files = sorted(resolve_dir.glob("KEY_*.yaml")) if resolve_dir.is_dir() else []
    merged_derivs: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    asymmetry: list[dict[str, Any]] = []

    for path in resolved_files:
        doc = read_yaml(path)
        if not isinstance(doc, dict):
            rejected.append({"file": path.name, "reason": "invalid_yaml"})
            continue
        key_id = str(doc.get("key_id") or path.stem)
        status = str(doc.get("status") or doc.get("confidence") or "").lower()
        kd = doc.get("key_derivation")
        if not isinstance(kd, dict):
            kd = {}
        expr = kd.get("expr") if "expr" in kd else doc.get("expr")
        var_id = str(kd.get("id") or f"VAR_{key_id}" if key_id.startswith("KEY_") else f"VAR_KEY_{key_id.removeprefix('KEY_')}")
        if not var_id.startswith("VAR_"):
            var_id = f"VAR_{var_id}"

        if status in {"unresolved", "needs_human", "not_csv_realizable"} or doc.get("not_csv_realizable") is True:
            legit = is_legitimate_skip(key_id, doc)
            fake = is_fake_not_csv_excuse({**doc, "key_id": key_id})
            entry = {
                "key_id": key_id,
                "var_id": var_id,
                "file": path.name,
                "status": status or "unresolved",
                "empty_allowlisted": is_empty_allowlisted(key_id, doc),
                "legitimate_skip": legit,
                "fake_not_csv_excuse": fake,
                "skip_reason": doc.get("skip_reason") or "",
                "unresolved_reason": doc.get("unresolved_reason") or "",
            }
            unresolved.append(entry)
            if fake:
                rejected.append(
                    {
                        "key_id": key_id,
                        "var_id": var_id,
                        "file": path.name,
                        "reason": f"fake_not_csv_excuse:{entry['skip_reason'] or entry['unresolved_reason'] or 'not_csv_realizable'}",
                        "ask": "fake_not_csv_excuse",
                    }
                )
            # Keep null expr entry so inventory knows it's intentionally open.
            merged_derivs.append(
                {
                    "id": var_id,
                    "type": kd.get("type") or "int",
                    "domain": kd.get("domain") or [0, 1],
                    "expr": None,
                    "rationale": doc.get("rationale") or "uo_query unresolved",
                    "source_refs": [{"path": f"uo_query_resolve/{path.name}", "kind": "uo_query"}],
                    "locked": False,
                    "status": "unresolved",
                    "not_csv_realizable": bool(legit),
                }
            )
            continue

        # HARD: high-only + chain→CSV + no opaque Host fn leaves
        gate_ok, gate_ask, gate_reason = validate_resolved_doc(doc, key_id=key_id, key_var=var_id)
        if not gate_ok:
            rejected.append(
                {
                    "key_id": key_id,
                    "var_id": var_id,
                    "file": path.name,
                    "reason": gate_reason,
                    "ask": gate_ask,
                }
            )
            continue

        ok, reason = validate_derivation_expr(expr, domains)
        if not ok:
            if auto_fix_heuristics and reason.startswith("domain_asymmetry"):
                fixed = try_fix_heuristic_expr(expr, domains)
                if fixed is not None:
                    expr = fixed
                    ok, reason = validate_derivation_expr(expr, domains)
            if not ok:
                asymmetry.append({"key_id": key_id, "var_id": var_id, "file": path.name, "reason": reason})
                rejected.append({"key_id": key_id, "var_id": var_id, "file": path.name, "reason": reason})
                continue

        item = {
            "id": var_id,
            "type": kd.get("type") or "int",
            "domain": kd.get("domain") or [0, 1],
            "expr": expr,
            "rationale": doc.get("rationale") or kd.get("rationale") or f"merged from {path.name}",
            "source_refs": [{"path": f"uo_query_resolve/{path.name}", "kind": "uo_query", "confidence": doc.get("confidence")}],
            # High-confidence uo-query merge is SMT-ready; plan gates treat locked|reviewed+high as bound.
            "locked": True,
            "status": "reviewed",
            "shape_expr": doc.get("shape_expr") or "",
            "shape_determined": doc.get("shape_determined") or [],
            "derivation_chain": doc.get("derivation_chain") or [],
            "confidence": "high",
        }
        merged_derivs.append(item)

    # Also scrub existing lexicon derivations for domain asymmetry / placeholders.
    scrubbed: list[dict[str, Any]] = []
    for item in lexicon.get("key_derivations") or []:
        if not isinstance(item, dict):
            continue
        vid = str(item.get("id") or "")
        # Prefer uo-merged ids
        if any(str(m.get("id")) == vid for m in merged_derivs):
            continue
        expr = item.get("expr")
        ok, reason = validate_derivation_expr(expr, domains)
        if not ok and auto_fix_heuristics and reason.startswith("domain_asymmetry"):
            fixed = try_fix_heuristic_expr(expr, domains)
            if fixed is not None:
                item = {**item, "expr": fixed, "status": item.get("status") or "proposed", "rationale": (item.get("rationale") or "") + " [auto-fixed domain sentinel]"}
                ok, reason = validate_derivation_expr(item.get("expr"), domains)
        if not ok:
            asymmetry.append({"var_id": vid, "reason": reason, "source": "existing_lexicon"})
            if auto_fix_heuristics:
                scrubbed.append(
                    {
                        **item,
                        "expr": None,
                        "status": "unresolved",
                        "not_csv_realizable": True,
                        "rationale": (item.get("rationale") or "") + f" [nulled: {reason}]",
                    }
                )
            else:
                rejected.append({"var_id": vid, "reason": reason, "source": "existing_lexicon"})
            continue
        scrubbed.append(item)

    patch = normalize_lexicon(
        {
            "version": 1,
            "source": "uo_query_resolve_merge",
            "key_derivations": merged_derivs + scrubbed,
            "warnings": [],
        }
    )
    merged = merge_lexicons(lexicon, patch)
    merged["source"] = "uo_query_resolve_merge+" + str(lexicon.get("source") or "")
    write_yaml(lexicon_path, merged)

    # Clear hard KEY↔CSV gaps that now have locked/reviewed+high lexicon entries.
    _sync_binding_gaps_after_merge(out_root, merged)

    # Sync bind key_shape_conditions; shape_determined comes from derivation closure.
    _write_bind_from_resolve(out_root, resolved_files)

    from .shape_derivation import build_and_write_shape_derivation, rebuild_branch_alignment

    shape_graph = build_and_write_shape_derivation(
        out_root,
        lexicon=merged,
        rmap=rmap,
        resolve_files=resolved_files,
    )
    alignment_rebuild = rebuild_branch_alignment(out_root)

    hard_asymmetry = [a for a in asymmetry if "nulled" not in str(a.get("reason") or "")]
    # Fail when resolved files were rejected OR nonempty KEY left unresolved
    key_rejects = [r for r in rejected if r.get("file")]
    nonempty_unresolved = [
        u for u in unresolved if not u.get("empty_allowlisted") and not u.get("legitimate_skip")
    ]
    gate_ask = ""
    if key_rejects:
        asks = {str(r.get("ask") or "") for r in key_rejects if r.get("ask")}
        if "fake_not_csv_excuse" in asks:
            gate_ask = "fake_not_csv_excuse"
        elif "confidence_not_high" in asks:
            gate_ask = "confidence_not_high"
        elif "opaque_fn_leaf" in asks:
            gate_ask = "opaque_fn_leaf"
        elif "shape_closure_incomplete" in asks:
            gate_ask = "shape_closure_incomplete"
        elif "placeholder_expr" in asks:
            gate_ask = "placeholder_expr"
        elif asymmetry:
            gate_ask = "domain_asymmetry"
        else:
            gate_ask = "uo_merge_required"
    elif nonempty_unresolved:
        if any(u.get("fake_not_csv_excuse") for u in nonempty_unresolved):
            gate_ask = "fake_not_csv_excuse"
        else:
            gate_ask = "key_unresolved"

    passed = len(key_rejects) == 0 and len(nonempty_unresolved) == 0

    # Closure must be non-empty when any KEY resolved
    resolved_count = sum(1 for m in merged_derivs if m.get("expr") is not None and m.get("status") != "unresolved")
    if passed and resolved_count > 0 and not (shape_graph.get("closure") or []):
        passed = False
        gate_ask = "shape_closure_incomplete"
        rejected.append({"reason": "empty_shape_closure_with_resolved_keys", "ask": gate_ask})

    mid_queue = write_mid_symbol_queue(out_root)
    placeholder_gate = require_no_placeholders(out_root)
    if passed and placeholder_gate.get("status") == "fail":
        passed = False
        gate_ask = "placeholder_expr"
        rejected.append({"reason": "placeholder_expr", "ask": gate_ask, "issues": placeholder_gate.get("issues")})

    # After KEY merge: open mids are expected → do not fail merge; parent must spawn Tasks.
    # Fail only when placeholders / rejects already set; full closure checked by --verify-csv-closure / confirm.
    report = {
        "version": 1,
        "status": "pass" if passed else "fail",
        "updated_at": _now(),
        "resolve_files": len(resolved_files),
        "merged_count": len(merged_derivs),
        "unresolved": unresolved,
        "nonempty_unresolved": nonempty_unresolved,
        "rejected": rejected,
        "domain_asymmetry": asymmetry,
        "domain_align": domain_align,
        "shape_derivation": {
            "roots": len(shape_graph.get("roots") or []),
            "closure": len(shape_graph.get("closure") or []),
            "edges": len(shape_graph.get("edges") or []),
        },
        "alignment_rebuild": {
            "status": alignment_rebuild.get("status"),
            "mapped": alignment_rebuild.get("mapped"),
            "abstract": alignment_rebuild.get("abstract"),
            "reason": alignment_rebuild.get("reason"),
        },
        "mid_symbol_queue": {
            "count": len(mid_queue.get("symbols") or []),
            "symbols": [s.get("name") for s in (mid_queue.get("symbols") or [])[:16]],
            "path": mid_queue.get("path"),
        },
        "gates": {
            "high_only": require_high_only(out_root),
            "chain_to_csv": require_chains_terminate_at_csv(out_root),
            "nonempty_unresolved": require_no_nonempty_unresolved(out_root),
            "no_placeholders": placeholder_gate,
        },
        "ask": "" if passed else (gate_ask or ("domain_asymmetry" if hard_asymmetry else "uo_merge_required")),
        "next": (
            (
                "PARENT: auto-spawn Task Follow uo-query per mid_symbol_queue "
                f"({len(mid_queue.get('symbols') or [])} open) → --merge-uo-resolve → --verify-csv-closure "
                "(do NOT ask user to open Tasks)"
                if mid_queue.get("symbols")
                else "PARENT: --verify-csv-closure → tg-init-audit → --confirm"
            )
            if passed
            else (
                "PARENT: fake not_csv excuses banned — write LogicExpr (cross-var ok) + nested mid Tasks; "
                "do NOT ask user / do NOT mark cross_variable_comparison_not_csv_realizable"
                if gate_ask == "fake_not_csv_excuse"
                else "PARENT: fix KEY resolve (high + chain→CSV + nested mid Tasks); do not ask user"
            )
        ),
    }
    write_yaml(realization / "uo_merge_report.yaml", report)
    if not passed:
        raise UoMergeError(
            f"uo merge failed: rejects={len(key_rejects)} nonempty_unresolved={len(nonempty_unresolved)}",
            ask=str(report.get("ask") or "uo_merge_required"),
            report=report,
        )
    return report


def require_merge_pass(out_root: Path) -> dict[str, Any]:
    path = Path(out_root) / "realization" / "uo_merge_report.yaml"
    if not path.is_file():
        raise UoMergeError(
            "Missing realization/uo_merge_report.yaml. Run tg-init --merge-uo-resolve first.",
            ask="uo_merge_required",
        )
    report = read_yaml(path)
    if not isinstance(report, dict) or str(report.get("status") or "").lower() != "pass":
        raise UoMergeError(
            "uo_merge_report.status != pass. Re-run tg-init --merge-uo-resolve.",
            ask=str((report or {}).get("ask") or "uo_merge_required") if isinstance(report, dict) else "uo_merge_required",
            report=report if isinstance(report, dict) else {},
        )
    return report


def _sync_binding_gaps_after_merge(out_root: Path, lexicon: dict[str, Any]) -> None:
    """Drop hard binding_gaps whose variable_id is now bound (locked or reviewed+high)."""
    unresolved_path = Path(out_root) / "realization" / "unresolved.yaml"
    if not unresolved_path.is_file():
        return
    doc = read_yaml(unresolved_path)
    if not isinstance(doc, dict):
        return
    bound = _bound_lexicon_ids(lexicon)
    gaps = [g for g in (doc.get("binding_gaps") or []) if isinstance(g, dict)]
    if not gaps:
        return
    kept: list[dict[str, Any]] = []
    cleared = 0
    for gap in gaps:
        code = str(gap.get("code") or "")
        vid = str(gap.get("variable_id") or gap.get("id") or "")
        if code in {"MISSING_CSV_REF", "UNBOUND_KEY"} and vid and vid in bound:
            cleared += 1
            continue
        kept.append(gap)
    if cleared:
        doc["binding_gaps"] = kept
        doc["binding_gaps_cleared_by_merge"] = cleared
        write_yaml(unresolved_path, doc)


def _bound_lexicon_ids(lexicon: dict[str, Any]) -> set[str]:
    bound: set[str] = set()
    for item in lexicon.get("key_derivations") or []:
        if not isinstance(item, dict):
            continue
        if item.get("expr") is None:
            continue
        status = str(item.get("status") or "").lower()
        conf = str(item.get("confidence") or "").lower()
        if item.get("locked") or status in {"reviewed", "confirmed", "locked"} or conf == "high":
            vid = str(item.get("id") or "")
            if vid:
                bound.add(vid)
    return bound


def require_domain_symmetry(out_root: Path) -> dict[str, Any]:
    """Validate lexicon exprs against effective domains (solve/confirm gate)."""
    out_root = Path(out_root)
    realization = out_root / "realization"
    lexicon = read_yaml(realization / "binding_lexicon.yaml") if (realization / "binding_lexicon.yaml").is_file() else {}
    rmap = read_yaml(realization / "realization_map.yaml") if (realization / "realization_map.yaml").is_file() else {}
    review = read_yaml(realization / "domain_review.yaml") if (realization / "domain_review.yaml").is_file() else {}
    hints = read_yaml(realization / "domain_hints.yaml") if (realization / "domain_hints.yaml").is_file() else {}
    if not isinstance(lexicon, dict):
        lexicon = {}
    if not isinstance(rmap, dict):
        rmap = {}
    domains = build_effective_domains(rmap, review if isinstance(review, dict) else {}, hints if isinstance(hints, dict) else {})
    issues: list[dict[str, Any]] = []
    for item in lexicon.get("key_derivations") or []:
        if not isinstance(item, dict):
            continue
        if item.get("expr") is None:
            continue
        ok, reason = validate_derivation_expr(item.get("expr"), domains)
        if not ok:
            issues.append({"id": item.get("id"), "reason": reason})
    report = {"status": "pass" if not issues else "fail", "issues": issues, "checked_at": _now()}
    write_yaml(realization / "domain_symmetry_report.yaml", report)
    if issues:
        raise UoMergeError(
            f"Domain asymmetry: {len(issues)} derivation(s) reference out-of-domain literals",
            ask="domain_asymmetry",
            report=report,
        )
    return report


def validate_derivation_expr(expr: Any, domains: dict[str, Any]) -> tuple[bool, str]:
    if expr is None:
        return False, "null_expr"
    if not isinstance(expr, dict):
        return False, "expr_not_dict"
    if _is_constant_fixed_expr(expr):
        return False, "then_equals_else"
    if _has_placeholder(expr):
        return False, "placeholder_literal"
    bad = _find_out_of_domain(expr, domains)
    if bad:
        return False, f"domain_asymmetry:{bad}"
    return True, ""


def try_fix_heuristic_expr(expr: Any, domains: dict[str, Any]) -> dict[str, Any] | None:
    """Rewrite eq(var, 0) when 0 not in domain → eq(var, sentinel) keeping then/else."""
    if not isinstance(expr, dict):
        return None
    if expr.get("op") != "if_then_else":
        return None
    cond = expr.get("condition")
    if not isinstance(cond, dict) or cond.get("op") != "eq":
        return None
    var = str(cond.get("var") or "")
    val = cond.get("value")
    if val not in (0, 0.0, "0"):
        return None
    sentinel = domain_sentinel(var, domains)
    if sentinel is None:
        return None
    fixed = {
        **expr,
        "condition": {**cond, "value": sentinel},
    }
    return fixed


def domain_sentinel(var_id: str, domains: dict[str, Any]) -> Any | None:
    spec = domains.get(var_id)
    if not spec:
        # try without prefix
        return None
    kind = spec.get("kind")
    if kind == "values":
        values = list(spec.get("values") or [])
        if not values:
            return None
        # Prefer 1.0 for keep_prob-like, else first value
        for cand in (1.0, 1, "1.0", "1"):
            if cand in values:
                return cand
        return values[0]
    if kind == "range":
        return spec.get("min", 1)
    return None


def build_effective_domains(
    realization_map: dict[str, Any],
    domain_review: dict[str, Any],
    domain_hints: dict[str, Any],
) -> dict[str, Any]:
    """var_id -> {kind: values|range, values|min|max}."""
    out: dict[str, Any] = {}
    for item in realization_map.get("csv_variables") or []:
        if not isinstance(item, dict):
            continue
        vid = str(item.get("id") or "")
        if not vid:
            col = str(item.get("column") or item.get("name") or "")
            vid = f"VAR_CSV_{col}" if col else ""
        if not vid:
            continue
        out[vid] = _normalize_domain_spec(item.get("domain"))
    # Overlay domain_review columns
    for col in domain_review.get("columns") or []:
        if not isinstance(col, dict):
            continue
        name = str(col.get("name") or "")
        if not name:
            continue
        vid = f"VAR_CSV_{name}"
        proposed = col.get("proposed_domain")
        if proposed is not None:
            out[vid] = _normalize_domain_spec(proposed)
    # Overlay hints
    columns = domain_hints.get("columns") if isinstance(domain_hints.get("columns"), dict) else domain_hints
    if isinstance(columns, dict):
        for name, spec in columns.items():
            if not isinstance(spec, dict):
                continue
            vid = f"VAR_CSV_{name}" if not str(name).startswith("VAR_") else str(name)
            dom = spec.get("domain") or spec.get("proposed_domain") or spec
            out[vid] = _normalize_domain_spec(dom)
    return {k: v for k, v in out.items() if v}


def align_domains_from_review(
    realization_map: dict[str, Any],
    domain_review: dict[str, Any],
    domain_hints: dict[str, Any],
) -> dict[str, Any]:
    """Rewrite csv_variables domains that are stub [NONE] when review has a real domain."""
    updated: list[str] = []
    by_col: dict[str, Any] = {}
    for col in domain_review.get("columns") or []:
        if isinstance(col, dict) and col.get("name"):
            by_col[str(col["name"])] = col.get("proposed_domain")
    hints_cols = domain_hints.get("columns") if isinstance(domain_hints.get("columns"), dict) else {}
    for item in realization_map.get("csv_variables") or []:
        if not isinstance(item, dict):
            continue
        col = str(item.get("column") or item.get("name") or "")
        vid = str(item.get("id") or "")
        proposed = by_col.get(col)
        if proposed is None and isinstance(hints_cols, dict):
            hint = hints_cols.get(col) or hints_cols.get(vid)
            if isinstance(hint, dict):
                proposed = hint.get("domain") or hint.get("proposed_domain")
        if proposed is None:
            continue
        current = item.get("domain")
        if _is_stub_domain(current) and not _is_stub_domain(proposed):
            item["domain"] = _materialize_domain(proposed)
            if isinstance(proposed, dict) and proposed.get("kind") == "range":
                item["type"] = item.get("type") or "int"
            elif _looks_float_domain(proposed):
                item["type"] = "float"
            updated.append(vid or col)
    return {"updated": updated, "count": len(updated)}


def value_in_domain(value: Any, spec: dict[str, Any] | None) -> bool:
    if not spec:
        return True
    if spec.get("kind") == "values":
        values = list(spec.get("values") or [])
        if value in values:
            return True
        # soft numeric equality for floats
        try:
            fv = float(value)
            return any(_num_eq(fv, v) for v in values)
        except (TypeError, ValueError):
            return str(value) in {str(v) for v in values}
    if spec.get("kind") == "range":
        try:
            num = float(value)
        except (TypeError, ValueError):
            return False
        lo = spec.get("min")
        hi = spec.get("max")
        if lo is not None and num < float(lo):
            return False
        if hi is not None and num > float(hi):
            return False
        return True
    return True


def _normalize_domain_spec(domain: Any) -> dict[str, Any] | None:
    if domain is None:
        return None
    if isinstance(domain, list):
        if not domain:
            return None
        return {"kind": "values", "values": list(domain)}
    if isinstance(domain, dict):
        if domain.get("kind") == "range" or ("min" in domain and "max" in domain):
            return {"kind": "range", "min": domain.get("min"), "max": domain.get("max")}
        if "values" in domain:
            return {"kind": "values", "values": list(domain.get("values") or [])}
        if domain.get("kind") == "values":
            return {"kind": "values", "values": list(domain.get("values") or [])}
    return None


def _materialize_domain(proposed: Any) -> Any:
    if isinstance(proposed, dict) and (proposed.get("kind") == "range" or ("min" in proposed and "max" in proposed)):
        return {"kind": "range", "min": proposed.get("min"), "max": proposed.get("max")}
    if isinstance(proposed, dict) and "values" in proposed:
        return list(proposed.get("values") or [])
    return proposed


def _is_stub_domain(domain: Any) -> bool:
    if domain is None:
        return True
    if domain == ["NONE"] or domain == ["None"] or domain == [""]:
        return True
    if isinstance(domain, list) and len(domain) == 1 and str(domain[0]).upper() in {"NONE", "NULL", ""}:
        return True
    if isinstance(domain, dict):
        values = domain.get("values")
        if isinstance(values, list) and len(values) == 1 and str(values[0]).upper() in {"NONE", "NULL", ""}:
            return True
    return False


def _looks_float_domain(proposed: Any) -> bool:
    values = proposed if isinstance(proposed, list) else (proposed.get("values") if isinstance(proposed, dict) else None)
    if not isinstance(values, list) or not values:
        return False
    return all(isinstance(v, float) or (isinstance(v, (int, str)) and _is_float_str(v)) for v in values)


def _is_float_str(v: Any) -> bool:
    try:
        float(v)
        return "." in str(v) or isinstance(v, float)
    except (TypeError, ValueError):
        return False


def _num_eq(a: float, b: Any) -> bool:
    try:
        return abs(a - float(b)) < 1e-9
    except (TypeError, ValueError):
        return False


def _has_placeholder(expr: Any) -> bool:
    if isinstance(expr, str) and expr.strip().lower() in PLACEHOLDER_STRINGS:
        return True
    if isinstance(expr, dict):
        for key in ("then", "else", "value"):
            if _has_placeholder(expr.get(key)):
                return True
        for key in ("args", "values"):
            for child in expr.get(key) or []:
                if _has_placeholder(child):
                    return True
        for key in ("condition", "arg", "lhs", "rhs", "expr"):
            if _has_placeholder(expr.get(key)):
                return True
    return False


def _find_out_of_domain(expr: Any, domains: dict[str, Any]) -> str:
    if not isinstance(expr, dict):
        return ""
    op = str(expr.get("op") or "")
    if op in {"eq", "ne", "lt", "le", "gt", "ge"}:
        var = str(expr.get("var") or "")
        if var and "value" in expr:
            if not value_in_domain(expr.get("value"), domains.get(var)):
                return f"{var}={expr.get('value')!r}"
        for side in ("lhs", "rhs"):
            child = expr.get(side)
            if isinstance(child, dict) and "var" in child and "value" in expr and side == "lhs":
                pass
            bad = _find_out_of_domain(child, domains) if isinstance(child, (dict, list)) else ""
            if bad:
                return bad
    if op in {"in", "not_in"}:
        var = str(expr.get("var") or "")
        for value in expr.get("values") or []:
            if var and not value_in_domain(value, domains.get(var)):
                return f"{var}={value!r}"
    for key in ("condition", "then", "else", "arg", "lhs", "rhs", "expr", "antecedent", "consequent"):
        child = expr.get(key)
        if isinstance(child, dict):
            bad = _find_out_of_domain(child, domains)
            if bad:
                return bad
    for key in ("args", "values"):
        for child in expr.get(key) or []:
            if isinstance(child, dict):
                bad = _find_out_of_domain(child, domains)
                if bad:
                    return bad
    return ""


def _write_bind_from_resolve(out_root: Path, resolve_files: list[Path]) -> None:
    """Write key_shape_conditions only; shape_determined is owned by shape_derivation closure."""
    bind = out_root / "bind"
    bind.mkdir(parents=True, exist_ok=True)
    keys: list[dict[str, Any]] = []
    for path in resolve_files:
        doc = read_yaml(path)
        if not isinstance(doc, dict):
            continue
        key_id = str(doc.get("key_id") or path.stem)
        keys.append(
            {
                "key_id": key_id,
                "shape_expr": doc.get("shape_expr") or "",
                "shape_determined": doc.get("shape_determined") or [],
                "derivation_chain": doc.get("derivation_chain") or [],
                "csv_bindings": doc.get("csv_bindings") or [],
                "confidence": doc.get("confidence") or "unknown",
                "needs_uo_query": False,
                "status": doc.get("status") or "resolved",
            }
        )
    write_yaml(
        bind / "key_shape_conditions.yaml",
        {"version": 1, "status": "merged", "keys": keys, "source": "uo_query_resolve"},
    )


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
