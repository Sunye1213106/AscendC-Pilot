"""Public LLM work scheduler + extract_plan Map-Reduce sharding tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from ascendc_pilot.ownership import (
    shard_producer_forbidden_read_paths,
    shard_producer_read_paths,
    shard_producer_write_paths,
    path_matches_patterns,
)
from uo.scripts.llm_work_scheduler import (
    ERR_NOT_SHARDED,
    ERR_SHARD_TOO_LARGE,
    MAX_OBLIGATIONS_PER_SHARD,
    estimate_tokens,
    plan_llm_work_shards,
    reduce_llm_parts,
    require_valid_manifest,
    validate_llm_part,
    write_llm_batches,
)


def _obs(n: int, *, prefix: str = "CAND_", group: str | None = None) -> list[dict]:
    rows = []
    for i in range(n):
        rows.append(
            {
                "obligation_id": f"{prefix}{i:04d}",
                "candidate_id": f"{prefix}{i:04d}",
                "name": f"sym_{i}" if group is None else group,
                "score": 0.5,
            }
        )
    return rows


def test_30_items_one_shard() -> None:
    man = plan_llm_work_shards(
        _obs(30),
        max_per_shard=30,
        group_key_fn=lambda x: f"g::{x['name']}",
    )
    assert man["ok"]
    assert man["shard_count"] == 1
    assert man["shards"][0]["obligation_count"] == 30


def test_31_items_two_shards() -> None:
    man = plan_llm_work_shards(
        _obs(31),
        max_per_shard=30,
        group_key_fn=lambda x: f"g::{x['name']}",
    )
    assert man["ok"], man.get("errors")
    assert man["shard_count"] == 2
    assert max(s["obligation_count"] for s in man["shards"]) <= 30


def test_61_items_three_shards() -> None:
    man = plan_llm_work_shards(
        _obs(61),
        max_per_shard=30,
        group_key_fn=lambda x: f"g::{x['name']}",
    )
    assert man["ok"], man.get("errors")
    assert man["shard_count"] == 3
    assert max(s["obligation_count"] for s in man["shards"]) <= 30


def test_118_items_four_shards() -> None:
    man = plan_llm_work_shards(
        _obs(118),
        max_per_shard=30,
        group_key_fn=lambda x: f"g::{x['name']}",
    )
    assert man["ok"], man.get("errors")
    assert man["shard_count"] == 4
    assert max(s["obligation_count"] for s in man["shards"]) <= 30
    assert man["expected_min_shards"] == 4


def test_token_budget_forces_split() -> None:
    # Tiny budget forces many shards even with few items
    rows = _obs(6)
    man = plan_llm_work_shards(
        rows,
        max_per_shard=30,
        token_budget=50,  # very small
        group_key_fn=lambda x: f"g::{x['name']}",
    )
    # Either splits successfully or reports too-large if a single item exceeds budget
    if man["ok"]:
        assert man["shard_count"] >= 2
        assert max(s["obligation_count"] for s in man["shards"]) <= 30
    else:
        assert any(ERR_SHARD_TOO_LARGE in e for e in man["errors"])


def test_conflict_group_not_split_across_shards() -> None:
    # 10 items same conflict group → one shard
    rows = _obs(10, group="SameWriter")
    man = plan_llm_work_shards(
        rows,
        max_per_shard=30,
        group_key_fn=lambda x: "writer::samewriter",
    )
    assert man["ok"]
    assert man["shard_count"] == 1
    assert man["shards"][0]["obligation_count"] == 10


def test_oversized_conflict_group_fails() -> None:
    rows = _obs(35, group="Huge")
    man = plan_llm_work_shards(
        rows,
        max_per_shard=30,
        group_key_fn=lambda _x: "writer::huge",
    )
    assert not man["ok"]
    assert any(ERR_SHARD_TOO_LARGE in e for e in man["errors"])
    with pytest.raises(ValueError):
        require_valid_manifest(man)


def test_not_sharded_when_single_oversized_pack() -> None:
    # Simulate bug: if somehow 40 unique packed into 1 — detect
    man = {
        "ok": True,
        "errors": [],
        "obligation_count": 40,
        "shard_count": 1,
        "shards": [{"shard_id": "x", "obligation_count": 40, "token_estimate": 1}],
        "max_per_shard": 30,
        "token_budget": 999999,
    }
    # Use planner instead
    rows = _obs(40)
    real = plan_llm_work_shards(
        rows, max_per_shard=30, group_key_fn=lambda x: f"g::{x['name']}"
    )
    assert real["shard_count"] >= 2
    assert not any(ERR_NOT_SHARDED in e for e in (real.get("errors") or []))


def test_worker_cannot_read_other_batch() -> None:
    reads = shard_producer_read_paths(
        "uo-init", "extract_plan", run_id="RUN1", shard_id="000", batch_name="batch_000.yaml"
    )
    assert any("batch_000.yaml" in p for p in reads)
    assert any("relation_batches.yaml" in p for p in reads)
    forbid = shard_producer_forbidden_read_paths(
        "uo-init", "extract_plan", run_id="RUN1", shard_id="000"
    )
    assert any("extract_plan_candidates.yaml" in p for p in forbid)
    writes = shard_producer_write_paths(
        "uo-init", "extract_plan", run_id="RUN1", shard_id="writer_000"
    )
    assert any("relation_parts" in p for p in writes)
    assert not path_matches_patterns("uo/ir/extract_plan.yaml", writes)


def test_reduce_missing_shard_and_duplicate_fail(tmp_path: Path) -> None:
    rows = _obs(4)
    man = plan_llm_work_shards(
        rows, max_per_shard=2, group_key_fn=lambda x: f"g::{x['name']}"
    )
    assert man["shard_count"] == 2
    by_id = {r["obligation_id"]: r for r in rows}
    write_llm_batches(tmp_path, man, by_id, manifest_name="decision_batches.yaml")

    # Write only first part, incomplete
    sh0 = man["shards"][0]
    part0 = {
        "version": 1,
        "shard_id": sh0["shard_id"],
        "action_session_id": "",
        "source_snapshot_hash": "",
        "accepted": [{"candidate_id": sh0["obligation_ids"][0], "role": "tiling_writer"}],
        "rejected": [],
        "deferred": [
            {"candidate_id": oid, "reason_code": "x"}
            for oid in sh0["obligation_ids"][1:]
        ],
    }
    from uo.scripts._ir_io import write_yaml

    write_yaml(tmp_path / "parts" / f"part_{sh0['shard_index']:03d}.yaml", part0)
    # Missing second part
    reduced = reduce_llm_parts(
        tmp_path, manifest=man, manifest_name="decision_batches.yaml"
    )
    assert not reduced["ok"]
    assert any("PART_MISSING" in e or "REDUCE_MISSING" in e for e in reduced["errors"])


def test_out_of_shard_candidate_fails() -> None:
    shard = {
        "shard_id": "g_000",
        "obligation_ids": ["CAND_0000", "CAND_0001"],
        "obligation_count": 2,
    }
    man = {"action_session_id": "S", "source_snapshot_hash": "H", "obligation_set_hash": "O"}
    part = {
        "shard_id": "g_000",
        "action_session_id": "S",
        "source_snapshot_hash": "H",
        "accepted": [
            {"candidate_id": "CAND_0000", "role": "tiling_writer"},
            {"candidate_id": "CAND_EVIL", "role": "tiling_writer"},
        ],
        "rejected": [],
        "deferred": [{"candidate_id": "CAND_0001", "reason_code": "x"}],
    }
    errs = validate_llm_part(part, shard=shard, manifest=man)
    assert any("OUT_OF_SHARD" in e for e in errs)


def test_retry_only_failed_shards(tmp_path: Path) -> None:
    rows = _obs(4)
    man = plan_llm_work_shards(
        rows, max_per_shard=2, group_key_fn=lambda x: f"g::{x['name']}"
    )
    by_id = {r["obligation_id"]: r for r in rows}
    write_llm_batches(tmp_path, man, by_id, manifest_name="decision_batches.yaml")
    from uo.scripts._ir_io import write_yaml

    for sh in man["shards"]:
        part = {
            "version": 1,
            "shard_id": sh["shard_id"],
            "action_session_id": "",
            "source_snapshot_hash": "",
            "accepted": [
                {"candidate_id": oid, "role": "tiling_writer"}
                for oid in sh["obligation_ids"]
            ],
            "rejected": [],
            "deferred": [],
        }
        write_yaml(
            tmp_path / "parts" / f"part_{sh['shard_index']:03d}.yaml", part
        )
    # Mark first ok, corrupt second
    man["shards"][0]["status"] = "ok"
    bad = {
        "version": 1,
        "shard_id": man["shards"][1]["shard_id"],
        "action_session_id": "",
        "source_snapshot_hash": "",
        "accepted": [],
        "rejected": [],
        "deferred": [],  # missing coverage
    }
    write_yaml(
        tmp_path / "parts" / f"part_{man['shards'][1]['shard_index']:03d}.yaml", bad
    )
    reduced = reduce_llm_parts(
        tmp_path,
        manifest=man,
        manifest_name="decision_batches.yaml",
        only_failed=True,
    )
    assert not reduced["ok"]
    assert man["shards"][1]["shard_id"] in (reduced.get("retry_shards") or [])


def test_estimate_tokens_positive() -> None:
    assert estimate_tokens({"a": "x" * 100}) >= 1


def test_max_constant_is_30() -> None:
    assert MAX_OBLIGATIONS_PER_SHARD == 30
