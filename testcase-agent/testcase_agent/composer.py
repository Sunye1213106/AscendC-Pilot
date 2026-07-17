from __future__ import annotations

from typing import Any

from .constraint_ir import normalize_expr, ConstraintIRError
from .extract import legal_exprs


def compose_global_legal(extract_doc: dict[str, Any] | None, human_supplement: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build GlobalLegal constraint list: AND of role=legal conditions + human supplements.

    implies/requires are preserved as true implication (not rewritten to AND).
    """
    constraints: list[dict[str, Any]] = []
    extract_doc = extract_doc if isinstance(extract_doc, dict) else {}
    for idx, expr in enumerate(legal_exprs(extract_doc), start=1):
        constraints.append(
            {
                "id": f"COMPOSED_LEGAL_{idx:03d}",
                "kind": "composed_legal",
                "expr": _ensure_true_implication(expr),
                "source": "extract.generation_conditions",
                "tags": ["global_legal"],
            }
        )
    human_supplement = human_supplement if isinstance(human_supplement, dict) else {}
    for idx, spec in enumerate(human_supplement.get("constraints") or [], start=1):
        if not isinstance(spec, dict):
            continue
        try:
            expr = normalize_expr(spec.get("expr") if "expr" in spec else spec)
        except ConstraintIRError:
            continue
        constraints.append(
            {
                "id": str(spec.get("id") or f"HUMAN_LEGAL_{idx:03d}"),
                "kind": "human_supplement",
                "expr": _ensure_true_implication(expr),
                "source": "plan/human_supplement.yaml",
                "tags": ["global_legal", "human"],
            }
        )
    return constraints


def merge_composed_into_ir(ir: dict[str, Any], composed: list[dict[str, Any]]) -> dict[str, Any]:
    out = dict(ir)
    existing = [item for item in out.get("constraints") or [] if isinstance(item, dict)]
    # Avoid duplicate ids
    seen = {str(item.get("id")) for item in existing}
    for item in composed:
        cid = str(item.get("id"))
        if cid in seen:
            continue
        existing.append(item)
        seen.add(cid)
    out["constraints"] = sorted(existing, key=lambda item: str(item.get("id")))
    return out


def _ensure_true_implication(expr: dict[str, Any]) -> dict[str, Any]:
    """Normalize implies/requires nodes; leave coverage-witness AND elsewhere untouched."""
    if not isinstance(expr, dict):
        return expr
    op = str(expr.get("op") or "")
    if op in {"implies", "requires"}:
        return {
            "op": "implies",
            "antecedent": _ensure_true_implication(expr.get("antecedent") or {}),
            "consequent": _ensure_true_implication(expr.get("consequent") or {}),
        }
    if op in {"and", "or", "mutex"}:
        args = expr.get("args") or []
        return {**expr, "args": [_ensure_true_implication(arg) if isinstance(arg, dict) else arg for arg in args]}
    if op == "not":
        arg = expr.get("arg")
        return {**expr, "arg": _ensure_true_implication(arg) if isinstance(arg, dict) else arg}
    return expr
