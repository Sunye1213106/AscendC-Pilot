# -*- coding: utf-8 -*-
"""Schema validation for CE obligation records."""

from __future__ import annotations

from typing import Any

FIELDS = {
    "id", "risk_class", "anchors", "evidence_tier", "max_verdict",
    "closure_requirement", "source_spans",
}
RISK_CLASSES = {"contract", "dispatch", "coverage", "shape", "sync", "precision", "perf"}


def validate_obligation(record: dict[str, Any]) -> list[str]:
    """Return deterministic schema errors for one obligation."""
    errors = [f"missing:{name}" for name in sorted(FIELDS - set(record))]
    if record.get("evidence_tier") not in {"A", "B", "C"}:
        errors.append("invalid:evidence_tier")
    if record.get("risk_class") not in RISK_CLASSES:
        errors.append("invalid:risk_class")
    if not isinstance(record.get("anchors"), list):
        errors.append("invalid:anchors")
    if not isinstance(record.get("source_spans"), list):
        errors.append("invalid:source_spans")
    for name in ("id", "max_verdict", "closure_requirement"):
        if not isinstance(record.get(name), str) or not record.get(name):
            errors.append(f"invalid:{name}")
    return errors


def validate_obligations(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate a collection and report errors by record index."""
    errors = {
        str(index): validate_obligation(record)
        for index, record in enumerate(records)
        if validate_obligation(record)
    }
    return {"ok": not errors, "errors": errors, "count": len(records)}
