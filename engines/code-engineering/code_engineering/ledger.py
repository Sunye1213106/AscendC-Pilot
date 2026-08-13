# -*- coding: utf-8 -*-
"""Persistent O/V/X/Open obligation ledger with evidence-backed transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml


def compute_open(
    obligations: Iterable[str], verified: Iterable[str], excepted: Iterable[str]
) -> set[str]:
    """Compute unresolved obligations."""
    return set(obligations) - set(verified) - set(excepted)


def _scope_root(project_root: Path | str, architecture: str) -> Path:
    pilot = Path(project_root).expanduser().resolve() / ".ascendc-pilot"
    return pilot / architecture if architecture else pilot


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _obligation_records(root: Path) -> dict[str, dict[str, Any]]:
    doc = _load_yaml(root / "ce" / "impact" / "obligations.yaml")
    rows = doc.get("obligations") or []
    return {
        str(row.get("id")): row
        for row in rows
        if isinstance(row, dict) and row.get("id")
    }


def _add_evidence(
    evidence: dict[str, list[dict[str, Any]]],
    obligation_id: str,
    record: dict[str, Any],
) -> None:
    evidence.setdefault(obligation_id, []).append(record)


def _review_verified(
    root: Path,
    obligations: dict[str, dict[str, Any]],
    evidence: dict[str, list[dict[str, Any]]],
) -> set[str]:
    """Accept reviewed source proof only for statically closable obligations."""
    doc = _load_yaml(root / "ce" / "verify" / "code_review.yaml")
    if doc.get("schema") != "ce-code-review-evidence/v1":
        return set()
    if str(doc.get("reviewer_id") or "") != "ce-reviewer":
        return set()
    closed: set[str] = set()
    for row in doc.get("verified_obligations") or []:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("obligation_id") or "")
        obligation = obligations.get(oid) or {}
        tier = str(row.get("evidence_tier") or "")
        refs = row.get("evidence_refs") or row.get("source_refs") or []
        verdict = str(row.get("verdict") or "").upper()
        if (
            oid
            and obligation.get("risk_class") == "contract"
            and tier in {"A", "B"}
            and verdict == "VERIFIED"
            and isinstance(refs, list)
            and bool(refs)
        ):
            closed.add(oid)
            _add_evidence(
                evidence,
                oid,
                {
                    "closure": "V",
                    "type": "reviewed_source_proof",
                    "tier": tier,
                    "refs": refs,
                    "reviewer_id": "ce-reviewer",
                },
            )
    return closed


def _external_verified(
    root: Path,
    evidence: dict[str, list[dict[str, Any]]],
) -> set[str]:
    """Accept only verification claims from validated external receipt batches."""
    doc = _load_yaml(root / "ce" / "verify" / "external_evidence.yaml")
    closed: set[str] = set()
    for receipt in doc.get("receipts") or []:
        if not isinstance(receipt, dict):
            continue
        if receipt.get("schema") != "ce-external-evidence/v1":
            continue
        for value in receipt.get("verified_obligations") or []:
            oid = str(value.get("obligation_id") if isinstance(value, dict) else value)
            if not oid:
                continue
            closed.add(oid)
            _add_evidence(
                evidence,
                oid,
                {
                    "closure": "V",
                    "type": "external_evidence",
                    "receipt_id": str(receipt.get("id") or receipt.get("receipt_id") or ""),
                    "declared_path": str(receipt.get("declared_path") or ""),
                },
            )
    return closed


def _review_excluded(
    root: Path,
    evidence: dict[str, list[dict[str, Any]]],
) -> set[str]:
    """Accept X only from the CE referee with explicit Tier-A proof refs."""
    doc = _load_yaml(root / "ce" / "verify" / "exclusion_review.yaml")
    if doc.get("schema") != "ce-exclusion-review/v1":
        return set()
    referee = str(doc.get("referee_id") or "")
    if referee != "ce-change-referee":
        return set()
    closed: set[str] = set()
    for row in doc.get("verdicts") or []:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("obligation_id") or "")
        verdict = str(row.get("verdict") or "").lower()
        tier = str(row.get("evidence_tier") or row.get("path_tier") or "")
        refs = row.get("proof_refs") or row.get("evidence_refs") or []
        if (
            oid
            and verdict in {"approve", "approved", "exclude", "excluded"}
            and tier == "A"
            and isinstance(refs, list)
            and bool(refs)
        ):
            closed.add(oid)
            _add_evidence(
                evidence,
                oid,
                {
                    "closure": "X",
                    "type": "referee_exclusion",
                    "tier": "A",
                    "refs": refs,
                    "referee_id": referee,
                    "reason_codes": list(row.get("reason_codes") or []),
                },
            )
    return closed


def _authorized_closures(
    project_root: Path | str,
    architecture: str,
    obligations: set[str],
) -> tuple[set[str], set[str], dict[str, list[dict[str, Any]]]]:
    root = _scope_root(project_root, architecture)
    records = _obligation_records(root)
    evidence: dict[str, list[dict[str, Any]]] = {}
    verified = _review_verified(root, records, evidence) | _external_verified(root, evidence)
    excepted = _review_excluded(root, evidence)
    verified &= obligations
    excepted &= obligations
    verified -= excepted
    evidence = {key: value for key, value in evidence.items() if key in verified | excepted}
    return verified, excepted, evidence


@dataclass
class Ledger:
    """Evidence-backed four-set obligation ledger."""

    O: set[str] = field(default_factory=set)
    V: set[str] = field(default_factory=set)
    X: set[str] = field(default_factory=set)
    closure_evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    transition_audit: list[dict[str, Any]] = field(default_factory=list)

    @property
    def Open(self) -> set[str]:  # noqa: N802 - schema field name
        return compute_open(self.O, self.V, self.X)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ce-impact-ledger/v2",
            "O": sorted(self.O),
            "V": sorted(self.V),
            "X": sorted(self.X),
            "Open": sorted(self.Open),
            "closure_evidence": self.closure_evidence,
            "transition_audit": self.transition_audit,
        }


def ledger_path(
    project_root: Path | str, *, architecture: str = "", name: str = "ledger.yaml"
) -> Path:
    """Return the arch-scoped CE impact ledger path."""
    return _scope_root(project_root, architecture) / "ce" / "impact" / name


def _read_sets(source: Path) -> tuple[set[str], set[str], set[str]]:
    doc = _load_yaml(source)
    return (
        {str(v) for v in doc.get("O", [])},
        {str(v) for v in doc.get("V", [])},
        {str(v) for v in doc.get("X", [])},
    )


def load_ledger(
    project_root: Path | str, *, architecture: str = "", path: Path | str | None = None
) -> Ledger:
    """Load and reconcile a ledger against current closure evidence."""
    source = Path(path) if path is not None else ledger_path(project_root, architecture=architecture)
    if not source.is_file():
        return Ledger()
    o, stored_v, stored_x = _read_sets(source)
    verified, excepted, evidence = _authorized_closures(project_root, architecture, o)
    audit: list[dict[str, Any]] = []
    rejected_v = sorted(stored_v - verified)
    rejected_x = sorted(stored_x - excepted)
    if rejected_v:
        audit.append({"kind": "rejected_unbacked_V", "obligations": rejected_v})
    if rejected_x:
        audit.append({"kind": "rejected_unbacked_X", "obligations": rejected_x})
    return Ledger(
        O=o,
        V=verified,
        X=excepted,
        closure_evidence=evidence,
        transition_audit=audit,
    )


def save_ledger(
    ledger: Ledger,
    project_root: Path | str,
    *,
    architecture: str = "",
    path: Path | str | None = None,
) -> Path:
    """Save a normalized ledger after fail-closed evidence reconciliation."""
    target = Path(path) if path is not None else ledger_path(project_root, architecture=architecture)

    canonical = ledger_path(project_root, architecture=architecture)
    if target != canonical and canonical.is_file():
        canonical_o, _, _ = _read_sets(canonical)
        ledger.O |= canonical_o

    requested_v, requested_x = set(ledger.V), set(ledger.X)
    verified, excepted, evidence = _authorized_closures(
        project_root, architecture, set(ledger.O)
    )
    rejected_v = sorted(requested_v - verified)
    rejected_x = sorted(requested_x - excepted)
    audit = list(ledger.transition_audit)
    if rejected_v:
        audit.append({"kind": "rejected_unbacked_V", "obligations": rejected_v})
    if rejected_x:
        audit.append({"kind": "rejected_unbacked_X", "obligations": rejected_x})

    ledger.V = verified
    ledger.X = excepted
    ledger.closure_evidence = evidence
    ledger.transition_audit = audit

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(ledger.to_dict(), sort_keys=False), encoding="utf-8")
    return target
