"""Empty-candidate semantic task canonicalization (fail-closed, no false mark_missing)."""

from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.llm_tasks import load_llm_tasks, upsert_tasks_from_score_items
from uo.scripts.semantic_task_triage import (
    apply_triage_to_tasks,
    validate_semantic_task_contract,
)

RUN_TEST = "UO_RUN_CANON"


def _prep(tmp_path: Path) -> Path:
    uo = tmp_path / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(
        uo / "manifest.yaml",
        {"version": 1, "source": {"root": str(tmp_path), "revision": "r1"}},
    )
    return uo


def test_empty_candidate_blocking_edge_becomes_candidate_generation(tmp_path: Path) -> None:
    uo = _prep(tmp_path)
    upsert_tasks_from_score_items(
        uo,
        [
            {
                "disposition": "llm_task",
                "severity": "blocking",
                "task_hint": "mark_missing",
                "object_type": "call_edge",
                "target_id": "edge_empty",
                "score": 0.1,
                "candidates": [],
            }
        ],
        checkpoint="extract.post_semantic",
        run_id=RUN_TEST,
        source_snapshot_hash="snap",
        score_phase="post_semantic",
    )
    task = next(t for t in load_llm_tasks(uo)["tasks"] if t["status"] == "open")
    assert task["type"] == "candidate_generation"
    tasks, rows = apply_triage_to_tasks([task], uo_root=uo)
    assert rows[0]["category"] == "candidate_generation_required"
    assert tasks[0]["route"] == "uo-semantic-resolve"
    assert tasks[0].get("contract_error") in {None, ""}
    assert validate_semantic_task_contract(tasks[0]).get("ok") is True


def test_bridge_gap_becomes_evidence_enrichment(tmp_path: Path) -> None:
    uo = _prep(tmp_path)
    upsert_tasks_from_score_items(
        uo,
        [
            {
                "disposition": "llm_task",
                "severity": "blocking",
                "task_hint": "mark_missing",
                "object_type": "tilingdata_bridge",
                "target_id": "bridge_gap",
                "score": 0.2,
                "candidates": [],
            }
        ],
        checkpoint="extract.post_semantic",
        run_id=RUN_TEST,
        source_snapshot_hash="snap",
        score_phase="post_semantic",
    )
    task = next(t for t in load_llm_tasks(uo)["tasks"] if t["status"] == "open")
    assert task["type"] == "evidence_enrichment"
    tasks, rows = apply_triage_to_tasks([task], uo_root=uo)
    assert tasks[0].get("contract_error") in {None, ""}
    assert rows[0]["route"] == "uo-semantic-resolve"


def test_mark_missing_requires_negative_evidence(tmp_path: Path) -> None:
    uo = _prep(tmp_path)
    upsert_tasks_from_score_items(
        uo,
        [
            {
                "disposition": "llm_task",
                "severity": "blocking",
                "task_hint": "mark_missing",
                "object_type": "call_edge",
                "target_id": "with_neg",
                "candidates": [],
                "negative_evidence": {
                    "scope_snapshot_sha256": "snap",
                    "include_closure_status": "complete",
                    "queries": [{"symbol": "X", "search_mode": "exact", "result_count": 0}],
                    "inspected_windows": [
                        {"file": "op_host/a.cpp", "lines": [1, 5], "window_sha256": "abc"}
                    ],
                    "absence_kind": "project_definition_absent",
                },
            }
        ],
        checkpoint="extract.post_semantic",
        run_id=RUN_TEST,
        source_snapshot_hash="snap",
        score_phase="post_semantic",
    )
    task = next(t for t in load_llm_tasks(uo)["tasks"] if t["status"] == "open")
    assert task["type"] == "mark_missing"
    assert task.get("negative_evidence")


def test_effective_type_contract_not_declared_type() -> None:
    """Canonicalized type must not conflict when declared/original was mark_missing."""
    task = {
        "task_id": "t1",
        "type": "candidate_generation",
        "original_task_type": "mark_missing",
        "triage_category": "candidate_generation_required",
        "effective_task_type": "candidate_generation",
        "route": "uo-semantic-resolve",
        "eligible_for_adjudication": True,
        "candidates": [],
    }
    assert validate_semantic_task_contract(task).get("ok") is True

    still_bad = {
        "task_id": "t2",
        "type": "mark_missing",
        "triage_category": "candidate_generation_required",
        "effective_task_type": "mark_missing",
        "route": "uo-semantic-resolve",
        "eligible_for_adjudication": True,
        "candidates": [],
    }
    assert validate_semantic_task_contract(still_bad).get("error") == "SEMANTIC_TASK_CONTRACT_CONFLICT"
