from __future__ import annotations

from typing import Any


def kind_matches(actual_kind: str, expected_kind_or_group: str, entity_spec: dict[str, Any]) -> bool:
    expected = str(expected_kind_or_group or "any")
    actual = str(actual_kind or "")
    if expected == "any" or actual == expected:
        return True
    groups = entity_spec.get("kind_groups") if isinstance(entity_spec, dict) else {}
    members = groups.get(expected) if isinstance(groups, dict) else None
    if isinstance(members, list):
        return actual in {str(item) for item in members}
    return False


def allowed_reference_kinds(entity_spec: dict[str, Any], kind: str, field_name: str, *, identity: bool = False) -> list[str]:
    entity_types = entity_spec.get("entity_types") if isinstance(entity_spec, dict) else {}
    config = entity_types.get(kind) if isinstance(entity_types, dict) else None
    if not isinstance(config, dict):
        return []
    if identity:
        refs = config.get("identity_reference_fields") if isinstance(config.get("identity_reference_fields"), dict) else {}
        allowed = refs.get(field_name)
        return [str(item) for item in allowed] if isinstance(allowed, list) else []
    refs = config.get("reference_fields") if isinstance(config.get("reference_fields"), dict) else {}
    for cardinality in ("single", "multiple"):
        declared = refs.get(cardinality) if isinstance(refs.get(cardinality), dict) else {}
        allowed = declared.get(field_name)
        if isinstance(allowed, list):
            return [str(item) for item in allowed]
    return []
