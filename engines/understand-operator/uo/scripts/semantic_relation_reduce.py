"""Reduce relation parts：唯一 schema 为 decisions[]。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.llm_work_scheduler import reduce_llm_parts
from uo.scripts.relation_evidence import validate_relation_decision_against_obligation
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
    """按 conflict_group 分片 llm_required obligations。"""
    from uo.scripts.llm_work_scheduler import plan_llm_work_shards

    items = []
    for obl in obligations.get("llm_required") or []:
        if not isinstance(obl, dict):
            continue
        row = dict(obl)
        row["obligation_id"] = obl.get("obligation_id")
        # conflict_group 必须细粒度；禁止整 pool 作为一个 conflict group
        cg = str(obl.get("conflict_group") or "").strip()
        if not cg or cg == str(obl.get("pool") or ""):
            cg = str(obl.get("obligation_id") or "relation")
        row["conflict_group"] = cg
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
        group_key_fn=lambda it: str(it.get("conflict_group") or it.get("obligation_id") or "relation"),
        id_keys=("obligation_id",),
        batch_dir="batches",
        part_dir="staging/relation_parts",
    )
    manifest["pruned"] = {"llm_obligations": items}
    return manifest


def _obl_index(action_dir: Path) -> dict[str, dict[str, Any]]:
    path = Path(action_dir) / "inputs" / "semantic_obligations.yaml"
    if not path.is_file():
        return {}
    doc = read_yaml(path) or {}
    out: dict[str, dict[str, Any]] = {}
    for bucket in ("llm_required", "deterministic"):
        for o in (doc.get(bucket) or []) if isinstance(doc, dict) else []:
            if isinstance(o, dict) and o.get("obligation_id"):
                out[str(o["obligation_id"])] = o
    return out


def _atomic_write_yaml(path: Path, doc: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    write_yaml(tmp, doc)
    os.replace(tmp, path)


def reduce_relation_parts(
    action_dir: Path,
    base_graph: dict[str, Any],
    *,
    only_failed: bool = False,
    part_root: str = "staging/relation_parts",
    manifest_name: str = "relation_batches.yaml",
) -> dict[str, Any]:
    """合并 relation part → staging/semantic_relations.yaml（原子写）。"""
    action_dir = Path(action_dir)
    man_path = action_dir / "inputs" / manifest_name
    manifest = read_yaml(man_path) if man_path.is_file() else {"shards": []}
    if not isinstance(manifest, dict):
        manifest = {"shards": []}

    session_id = str(manifest.get("action_session_id") or "")
    snap_hash = str(manifest.get("source_snapshot_hash") or "")
    obl_by_id = _obl_index(action_dir)

    reduced = reduce_llm_parts(
        action_dir,
        manifest=manifest,
        manifest_name=manifest_name,
        parts_subdir=part_root,
        decision_key="decisions",
        id_field="obligation_id",
        only_failed=only_failed,
    )

    errors: list[str] = list(reduced.get("errors") or [])
    parts: list[dict[str, Any]] = []
    seen_obl: set[str] = set()
    part_dir = action_dir / part_root

    expected_shards = [
        s for s in (manifest.get("shards") or []) if isinstance(s, dict)
    ]
    for shard in expected_shards:
        part_file = str(shard.get("part_file") or "")
        p = action_dir / part_file if part_file else None
        if p is None or not p.is_file():
            # 也尝试 part_NNN.yaml
            sid = str(shard.get("shard_id") or shard.get("shard_index") or "")
            alt = part_dir / f"part_{sid}.yaml" if sid else None
            if alt is None or not alt.is_file():
                errors.append(f"缺少 shard part: {part_file or sid}")
                continue
            p = alt
        doc = read_yaml(p)
        if not isinstance(doc, dict):
            errors.append(f"part 非 mapping: {p.name}")
            continue
        if session_id and str(doc.get("action_session_id") or "") not in {"", session_id}:
            errors.append(f"session 不匹配: {p.name}")
            continue
        if snap_hash and str(doc.get("source_snapshot_hash") or "") not in {"", snap_hash}:
            errors.append(f"source_snapshot_hash 不匹配: {p.name}")
            continue
        decisions = doc.get("decisions")
        if not isinstance(decisions, list):
            errors.append(f"缺少 decisions[]: {p.name}")
            continue
        shard_oids = {
            str(x)
            for x in (shard.get("obligation_ids") or [])
            if str(x).strip()
        }
        for d in decisions:
            if not isinstance(d, dict):
                continue
            oid = str(d.get("obligation_id") or "").strip()
            if not oid:
                errors.append(f"decision 缺少 obligation_id: {p.name}")
                continue
            if oid in seen_obl:
                errors.append(f"obligation 重复出现: {oid}")
                continue
            seen_obl.add(oid)
            obl = obl_by_id.get(oid) or {}
            check = validate_relation_decision_against_obligation(
                d, obl if obl else {"obligation_id": oid}, shard_obligation_ids=shard_oids or None
            )
            if not check.get("ok"):
                errors.append(str(check.get("message") or check.get("error")))
                continue
            parts.append(d)

    # 覆盖校验：每个 expected llm obligation 恰好一次
    expected_oids = set()
    for shard in expected_shards:
        for oid in shard.get("obligation_ids") or []:
            expected_oids.add(str(oid))
    missing = sorted(expected_oids - seen_obl)
    if missing and not only_failed:
        errors.append(f"obligation 未覆盖: {missing[:20]}")

    graph = merge_llm_relation_parts(base_graph, parts)
    # unresolved decisions
    for d in parts:
        if str(d.get("status") or "").lower() == "unresolved":
            graph.setdefault("unresolved", []).append(
                {
                    "obligation_id": d.get("obligation_id"),
                    "reason_code": d.get("reason_code") or "unresolved",
                    "status": "unresolved",
                    "affected_entity_ids": list(d.get("affected_entity_ids") or []),
                    "affected_relation_ids": list(d.get("affected_relation_ids") or []),
                }
            )

    grounding_errors = validate_input_root_grounding(graph)
    staging = action_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    _atomic_write_yaml(staging / "semantic_relations.yaml", graph)

    ok = bool(reduced.get("ok", True)) and not errors and not any(
        str(u.get("status") or "") == "conflict"
        for u in (graph.get("unresolved") or [])
        if isinstance(u, dict)
    )
    hard = [e for e in grounding_errors if "does not reach" in e or "无法到达" in e]
    retry = list(reduced.get("retry_shards") or reduced.get("failed_shards") or [])
    return {
        "ok": ok and not hard,
        "graph": graph,
        "reduce": reduced,
        "grounding_errors": grounding_errors,
        "errors": errors + hard,
        "retry_shards": retry,
    }


def failed_shards_safe(reduced: dict[str, Any]) -> list[str]:
    return list(reduced.get("retry_shards") or reduced.get("failed_shards") or [])


__all__ = [
    "plan_relation_batches",
    "reduce_relation_parts",
    "failed_shards_safe",
]
