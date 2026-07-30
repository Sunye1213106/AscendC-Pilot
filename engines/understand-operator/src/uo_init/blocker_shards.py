# -*- coding: utf-8 -*-
"""Shard unresolved blockers for resolve_gaps Map workers.

Host prepare owns the split; prompts must not implement sharding.
Hard limit mirrors ``bounded-semantic-batch``: ≤30 obligations per shard.
"""
from __future__ import annotations

from typing import Any

MAX_BLOCKERS_PER_SHARD = 30
ERR_NOT_SHARDED = "LLM_WORK_NOT_SHARDED"
ERR_SHARD_TOO_LARGE = "LLM_SHARD_TOO_LARGE"


def _blocker_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    """Prefer derivation blockers, then stable id."""
    reason = str(row.get("reason_code") or row.get("reason") or "")
    der = 0 if reason.startswith("DERIVATION_") else 1
    topic = str(row.get("topic") or row.get("atom") or "")
    bid = str(row.get("id") or row.get("blocker_id") or "")
    return (der, topic, bid)


def plan_blocker_shards(
    blockers: list[dict[str, Any]] | None,
    *,
    max_per_shard: int = MAX_BLOCKERS_PER_SHARD,
) -> dict[str, Any]:
    """Partition blockers into shards of at most ``max_per_shard``.

    Returns a manifest dict::

        {
          "ok": True,
          "obligation_count": N,
          "shard_count": K,
          "max_per_shard": 30,
          "shards": [
            {
              "shard_id": "000",
              "shard_index": 0,
              "blocker_ids": [...],
              "task_count": n,
              "batch_file": "inputs/batches/batch_000.yaml",
              "part_file": "parts/part_000.yaml",
            },
            ...
          ],
        }

    When ``N > max_per_shard`` but only one shard would be produced, sets
    ``ok=False`` with ``error=LLM_WORK_NOT_SHARDED``.
    """
    rows = [b for b in (blockers or []) if isinstance(b, dict)]
    ordered = sorted(rows, key=_blocker_sort_key)
    ids: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for row in ordered:
        bid = str(row.get("id") or row.get("blocker_id") or "").strip()
        if not bid or bid in by_id:
            continue
        by_id[bid] = row
        ids.append(bid)

    n = len(ids)
    limit = max(1, int(max_per_shard))
    shards: list[dict[str, Any]] = []
    if n == 0:
        return {
            "ok": True,
            "obligation_count": 0,
            "shard_count": 0,
            "max_per_shard": limit,
            "shards": [],
        }

    for start in range(0, n, limit):
        chunk = ids[start : start + limit]
        idx = len(shards)
        sid = f"{idx:03d}"
        shards.append(
            {
                "shard_id": sid,
                "shard_index": idx,
                "blocker_ids": list(chunk),
                "task_count": len(chunk),
                "batch_file": f"inputs/batches/batch_{sid}.yaml",
                "part_file": f"parts/part_{sid}.yaml",
            }
        )

    # Defensive: a single shard must never exceed the hard limit.
    for sh in shards:
        if int(sh.get("task_count") or 0) > limit:
            return {
                "ok": False,
                "error": ERR_SHARD_TOO_LARGE,
                "obligation_count": n,
                "shard_count": len(shards),
                "max_per_shard": limit,
                "shards": shards,
                "message_zh": f"单 shard 超过 {limit} 个 blocker",
            }

    if n > limit and len(shards) < 2:
        return {
            "ok": False,
            "error": ERR_NOT_SHARDED,
            "obligation_count": n,
            "shard_count": len(shards),
            "max_per_shard": limit,
            "shards": shards,
            "message_zh": f"任务数 {n} > {limit} 却未分片",
        }

    return {
        "ok": True,
        "obligation_count": n,
        "shard_count": len(shards),
        "max_per_shard": limit,
        "shards": shards,
        "blockers_by_id": by_id,
    }


def materialize_blocker_batches(
    action_dir: Any,
    manifest: dict[str, Any],
    *,
    unresolved: dict[str, Any] | None = None,
    closed_vocabulary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write batch YAML files under ``action_dir/inputs/batches/``.

    ``action_dir`` is ``runs/{run_id}/actions/resolve_gaps``.
    """
    from pathlib import Path

    import yaml

    root = Path(action_dir)
    batches_dir = root / "inputs" / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(parents=True, exist_ok=True)
    (root / "scratch").mkdir(parents=True, exist_ok=True)

    by_id = manifest.get("blockers_by_id") or {}
    if not by_id and unresolved:
        for row in unresolved.get("blockers") or []:
            if isinstance(row, dict) and row.get("id"):
                by_id[str(row["id"])] = row

    vocab = closed_vocabulary
    if vocab is None and unresolved:
        vocab = unresolved.get("closed_vocabulary")

    written: list[str] = []
    for sh in manifest.get("shards") or []:
        if not isinstance(sh, dict):
            continue
        sid = str(sh.get("shard_id") or "")
        bids = [str(x) for x in (sh.get("blocker_ids") or [])]
        blockers = [by_id[b] for b in bids if b in by_id]
        batch = {
            "version": 1,
            "shard_id": sid,
            "shard_index": int(sh.get("shard_index") or 0),
            "blocker_ids": bids,
            "blockers": blockers,
            "closed_vocabulary": vocab or {},
            "part_file": str(sh.get("part_file") or f"parts/part_{sid}.yaml"),
            "instruction_zh": (
                "仅处理本 batch 的 blocker_ids；"
                "classification 必须落在封闭词汇表；"
                "input_derived 的 var_id 必须来自白名单；"
                f"写 parts/part_{sid}.yaml（patches 列表）；禁止写 uo/ir/**。"
            ),
        }
        path = batches_dir / f"batch_{sid}.yaml"
        path.write_text(
            yaml.safe_dump(batch, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        written.append(path.as_posix())

    man_path = root / "inputs" / "blocker_batches.yaml"
    man_out = {
        "version": 1,
        "obligation_count": manifest.get("obligation_count"),
        "shard_count": manifest.get("shard_count"),
        "max_per_shard": manifest.get("max_per_shard"),
        "shards": [
            {k: v for k, v in sh.items() if k != "blockers_by_id"}
            for sh in (manifest.get("shards") or [])
            if isinstance(sh, dict)
        ],
    }
    man_path.write_text(
        yaml.safe_dump(man_out, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"ok": True, "batches": written, "manifest": man_path.as_posix()}
