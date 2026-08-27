"""Deterministic structural validation for source-proof/v1 certificates.

Form only: enums, required fields, PROVED ⇒ applicable obligations CLOSED,
receipt taxonomy, evidence-id resolution. Semantic soundness stays in
proof-review. Exclusion stays engine-owned after accept.
"""

from __future__ import annotations

from typing import Any, Mapping

SCHEMA_ID = "source-proof/v1"
LAYERS = frozenset({"domain", "template", "host", "kernel"})
RESULTS = frozenset({"PROVED", "REFUTED", "INSUFFICIENT"})
OBLIGATION_STATES = frozenset({"CLOSED", "OPEN", "BLOCKED", "NA"})
OBLIGATION_KEYS = (
    "entry",
    "control",
    "writes",
    "calls",
    "overwrite",
    "alternatives",
    "completeness",
)
COMPLETENESS_KEYS = ("writers", "calls", "macros")
COMPLETENESS_STATUS = frozenset({"full", "partial", "unknown"})
REVIEW_VERDICTS = frozenset({"accept", "reject", "defer"})

WRITER_RECEIPTS = frozenset(
    {
        "UO_WRITER_CLOSURE_RECEIPT",
        "SOURCE_CLOSURE_RECEIPT",
        "PRODUCT_COVERAGE_RECEIPT",
    }
)
CALL_RECEIPTS = frozenset(
    {
        "UO_CALL_CLOSURE_RECEIPT",
        "SOURCE_CLOSURE_RECEIPT",
        "PRODUCT_COVERAGE_RECEIPT",
    }
)
MACRO_RECEIPTS = frozenset({"PRODUCT_COVERAGE_RECEIPT", "SOURCE_CLOSURE_RECEIPT"})
RECEIPTS_BY_FIELD = {
    "writers": WRITER_RECEIPTS,
    "calls": CALL_RECEIPTS,
    "macros": MACRO_RECEIPTS,
}


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


def _mapping(val: Any) -> dict[str, Any]:
    return dict(val) if isinstance(val, Mapping) else {}


def _evidence_ids(doc: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    rows = doc.get("evidence")
    if not isinstance(rows, list):
        return ids
    for row in rows:
        if isinstance(row, Mapping):
            eid = _s(row.get("id"))
            if eid:
                ids.add(eid)
    return ids


def _is_locator(cite: str) -> bool:
    if not cite:
        return False
    if cite.startswith("EV_"):
        return False
    return ":" in cite or "/" in cite or "\\" in cite


def _cited_ids(doc: Mapping[str, Any]) -> list[str]:
    cites: list[str] = []
    rows = doc.get("reasoning")
    if not isinstance(rows, list):
        return cites
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw = row.get("cites")
        if isinstance(raw, list):
            cites.extend(_s(x) for x in raw if _s(x))
        elif _s(raw):
            cites.append(_s(raw))
    return cites


def validate(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(doc, Mapping):
        return {"ok": False, "errors": ["certificate_missing"]}

    if _s(doc.get("schema")) != SCHEMA_ID:
        errors.append(f"schema must be {SCHEMA_ID}")

    claim = _mapping(doc.get("claim"))
    if not claim:
        errors.append("claim missing")
    layer = _s(claim.get("layer"))
    if layer not in LAYERS:
        errors.append("claim.layer must be domain|template|host|kernel")
    if not _s(claim.get("premise")):
        errors.append("claim.premise missing")
    if not _s(claim.get("conclusion")):
        errors.append("claim.conclusion missing")

    result = _s(doc.get("result"))
    if result not in RESULTS:
        errors.append("result must be PROVED|REFUTED|INSUFFICIENT")

    obligations = _mapping(doc.get("obligations"))
    if not obligations:
        errors.append("obligations missing")
    else:
        for key in OBLIGATION_KEYS:
            state = _s(obligations.get(key))
            if state not in OBLIGATION_STATES:
                errors.append(f"obligations.{key} must be CLOSED|OPEN|BLOCKED|NA")

    reasoning = doc.get("reasoning")
    if not isinstance(reasoning, list):
        errors.append("reasoning missing")

    evidence = doc.get("evidence")
    if not isinstance(evidence, list):
        errors.append("evidence missing")
    else:
        seen: set[str] = set()
        for idx, row in enumerate(evidence):
            if not isinstance(row, Mapping):
                errors.append(f"evidence[{idx}] not a mapping")
                continue
            eid = _s(row.get("id"))
            if not eid:
                errors.append(f"evidence[{idx}].id missing")
                continue
            if eid in seen:
                errors.append(f"evidence id duplicate: {eid}")
            seen.add(eid)

    counter = _mapping(doc.get("counterexample"))
    if not counter:
        errors.append("counterexample missing")

    completeness = _mapping(doc.get("completeness"))
    if not completeness:
        errors.append("completeness missing")
    else:
        for field in COMPLETENESS_KEYS:
            block = _mapping(completeness.get(field))
            if not block:
                errors.append(f"completeness.{field} missing")
                continue
            status = _s(block.get("status"))
            source = _s(block.get("source"))
            if status not in COMPLETENESS_STATUS:
                errors.append(f"completeness.{field}.status must be full|partial|unknown")
                continue
            if status == "full":
                allowed = RECEIPTS_BY_FIELD[field]
                if not source:
                    errors.append(f"completeness.{field}.status=full requires machine receipt source")
                elif source not in allowed:
                    hint = "UO_CALL_CLOSURE_RECEIPT" if field == "calls" else "|".join(sorted(allowed))
                    errors.append(
                        f"completeness.{field}.source {source} is not a valid {field} receipt; use {hint}"
                    )
            elif source == "UO_WRITER_CLOSURE_RECEIPT" and field == "calls":
                errors.append("completeness.calls must not use UO_WRITER_CLOSURE_RECEIPT")

    if result == "PROVED":
        for key in OBLIGATION_KEYS:
            state = _s(obligations.get(key))
            if state in {"OPEN", "BLOCKED"}:
                errors.append(f"PROVED forbids applicable obligations.{key}={state}")
        checked = counter.get("checked")
        if checked is not True and _s(checked).lower() not in {"true", "1", "yes"}:
            errors.append("PROVED requires counterexample.checked == true")
        if not isinstance(evidence, list) or not evidence:
            errors.append("PROVED requires evidence")
        ids = _evidence_ids(doc)
        for cite in _cited_ids(doc):
            if _is_locator(cite):
                continue
            if cite not in ids:
                errors.append(f"evidence id does not resolve: {cite}")
        if isinstance(evidence, list):
            for idx, row in enumerate(evidence):
                if isinstance(row, Mapping) and not _s(row.get("source")):
                    errors.append(f"evidence[{idx}].source missing")
        if not isinstance(reasoning, list) or not reasoning:
            errors.append("PROVED requires reasoning")

    if result == "REFUTED":
        checked = counter.get("checked")
        if checked is not True and _s(checked).lower() not in {"true", "1", "yes"}:
            errors.append("REFUTED requires counterexample.checked == true")
        opposite = counter.get("result")
        if opposite in (None, "", "none", "None"):
            errors.append("REFUTED requires a counterexample result")

    return {"ok": not errors, "errors": errors}


def validate_review_accept(
    certificate: Mapping[str, Any] | None,
    review: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Engine gate: accept is illegal unless the certificate is schema-valid."""
    review_map = _mapping(review)
    verdict = _s(review_map.get("verdict")).lower()
    errors: list[str] = []
    if verdict not in REVIEW_VERDICTS:
        errors.append("review.verdict must be accept|reject|defer")
        return {"ok": False, "errors": errors}
    cert = validate(certificate)
    if verdict == "accept" and not cert["ok"]:
        errors.append("accept requires schema-valid certificate")
        errors.extend(cert["errors"])
    return {"ok": not errors, "errors": errors}
