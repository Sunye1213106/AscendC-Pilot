# -*- coding: utf-8 -*-
from uo_init.blocker_shards import (
    ERR_NOT_SHARDED,
    MAX_BLOCKERS_PER_SHARD,
    plan_blocker_shards,
)


def _blk(i: int, *, der: bool = False) -> dict:
    return {
        "id": f"BLK_{i:04d}",
        "reason_code": "DERIVATION_UNDECIDED" if der else "UNMAPPED_SYMBOL",
        "topic": "t" if der else "u",
    }


def test_empty():
    m = plan_blocker_shards([])
    assert m["ok"] and m["shard_count"] == 0 and m["obligation_count"] == 0


def test_single_shard_under_limit():
    rows = [_blk(i, der=True) for i in range(12)]
    m = plan_blocker_shards(rows)
    assert m["ok"]
    assert m["shard_count"] == 1
    assert m["obligation_count"] == 12
    assert m["shards"][0]["task_count"] == 12


def test_splits_over_thirty():
    rows = [_blk(i) for i in range(45)]
    m = plan_blocker_shards(rows)
    assert m["ok"]
    assert m["shard_count"] == 2
    assert m["shards"][0]["task_count"] == MAX_BLOCKERS_PER_SHARD
    assert m["shards"][1]["task_count"] == 15
    for sh in m["shards"]:
        assert sh["task_count"] <= MAX_BLOCKERS_PER_SHARD


def test_prefers_derivation_first():
    rows = [_blk(1), _blk(2, der=True), _blk(3)]
    m = plan_blocker_shards(rows)
    assert m["shards"][0]["blocker_ids"][0] == "BLK_0002"


def test_not_sharded_guard_unreachable_with_chunking():
    # With correct chunking, N>30 always yields ≥2 shards; ERR_NOT_SHARDED
    # is reserved for broken schedulers. Sanity: 31 → 2 shards.
    m = plan_blocker_shards([_blk(i) for i in range(31)])
    assert m["ok"] and m["shard_count"] == 2
    assert m.get("error") != ERR_NOT_SHARDED
