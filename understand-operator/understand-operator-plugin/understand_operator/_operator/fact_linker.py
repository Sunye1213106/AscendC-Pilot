from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from understand_operator._operator.fact_registry import FactRegistry
from understand_operator._operator.identity import IdentityError, resolve_identity
from understand_operator._operator.kind_match import kind_matches
from understand_operator._operator.reference_paths import ReferenceDeclaration, iter_reference_values, reference_declarations


@dataclass(frozen=True)
class LinkResult:
    status: Literal["resolved", "unresolved", "ambiguous"]
    stable_id: str | None
    candidates: tuple[str, ...]
    reason: str | None
    kind: str | None = None


def resolve_entity_ref(
    ref: dict[str, object],
    *,
    local_symbols: dict[str, str],
    registry: FactRegistry,
    repo_root: Path,
) -> LinkResult:
    if not isinstance(ref, dict):
        return LinkResult("unresolved", None, (), "ENTITY_REFERENCE_INVALID")
    ref_type = ref.get("ref_type")
    if ref_type == "local":
        local_id = ref.get("local_id")
        if isinstance(local_id, str) and local_id in local_symbols:
            stable_id = local_symbols[local_id]
            return LinkResult("resolved", stable_id, (stable_id,), None, registry.kind_of(stable_id))
        return LinkResult("unresolved", None, (), "LOCAL_REFERENCE_UNKNOWN", None)
    if ref_type == "entity":
        kind = ref.get("kind")
        identity = ref.get("identity")
        if not isinstance(kind, str) or not isinstance(identity, dict):
            return LinkResult("unresolved", None, (), "ENTITY_REFERENCE_INVALID", None)
        try:
            resolved = resolve_identity(kind, identity, repo_root=repo_root)
        except IdentityError as exc:
            return LinkResult("unresolved", None, (), exc.code, None)
        stable = registry.find_canonical(resolved.canonical_key)
        if stable:
            return LinkResult("resolved", stable, (stable,), None, registry.kind_of(stable) or kind)
        return LinkResult("unresolved", None, (), "ENTITY_REFERENCE_UNRESOLVED", None)
    if ref_type == "symbol":
        kind = ref.get("kind")
        symbol = ref.get("qualified_symbol") or ref.get("symbol")
        signature = ref.get("signature")
        if not isinstance(kind, str) or not isinstance(symbol, str) or not symbol.strip():
            return LinkResult("unresolved", None, (), "ENTITY_REFERENCE_INVALID", None)
        candidates = registry.find_symbol_kind(kind.strip(), symbol.strip(), signature.strip() if isinstance(signature, str) and signature.strip() else None)
        if len(candidates) == 1:
            return LinkResult("resolved", candidates[0], candidates, None, registry.kind_of(candidates[0]) or kind.strip())
        if len(candidates) > 1:
            return LinkResult("ambiguous", None, candidates, "ENTITY_REFERENCE_AMBIGUOUS", None)
        return LinkResult("unresolved", None, (), "ENTITY_REFERENCE_UNRESOLVED", None)
    return LinkResult("unresolved", None, (), "ENTITY_REFERENCE_INVALID", None)


def resolve_typed_entity_ref(
    ref: dict[str, object],
    *,
    local_symbols: dict[str, str],
    local_kinds: dict[str, str],
    registry: FactRegistry,
    repo_root: Path,
    allowed: list[str],
    entity_spec: dict[str, Any],
    code: str,
) -> LinkResult:
    result = resolve_entity_ref(ref, local_symbols=local_symbols, registry=registry, repo_root=repo_root)
    if result.status != "resolved":
        return result
    actual_kind = result.kind
    if ref.get("ref_type") == "local" and isinstance(ref.get("local_id"), str):
        actual_kind = local_kinds.get(str(ref["local_id"])) or actual_kind
    if not actual_kind:
        return LinkResult("unresolved", None, (), "REFERENCE_KIND_UNKNOWN", None)
    if allowed and not any(kind_matches(actual_kind, expected, entity_spec) for expected in allowed):
        return LinkResult("unresolved", None, tuple(result.candidates), code, actual_kind)
    return result


def resolve_reference_fields(
    value: Any,
    *,
    local_symbols: dict[str, str],
    local_kinds: dict[str, str] | None = None,
    registry: FactRegistry,
    repo_root: Path,
    kind: str = "",
    entity_spec: dict[str, Any] | None = None,
    path: str = "fields",
) -> tuple[Any, list[dict[str, Any]]]:
    if kind and entity_spec:
        return _resolve_declared_reference_fields(
            value,
            local_symbols=local_symbols,
            local_kinds=local_kinds or {},
            registry=registry,
            repo_root=repo_root,
            kind=kind,
            entity_spec=entity_spec,
            path=path,
        )
    return _resolve_reference_fields_legacy(value, local_symbols=local_symbols, registry=registry, repo_root=repo_root, path=path)


def _resolve_declared_reference_fields(
    value: Any,
    *,
    local_symbols: dict[str, str],
    local_kinds: dict[str, str],
    registry: FactRegistry,
    repo_root: Path,
    kind: str,
    entity_spec: dict[str, Any],
    path: str,
) -> tuple[Any, list[dict[str, Any]]]:
    output = _copy(value)
    failures: list[dict[str, Any]] = []
    declarations = reference_declarations(entity_spec, kind)
    for found in iter_reference_values(value, declarations, base_path=path):
        _resolve_declared_value(
            output,
            found.path,
            found.declaration,
            local_symbols=local_symbols,
            local_kinds=local_kinds,
            registry=registry,
            repo_root=repo_root,
            entity_spec=entity_spec,
            failures=failures,
        )
    return output, failures


def _resolve_declared_value(
    output: Any,
    actual_path: str,
    declaration: ReferenceDeclaration,
    *,
    local_symbols: dict[str, str],
    local_kinds: dict[str, str],
    registry: FactRegistry,
    repo_root: Path,
    entity_spec: dict[str, Any],
    failures: list[dict[str, Any]],
) -> None:
    value = _get_at_actual_path(output, actual_path)
    if declaration.cardinality == "single":
        if not isinstance(value, dict):
            failures.append({"path": actual_path, "status": "unresolved", "reason": "REFERENCE_OBJECT_REQUIRED"})
            return
        result = resolve_typed_entity_ref(
            value,
            local_symbols=local_symbols,
            local_kinds=local_kinds,
            registry=registry,
            repo_root=repo_root,
            allowed=list(declaration.allowed),
            entity_spec=entity_spec,
            code="REFERENCE_KIND_NOT_ALLOWED",
        )
        if result.status == "resolved":
            _set_at_actual_path(output, actual_path, result.stable_id)
            return
        failures.append({"path": actual_path, "status": result.status, "reason": result.reason, "actual_kind": result.kind, "allowed": list(declaration.allowed), "candidates": list(result.candidates)})
        return
    if not isinstance(value, list):
        failures.append({"path": actual_path, "status": "unresolved", "reason": "REFERENCE_ARRAY_REQUIRED"})
        return
    resolved_values: list[Any] = []
    for index, item in enumerate(value):
        item_path = f"{actual_path}[{index}]"
        if not isinstance(item, dict):
            failures.append({"path": item_path, "status": "unresolved", "reason": "REFERENCE_OBJECT_REQUIRED"})
            resolved_values.append(item)
            continue
        result = resolve_typed_entity_ref(
            item,
            local_symbols=local_symbols,
            local_kinds=local_kinds,
            registry=registry,
            repo_root=repo_root,
            allowed=list(declaration.allowed),
            entity_spec=entity_spec,
            code="REFERENCE_KIND_NOT_ALLOWED",
        )
        if result.status == "resolved":
            resolved_values.append(result.stable_id)
        else:
            failures.append({"path": item_path, "status": result.status, "reason": result.reason, "actual_kind": result.kind, "allowed": list(declaration.allowed), "candidates": list(result.candidates)})
            resolved_values.append(item)
    _set_at_actual_path(output, actual_path, resolved_values)


def _resolve_reference_fields_legacy(
    value: Any,
    *,
    local_symbols: dict[str, str],
    registry: FactRegistry,
    repo_root: Path,
    path: str = "fields",
    field_name: str = "",
) -> tuple[Any, list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("ref_type") in {"local", "entity", "symbol"} and _is_reference_context(field_name):
            result = resolve_entity_ref(value, local_symbols=local_symbols, registry=registry, repo_root=repo_root)
            if result.status == "resolved":
                return result.stable_id, failures
            failures.append({"path": path, "status": result.status, "reason": result.reason, "candidates": list(result.candidates)})
            return value, failures
        out: dict[str, Any] = {}
        for key, child in value.items():
            resolved, child_failures = _resolve_reference_fields_legacy(
                child,
                local_symbols=local_symbols,
                registry=registry,
                repo_root=repo_root,
                path=f"{path}.{key}" if path else str(key),
                field_name=str(key),
            )
            out[key] = resolved
            failures.extend(child_failures)
        return out, failures
    if isinstance(value, list):
        out_list: list[Any] = []
        for index, child in enumerate(value):
            resolved, child_failures = _resolve_reference_fields_legacy(
                child,
                local_symbols=local_symbols,
                registry=registry,
                repo_root=repo_root,
                path=f"{path}[{index}]",
                field_name=field_name,
            )
            out_list.append(resolved)
            failures.extend(child_failures)
        return out_list, failures
    return value, failures


def _is_reference_context(field_name: str) -> bool:
    return field_name.endswith(("_ref", "_refs"))


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_copy(child) for child in value]
    return value


def _parse_actual_path(path: str) -> list[str | int]:
    path = _relative_actual_path(path)
    result: list[str | int] = []
    for part in path.split("."):
        while "[" in part and part.endswith("]"):
            key, index_text = part[:-1].split("[", 1)
            if key:
                result.append(key)
            result.append(int(index_text))
            part = ""
        if part:
            result.append(part)
    return result


def _relative_actual_path(path: str) -> str:
    match = re.match(r"^[A-Za-z_]+\[\d+\]\.(.+)$", path)
    return match.group(1) if match else path


def _get_at_actual_path(value: Any, path: str) -> Any:
    node = value
    for part in _parse_actual_path(path):
        if isinstance(part, int):
            node = node[part]
        else:
            node = node[part]
    return node


def _set_at_actual_path(value: Any, path: str, replacement: Any) -> None:
    parts = _parse_actual_path(path)
    node = value
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = replacement
