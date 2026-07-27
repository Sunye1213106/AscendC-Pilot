"""Map-Reduce helpers for adjudicate_llm_tasks: batch plan, part validate, reduce.

Uses public ``llm_work_scheduler`` (max 30 obligations + token budget).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.llm_work_scheduler import (
    DEFAULT_TOKEN_BUDGET,
    MAX_OBLIGATIONS_PER_SHARD,
    build_dispatch_tasks,
    plan_llm_work_shards,
    reduce_llm_parts,
    require_valid_manifest,
    validate_llm_part,
    write_llm_batches,
)

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
    token_budget: int = DEFAULT_TOKEN_BUDGET,
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
        if _task_category(t) == "macro":
            continue
        route = str(t.get("route") or t.get("actor_route") or "uo-semantic-resolve")
        if route and route not in {"uo-semantic-resolve", ""}:
            continue
        row = dict(t)
        row["obligation_id"] = str(t.get("task_id") or "")
        eligible.append(row)

    manifest = plan_llm_work_shards(
        eligible,
        action_session_id=action_session_id,
        source_snapshot_hash=source_snapshot_hash,
        max_per_shard=max_per_shard,
        token_budget=token_budget,
        group_key_fn=_group_key,
        id_keys=("obligation_id", "task_id"),
        batch_dir="batches",
        part_dir="parts",
        batch_name_fn=lambda sid, _idx: f"batches/batch_{sid}.yaml",
        part_name_fn=lambda sid, _idx: f"parts/part_{sid}.yaml",
    )
    for sh in manifest.get("shards") or []:
        if isinstance(sh, dict):
            sh["task_ids"] = list(sh.get("obligation_ids") or [])
            sh["task_count"] = sh.get("obligation_count")
    manifest["task_set_hash"] = manifest.get("obligation_set_hash")
    manifest["excluded_macro"] = True
    manifest["excluded_degraded"] = not include_degraded
    return manifest


def write_semantic_batches(
    action_dir: Path,
    manifest: dict[str, Any],
    tasks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Persist manifest + per-shard batch YAML under action_dir."""
    by_obl: dict[str, dict[str, Any]] = {}
    for tid, t in (tasks_by_id or {}).items():
        if isinstance(t, dict):
            by_obl[str(tid)] = t
    return write_llm_batches(
        action_dir,
        manifest,
        by_obl,
        batches_subdir="batches",
        parts_subdir="parts",
        manifest_name="semantic_batches.yaml",
    )


def validate_part(
    part: dict[str, Any],
    *,
    shard: dict[str, Any],
    manifest: dict[str, Any],
) -> list[str]:
    sh = dict(shard)
    if not sh.get("obligation_ids") and sh.get("task_ids"):
        sh["obligation_ids"] = list(sh.get("task_ids") or [])
        sh["obligation_count"] = len(sh["obligation_ids"])
    adapted = dict(part) if isinstance(part, dict) else {}
    if "patches" in adapted and "decisions" not in adapted:
        adapted["decisions"] = [
            {**p, "candidate_id": p.get("task_id")}
            for p in (adapted.get("patches") or [])
            if isinstance(p, dict)
        ]
    errs = validate_llm_part(
        adapted,
        shard=sh,
        manifest=manifest,
        decision_key="decisions",
        id_field="candidate_id",
    )
    out = []
    for e in errs:
        out.append(
            e.replace("PART_DECISION_OUT_OF_SHARD", "PART_PATCH_OUT_OF_SHARD")
            .replace("PART_DECISION_DUPLICATE", "PART_PATCH_DUPLICATE_TASK")
            .replace("PART_DECISION_MISSING_ID", "PART_PATCH_MISSING_TASK_ID")
            .replace("PART_DECISION_MISSING:", "PART_PATCH_MISSING_TASK:")
        )
    return out


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
        manifest = read_yaml(man_path) or {}
    if isinstance(manifest, dict):
        for sh in manifest.get("shards") or []:
            if isinstance(sh, dict) and not sh.get("obligation_ids"):
                sh["obligation_ids"] = list(sh.get("task_ids") or [])
                sh["obligation_count"] = len(sh["obligation_ids"])

    parts_dir = action_dir / "parts"
    if parts_dir.is_dir():
        for p in parts_dir.glob("part_*.yaml"):
            doc = read_yaml(p)
            if isinstance(doc, dict) and doc.get("patches") and not doc.get("decisions"):
                doc["decisions"] = [
                    {**x, "candidate_id": x.get("task_id")}
                    for x in (doc.get("patches") or [])
                    if isinstance(x, dict)
                ]
                write_yaml(p, doc)

    reduced = reduce_llm_parts(
        action_dir,
        manifest=manifest if isinstance(manifest, dict) else None,
        manifest_name="semantic_batches.yaml",
        parts_subdir="parts",
        decision_key="decisions",
        id_field="candidate_id",
    )
    if not reduced.get("ok"):
        return reduced
    patches = []
    for row in reduced.get("decisions") or []:
        if not isinstance(row, dict):
            continue
        p = dict(row)
        if not p.get("task_id") and p.get("candidate_id"):
            p["task_id"] = p.get("candidate_id")
        p.pop("_bucket", None)
        patches.append(p)
    merged = {
        "version": 1,
        "patches": patches,
        "action_session_id": (manifest or {}).get("action_session_id"),
        "source_snapshot_hash": (manifest or {}).get("source_snapshot_hash"),
        "task_set_hash": (manifest or {}).get("task_set_hash")
        or (manifest or {}).get("obligation_set_hash"),
    }
    write_yaml(action_dir / "reduce_report.yaml", reduced.get("report") or {})
    return {
        "ok": True,
        "patches": patches,
        "merged": merged,
        "report": reduced.get("report"),
    }


__all__ = [
    "DEFAULT_PARALLELISM",
    "DEFAULT_TOKEN_BUDGET",
    "MAX_OBLIGATIONS_PER_SHARD",
    "build_dispatch_tasks",
    "plan_semantic_batches",
    "reduce_semantic_parts",
    "require_valid_manifest",
    "validate_part",
    "write_semantic_batches",
]
