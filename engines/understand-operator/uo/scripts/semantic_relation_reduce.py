"""Reduce relation parts and validate coverage / conflicts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.llm_work_scheduler import reduce_llm_parts
from uo.scripts.semantic_graph_builder import (
    merge_llm_relation_parts,
    validate_input_root_grounding,
)


def plan_relation_batches(
    obligations: dict[str, Any],
    *,
    action_session_id: str,
    source_snapshot_hash: str = "",
    max_items_per_shard: int = 30,
) -> dict[str, Any]:
    """Shard llm_required obligations via llm_work_scheduler."""
    from uo.scripts.llm_work_scheduler import plan_llm_work_shards

    items = []
    for obl in obligations.get("llm_required") or []:
        if not isinstance(obl, dict):
            continue
        row = dict(obl)
        row["obligation_id"] = obl.get("obligation_id")
        row["conflict_group"] = str(obl.get("pool") or "relation")
        items.append(row)

    if not items:
        return {
            "version": 1,
            "action_session_id": action_session_id,
            "source_snapshot_hash": source_snapshot_hash,
            "obligation_count": 0,
            "shard_count": 0,
            "shards": [],
            "pruned": {"llm_obligations": []},
            "ok": True,
            "errors": [],
        }

    manifest = plan_llm_work_shards(
        items,
        action_session_id=action_session_id,
        source_snapshot_hash=source_snapshot_hash,
        max_per_shard=max_items_per_shard,
        group_key_fn=lambda it: str(it.get("conflict_group") or it.get("pool") or "relation"),
        id_keys=("obligation_id", "candidate_id", "id"),
        batch_dir="batches",
        part_dir="staging/relation_parts",
    )
    manifest["pruned"] = {"llm_obligations": items}
    return manifest


def reduce_relation_parts(
    action_dir: Path,
    base_graph: dict[str, Any],
    *,
    only_failed: bool = False,
    part_root: str = "staging/relation_parts",
    manifest_name: str = "relation_batches.yaml",
) -> dict[str, Any]:
    """Merge relation part YAMLs into base_graph; write semantic_relations.yaml."""
    action_dir = Path(action_dir)
    man_path = action_dir / "inputs" / manifest_name
    manifest = read_yaml(man_path) if man_path.is_file() else {"shards": []}
    reduced = reduce_llm_parts(
        action_dir,
        manifest=manifest if isinstance(manifest, dict) else {},
        manifest_name=manifest_name,
        parts_subdir=part_root,
        decision_key="relations",
        id_field="obligation_id",
        only_failed=only_failed,
    )
    parts = []
    part_dir = action_dir / part_root
    if part_dir.is_dir():
        for p in sorted(part_dir.glob("part_*.yaml")):
            doc = read_yaml(p)
            if isinstance(doc, dict):
                if "decisions" in doc and isinstance(doc["decisions"], list):
                    parts.extend([d for d in doc["decisions"] if isinstance(d, dict)])
                elif "relations" in doc and isinstance(doc.get("status"), str):
                    parts.append(doc)
                else:
                    parts.append(doc)

    graph = merge_llm_relation_parts(base_graph, parts)
    grounding_errors = validate_input_root_grounding(graph)
    staging = action_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    write_yaml(staging / "semantic_relations.yaml", graph)

    ok = bool(reduced.get("ok", True)) and not any(
        str(u.get("status") or "") == "conflict"
        for u in (graph.get("unresolved") or [])
        if isinstance(u, dict)
    )
    hard = [e for e in grounding_errors if "does not reach" in e]
    return {
        "ok": ok and not hard,
        "graph": graph,
        "reduce": reduced,
        "grounding_errors": grounding_errors,
        "errors": list(reduced.get("errors") or []) + hard,
        "retry_shards": reduced.get("retry_shards") or failed_shards_safe(reduced),
    }


def failed_shards_safe(reduced: dict[str, Any]) -> list[str]:
    return list(reduced.get("retry_shards") or reduced.get("failed_shards") or [])



__all__ = [
    "plan_relation_batches",
    "reduce_relation_parts",
]
