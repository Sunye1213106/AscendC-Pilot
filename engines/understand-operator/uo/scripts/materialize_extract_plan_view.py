"""从 HCG + TCG 物化 extract_plan 视图（可删可重建，非权威）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import write_yaml
from uo.scripts.host_configuration_builder import load_host_configuration
from uo.scripts.tiling_contract_builder import load_tiling_contract

VIEW_VERSION = "1.0.0"


def materialize_extract_plan_view(
    repo_root: Path,
    op_name: str,
    *,
    uo_root: Path | None = None,
) -> dict[str, Any]:
    from uo._operator.artifacts import existing_operator_root

    root = uo_root or existing_operator_root(repo_root, op_name)
    ir_dir = root / "ir"
    hcg = load_host_configuration(root)
    tcg = load_tiling_contract(root)

    writers: list[dict[str, Any]] = []
    receivers: list[dict[str, Any]] = []
    seen_writers: set[str] = set()
    seen_receivers: set[str] = set()

    for ent in tcg.get("entities") or []:
        kind = ent.get("kind")
        if kind == "FieldWrite":
            fn = str(ent.get("writer_function") or "")
            if fn and fn not in seen_writers:
                seen_writers.add(fn)
                writers.append(
                    {
                        "name": fn,
                        "role": "tiling_writer",
                        "derived_from": "WRITES_FIELD",
                        "entity_id": ent["id"],
                    }
                )
            recv = str(ent.get("receiver") or "")
            if recv and recv not in seen_receivers:
                seen_receivers.add(recv)
                receivers.append(
                    {
                        "name": recv,
                        "root_schema_variant": ent.get("schema_variant"),
                        "entity_id": ent["id"],
                    }
                )
        if kind in {"KeyReturnComposer", "KeyContextMutation", "ObservedKeyComposition"}:
            name = str(ent.get("qualified_name") or ent.get("composer_function") or kind)
            key = f"key:{name}"
            if key not in seen_writers:
                seen_writers.add(key)
                writers.append(
                    {
                        "name": name,
                        "role": "key_writer",
                        "derived_from": "COMPOSES_TILING_KEY",
                        "entity_id": ent["id"],
                    }
                )
        if kind == "HostContractEndpoint" and ent.get("channel_type") == "WORKSPACE_CHANNEL":
            writers.append(
                {
                    "name": str(ent.get("qualified_name") or "workspace"),
                    "role": "workspace_writer",
                    "derived_from": "WORKSPACE_CHANNEL",
                    "entity_id": ent["id"],
                }
            )

    # Also from HCG function summaries with guarded setter effects
    for summary in hcg.get("function_summaries") or []:
        fn = str(summary.get("function_name") or "")
        if not fn or fn in seen_writers:
            continue
        if summary.get("guarded_effects"):
            seen_writers.add(fn)
            writers.append(
                {
                    "name": fn,
                    "role": "tiling_writer",
                    "derived_from": "HostFunctionSummary.guarded_effects",
                    "entity_id": summary.get("function_id"),
                }
            )

    plan = {
        "version": VIEW_VERSION,
        "materialized_view": True,
        "authoritative": False,
        "note_zh": "extract_plan 为可删可重建视图；权威为 host_configuration_graph + tiling_contract_graph",
        "writers": writers,
        "receivers": receivers,
        "aliases_ref": "uo/ir/extract_plan_aliases.yaml",
        "receiver_bindings_ref": "uo/ir/receiver_bindings.yaml",
        "host_configuration_ref": "uo/ir/host_configuration_graph.yaml",
        "tiling_contract_ref": "uo/ir/tiling_contract_graph.yaml",
        "counts": {
            "writers": len(writers),
            "receivers": len(receivers),
            "tiling_writers": len([w for w in writers if w.get("role") == "tiling_writer"]),
            "key_writers": len([w for w in writers if w.get("role") == "key_writer"]),
        },
        "compile_context_id": hcg.get("compile_context_id") or tcg.get("compile_context_id"),
    }
    write_yaml(ir_dir / "extract_plan.yaml", plan)
    return plan
