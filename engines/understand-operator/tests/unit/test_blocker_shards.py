# -*- coding: utf-8 -*-
import yaml

from uo_init.blocker_shards import (
    ERR_NOT_SHARDED,
    MAX_BLOCKERS_PER_SHARD,
    materialize_blocker_batches,
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


# -- what a worker gets to read ---------------------------------------------
_LOOP_SRC = """\
void Count(Params &p)
{
    int64_t n = 0;
    for (int64_t i = 0; i < p.k; i++) {
        if (p.invalid[i] != 0) {
            n += 1;
        }
    }
    p.count = n;
}
"""


def _loop_blocker(rel: str, line: int) -> dict:
    return {
        "id": "BLK_0001",
        "reason_code": "LOOP_SUMMARY_NEEDED",
        "topic": "t",
        "evidence": [{"file": rel, "line": line, "snippet": "p.invalid[i] != 0"}],
    }


def _batch(tmp_path, row: dict) -> dict:
    manifest = plan_blocker_shards([row])
    materialize_blocker_batches(
        tmp_path / "action", manifest, ops_root=tmp_path
    )
    text = (tmp_path / "action" / "inputs" / "batches" / "batch_000.yaml").read_text(
        encoding="utf-8"
    )
    return yaml.safe_load(text)


def test_a_loop_question_ships_the_loop(tmp_path):
    """Asking what a loop computes while showing one line of it asks for a
    guess. The source travels with the question."""
    (tmp_path / "op.cpp").write_text(_LOOP_SRC, encoding="utf-8")
    batch = _batch(tmp_path, _loop_blocker("op.cpp", 5))
    source = batch["blockers"][0]["source"]
    assert source[0]["kind"] == "function"
    assert "for (int64_t i = 0; i < p.k; i++)" in source[0]["text"]
    assert "p.count = n;" in source[0]["text"]


def test_the_shipped_source_says_where_it_came_from(tmp_path):
    """A quote has to be checkable against the same lines the worker read."""
    (tmp_path / "op.cpp").write_text(_LOOP_SRC, encoding="utf-8")
    source = _batch(tmp_path, _loop_blocker("op.cpp", 5))["blockers"][0]["source"][0]
    assert source["file"] == "op.cpp"
    assert (source["line_start"], source["line_end"]) == (1, 10)


def test_a_question_that_does_not_need_the_code_does_not_carry_it(tmp_path):
    """Thirty of these go in one batch; padding each with a function body
    spends the worker's attention on what it did not need."""
    (tmp_path / "op.cpp").write_text(_LOOP_SRC, encoding="utf-8")
    row = _loop_blocker("op.cpp", 5) | {"reason_code": "UNMAPPED_SYMBOL"}
    assert "source" not in _batch(tmp_path, row)["blockers"][0]


def test_evidence_pointing_at_no_file_is_simply_left_out(tmp_path):
    batch = _batch(tmp_path, _loop_blocker("gone.cpp", 5))
    assert "source" not in batch["blockers"][0]
    assert batch["blockers"][0]["evidence"][0]["file"] == "gone.cpp"


def test_not_sharded_guard_unreachable_with_chunking():
    # With correct chunking, N>30 always yields ≥2 shards; ERR_NOT_SHARDED
    # is reserved for broken schedulers. Sanity: 31 → 2 shards.
    m = plan_blocker_shards([_blk(i) for i in range(31)])
    assert m["ok"] and m["shard_count"] == 2
    assert m.get("error") != ERR_NOT_SHARDED
