# -*- coding: utf-8 -*-
"""Evidence-strength classification for CodeMap records."""

from __future__ import annotations

from typing import Literal

Tier = Literal["A", "B", "C"]


def _attrs(record: dict) -> dict:
    data = record.get("attrs") or record.get("data") or {}
    return data if isinstance(data, dict) else {}


def _provenance(record: dict) -> str:
    attrs = _attrs(record)
    value = record.get("provenance") or attrs.get("provenance") or ""
    return str(value).lower()


def _trust(record: dict) -> str:
    attrs = _attrs(record)
    return str(record.get("trust") or attrs.get("trust") or "")


def classify_entity(entity: dict) -> Tier:
    """Classify an entity, preferring explicit trust over status=confirmed."""
    attrs = _attrs(entity)
    status = str(entity.get("status") or attrs.get("status") or "").lower()
    provenance = _provenance(entity)
    trust = _trust(entity)
    gap = entity.get("gap_code") or attrs.get("gap_code")
    identity = entity.get("id") or attrs.get("usr") or entity.get("name")
    structure = bool(identity or entity.get("kind") or entity.get("file"))
    orphan = not provenance and attrs.get("root_status") not in {"REACHED", "reached"}
    if gap or "lexical_source_calls" in provenance or (status == "extracted" and gap) or orphan:
        return "C"
    if trust == "advisory":
        return "C"
    if trust == "authoritative":
        return "A"
    if trust in {"derived", "legacy_unknown"}:
        return "B"
    if status == "confirmed" and not gap:
        return "B"
    return "B" if structure else "C"


def classify_relation(relation: dict) -> Tier:
    """Classify a relation using trust first, then status and provenance."""
    attrs = _attrs(relation)
    status = str(relation.get("status") or attrs.get("status") or "").lower()
    provenance = _provenance(relation)
    trust = _trust(relation)
    gap = relation.get("gap_code") or attrs.get("gap_code")
    has_identity = bool(relation.get("id") and relation.get("src") and relation.get("dst"))
    structure = bool(relation.get("src") or relation.get("dst") or relation.get("kind"))
    if gap or "lexical_source_calls" in provenance or (status == "extracted" and gap):
        return "C"
    if trust == "advisory":
        return "C"
    if not provenance and not (relation.get("src") and relation.get("dst")):
        return "C"
    if trust == "authoritative" and has_identity:
        return "A"
    if trust in {"derived", "legacy_unknown"}:
        return "B"
    if status == "confirmed" and has_identity and not gap:
        return "B"
    return "B" if structure else "C"


def path_tier(tiers: list[Tier]) -> Tier:
    """Return the weakest tier on a path (an empty path is unproven)."""
    return max(tiers, key={"A": 0, "B": 1, "C": 2}.get) if tiers else "C"
