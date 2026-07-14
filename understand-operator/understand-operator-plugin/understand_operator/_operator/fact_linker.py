from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from understand_operator._operator.fact_registry import FactRegistry
from understand_operator._operator.identity import IdentityError, resolve_identity


@dataclass(frozen=True)
class LinkResult:
    status: Literal["resolved", "unresolved", "ambiguous"]
    stable_id: str | None
    candidates: tuple[str, ...]
    reason: str | None


REFERENCE_FIELD_NAMES = {
    "scope_ref",
    "predicate_ref",
    "expression_ref",
    "api_refs",
    "producer_refs",
    "consumer_refs",
    "kernel_entry_ref",
    "output_tensor_refs",
    "compute_operation_ref",
    "field_refs",
    "signal_call_refs",
    "wait_call_refs",
    "caller_ref",
    "callee_ref",
    "argument_refs",
    "return_ref",
    "condition_refs",
    "operand_refs",
    "parent_branch_ref",
    "outcome_refs",
    "controlled_item_refs",
    "input_tensor_refs",
    "output_refs",
    "source_tensor_ref",
    "target_tensor_ref",
    "length_expression_ref",
    "source_offset_ref",
    "target_offset_ref",
    "buffer_refs",
    "sync_refs",
    "input_refs",
    "output_refs",
    "allocation_site_ref",
    "lifetime_start_ref",
    "lifetime_end_ref",
    "reuse_refs",
    "queue_operation_refs",
    "before_refs",
    "after_refs",
    "kernel_entry_ref",
    "output_write_refs",
    "exported_refs",
    "imported_refs",
    "source_slice_ref",
    "target_slice_ref",
    "function_ref",
    "candidate_compute_operation_ref",
    "instantiation_refs",
    "macro_or_template_ref",
    "variable_ref",
    "encoding_call_ref",
    "derived_from",
    "constrained_refs",
    "proof_source_ref",
    "value_expression_ref",
    "source_variable_refs",
    "read_site_ref",
    "target_variable_ref",
    "read_condition_ref",
    "host_write_candidate_ref",
    "producer_ref",
    "consumer_ref",
    "input_tensor_ref",
    "output_tensor_ref",
}


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
            return LinkResult("resolved", local_symbols[local_id], (local_symbols[local_id],), None)
        return LinkResult("unresolved", None, (), "LOCAL_REFERENCE_UNKNOWN")
    if ref_type == "entity":
        kind = ref.get("kind")
        identity = ref.get("identity")
        if not isinstance(kind, str) or not isinstance(identity, dict):
            return LinkResult("unresolved", None, (), "ENTITY_REFERENCE_INVALID")
        try:
            resolved = resolve_identity(kind, identity, repo_root=repo_root)
        except IdentityError as exc:
            return LinkResult("unresolved", None, (), exc.code)
        stable = registry.find_canonical(resolved.canonical_key)
        if stable:
            return LinkResult("resolved", stable, (stable,), None)
        return LinkResult("unresolved", None, (), "ENTITY_REFERENCE_UNRESOLVED")
    if ref_type == "symbol":
        kind = ref.get("kind")
        symbol = ref.get("qualified_symbol") or ref.get("symbol")
        signature = ref.get("signature")
        if not isinstance(kind, str) or not isinstance(symbol, str) or not symbol.strip():
            return LinkResult("unresolved", None, (), "ENTITY_REFERENCE_INVALID")
        candidates = registry.find_symbol_kind(kind.strip(), symbol.strip(), signature.strip() if isinstance(signature, str) and signature.strip() else None)
        if len(candidates) == 1:
            return LinkResult("resolved", candidates[0], candidates, None)
        if len(candidates) > 1:
            return LinkResult("ambiguous", None, candidates, "ENTITY_REFERENCE_AMBIGUOUS")
        return LinkResult("unresolved", None, (), "ENTITY_REFERENCE_UNRESOLVED")
    return LinkResult("unresolved", None, (), "ENTITY_REFERENCE_INVALID")


def resolve_reference_fields(
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
            resolved, child_failures = resolve_reference_fields(
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
            resolved, child_failures = resolve_reference_fields(
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
    return field_name in REFERENCE_FIELD_NAMES or field_name.endswith(("_ref", "_refs"))
