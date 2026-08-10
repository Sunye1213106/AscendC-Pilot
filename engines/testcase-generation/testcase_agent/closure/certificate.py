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


def _collect_evidence_ids(raw: Mapping[str, Any], certificate: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for src in (
        certificate.get("evidence_entry_ids"),
        (raw.get("proof") or {}).get("evidence_entry_ids") if isinstance(raw.get("proof"), Mapping) else None,
        raw.get("evidence_entry_ids"),
    ):
        if isinstance(src, list):
            ids.extend(str(x) for x in src if x)
    return ids


def validate(raw: Mapping[str, Any], *, evidence_pack: Mapping[str, Any] | None = None) -> dict[str, Any]:
    certificate = raw.get("certificate")
    if not isinstance(certificate, Mapping):
        return {"ok": False, "status": "needs_evidence", "errors": ["certificate_missing"]}
    errors: list[str] = []
    warnings: list[str] = []
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

    # Soft: when an evidence pack is present, proof-check fields should cite
    # evidence entry IDs. Without a pack this stays advisory.
    cited = _collect_evidence_ids(raw, certificate)
    pack_ids: set[str] = set()
    if evidence_pack and isinstance(evidence_pack, Mapping):
        for e in evidence_pack.get("entries") or []:
            if isinstance(e, Mapping) and e.get("id"):
                pack_ids.add(str(e["id"]))
    if pack_ids:
        if not cited:
            # Pack present → fill-in required; skip/reject without entry IDs.
            errors.append("evidence_entry_ids_missing_while_pack_present")
        else:
            unknown = [i for i in cited if i not in pack_ids]
            if unknown:
                bad = ",".join(unknown[:5])
                errors.append(f"evidence_entry_ids_unknown:{bad}")
    elif cited:
        # Citations without a pack are fine; pack may live on disk separately.
        pass
    else:
        # Soft hint for review templates that expect IDs once lemma-evidence ran.
        proof = raw.get("proof") if isinstance(raw.get("proof"), Mapping) else {}
        if proof and not cited:
            warnings.append("proof_missing_evidence_entry_ids")

    return {
        "ok": not errors,
        "status": "active_eligible" if not errors else "needs_evidence",
        "errors": errors,
        "warnings": warnings,
        "evidence_entry_ids": cited,
    }
