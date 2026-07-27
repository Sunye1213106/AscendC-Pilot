"""P1: contract fail-closed, enrichment re-triage, KEY evidence tightening."""

from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.classify_input_derivable import _classify_one
from uo.scripts.llm_tasks import apply_task_patch, candidate_set_hash
from uo.scripts.semantic_task_triage import apply_triage_to_tasks


def test_contract_fail_blocks_adjudication() -> None:
    from uo.scripts.semantic_task_triage import validate_semantic_task_contract

    # Direct contract: effective still mark_missing + candidate_generation_required → conflict.
    illegal = {
        "task_id": "t_contract",
        "type": "mark_missing",
        "triage_category": "candidate_generation_required",
        "effective_task_type": "mark_missing",
        "candidates": [],
        "route": "uo-semantic-resolve",
        "eligible_for_adjudication": True,
    }
    assert validate_semantic_task_contract(illegal).get("error") == "SEMANTIC_TASK_CONTRACT_CONFLICT"

    # After triage remap, effective becomes candidate_generation — no conflict on declared type.
    task = {
        "task_id": "t_contract_remap",
        "type": "mark_missing",
        "original_task_type": "mark_missing",
        "candidates": [],
        "route": "uo-semantic-resolve",
    }
    tasks, rows = apply_triage_to_tasks([task])
    assert tasks[0].get("effective_task_type") == "candidate_generation"
    assert tasks[0].get("contract_error") in {None, ""}
    assert rows[0]["category"] == "candidate_generation_required"


def test_enrichment_commit_reruns_triage(tmp_path: Path) -> None:
    uo = tmp_path / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    empty_hash = candidate_set_hash([])
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        {
            "version": 1,
            "active_run_id": "r1",
            "workflow_id": "uo-init",
            "artifact_identity": {"run_id": "r1", "workflow_id": "uo-init"},
            "tasks": [
                {
                    "task_id": "TASK_en",
                    "run_id": "r1",
                    "type": "candidate_generation",
                    "triage_category": "candidate_generation_required",
                    "effective_task_type": "candidate_generation",
                    "task_status": "open",
                    "status": "open",
                    "candidates": [],
                    "candidate_set_hash": empty_hash,
                    "source_snapshot_hash": "snap1",
                    "allowed_actions": ["candidate_enrichment"],
                    "source_proven_unique": True,
                    "eligible_for_adjudication": True,
                }
            ],
        },
    )
    patch = {
        "task_id": "TASK_en",
        "run_id": "r1",
        "action": "candidate_enrichment",
        "patch_type": "candidate_enrichment",
        "candidates": [{"id": "cand_a", "symbol_ref": "Foo", "evidence": {"path": "a.cpp"}}],
        "candidate_set_hash": empty_hash,
        "source_snapshot_hash": "snap1",
    }
    result = apply_task_patch(
        uo,
        patch,
        current_run_id="r1",
        current_source_hash="snap1",
    )
    assert result.get("ok") is True, result
    doc = read_yaml(uo / "ir" / "llm_tasks.yaml")
    task = next(t for t in doc["tasks"] if t["task_id"] == "TASK_en")
    assert task.get("candidates")
    assert "eligible_for_adjudication" in task
    assert task.get("triage_category")


def test_substring_alone_not_false_high() -> None:
    entry = _classify_one(
        "KEY_x",
        nodes_by_id={},
        reverse_adj={},
        forward_writes={},
        key_card={
            "key_id": "KEY_x",
            "name": "tilingKey_ASCEND_MACRO_like",
            "set_by": {
                "status": "present",
                "expr_raw": "ASCEND_MACRO * 2",
                "source_kind": "CompileMacro",
                "file_path": "op_host/tiling.cpp",
                "start_line": 10,
            },
        },
        max_depth=6,
    )
    if entry.get("input_derivable") in {False, "false"}:
        assert entry.get("confidence") != "high"
    else:
        assert entry.get("input_derivable") == "unsolved"
