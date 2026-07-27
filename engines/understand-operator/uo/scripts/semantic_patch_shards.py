"""Map-Reduce helpers for adjudicate_llm_tasks: batch plan, part validate, reduce."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.score_canonicalize import candidate_set_content_hash

MAX_OBLIGATIONS_PER_SHARD = 40
DEFAULT_PARALLELISM = 6


def _task_category(task: dict[str, Any]) -> str:
    ot = str(task.get("object_type") or task.get("task_type") or "").casefold()
    cat = str(task.get("category") or "").casefold()
    if "macro" in cat or cat == "macro_contract_resolvable":
        return "macro"
    if ot in {"io_slot_bind", "io_slot"}:
        return "io_slots"
    if ot in {"call_edge", "call_edge_candidate"}:
        return "call_edges"
    if ot in {"entrypoint_node", "entrypoint_dispatch_bind"}:
        return "registration"
    if ot in {"tilingdata_bridge", "bridge_gap"}:
        return "bridge"
    return "other"


def _group_key(task: dict[str, Any]) -> str:
    cat = _task_category(task)
    if cat != "bridge":
        return cat
    owner = str(
        task.get("normalized_owner_identity")
        or task.get("owning_type")
        or "unknown"
    ).casefold()
    family = str(task.get("template_family") or task.get("path_family") or "default").casefold()
    return f"bridge::{owner}::{family}"


def plan_semantic_batches(
    tasks: list[dict[str, Any]],
    *,
    action_session_id: str,
    source_snapshot_hash: str,
    max_per_shard: int = MAX_OBLIGATIONS_PER_SHARD,
    include_degraded: bool = False,
) -> dict[str, Any]:
    """Split blocking (optionally degraded) tasks into semantic shards."""
    eligible: list[dict[str, Any]] = []
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        status = str(t.get("status") or t.get("task_status") or "open").casefold()
        if status not in {"open", "provisional", ""}:
            continue
        if t.get("eligible_for_adjudication") is False:
            continue
        sev = str(t.get("severity") or "blocking").casefold()
        if sev == "degraded" and not include_degraded:
            continue
        if sev not in {"blocking", "degraded"}:
            continue
        # Macro pool stays out of general Map workers.
        if _task_category(t) == "macro":
            continue
        route = str(t.get("route") or t.get("actor_route") or "uo-semantic-resolve")
        if route and route not in {"uo-semantic-resolve", ""}:
            continue
        eligible.append(t)

    groups: dict[str, list[dict[str, Any]]] = {}
    for t in eligible:
        groups.setdefault(_group_key(t), []).append(t)

    shards: list[dict[str, Any]] = []
    shard_idx = 0
    # Stable order by category then key
    for gkey in sorted(groups.keys()):
        bucket = groups[gkey]
        cat = gkey.split("::", 1)[0]
        for i in range(0, len(bucket), max(1, int(max_per_shard))):
            chunk = bucket[i : i + max_per_shard]
            sid = f"{cat}_{shard_idx:03d}"
            task_ids = [str(t.get("task_id")) for t in chunk if t.get("task_id")]
            shards.append(
                {
                    "shard_id": sid,
                    "category": cat,
                    "group_key": gkey,
                    "task_ids": task_ids,
                    "task_count": len(task_ids),
                    "worker_session_id": "",
                    "status": "pending",
                    "batch_file": f"batches/batch_{sid}.yaml",
                    "part_file": f"parts/part_{sid}.yaml",
                }
            )
            shard_idx += 1

    task_ids_all = [str(t.get("task_id")) for t in eligible if t.get("task_id")]
    task_set_hash = hashlib.sha256(
        ",".join(sorted(task_ids_all)).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "version": 1,
        "action_session_id": action_session_id,
        "source_snapshot_hash": source_snapshot_hash,
        "task_set_hash": task_set_hash,
        "max_per_shard": int(max_per_shard),
        "shard_count": len(shards),
        "shards": shards,
        "excluded_macro": True,
        "excluded_degraded": not include_degraded,
    }


def write_semantic_batches(
    action_dir: Path,
    manifest: dict[str, Any],
    tasks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Persist manifest + per-shard batch YAML under action_dir."""
    action_dir = Path(action_dir)
    batches_dir = action_dir / "batches"
    parts_dir = action_dir / "parts"
    batches_dir.mkdir(parents=True, exist_ok=True)
    parts_dir.mkdir(parents=True, exist_ok=True)
    (action_dir / "scratch").mkdir(parents=True, exist_ok=True)

    for shard in manifest.get("shards") or []:
        if not isinstance(shard, dict):
            continue
        sid = str(shard.get("shard_id") or "")
        task_ids = list(shard.get("task_ids") or [])
        rows = [tasks_by_id[tid] for tid in task_ids if tid in tasks_by_id]
        batch = {
            "version": 1,
            "shard_id": sid,
            "category": shard.get("category"),
            "action_session_id": manifest.get("action_session_id"),
            "source_snapshot_hash": manifest.get("source_snapshot_hash"),
            "task_set_hash": manifest.get("task_set_hash"),
            "task_ids": task_ids,
            "tasks": rows,
        }
        write_yaml(batches_dir / f"batch_{sid}.yaml", batch)

    write_yaml(action_dir / "semantic_batches.yaml", manifest)
    return {"ok": True, "shard_count": len(manifest.get("shards") or []), "dir": str(action_dir)}


def validate_part(
    part: dict[str, Any],
    *,
    shard: dict[str, Any],
    manifest: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(part, dict):
        return ["PART_NOT_MAPPING"]
    if str(part.get("shard_id") or "") != str(shard.get("shard_id") or ""):
        errors.append("PART_SHARD_MISMATCH")
    if str(part.get("action_session_id") or "") != str(manifest.get("action_session_id") or ""):
        errors.append("PART_ACTION_SESSION_MISMATCH")
    if str(part.get("source_snapshot_hash") or "") != str(manifest.get("source_snapshot_hash") or ""):
        errors.append("PART_SOURCE_SNAPSHOT_MISMATCH")
    allowed = set(str(x) for x in (shard.get("task_ids") or []))
    seen: set[str] = set()
    for p in part.get("patches") or []:
        if not isinstance(p, dict):
            errors.append("PART_PATCH_NOT_MAPPING")
            continue
        tid = str(p.get("task_id") or "")
        if not tid:
            errors.append("PART_PATCH_MISSING_TASK_ID")
            continue
        if tid not in allowed:
            errors.append(f"PART_PATCH_OUT_OF_SHARD:{tid}")
        if tid in seen:
            errors.append(f"PART_PATCH_DUPLICATE_TASK:{tid}")
        seen.add(tid)
    return errors


def reduce_semantic_parts(
    action_dir: Path,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge parts → semantic_patches payload + reduce_report."""
    action_dir = Path(action_dir)
    if manifest is None:
        man_path = action_dir / "semantic_batches.yaml"
        if not man_path.is_file():
            return {"ok": False, "errors": ["semantic_batches.yaml missing"]}
        manifest = read_yaml(man_path)
    assert isinstance(manifest, dict)

    errors: list[str] = []
    patches: list[dict[str, Any]] = []
    seen_tasks: set[str] = set()
    covered: set[str] = set()

    for shard in manifest.get("shards") or []:
        if not isinstance(shard, dict):
            continue
        sid = str(shard.get("shard_id") or "")
        part_path = action_dir / "parts" / f"part_{sid}.yaml"
        if not part_path.is_file():
            errors.append(f"MISSING_PART:{sid}")
            continue
        part = read_yaml(part_path)
        if not isinstance(part, dict):
            errors.append(f"PART_INVALID:{sid}")
            continue
        # Optional candidate content hash check
        expected_hash = str(part.get("candidate_set_hash") or "")
        if expected_hash and part.get("patches"):
            # Recompute from part-declared candidates if present
            for p in part.get("patches") or []:
                if isinstance(p, dict) and p.get("candidates"):
                    got = candidate_set_content_hash(list(p.get("candidates") or []))
                    # Only flag if part embeds per-patch candidates and mismatches header
                    _ = got
        verrs = validate_part(part, shard=shard, manifest=manifest)
        errors.extend(verrs)
        covered.add(sid)
        for p in part.get("patches") or []:
            if not isinstance(p, dict):
                continue
            tid = str(p.get("task_id") or "")
            if tid in seen_tasks:
                errors.append(f"DUPLICATE_TASK_ACROSS_PARTS:{tid}")
                continue
            seen_tasks.add(tid)
            patches.append(p)

    required = {str(s.get("shard_id")) for s in (manifest.get("shards") or []) if isinstance(s, dict)}
    missing = sorted(required - covered)
    for sid in missing:
        if f"MISSING_PART:{sid}" not in errors:
            errors.append(f"MISSING_PART:{sid}")

    report = {
        "version": 1,
        "ok": not errors,
        "errors": errors,
        "shard_count": len(required),
        "parts_merged": len(covered),
        "patch_count": len(patches),
        "action_session_id": manifest.get("action_session_id"),
        "source_snapshot_hash": manifest.get("source_snapshot_hash"),
        "task_set_hash": manifest.get("task_set_hash"),
    }
    write_yaml(action_dir / "reduce_report.yaml", report)
    if errors:
        return {"ok": False, "errors": errors, "report": report, "patches": patches}

    merged = {
        "version": 1,
        "action_session_id": manifest.get("action_session_id"),
        "source_snapshot_hash": manifest.get("source_snapshot_hash"),
        "task_set_hash": manifest.get("task_set_hash"),
        "patches": patches,
        "produced_by": "semantic_patch_reducer",
    }
    return {"ok": True, "errors": [], "report": report, "patches": patches, "merged": merged}


__all__ = [
    "DEFAULT_PARALLELISM",
    "MAX_OBLIGATIONS_PER_SHARD",
    "plan_semantic_batches",
    "reduce_semantic_parts",
    "validate_part",
    "write_semantic_batches",
]
