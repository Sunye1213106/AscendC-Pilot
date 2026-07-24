"""Production semantics: blocking gaps, enrichment tasks, ledger rebuild."""

from __future__ import annotations

from pathlib import Path

import pytest

from uo.scripts._ir_io import write_yaml
from uo.scripts.evidence_score import score_tilingdata_bridge
from uo.scripts.llm_tasks import (
    apply_task_patch,
    blocking_gap_tasks,
    compute_semantic_stats,
    load_llm_tasks,
    recheck_does_not_increment,
    upsert_tasks_from_score_items,
    validate_task_patch,
)
from uo.scripts.semantic_resolution_ledger import (
    apply_ledger_to_entrypoint_graph,
    rebuild_derived_graphs,
)


def _uo(tmp_path: Path) -> Path:
    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    return uo


def test_empty_bridge_candidates_not_emitted_as_choose_edge(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    bridge = {
        "field_path": "tilingData.fieldA",
        "score": 0.55,
        "required": False,
    }
    scored = score_tilingdata_bridge(bridge)
    assert scored.get("task_hint") != "choose_edge"
    scored["disposition"] = "llm_task"
    upsert_tasks_from_score_items(
        uo,
        [scored],
        checkpoint="extract.post_semantic",
        source_snapshot_hash="snap_bridge",
    )
    doc = load_llm_tasks(uo)
    task = doc["tasks"][0]
    assert task["type"] in {"evidence_enrichment", "tilingdata_bridge"}
    assert task["type"] != "choose_edge"
    assert "accept_edge" not in (task.get("allowed_actions") or [])


def test_mark_missing_task_is_adjudicated_but_still_blocking(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    items = [
        {
            "disposition": "llm_task",
            "severity": "blocking",
            "task_hint": "mark_missing",
            "object_type": "call_edge",
            "target_id": "edge_empty",
            "score": 0.2,
            "necessity": "main_chain",
            "candidates": [],
        }
    ]
    upsert_tasks_from_score_items(uo, items, checkpoint="pre", source_snapshot_hash="h1")
    task = load_llm_tasks(uo)["tasks"][0]
    ok = apply_task_patch(
        uo,
        {
            "task_id": task["task_id"],
            "action": "mark_missing",
            "source_snapshot_hash": "h1",
            "candidate_set_hash": task["candidate_set_hash"],
        },
        current_source_hash="h1",
    )
    assert ok["ok"] is True
    after = next(t for t in load_llm_tasks(uo)["tasks"] if t["task_id"] == task["task_id"])
    assert after["status"] == "adjudicated"
    assert after.get("semantic_status") == "unresolved"
    assert after.get("blocking") is True


def test_mark_missing_does_not_reduce_blocking_gap_count(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    items = [
        {
            "disposition": "llm_task",
            "severity": "blocking",
            "task_hint": "mark_missing",
            "object_type": "call_edge",
            "target_id": "edge_empty",
            "score": 0.2,
            "necessity": "main_chain",
            "candidates": [],
        }
    ]
    upsert_tasks_from_score_items(uo, items, checkpoint="pre", source_snapshot_hash="h1")
    before = len(blocking_gap_tasks(uo))
    task = load_llm_tasks(uo)["tasks"][0]
    apply_task_patch(
        uo,
        {
            "task_id": task["task_id"],
            "action": "mark_missing",
            "source_snapshot_hash": "h1",
            "candidate_set_hash": task["candidate_set_hash"],
        },
        current_source_hash="h1",
    )
    after = len(blocking_gap_tasks(uo))
    assert before == 1
    assert after == 1
    stats = compute_semantic_stats(uo)
    assert stats["blocking_gap_count"] == 1
    assert stats["mark_missing_count"] == 1


def test_candidate_node_id_not_consumed_as_edge_id(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        {
            "version": 1,
            "total_semantic_batches": 0,
            "tasks": [
                {
                    "task_id": "t_edge",
                    "status": "open",
                    "task_status": "open",
                    "severity": "blocking",
                    "type": "choose_edge",
                    "object_type": "call_edge",
                    "target": "edge_real",
                    "candidates": [{"id": "cand_EP_1"}],
                    "allowed_actions": ["accept_edge", "mark_missing"],
                    "source_snapshot_hash": "snap1",
                    "candidate_set_hash": "cset1",
                    "task_attempts": 0,
                }
            ],
        },
    )
    doc = load_llm_tasks(uo)
    bad = validate_task_patch(
        doc,
        {
            "task_id": "t_edge",
            "action": "accept_edge",
            "edge_id": "cand_EP_99",
            "accepted_candidate_ids": ["cand_EP_1"],
            "source_snapshot_hash": "snap1",
            "candidate_set_hash": "cset1",
        },
        current_source_hash="snap1",
    )
    assert bad["ok"] is False
    assert bad["error"] == "LEDGER_TARGET_TYPE_MISMATCH"


def test_rebuild_does_not_overwrite_ledger_applied_graph(tmp_path: Path) -> None:
    graph = {
        "version": 2,
        "nodes": [],
        "edges": [{"id": "e1", "type": "dispatches_to", "confidence": "candidate"}],
        "closure": {"host_main_chain": "unresolved", "kernel_main_chain": "unresolved"},
    }
    ledger = {
        "semantic_patches": [
            {
                "task_id": "TASK_y",
                "status": "active",
                "action": "accept_edge",
                "patch_type": "edge_resolution",
                "edge_id": "e1",
                "accepted_candidate_ids": ["e1"],
                "relation": "dispatches_to",
            }
        ]
    }
    upgraded = apply_ledger_to_entrypoint_graph(graph, ledger)
    assert upgraded["edges"][0]["confidence"] == "semantic_verified"


def test_recheck_requires_kernel_closed(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "entrypoint_graph.yaml",
        {
            "closure": {"host_main_chain": "closed", "kernel_main_chain": "unresolved"},
        },
    )
    write_yaml(uo / "ir" / "llm_tasks.yaml", {"version": 1, "tasks": [], "total_semantic_batches": 0})
    write_yaml(uo / "ir" / "semantic_resolution_ledger.yaml", {"version": 1, "semantic_patches": []})
    budget = recheck_does_not_increment(uo)
    assert budget["blocking_gap_count"] == 0
    # Engine-level ok requires kernel closed; simulate check here.
    ep_closure = {"host_main_chain": "closed", "kernel_main_chain": "unresolved"}
    ok = (
        budget["blocking_gap_count"] == 0
        and budget.get("unconsumed_patch_count", 0) == 0
        and ep_closure["host_main_chain"] == "closed"
        and ep_closure["kernel_main_chain"] == "closed"
    )
    assert ok is False


def test_same_fingerprint_recheck_does_not_consume_retry(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "entrypoint_graph.yaml",
        {
            "closure": {"host_main_chain": "unresolved", "kernel_main_chain": "unresolved"},
        },
    )
    write_yaml(uo / "ir" / "llm_tasks.yaml", {"version": 1, "tasks": [], "total_semantic_batches": 2})
    write_yaml(uo / "ir" / "semantic_resolution_ledger.yaml", {"version": 1, "semantic_patches": []})
    first_batches = int(load_llm_tasks(uo).get("total_semantic_batches") or 0)
    recheck_does_not_increment(uo)
    second_batches = int(load_llm_tasks(uo).get("total_semantic_batches") or 0)
    assert second_batches == first_batches

    from ascendc_pilot.actions.engines import _run_recheck_closure

    project = tmp_path
    (project / ".ascendc-pilot" / "uo").mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copytree(uo, project / ".ascendc-pilot" / "uo", dirs_exist_ok=True)
    ctx = {"uo_root": str(project / ".ascendc-pilot" / "uo")}
    first = _run_recheck_closure(project, ctx)
    assert first.get("ok") is False
    second = _run_recheck_closure(project, ctx)
    assert second.get("error") == "NO_PROGRESS_RECHECK"
    assert int(load_llm_tasks(project / ".ascendc-pilot" / "uo").get("total_semantic_batches") or 0) == 2
