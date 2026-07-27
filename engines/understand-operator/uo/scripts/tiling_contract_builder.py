"""组装 ir/tiling_contract_graph.yaml（Host producer_only）。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import write_yaml
from uo.scripts.host_compile_context import load_host_compile_context
from uo.scripts.host_configuration_builder import load_host_configuration
from uo.scripts.host_contract_schema import empty_graph_doc, make_edge, make_entity
from uo.scripts.tiling_data_flow import build_tiling_data_flow
from uo.scripts.tiling_data_schema import build_tiling_data_schemas
from uo.scripts.tiling_key_composition import build_tiling_key_composition

CONTRACT_VERSION = "1.1.0"


def _dedupe_unresolved(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for u in items:
        if not isinstance(u, dict):
            continue
        key = "|".join(
            [
                str(u.get("reason_code") or ""),
                str(u.get("receiver") or ""),
                str(u.get("field") or u.get("field_path") or ""),
                str(u.get("symbol") or u.get("argument") or ""),
                str(u.get("file_path") or ""),
                str(u.get("line") or u.get("position") or ""),
                str(u.get("fact_id") or u.get("edge_id") or ""),
                str(u.get("callee") or ""),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def build_tiling_contract(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    uo_root: Path | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    from uo._operator.artifacts import existing_operator_root

    root = uo_root or existing_operator_root(repo_root, op_name)
    ir_dir = root / "ir"
    ir_dir.mkdir(parents=True, exist_ok=True)

    ctx = load_host_compile_context(root)
    ccid = str(ctx.get("compile_context_id") or "")
    snapshot = str(ctx.get("source_snapshot_hash") or "")
    hcg = load_host_configuration(root)

    schemas = build_tiling_data_schemas(
        repo_root, op_name, architecture=architecture, uo_root=root
    )
    flow = build_tiling_data_flow(
        repo_root,
        op_name,
        architecture=architecture,
        uo_root=root,
        schema_entities=schemas.get("entities") or [],
    )
    keys = build_tiling_key_composition(
        repo_root, op_name, architecture=architecture, uo_root=root
    )

    doc = empty_graph_doc(
        graph_kind="tiling_contract",
        compile_context_id=ccid,
        architecture=architecture,
        source_snapshot_hash=snapshot,
    )
    doc["contract_status"] = "producer_only"
    doc["kb_status"] = "partial"
    doc["build_profile"] = "host_contract_only"
    doc["completed_capabilities"] = ["host_configuration", "tiling_contract_producer"]
    doc["pending_capabilities"] = [
        "kernel_variant",
        "kernel_execution",
        "bridge_consumer",
    ]

    entities = list(schemas.get("entities") or []) + list(flow.get("entities") or []) + list(
        keys.get("entities") or []
    )
    edges = list(flow.get("edges") or []) + list(keys.get("edges") or [])
    evidence = (
        list(schemas.get("evidence") or [])
        + list(flow.get("evidence") or [])
        + list(keys.get("evidence") or [])
    )
    unresolved = (
        list(schemas.get("unresolved") or [])
        + list(flow.get("unresolved") or [])
        + list(keys.get("unresolved") or [])
    )
    unresolved = _dedupe_unresolved(unresolved)

    # HostContractEndpoint channels (producer_only)
    endpoints: list[dict[str, Any]] = []
    for ent in entities:
        if ent.get("kind") == "FieldWrite":
            ep = make_entity(
                kind="HostContractEndpoint",
                identity_key=f"endpoint:field:{ent['id']}",
                qualified_name=str(ent.get("field_path") or ent.get("qualified_name")),
                binding_time="host_runtime",
                architecture=architecture,
                compile_context_id=ccid,
                extra={
                    "channel_type": "TILING_FIELD_CHANNEL",
                    "contract_status": "producer_only",
                    "producer": ent["id"],
                    "carrier": ent.get("schema_variant"),
                    "consumer": None,
                    "consumer_status": "pending_kernel_analysis",
                    "input_roots": [],
                    "guard_context": ent.get("guard_context") or {},
                    "evidence_refs": ent.get("evidence_refs") or [],
                },
            )
            endpoints.append(ep)
            edges.append(
                make_edge(
                    edge_type="PRODUCES_CHANNEL",
                    source_ids=[ent["id"]],
                    target_ids=[ep["id"]],
                )
            )
        if ent.get("kind") in {
            "KeyReturnComposer",
            "KeyContextMutation",
            "ObservedKeyComposition",
        }:
            ep = make_entity(
                kind="HostContractEndpoint",
                identity_key=f"endpoint:key:{ent['id']}",
                qualified_name=str(ent.get("qualified_name")),
                binding_time="host_runtime",
                architecture=architecture,
                compile_context_id=ccid,
                extra={
                    "channel_type": "TILING_KEY_CHANNEL",
                    "contract_status": "producer_only",
                    "producer": ent["id"],
                    "consumer": None,
                    "consumer_status": "pending_kernel_analysis",
                    "producer_binding_time": "host_runtime",
                    "consumer_binding_time": "kernel_compile_time",
                    "evidence_refs": ent.get("evidence_refs") or [],
                },
            )
            endpoints.append(ep)

    # TilingImplementation from compile context
    for impl in ctx.get("tiling_implementations") or []:
        entities.append(
            make_entity(
                kind="TilingImplementation",
                identity_key=f"TilingImpl:{impl.get('template_class')}:{impl.get('architecture')}",
                qualified_name=str(impl.get("template_class") or ""),
                binding_time="build_time",
                architecture=str(impl.get("architecture") or architecture),
                compile_context_id=ccid,
                extra=dict(impl),
            )
        )

    doc["entities"] = entities + endpoints
    doc["edges"] = edges
    doc["evidence"] = evidence
    doc["unresolved"] = unresolved
    doc["host_configuration_ref"] = {
        "compile_context_id": hcg.get("compile_context_id"),
        "entity_count": len(hcg.get("entities") or []),
    }
    doc["declared_key_space"] = {
        "dimensions": (keys.get("declared") or {}).get("dimensions") or [],
    }
    doc["counts"] = {
        "entities": len(doc["entities"]),
        "edges": len(edges),
        "endpoints": len(endpoints),
        "unresolved": len(unresolved),
        "field_writes": len([e for e in entities if e.get("kind") == "FieldWrite"]),
        "key_dimensions": len(doc["declared_key_space"]["dimensions"]),
    }
    doc["builder_version"] = CONTRACT_VERSION
    doc["timing_ms"] = int((time.perf_counter() - t0) * 1000)
    write_yaml(ir_dir / "tiling_contract_graph.yaml", doc)
    return doc


def load_tiling_contract(uo_root: Path) -> dict[str, Any]:
    from uo.scripts._ir_io import read_yaml

    return read_yaml(uo_root / "ir" / "tiling_contract_graph.yaml") or {}
