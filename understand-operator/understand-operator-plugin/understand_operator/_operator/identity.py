from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from understand_operator._operator.candidate import stable_id
from understand_operator._operator.spec import load_spec


IDENTITY_VERSION = 1

KIND_TO_PREFIX = {
    "operator": "OP",
    "input_tensor": "ARG",
    "output_tensor": "ARG",
    "optional_input": "ARG",
    "optional_output": "ARG",
    "operator_attribute": "ATTR",
    "attribute": "ATTR",
    "dtype_domain": "ATTR",
    "layout_domain": "ATTR",
    "interface_constraint": "ATTR",
    "format_conversion": "ATTR",
    "rank": "SHAPE",
    "shape_symbol": "SHAPE",
    "function": "SYM",
    "host_function": "SYM",
    "kernel_function": "SYM",
    "kernel_method": "SYM",
    "helper_function": "SYM",
    "registration_entry": "SYM",
    "api_definition": "SYM",
    "proto_definition": "SYM",
    "host_entry": "SYM",
    "tiling_entry": "SYM",
    "golden_entry": "SYM",
    "unresolved_entry": "SYM",
    "source_file": "SYM",
    "dependency_file": "SYM",
    "external_system_file": "SYM",
    "third_party_file": "SYM",
    "generated_file": "SYM",
    "excluded_file": "SYM",
    "uncertain_file": "SYM",
    "architecture_variant": "SYM",
    "include_rule": "SYM",
    "exclude_rule": "SYM",
    "branch_skip": "SYM",
    "source_hint": "SYM",
    "runtime_variable": "VAR",
    "compile_time_variable": "VAR",
    "template_parameter": "VAR",
    "template_variable": "VAR",
    "kernel_variable": "VAR",
    "kernel_parameter": "VAR",
    "tilingdata_variable": "VAR",
    "loop_variable": "VAR",
    "buffer_variable": "VAR",
    "feature_flag": "VAR",
    "input_derived_variable": "VAR",
    "attribute_derived_variable": "VAR",
    "shape_variable": "VAR",
    "numeric_tiling_variable": "VAR",
    "expression": "EXPR",
    "host_expression": "EXPR",
    "kernel_expression": "EXPR",
    "predicate_expression": "EXPR",
    "value_expression": "EXPR",
    "shape_expression": "EXPR",
    "offset_expression": "EXPR",
    "length_expression": "EXPR",
    "tail_expression": "EXPR",
    "loop_bound_expression": "EXPR",
    "callsite": "CALL",
    "host_call": "CALL",
    "kernel_call": "CALL",
    "kernel_call_edge": "CALL",
    "macro_call": "CALL",
    "template_call": "CALL",
    "tiling_call": "CALL",
    "tiling_key_setter_call": "CALL",
    "ascendc_api_call": "API",
    "datacopy_call": "API",
    "compute_api_call": "API",
    "queue_call": "CALL",
    "branch": "BRANCH",
    "branch_site": "BRANCH",
    "if_branch": "BRANCH",
    "switch_branch": "BRANCH",
    "ternary_branch": "BRANCH",
    "early_return": "BRANCH",
    "kernel_branch": "BRANCH",
    "frontier_site": "BRANCH",
    "api_site": "BRANCH",
    "memory_site": "BRANCH",
    "sync_site": "BRANCH",
    "output_site": "BRANCH",
    "tilingdata_read_site": "BRANCH",
    "branch_outcome": "OUTCOME",
    "loop": "LOOP",
    "kernel_loop": "LOOP",
    "loop_site": "LOOP",
    "tiling_key_field": "KEY",
    "tiling_key_encoding": "KEY",
    "tiling_key_enumeration": "KEYBLOCK",
    "tiling_key_enumeration_block": "KEYBLOCK",
    "tilingdata_field": "TDATA",
    "tilingdata_struct": "TDATA",
    "tilingdata_write": "TDWRITE",
    "block_dim_write": "TDWRITE",
    "workspace_write": "TDWRITE",
    "tilingdata_read": "TDREAD",
    "kernel_entry": "KERNEL",
    "kernel_class_entry": "KERNEL",
    "kernel_global_entry": "KERNEL",
    "kernel_template_instance": "KERNEL",
    "kernel_launch_site": "KERNEL",
    "tiling_key_setter": "KERNEL",
    "tensor": "TENSOR",
    "intermediate_tensor": "TENSOR",
    "alias_tensor": "TENSOR",
    "view_tensor": "TENSOR",
    "compute_operation": "OPR",
    "data_movement_operation": "OPR",
    "shape_operation": "OPR",
    "layout_operation": "OPR",
    "cast_operation": "OPR",
    "control_operation": "OPR",
    "dataflow_edge": "OPR",
    "tensor_dependency": "OPR",
    "operation_order": "OPR",
    "takes_tensor": "OPR",
    "produces_tensor": "OPR",
    "data_depends_on": "OPR",
    "shape_depends_on": "OPR",
    "dtype_depends_on": "OPR",
    "layout_depends_on": "OPR",
    "alias_depends_on": "OPR",
    "kernel_dataflow_edge": "OPR",
    "datacopy_flow": "OPR",
    "api_flow": "OPR",
    "output_flow": "OPR",
    "numerical_policy": "OPR",
    "tolerance_policy": "OPR",
    "stability_policy": "OPR",
    "numeric_sensitive_operation": "OPR",
    "accumulation_policy": "OPR",
    "cast_policy": "OPR",
    "golden_kernel_diff": "OPR",
    "buffer": "BUF",
    "memory_resource": "BUF",
    "global_tensor_resource": "BUF",
    "local_tensor_resource": "BUF",
    "queue_resource": "BUF",
    "buffer_resource": "BUF",
    "workspace_resource": "BUF",
    "global_resource": "BUF",
    "synchronization_event": "SYNC",
    "sync_event": "SYNC",
    "setflag_event": "SYNC",
    "waitflag_event": "SYNC",
    "pipebarrier_event": "SYNC",
    "syncall_event": "SYNC",
    "slice_interface": "KERNEL",
    "cross_slice_call": "CALL",
    "cross_slice_dataflow": "OPR",
    "kernel_slice": "KERNEL",
    "value_constraint": "KEY",
    "range_constraint": "KEY",
    "requires_constraint": "KEY",
    "implies_constraint": "KEY",
    "mutex_constraint": "KEY",
    "pruning_rule": "KEY",
    "merging_rule": "KEY",
    "unreachable_combination": "KEY",
    "input_realization": "KEY",
    "abstraction_rule_record": "ARULE",
    "derived_node_record": "DVIEW",
    "derived_edge_record": "DVIEW",
    "derived_index_record": "DVIEW",
    "derived_expansion_record": "DVIEW",
    "raw_node_record": "SYM",
    "raw_edge_record": "SYM",
    "raw_index_record": "SYM",
    "raw_path_record": "SYM",
    "raw_manifest_record": "SYM",
}


class IdentityError(ValueError):
    def __init__(self, code: str, message: str, field: str = "identity") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


@dataclass(frozen=True)
class ResolvedIdentity:
    kind: str
    identity_version: int
    canonical_key: str
    prefix: str
    stable_id: str
    normalized_identity: dict[str, object]


def resolve_identity(kind: str, identity: dict[str, object], *, repo_root: Path) -> ResolvedIdentity:
    kind = _clean(kind)
    config = _entity_type_config(kind)
    prefix = str(config.get("prefix") or "")
    if not prefix:
        raise IdentityError("IDENTITY_KIND_UNSUPPORTED", f"unsupported identity kind: {kind}", "kind")
    if not isinstance(identity, dict):
        raise IdentityError("IDENTITY_MISSING", "identity must be an object")
    resolver = _strategy_for_kind(kind, config)
    normalized, parts = resolver(identity, repo_root)
    canonical_key = ":".join([kind, *(_escape(part) for part in parts)])
    return ResolvedIdentity(
        kind=kind,
        identity_version=IDENTITY_VERSION,
        canonical_key=canonical_key,
        prefix=prefix,
        stable_id=stable_id(prefix, canonical_key),
        normalized_identity=normalized,
    )


def relation_stable_id(relation_type: str, source_id: str, target_id: str, qualifier: Any = None) -> str:
    material = "\0".join((str(relation_type), str(source_id), str(target_id), _canonical_jsonish(qualifier)))
    return stable_id("REL", material)


def _strategy_for_kind(kind: str, config: dict[str, Any]) -> Callable[[dict[str, object], Path], tuple[dict[str, object], list[str]]]:
    strategy = str(config.get("identity_strategy") or "")
    mapping: dict[str, Callable[[dict[str, object], Path], tuple[dict[str, object], list[str]]]] = {
        "scoped_declaration": _local_variable_identity,
        "qualified_symbol_signature": _function_identity,
        "scoped_callsite": _callsite_identity,
        "scoped_predicate": _branch_identity,
        "branch_outcome": _branch_outcome_identity,
        "scoped_loop": _loop_identity,
        "repo_path": _repo_path_identity,
        "qualified_struct": _qualified_struct_identity,
        "struct_field": _tilingdata_field_identity,
        "operator_io": _operator_io_identity,
        "kernel_entry": _kernel_entry_identity,
        "kernel_slice_signature": _kernel_slice_identity,
        "slice_interface": _slice_interface_identity,
        "compute_operation": _compute_operation_identity,
        "endpoint_relation_entity": _endpoint_relation_identity,
        "scoped_policy": _source_span_identity,
        "scoped_resource": _local_variable_identity,
        "scoped_event": _source_span_identity,
        "source_span": _source_span_identity,
        "qualified_symbol": _qualified_symbol_only_identity,
    }
    if strategy == "scoped_field_write":
        return _tilingdata_access_identity("write_span")
    if strategy == "scoped_field_read":
        return _tilingdata_access_identity("read_span")
    if strategy in mapping:
        return mapping[strategy]
    raise IdentityError("SPEC_IDENTITY_STRATEGY_UNKNOWN", f"unknown identity strategy for {kind}: {strategy}", "kind")


def _entity_type_config(kind: str) -> dict[str, Any]:
    try:
        entity_types = (load_spec().get("entity_types") or {}).get("entity_types") or {}
    except Exception:
        entity_types = {}
    config = entity_types.get(kind)
    if isinstance(config, dict):
        return config
    return {}


def _legacy_strategy_for_kind(kind: str) -> str:
    if KIND_TO_PREFIX[kind] == "VAR":
        return "scoped_declaration"
    if kind in {"function", "host_function", "kernel_function", "kernel_method", "helper_function"}:
        return "qualified_symbol_signature"
    if KIND_TO_PREFIX[kind] in {"CALL", "API"}:
        return "scoped_callsite"
    if KIND_TO_PREFIX[kind] == "BRANCH":
        return "scoped_predicate"
    if KIND_TO_PREFIX[kind] == "OUTCOME":
        return "branch_outcome"
    if KIND_TO_PREFIX[kind] == "LOOP":
        return "scoped_loop"
    if kind == "tilingdata_struct":
        return "qualified_struct"
    if KIND_TO_PREFIX[kind] == "TDATA":
        return "struct_field"
    if KIND_TO_PREFIX[kind] == "TDWRITE":
        return "scoped_field_write"
    if KIND_TO_PREFIX[kind] == "TDREAD":
        return "scoped_field_read"
    if kind in {"input_tensor", "output_tensor"}:
        return "operator_io"
    if KIND_TO_PREFIX[kind] == "KERNEL":
        return "kernel_entry"
    if KIND_TO_PREFIX[kind] == "OPR":
        return "compute_operation"
    return "source_span"


def _local_variable_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {
        "source_file": _path(identity, "source_file", repo_root),
        "scope_symbol": _symbol(identity, "scope_symbol"),
        "source_name": _symbol(identity, "source_name"),
        "declaration_span": _span(identity, "declaration_span"),
    }
    span = norm["declaration_span"]
    assert isinstance(span, dict)
    return norm, [str(norm["source_file"]), str(norm["scope_symbol"]), str(norm["source_name"]), str(span["start_line"]), str(span["end_line"])]


def _function_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {
        "qualified_symbol": _symbol(identity, "qualified_symbol"),
        "signature": _signature(identity, "signature"),
    }
    if identity.get("source_file"):
        norm["source_file"] = _path(identity, "source_file", repo_root)
    if identity.get("definition_span"):
        norm["definition_span"] = _span(identity, "definition_span")
    return norm, [str(norm["qualified_symbol"]), str(norm["signature"])]


def _callsite_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {
        "source_file": _path(identity, "source_file", repo_root),
        "scope_symbol": _symbol(identity, "scope_symbol"),
        "callee_symbol": _symbol(identity, "callee_symbol"),
        "call_span": _span(identity, "call_span"),
    }
    span = norm["call_span"]
    assert isinstance(span, dict)
    return norm, [str(norm["source_file"]), str(norm["scope_symbol"]), str(norm["callee_symbol"]), str(span["start_line"]), str(span["end_line"])]


def _branch_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {"source_file": _path(identity, "source_file", repo_root), "scope_symbol": _symbol(identity, "scope_symbol"), "predicate_span": _span(identity, "predicate_span")}
    span = norm["predicate_span"]
    assert isinstance(span, dict)
    return norm, [str(norm["source_file"]), str(norm["scope_symbol"]), str(span["start_line"]), str(span["end_line"])]


def _branch_outcome_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    if isinstance(identity.get("parent_branch"), dict):
        parent = resolve_identity("branch", identity["parent_branch"], repo_root=repo_root).canonical_key
    else:
        parent = _required_str(identity, "parent_branch_canonical_key")
    outcome = _required_str(identity, "outcome")
    return {"parent_branch_canonical_key": parent, "outcome": outcome}, [parent, outcome]


def _loop_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {"source_file": _path(identity, "source_file", repo_root), "scope_symbol": _symbol(identity, "scope_symbol"), "loop_header_span": _span(identity, "loop_header_span")}
    span = norm["loop_header_span"]
    assert isinstance(span, dict)
    return norm, [str(norm["source_file"]), str(norm["scope_symbol"]), str(span["start_line"]), str(span["end_line"])]


def _tilingdata_field_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {"qualified_struct_name": _symbol(identity, "qualified_struct_name", aliases=("struct_name",)), "field_name": _symbol(identity, "field_name", aliases=("field_ref",))}
    return norm, [str(norm["qualified_struct_name"]), str(norm["field_name"])]


def _qualified_struct_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {"qualified_struct_name": _symbol(identity, "qualified_struct_name", aliases=("struct_name",))}
    return norm, [str(norm["qualified_struct_name"])]


def _tilingdata_access_identity(span_key: str) -> Callable[[dict[str, object], Path], tuple[dict[str, object], list[str]]]:
    def resolve(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
        norm = {
            "source_file": _path(identity, "source_file", repo_root),
            "scope_symbol": _symbol(identity, "scope_symbol"),
            "struct_name": _symbol(identity, "struct_name", aliases=("struct_ref",)),
            "field_name": _symbol(identity, "field_name", aliases=("field_ref",)),
            span_key: _span(identity, span_key),
        }
        span = norm[span_key]
        assert isinstance(span, dict)
        return norm, [str(norm["source_file"]), str(norm["scope_symbol"]), str(norm["struct_name"]), str(norm["field_name"]), str(span["start_line"]), str(span["end_line"])]
    return resolve


def _operator_io_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {"operator_name": _symbol(identity, "operator_name"), "direction": _required_str(identity, "direction"), "index": _required_int(identity, "index")}
    return norm, [str(norm["operator_name"]), str(norm["direction"]), str(norm["index"])]


def _kernel_entry_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {
        "qualified_entry_symbol": _symbol(identity, "qualified_entry_symbol", aliases=("qualified_symbol", "symbol")),
        "signature": _signature(identity, "signature"),
        "discriminator": _clean(str(identity.get("discriminator") or identity.get("architecture_variant") or identity.get("template_binding") or "generic")),
    }
    return norm, [str(norm["qualified_entry_symbol"]), str(norm["signature"]), str(norm["discriminator"])]


def _kernel_slice_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {
        "kernel_entry_ref": _required_str(identity, "kernel_entry_ref"),
        "template_binding_signature": _required_str(identity, "template_binding_signature"),
        "structural_flow_signature": _required_str(identity, "structural_flow_signature"),
        "tilingdata_read_signature": str(identity.get("tilingdata_read_signature") or ""),
        "output_signature": _required_str(identity, "output_signature"),
    }
    return norm, [str(norm[key]) for key in ("kernel_entry_ref", "template_binding_signature", "structural_flow_signature", "tilingdata_read_signature", "output_signature")]


def _slice_interface_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {
        "source_slice_ref": _required_str(identity, "source_slice_ref"),
        "target_slice_ref": _required_str(identity, "target_slice_ref"),
        "interface_kind": _required_str(identity, "interface_kind"),
        "position": str(identity.get("position") if identity.get("position") is not None else identity.get("index") if identity.get("index") is not None else ""),
    }
    if not norm["position"]:
        raise IdentityError("IDENTITY_MISSING_FIELD", "position is required", "identity.position")
    return norm, [str(norm[key]) for key in ("source_slice_ref", "target_slice_ref", "interface_kind", "position")]


def _compute_operation_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {
        "compute_scope": _symbol(identity, "compute_scope", aliases=("scope_symbol",)),
        "operation_type": _required_str(identity, "operation_type"),
        "output_identity": _required_str(identity, "output_identity"),
        "source_span": _span(identity, "source_span"),
    }
    span = norm["source_span"]
    assert isinstance(span, dict)
    return norm, [str(norm["compute_scope"]), str(norm["operation_type"]), str(norm["output_identity"]), str(span["start_line"]), str(span["end_line"])]


def _endpoint_relation_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {
        "source_ref": _required_str(identity, "source_ref"),
        "target_ref": _required_str(identity, "target_ref"),
        "order_index": str(identity.get("order_index") if identity.get("order_index") is not None else ""),
        "condition_ref": str(identity.get("condition_ref") or ""),
        "qualifier": str(identity.get("qualifier") or ""),
    }
    return norm, [str(norm[key]) for key in ("source_ref", "target_ref", "order_index", "condition_ref", "qualifier")]


def _source_span_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    if identity.get("source_file") and identity.get("scope_symbol") and identity.get("source_span"):
        norm = {"source_file": _path(identity, "source_file", repo_root), "scope_symbol": _symbol(identity, "scope_symbol"), "source_span": _span(identity, "source_span")}
        span = norm["source_span"]
        assert isinstance(span, dict)
        return norm, [str(norm["source_file"]), str(norm["scope_symbol"]), str(span["start_line"]), str(span["end_line"])]
    if identity.get("qualified_symbol"):
        norm = {"qualified_symbol": _symbol(identity, "qualified_symbol"), "signature": _signature(identity, "signature") if identity.get("signature") else ""}
        return norm, [str(norm["qualified_symbol"]), str(norm["signature"])]
    raise IdentityError("IDENTITY_MISSING_FIELD", "identity needs structured source span or qualified symbol")


def _repo_path_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {"path": _path(identity, "path", repo_root)}
    return norm, [str(norm["path"])]


def _qualified_symbol_only_identity(identity: dict[str, object], repo_root: Path) -> tuple[dict[str, object], list[str]]:
    norm = {"qualified_symbol": _symbol(identity, "qualified_symbol", aliases=("symbol",))}
    return norm, [str(norm["qualified_symbol"])]


def _path(identity: dict[str, object], key: str, repo_root: Path) -> str:
    raw = _required_str(identity, key).replace("\\", "/")
    path = Path(raw)
    root = repo_root.resolve()
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise IdentityError("IDENTITY_PATH_INVALID", f"{key} must stay within repo root", f"identity.{key}") from exc


def _symbol(identity: dict[str, object], key: str, aliases: tuple[str, ...] = ()) -> str:
    for candidate in (key, *aliases):
        if identity.get(candidate) not in (None, ""):
            return re.sub(r"\s+", " ", str(identity[candidate]).strip())
    raise IdentityError("IDENTITY_MISSING_FIELD", f"{key} is required", f"identity.{key}")


def _signature(identity: dict[str, object], key: str) -> str:
    value = _required_str(identity, key)
    return re.sub(r"\s+", " ", value).replace(" ,", ",").replace("( ", "(").replace(" )", ")")


def _span(identity: dict[str, object], key: str) -> dict[str, int]:
    value = identity.get(key)
    if not isinstance(value, dict):
        raise IdentityError("IDENTITY_MISSING_FIELD", f"{key} is required", f"identity.{key}")
    start = _required_int(value, "start_line", f"identity.{key}.start_line")
    end = _required_int(value, "end_line", f"identity.{key}.end_line")
    if start < 1 or end < start:
        raise IdentityError("IDENTITY_SPAN_INVALID", f"{key} start_line/end_line invalid", f"identity.{key}")
    return {"start_line": start, "end_line": end}


def _required_str(identity: dict[str, object], key: str) -> str:
    value = identity.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IdentityError("IDENTITY_MISSING_FIELD", f"{key} is required", f"identity.{key}")
    return _clean(value)


def _required_int(identity: dict[str, object], key: str, field: str | None = None) -> int:
    value = identity.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise IdentityError("IDENTITY_MISSING_FIELD", f"{key} must be an integer", field or f"identity.{key}")
    return value


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


def _canonical_jsonish(value: Any) -> str:
    if value in (None, {}, []):
        return ""
    if isinstance(value, dict):
        return "{" + ",".join(f"{_canonical_jsonish(key)}:{_canonical_jsonish(value[key])}" for key in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_canonical_jsonish(item) for item in value) + "]"
    return str(value)
