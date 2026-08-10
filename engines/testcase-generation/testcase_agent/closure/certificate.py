"""Validation for source-lemma certificates that are allowed to populate E."""

from __future__ import annotations

from pathlib import Path
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


def _source_refs(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Gather file:line citations from every place a producer may put them."""
    refs: list[dict[str, Any]] = []
    cert = raw.get("certificate") if isinstance(raw.get("certificate"), Mapping) else {}
    scope = cert.get("proof_scope") if isinstance(cert.get("proof_scope"), Mapping) else {}
    for src in (
        raw.get("source_refs"),
        raw.get("source_citations"),
        cert.get("source_refs"),
        scope.get("assignments"),
        scope.get("guards"),
    ):
        if not isinstance(src, list):
            continue
        for item in src:
            if isinstance(item, Mapping):
                refs.append(dict(item))
            elif isinstance(item, str) and item.strip():
                # "path/to/file.cpp:123" form used by proof_scope.assignments
                path, _, line = item.partition(":")
                refs.append({"file": path, "line": line or ""})
    return refs


def live_source_refs(
    raw: Mapping[str, Any],
    *,
    roots: list[Path] | None = None,
) -> list[dict[str, Any]]:
    """Subset of citations whose file exists under one of ``roots`` (or absolute)."""
    live: list[dict[str, Any]] = []
    for ref in _source_refs(raw):
        f = str(ref.get("file") or ref.get("path") or "").strip()
        if not f:
            continue
        p = Path(f)
        if p.is_file():
            live.append(ref)
            continue
        for root in roots or []:
            cand = root / f
            if cand.is_file():
                live.append({**ref, "file": str(cand)})
                break
    return live


def validate(
    raw: Mapping[str, Any],
    *,
    evidence_pack: Mapping[str, Any] | None = None,
    operator_root: Path | str | None = None,
) -> dict[str, Any]:
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
            errors.append("evidence_entry_ids_missing_while_pack_present")
        else:
            unknown = [i for i in cited if i not in pack_ids]
            if unknown:
                bad = ",".join(unknown[:5])
                errors.append(f"evidence_entry_ids_unknown:{bad}")
    elif cited:
        pass
    else:
        proof = raw.get("proof") if isinstance(raw.get("proof"), Mapping) else {}
        if proof and not cited:
            warnings.append("proof_missing_evidence_entry_ids")

    # Hint families are hypotheses about a previous operator run. Promote only
    # when this run's source is cited with a file that still exists.
    origin = str(raw.get("origin") or raw.get("from") or "").strip().lower()
    from_hint = origin in {"hint", "hint_family", "hint_families"} or bool(
        raw.get("from_hint") or raw.get("hint_family")
    )
    roots = [Path(operator_root)] if operator_root else []
    live = live_source_refs(raw, roots=roots)
    if from_hint and not live:
        errors.append("hint_requires_live_source_ref")
    elif not live and isinstance(scope, Mapping) and (
        scope.get("assignments") or scope.get("guards")
    ):
        warnings.append("source_refs_unresolved")

    return {
        "ok": not errors,
        "status": "active_eligible" if not errors else "needs_evidence",
        "errors": errors,
        "warnings": warnings,
        "evidence_entry_ids": cited,
        "live_source_refs": live,
        "from_hint": from_hint,
    }
