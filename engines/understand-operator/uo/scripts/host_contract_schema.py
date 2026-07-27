"""Host Configuration / Tiling Contract 统一 Schema。

所有 HCG/TCG 模块必须复用本模块的 Entity / Edge / Expression / Evidence，
禁止并行发明 dependencies / rhs_symbols 等平行字段名。
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# 时间语义 / 选择效应（强制枚举）
# ---------------------------------------------------------------------------

BINDING_TIMES = frozenset(
    {
        "build_time",
        "host_runtime",
        "kernel_compile_time",
        "kernel_runtime",
    }
)

SELECTION_EFFECTS = frozenset(
    {
        "filters_source_region",
        "selects_tiling_implementation",
        "composes_tiling_key",
        "selects_kernel_variant",
    }
)

EVIDENCE_LEVELS = frozenset(
    {
        "compiler_fact",
        "structured_source_fact",
        "macro_contract_fact",
        "cbm_fact",
        "lexical_hint",
        "llm_confirmed",
    }
)

CONTRACT_STATUSES = frozenset(
    {
        "producer_only",
        "consumer_only",
        "matched",
        "conflicted",
    }
)

CONFIGURATION_ROOT_KINDS = frozenset(
    {
        "OperatorInputRoot",
        "OptionalInputRoot",
        "OperatorAttributeRoot",
        "ShapeRoot",
        "PlatformRoot",
        "BuildConfigRoot",
        "ArchitectureRoot",
        "ConstantRoot",
        "RegistrationRoot",
    }
)

COMPOSITION_STRATEGIES = frozenset(
    {
        "positional_full_key",
        "positional_dimension_selection",
        "context_mutation",
        "nested_selector",
    }
)

CONTRACT_CLASSES = frozenset(
    {
        "framework_required",
        "optional_framework_pattern",
        "repository_discovered",
    }
)

SCHEMA_VERSION = "1.0.0"


def stable_id(*parts: Any, prefix: str = "") -> str:
    raw = "|".join(str(p) for p in parts if p is not None)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}{digest}" if prefix else digest


def make_entity(
    *,
    kind: str,
    identity_key: str,
    qualified_name: str = "",
    binding_time: str | None = None,
    architecture: str = "",
    compile_context_id: str = "",
    source_region_id: str = "",
    evidence_refs: Sequence[str] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if binding_time is not None and binding_time not in BINDING_TIMES:
        raise ValueError(f"非法 binding_time: {binding_time}")
    entity: dict[str, Any] = {
        "id": stable_id(kind, identity_key, prefix=f"{kind}:"),
        "kind": kind,
        "identity_key": identity_key,
        "qualified_name": qualified_name or identity_key,
        "architecture": architecture,
        "compile_context_id": compile_context_id,
        "source_region_id": source_region_id,
        "evidence_refs": list(evidence_refs or []),
    }
    if binding_time is not None:
        entity["binding_time"] = binding_time
    if extra:
        for key, value in extra.items():
            if key not in entity:
                entity[key] = value
    return entity


def make_expression_ir(
    *,
    kind: str,
    op: str = "",
    operands: Sequence[Any] | None = None,
    symbols: Sequence[str] | None = None,
    constants: Sequence[Any] | None = None,
    type_name: str = "",
    source_text: str = "",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "op": op,
        "operands": list(operands or []),
        "symbols": list(symbols or []),
        "constants": list(constants or []),
        "type": type_name,
        "source_text": source_text,
    }


def make_edge(
    *,
    edge_type: str,
    source_ids: Sequence[str],
    target_ids: Sequence[str],
    guard_context: Mapping[str, Any] | None = None,
    transform: Mapping[str, Any] | str | None = None,
    evidence_refs: Sequence[str] | None = None,
    confidence: float | str | None = None,
    origin: str = "deterministic",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    src = list(source_ids)
    tgt = list(target_ids)
    edge: dict[str, Any] = {
        "id": stable_id(edge_type, ",".join(src), ",".join(tgt), prefix="E:"),
        "type": edge_type,
        "source_ids": src,
        "target_ids": tgt,
        "guard_context": dict(guard_context or {}),
        "transform": transform if transform is not None else {},
        "evidence_refs": list(evidence_refs or []),
        "confidence": confidence if confidence is not None else "deterministic",
        "origin": origin,
    }
    if extra:
        for key, value in extra.items():
            if key not in edge:
                edge[key] = value
    return edge


def make_evidence(
    *,
    file_path: str,
    start_line: int,
    end_line: int | None = None,
    sha256: str = "",
    source_snapshot_hash: str = "",
    extractor: str = "",
    extractor_version: str = "",
    evidence_level: str = "structured_source_fact",
    evidence_id: str | None = None,
) -> dict[str, Any]:
    if evidence_level not in EVIDENCE_LEVELS:
        raise ValueError(f"非法 evidence_level: {evidence_level}")
    end = int(end_line if end_line is not None else start_line)
    eid = evidence_id or stable_id(
        file_path, start_line, end, sha256, prefix="EV:"
    )
    return {
        "id": eid,
        "file_path": str(file_path).replace("\\", "/"),
        "start_line": int(start_line),
        "end_line": end,
        "sha256": sha256,
        "source_snapshot_hash": source_snapshot_hash,
        "extractor": extractor,
        "extractor_version": extractor_version,
        "evidence_level": evidence_level,
    }


def make_guard_context(
    *,
    binding_time: str,
    selection_effect: Sequence[str] | None = None,
    condition_text: str = "",
    condition_class: str = "",
    active: bool | None = None,
) -> dict[str, Any]:
    if binding_time not in BINDING_TIMES:
        raise ValueError(f"非法 binding_time: {binding_time}")
    effects = list(selection_effect or [])
    for effect in effects:
        if effect not in SELECTION_EFFECTS:
            raise ValueError(f"非法 selection_effect: {effect}")
    return {
        "binding_time": binding_time,
        "selection_effect": effects,
        "condition_text": condition_text,
        "condition_class": condition_class,
        "active": active,
    }


def validate_entity(entity: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("id", "kind", "identity_key"):
        if not entity.get(key):
            errors.append(f"实体缺少字段: {key}")
    bt = entity.get("binding_time")
    if bt is not None and bt not in BINDING_TIMES:
        errors.append(f"实体 binding_time 非法: {bt}")
    return errors


def validate_edge(edge: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not edge.get("id"):
        errors.append("边缺少 id")
    if not edge.get("type"):
        errors.append("边缺少 type")
    if not isinstance(edge.get("source_ids"), list):
        errors.append("边 source_ids 必须为列表")
    if not isinstance(edge.get("target_ids"), list):
        errors.append("边 target_ids 必须为列表")
    return errors


def index_entities(entities: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in entities:
        if isinstance(item, Mapping) and item.get("id"):
            out[str(item["id"])] = dict(item)
    return out


def empty_graph_doc(
    *,
    graph_kind: str,
    compile_context_id: str = "",
    architecture: str = "",
    source_snapshot_hash: str = "",
) -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "graph_kind": graph_kind,
        "compile_context_id": compile_context_id,
        "architecture": architecture,
        "source_snapshot_hash": source_snapshot_hash,
        "entities": [],
        "edges": [],
        "evidence": [],
        "unresolved": [],
    }
