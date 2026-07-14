from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from understand_operator._operator.candidate import stable_id


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
    if kind not in KIND_TO_PREFIX:
        raise IdentityError("IDENTITY_KIND_UNSUPPORTED", f"unsupported identity kind: {kind}", "kind")
    if not isinstance(identity, dict):
        raise IdentityError("IDENTITY_MISSING", "identity must be an object")
    resolver = _strategy_for_kind(kind)
    normalized, parts = resolver(identity, repo_root)
    canonical_key = ":".join([kind, *(_escape(part) for part in parts)])
    prefix = KIND_TO_PREFIX[kind]
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


def _strategy_for_kind(kind: str) -> Callable[[dict[str, object], Path], tuple[dict[str, object], list[str]]]:
    if KIND_TO_PREFIX[kind] == "VAR":
        return _local_variable_identity
    if kind in {"function", "host_function", "kernel_function", "kernel_method", "helper_function"}:
        return _function_identity
    if KIND_TO_PREFIX[kind] in {"CALL", "API"}:
        return _callsite_identity
    if KIND_TO_PREFIX[kind] == "BRANCH":
        return _branch_identity
    if KIND_TO_PREFIX[kind] == "OUTCOME":
        return _branch_outcome_identity
    if KIND_TO_PREFIX[kind] == "LOOP":
        return _loop_identity
    if KIND_TO_PREFIX[kind] == "TDATA":
        return _tilingdata_field_identity
    if KIND_TO_PREFIX[kind] == "TDWRITE":
        return _tilingdata_access_identity("write_span")
    if KIND_TO_PREFIX[kind] == "TDREAD":
        return _tilingdata_access_identity("read_span")
    if kind in {"input_tensor", "output_tensor"}:
        return _operator_io_identity
    if KIND_TO_PREFIX[kind] == "KERNEL":
        return _kernel_entry_identity
    if KIND_TO_PREFIX[kind] == "OPR":
        return _compute_operation_identity
    return _source_span_identity


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


def _path(identity: dict[str, object], key: str, repo_root: Path) -> str:
    raw = _required_str(identity, key).replace("\\", "/")
    path = Path(raw)
    if path.is_absolute():
        try:
            raw = path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError as exc:
            raise IdentityError("IDENTITY_PATH_INVALID", f"{key} must be repo-relative", f"identity.{key}") from exc
    return re.sub(r"/+", "/", raw).strip("/")


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
