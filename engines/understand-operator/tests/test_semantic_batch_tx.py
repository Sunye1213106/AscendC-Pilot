"""Transactional semantic patch batch: validate-then-commit."""

from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.llm_tasks import (
    MAX_SEMANTIC_BATCHES,
    apply_patches_batch,
    apply_task_patch,
    load_llm_tasks,
    validate_patches_batch,
    validate_task_patch,
)
from uo.scripts.semantic_resolution_ledger import load_ledger

RUN_TEST = "RUN_TEST"


def _uo(tmp_path: Path) -> Path:
    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    return uo


def _tasks_doc(tasks: list[dict], *, total_semantic_batches: int = 0) -> dict:
    return {
        "version": 1,
        "artifact_identity": {"run_id": RUN_TEST, "workflow_id": "uo-init"},
        "active_run_id": RUN_TEST,
        "total_semantic_batches": total_semantic_batches,
        "tasks": tasks,
    }


def _task(
    task_id: str,
    *,
    candidates: list | None = None,
    source_hash: str = "snap1",
) -> dict:
    cands = candidates if candidates is not None else [{"id": "cand_1"}]
    return {
        "task_id": task_id,
        "run_id": RUN_TEST,
        "workflow_id": "uo-init",
        "status": "open",
        "severity": "blocking",
        "type": "choose_edge",
        "candidates": cands,
        "allowed_actions": ["choose_one", "mark_missing", "accept_edge"],
        "source_snapshot_hash": source_hash,
        "candidate_set_hash": "cset",
        "task_attempts": 0,
    }


def _patch(task_id: str, *, cand: str = "cand_1", bad: bool = False) -> dict:
    return {
        "task_id": task_id,
        "run_id": RUN_TEST,
        "action": "accept_edge",
        "accepted_candidate_ids": ["cand_BAD" if bad else cand],
        "rejected_candidate_ids": [],
        "source_snapshot_hash": "snap1",
        "candidate_set_hash": "cset",
    }


def test_batch_increments_semantic_budget_once(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        _tasks_doc([_task("t_a"), _task("t_b", candidates=[{"id": "cand_2"}])]),
    )
    t_a = "t_a"
    t_b = "t_b"
    # Fix task ids from _task helper (uses literal ids)
    doc = load_llm_tasks(uo)
    ids = [t["task_id"] for t in doc["tasks"]]
    t_a, t_b = ids[0], ids[1]

    result = apply_patches_batch(
        uo,
        [_patch(t_a), _patch(t_b, cand="cand_2")],
        current_run_id=RUN_TEST,
        current_source_hash="snap1",
    )
    assert result["ok"] is True
    assert result["applied_count"] == 2
    after = load_llm_tasks(uo)
    assert int(after["total_semantic_batches"]) == 1


def test_atomic_rollback_on_mid_batch_failure(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        _tasks_doc([_task("t_ok"), _task("t_bad")]),
    )
    doc = load_llm_tasks(uo)
    t_ok, t_bad = doc["tasks"][0]["task_id"], doc["tasks"][1]["task_id"]

    fail = apply_patches_batch(
        uo,
        [_patch(t_ok), _patch(t_bad, bad=True)],
        current_run_id=RUN_TEST,
        current_source_hash="snap1",
    )
    assert fail["ok"] is False
    doc_after = load_llm_tasks(uo)
    assert int(doc_after["total_semantic_batches"]) == 0
    assert all(t["status"] == "open" for t in doc_after["tasks"])
    ledger = load_ledger(uo)
    assert not ledger.get("semantic_patches")


def test_stale_patch_validate_no_side_effects(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        _tasks_doc([_task("t_stale")]),
    )
    doc = load_llm_tasks(uo)
    tid = doc["tasks"][0]["task_id"]
    stale = validate_task_patch(
        doc,
        _patch(tid),
        current_source_hash="other_snap",
        current_run_id=RUN_TEST,
    )
    assert stale["ok"] is False
    assert stale["error"] == "source_snapshot_stale"
    assert doc["tasks"][0]["status"] == "open"
    assert int(doc.get("total_semantic_batches") or 0) == 0

    apply_stale = apply_task_patch(
        uo,
        _patch(tid),
        current_run_id=RUN_TEST,
        current_source_hash="other_snap",
    )
    assert apply_stale["ok"] is False
    assert apply_stale["error"] == "source_snapshot_stale"
    reloaded = load_llm_tasks(uo)
    assert reloaded["tasks"][0]["status"] == "open"
    assert int(reloaded["total_semantic_batches"]) == 0


def test_retry_after_failed_batch_succeeds(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        _tasks_doc([_task("t_retry")]),
    )
    tid = load_llm_tasks(uo)["tasks"][0]["task_id"]

    first = apply_patches_batch(
        uo,
        [_patch(tid, bad=True)],
        current_run_id=RUN_TEST,
        current_source_hash="snap1",
    )
    assert first["ok"] is False

    second = apply_patches_batch(
        uo,
        [_patch(tid)],
        current_run_id=RUN_TEST,
        current_source_hash="snap1",
    )
    assert second["ok"] is True
    after = load_llm_tasks(uo)
    assert int(after["total_semantic_batches"]) == 1
    assert after["tasks"][0]["status"] == "pending_materialization"
    assert after["tasks"][0]["semantic_status"] == "pending_materialization"
    assert after["tasks"][0]["blocking"] is True


def test_validate_batch_budget_current_plus_one(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        _tasks_doc([_task("t_budget")], total_semantic_batches=MAX_SEMANTIC_BATCHES),
    )
    tid = load_llm_tasks(uo)["tasks"][0]["task_id"]
    checked = validate_patches_batch(
        uo,
        [_patch(tid)],
        current_run_id=RUN_TEST,
        current_source_hash="snap1",
    )
    assert checked["ok"] is False
    assert checked["error"] == "total_semantic_batches_exhausted"
    doc = load_llm_tasks(uo)
    assert int(doc["total_semantic_batches"]) == MAX_SEMANTIC_BATCHES
