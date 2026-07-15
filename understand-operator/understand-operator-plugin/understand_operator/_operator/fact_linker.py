from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from understand_operator._operator.fact_registry import FactRegistry
from understand_operator._operator.identity import IdentityError, ResolvedIdentity, resolve_identity
from understand_operator._operator.kind_match import kind_matches
from understand_operator._operator.reference_paths import ReferenceDeclaration, iter_reference_values, reference_declarations
from understand_operator._operator.spec import load_spec


MAX_IDENTITY_REFERENCE_DEPTH = 16


@dataclass(frozen=True)
class LinkResult:
    status: Literal["resolved", "unresolved", "ambiguous"]
    stable_id: str | None
    candidates: tuple[str, ...]
    reason: str | None
    kind: str | None = None


@dataclass(frozen=True)
class ResolvedIdentityResult:
    status: Literal["resolved", "unresolved", "ambiguous"]
    resolved_identity: ResolvedIdentity | None
    stable_id: str | None
    candidates: tuple[str, ...]
    reason: str | None
    kind: str | None = None
    normalized_input: dict[str, object] | None = None


def resolve_entity_ref(
    ref: dict[str, object],
    *,
    local_symbols: dict[str, str],
    local_kinds: dict[str, str] | None = None,
    registry: FactRegistry,
    repo_root: Path,
    entity_spec: dict[str, Any] | None = None,
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
        resolved = resolve_structured_identity(
            kind,
            identity,
            local_symbols=local_symbols,
            local_kinds=local_kinds or {},
            registry=registry,
            repo_root=repo_root,
            entity_spec=entity_spec or _entity_spec(),
        )
        if resolved.status == "resolved" and resolved.stable_id:
            return LinkResult("resolved", resolved.stable_id, (resolved.stable_id,), None, resolved.kind)
        return LinkResult(resolved.status, None, resolved.candidates, resolved.reason, resolved.kind)
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


def resolve_structured_identity(
    kind: str,
    identity: dict[str, object],
    *,
    local_symbols: dict[str, str],
    local_kinds: dict[str, str],
    registry: FactRegistry,
    repo_root: Path,
    entity_spec: dict[str, Any],
    visited: set[str] | None = None,
    depth: int = 0,
    require_registered: bool = True,
) -> ResolvedIdentityResult:
    if depth > MAX_IDENTITY_REFERENCE_DEPTH:
        return ResolvedIdentityResult("unresolved", None, None, (), "ENTITY_IDENTITY_REFERENCE_DEPTH_EXCEEDED", kind)
    if not isinstance(identity, dict):
        return ResolvedIdentityResult("unresolved", None, None, (), "IDENTITY_MISSING", kind)
    marker = f"{kind}:{_canonical_jsonish(identity)}"
    seen = set(visited or set())
    if marker in seen:
        return ResolvedIdentityResult("unresolved", None, None, (), "ENTITY_IDENTITY_REFERENCE_CYCLE", kind)
    seen.add(marker)
    normalized = dict(identity)
    for field_name, allowed in _identity_reference_fields(entity_spec, kind).items():
        value = normalized.get(field_name)
        if not isinstance(value, dict):
            continue
        result = _resolve_identity_reference_value(
            value,
            local_symbols=local_symbols,
            local_kinds=local_kinds,
            registry=registry,
            repo_root=repo_root,
            entity_spec=entity_spec,
            allowed=allowed,
            visited=seen,
            depth=depth + 1,
        )
        if result.status != "resolved" or not result.stable_id:
            return ResolvedIdentityResult(result.status, None, None, result.candidates, result.reason, result.kind)
        normalized[field_name] = result.stable_id
    try:
        resolved = resolve_identity(kind, normalized, repo_root=repo_root)
    except IdentityError as exc:
        return ResolvedIdentityResult("unresolved", None, None, (), exc.code, kind, normalized)
    stable = registry.find_canonical(resolved.canonical_key)
    if require_registered and not stable:
        return ResolvedIdentityResult("unresolved", resolved, None, (), "ENTITY_IDENTITY_REFERENCE_UNRESOLVED", kind, normalized)
    return ResolvedIdentityResult("resolved", resolved, stable or resolved.stable_id, (stable or resolved.stable_id,), None, registry.kind_of(stable) if stable else kind, normalized)


def _resolve_identity_reference_value(
    ref: dict[str, object],
    *,
    local_symbols: dict[str, str],
    local_kinds: dict[str, str],
    registry: FactRegistry,
    repo_root: Path,
    entity_spec: dict[str, Any],
    allowed: list[str],
    visited: set[str],
    depth: int,
) -> ResolvedIdentityResult:
    ref_type = ref.get("ref_type")
    if ref_type == "local":
        local_id = ref.get("local_id")
        if not isinstance(local_id, str) or local_id not in local_symbols:
            return ResolvedIdentityResult("unresolved", None, None, (), "ENTITY_IDENTITY_REFERENCE_UNRESOLVED", None)
        stable = local_symbols[local_id]
        actual_kind = local_kinds.get(local_id) or registry.kind_of(stable)
        if actual_kind and allowed and not any(kind_matches(actual_kind, expected, entity_spec) for expected in allowed):
            return ResolvedIdentityResult("unresolved", None, None, (stable,), "IDENTITY_REFERENCE_KIND_NOT_ALLOWED", actual_kind)
        return ResolvedIdentityResult("resolved", None, stable, (stable,), None, actual_kind)
    if ref_type == "symbol":
        kind = ref.get("kind")
        symbol = ref.get("qualified_symbol") or ref.get("symbol")
        signature = ref.get("signature")
        if not isinstance(kind, str) or not isinstance(symbol, str) or not symbol.strip():
            return ResolvedIdentityResult("unresolved", None, None, (), "ENTITY_REFERENCE_INVALID", None)
        if allowed and not any(kind_matches(kind.strip(), expected, entity_spec) for expected in allowed):
            return ResolvedIdentityResult("unresolved", None, None, (), "IDENTITY_REFERENCE_KIND_NOT_ALLOWED", kind.strip())
        candidates = registry.find_symbol_kind(kind.strip(), symbol.strip(), signature.strip() if isinstance(signature, str) and signature.strip() else None)
        if len(candidates) == 1:
            return ResolvedIdentityResult("resolved", None, candidates[0], (candidates[0],), None, registry.kind_of(candidates[0]) or kind.strip())
        if len(candidates) > 1:
            return ResolvedIdentityResult("ambiguous", None, None, tuple(candidates), "ENTITY_IDENTITY_REFERENCE_AMBIGUOUS", kind.strip())
        return ResolvedIdentityResult("unresolved", None, None, (), "ENTITY_IDENTITY_REFERENCE_UNRESOLVED", kind.strip())
    if ref_type == "entity":
        kind = ref.get("kind")
        identity = ref.get("identity")
        if not isinstance(kind, str) or not isinstance(identity, dict):
            return ResolvedIdentityResult("unresolved", None, None, (), "ENTITY_REFERENCE_INVALID", None)
        if allowed and not any(kind_matches(kind, expected, entity_spec) for expected in allowed):
            return ResolvedIdentityResult("unresolved", None, None, (), "IDENTITY_REFERENCE_KIND_NOT_ALLOWED", kind)
        return resolve_structured_identity(
            kind,
            identity,
            local_symbols=local_symbols,
            local_kinds=local_kinds,
            registry=registry,
            repo_root=repo_root,
            entity_spec=entity_spec,
            visited=visited,
            depth=depth,
            require_registered=True,
        )
    return ResolvedIdentityResult("unresolved", None, None, (), "ENTITY_REFERENCE_INVALID", None)


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
    result = resolve_entity_ref(ref, local_symbols=local_symbols, local_kinds=local_kinds, registry=registry, repo_root=repo_root, entity_spec=entity_spec)
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
    if not kind or not entity_spec:
        return _copy(value), []
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


def _identity_reference_fields(entity_spec: dict[str, Any], kind: str) -> dict[str, list[str]]:
    entity_types = entity_spec.get("entity_types") if isinstance(entity_spec.get("entity_types"), dict) else {}
    config = entity_types.get(kind) if isinstance(entity_types, dict) else None
    refs = config.get("identity_reference_fields") if isinstance(config, dict) and isinstance(config.get("identity_reference_fields"), dict) else {}
    return {str(key): [str(item) for item in value] for key, value in refs.items() if isinstance(value, list)}


def _entity_spec() -> dict[str, Any]:
    spec = load_spec()
    return spec.get("entity_types") if isinstance(spec.get("entity_types"), dict) else {}


def _canonical_jsonish(value: Any) -> str:
    if value in (None, {}, []):
        return ""
    if isinstance(value, dict):
        return "{" + ",".join(f"{_canonical_jsonish(key)}:{_canonical_jsonish(value[key])}" for key in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_canonical_jsonish(item) for item in value) + "]"
    return str(value)
