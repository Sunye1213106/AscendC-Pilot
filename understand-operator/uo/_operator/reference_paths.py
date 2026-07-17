from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReferenceDeclaration:
    path: str
    cardinality: str
    allowed: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceValue:
    path: str
    declaration: ReferenceDeclaration
    value: Any


def reference_declarations(entity_spec: dict[str, Any], kind: str) -> dict[str, ReferenceDeclaration]:
    entity_types = entity_spec.get("entity_types") if isinstance(entity_spec.get("entity_types"), dict) else {}
    config = entity_types.get(kind) if isinstance(entity_types, dict) else None
    refs = config.get("reference_fields") if isinstance(config, dict) and isinstance(config.get("reference_fields"), dict) else {}
    result: dict[str, ReferenceDeclaration] = {}
    for cardinality in ("single", "multiple"):
        fields = refs.get(cardinality) if isinstance(refs.get(cardinality), dict) else {}
        for path, allowed in fields.items():
            if isinstance(allowed, list):
                result[str(path)] = ReferenceDeclaration(str(path), cardinality, tuple(str(item) for item in allowed))
    return result


def identity_reference_declarations(entity_spec: dict[str, Any], kind: str) -> dict[str, ReferenceDeclaration]:
    entity_types = entity_spec.get("entity_types") if isinstance(entity_spec.get("entity_types"), dict) else {}
    config = entity_types.get(kind) if isinstance(entity_types, dict) else None
    refs = config.get("identity_reference_fields") if isinstance(config, dict) and isinstance(config.get("identity_reference_fields"), dict) else {}
    return {
        str(path): ReferenceDeclaration(str(path), "single", tuple(str(item) for item in allowed))
        for path, allowed in refs.items()
        if isinstance(allowed, list)
    }


def iter_reference_values(value: Any, declarations: dict[str, ReferenceDeclaration], *, base_path: str = "") -> list[ReferenceValue]:
    found: list[ReferenceValue] = []
    for declared_path, declaration in declarations.items():
        for actual_path, item in _values_at_path(value, declared_path, base_path=base_path):
            found.append(ReferenceValue(actual_path, declaration, item))
    return found


def declared_reference_for_path(declarations: dict[str, ReferenceDeclaration], path: str) -> ReferenceDeclaration | None:
    normalized = _normalize_actual_path(path)
    for declared, declaration in declarations.items():
        if normalized == declared:
            return declaration
    return None


def iter_reference_like_paths(value: Any, *, base_path: str = "") -> list[tuple[str, str, Any]]:
    result: list[tuple[str, str, Any]] = []

    def visit(node: Any, path: str, key: str) -> None:
        if key.endswith(("_ref", "_refs")):
            result.append((path, key, node))
            return
        if isinstance(node, dict):
            for child_key, child in node.items():
                child_path = f"{path}.{child_key}" if path else str(child_key)
                visit(child, child_path, str(child_key))
            return
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{path}[{index}]", key)
            return
    visit(value, base_path, "")
    return result


def _values_at_path(value: Any, declared_path: str, *, base_path: str) -> list[tuple[str, Any]]:
    parts = declared_path.split(".") if declared_path else []
    current: list[tuple[str, Any]] = [(base_path, value)]
    for part in parts:
        next_items: list[tuple[str, Any]] = []
        is_array = part.endswith("[]")
        key = part[:-2] if is_array else part
        for path, node in current:
            if not isinstance(node, dict) or key not in node:
                continue
            child = node[key]
            child_path = f"{path}.{key}" if path else key
            if is_array:
                if isinstance(child, list):
                    next_items.extend((f"{child_path}[{index}]", item) for index, item in enumerate(child))
                else:
                    next_items.append((child_path, child))
            else:
                next_items.append((child_path, child))
        current = next_items
    return current


def _normalize_actual_path(path: str) -> str:
    return re.sub(r"\[\d+\]", "[]", path)
