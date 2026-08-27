"""Apply accepted source-proof certificates onto the worklog ledger.

Exclusion is engine-owned. Plan.md L2 exclusions are never mutated here.
PROVED + review accept + schema-valid is the only upgrade to
``PROVED_UNREACHABLE``. Composition requires every atomic certificate for an
obligation to be accept+PROVED.
"""

from __future__ import annotations

from typing import Any, Mapping

from testcase_agent.coverage.ledger import upsert_obligation
from testcase_agent.proof_validate import validate, validate_review_accept

_CERT_NEST = ("certificates", "certificate")
_REVIEW_NEST = ("reviews", "review")


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


def _mapping(val: Any) -> dict[str, Any]:
    return dict(val) if isinstance(val, Mapping) else {}


def _as_rows(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    return [raw]


def _nested_maps(row: Mapping[str, Any], nest_keys: tuple[str, ...]) -> list[dict[str, Any]] | None:
    for key in nest_keys:
        if key not in row:
            continue
        inner = row.get(key)
        if isinstance(inner, list):
            return [dict(x) for x in inner if isinstance(x, Mapping)]
        if isinstance(inner, Mapping):
            return [dict(inner)]
        return []
    return None


def flatten_certificates(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _as_rows(raw):
        if not isinstance(row, Mapping):
            continue
        nested = _nested_maps(row, _CERT_NEST)
        if nested is not None:
            out.extend(nested)
        else:
            out.append(dict(row))
    return out


def flatten_reviews(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _as_rows(raw):
        if not isinstance(row, Mapping):
            continue
        nested = _nested_maps(row, _REVIEW_NEST)
        if nested is not None:
            out.extend(nested)
        else:
            out.append(dict(row))
    return out


def _obligation_id(row: Mapping[str, Any] | None) -> str:
    data = _mapping(row)
    oid = _s(data.get("obligation")) or _s(data.get("on"))
    if not oid and True in data:
        # YAML 1.1: unquoted `on:` becomes boolean True.
        oid = _s(data.get(True))
    if oid:
        return oid
    claim = _mapping(data.get("claim"))
    return _s(claim.get("obligation")) or _s(claim.get("on"))


def pair_items(*, certificates: Any, reviews: Any) -> list[dict[str, Any]]:
    """Match reviews to certificates by obligation id (``obligation`` / ``on``)."""
    certs = flatten_certificates(certificates)
    reviews_by_oid: dict[str, list[dict[str, Any]]] = {}
    for review in flatten_reviews(reviews):
        oid = _obligation_id(review)
        if not oid:
            continue
        reviews_by_oid.setdefault(oid, []).append(review)
    items: list[dict[str, Any]] = []
    for cert in certs:
        oid = _obligation_id(cert)
        matched = list(reviews_by_oid.get(oid) or [])
        review = _compose_review(matched)
        items.append({"obligation": oid, "certificate": cert, "review": review})
    return items


def _compose_review(matched: list[dict[str, Any]]) -> dict[str, Any]:
    if not matched:
        return {}
    for preferred in ("reject", "defer"):
        for row in matched:
            if _s(row.get("verdict")).lower() == preferred:
                return row
    return matched[0]


def promote(*, items: list[Mapping[str, Any]], ledger: dict[str, Any]) -> dict[str, Any]:
    rows = ledger.get("obligations") if isinstance(ledger.get("obligations"), dict) else {}
    groups: dict[str, list[Mapping[str, Any]]] = {}
    errors: list[str] = []
    for item in items or []:
        if not isinstance(item, Mapping):
            errors.append("item not a mapping")
            continue
        oid = _s(item.get("obligation")) or _obligation_id(item)
        if not oid:
            errors.append("obligation missing")
            continue
        groups.setdefault(oid, []).append(item)

    to_apply: list[str] = []
    for oid, group in groups.items():
        if oid not in rows:
            errors.append(f"unknown obligation {oid}")
            continue
        status = _s((rows.get(oid) or {}).get("status")) or "OPEN"
        if status == "CLOSED":
            continue
        apply = True
        for item in group:
            cert = _mapping(item.get("certificate"))
            review = _mapping(item.get("review"))
            gate = validate_review_accept(cert, review)
            verdict = _s(review.get("verdict")).lower()
            if verdict == "accept" and not gate["ok"]:
                errors.append(f"{oid}: accept requires schema-valid certificate")
                errors.extend(str(x) for x in gate.get("errors") or [])
                apply = False
                continue
            if not gate["ok"] and verdict not in {"accept", "reject", "defer"}:
                errors.append(f"{oid}: review.verdict must be accept|reject|defer")
                apply = False
                continue
            form = validate(cert)
            result = _s(cert.get("result"))
            if verdict != "accept" or result != "PROVED" or not form["ok"]:
                apply = False
        if apply and group:
            to_apply.append(oid)

    if errors:
        return {"ok": False, "applied": [], "errors": errors}

    applied: list[str] = []
    for oid in to_apply:
        status = _s((rows.get(oid) or {}).get("status"))
        if status == "CLOSED":
            continue
        upsert_obligation(ledger, oid, status="PROVED_UNREACHABLE")
        applied.append(oid)
        proof_row = {
            "obligation": oid,
            "status": "PROVED_UNREACHABLE",
            "layers": [
                _s(_mapping(_mapping(item.get("certificate")).get("claim")).get("layer"))
                for item in groups.get(oid) or []
            ],
        }
        seen = list(ledger.get("proofs") or [])
        if not isinstance(seen, list):
            seen = []
        seen.append(proof_row)
        ledger["proofs"] = seen
    return {"ok": True, "applied": applied, "errors": []}


__all__ = ["flatten_certificates", "flatten_reviews", "pair_items", "promote"]
