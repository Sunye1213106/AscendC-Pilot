"""Validation for source-lemma certificates that are allowed to populate E."""

from __future__ import annotations

from typing import Any, Mapping


_SCOPE_FIELDS = ("target_dimensions", "relevant_functions", "assignments", "guards")
_EVIDENCE_FIELDS = (
    "assignment_sites_complete",
    "call_closure_complete",
    "alias_state_exact",
    "macro_context_complete",
)


def validate(raw: Mapping[str, Any]) -> dict[str, Any]:
    certificate = raw.get("certificate")
    if not isinstance(certificate, Mapping):
        return {"ok": False, "status": "needs_evidence", "errors": ["certificate_missing"]}
    errors: list[str] = []
    scope = certificate.get("proof_scope")
    if not isinstance(scope, Mapping):
        errors.append("proof_scope_missing")
    else:
        for field in _SCOPE_FIELDS:
            value = scope.get(field)
            if value is None or value == "" or value == []:
                errors.append(f"proof_scope.{field}_missing")
    assumptions = certificate.get("assumptions")
    if not isinstance(assumptions, list):
        errors.append("assumptions_not_list")
    completeness = certificate.get("completeness_evidence")
    if not isinstance(completeness, Mapping):
        errors.append("completeness_evidence_missing")
    else:
        for field in _EVIDENCE_FIELDS:
            if completeness.get(field) is not True:
                errors.append(f"completeness_evidence.{field}_not_true")
    strategy = certificate.get("counterexample_strategy")
    if not isinstance(strategy, Mapping) or not strategy:
        errors.append("counterexample_strategy_missing")
    return {
        "ok": not errors,
        "status": "active_eligible" if not errors else "needs_evidence",
        "errors": errors,
    }
