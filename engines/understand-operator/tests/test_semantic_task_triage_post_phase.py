from __future__ import annotations

from uo.scripts.semantic_task_triage import apply_triage_to_tasks, write_semantic_task_triage


def test_post_semantic_explicit_phase_promotes_reused_provisional_task(tmp_path) -> None:
    task = {
        "task_id": "TASK_1",
        "status": "open",
        "task_status": "provisional",
        "score_phase": "post_semantic",
        "checkpoint": "extract.pre_semantic",
        "type": "entrypoint_dispatch_bind",
        "object_type": "call_edge",
        "target": "E_KERNEL_DISPATCH",
        "candidates": [
            {
                "id": "cand_1",
                "file_path": "op_kernel/flash_attention_score_grad.cpp",
                "start_line": 100,
                "symbol_ref": "flash_attention_score_grad",
                "snippet": "RegbaseFAG<...>(...)",
            }
        ],
    }

    tasks, rows = apply_triage_to_tasks([task], uo_root=tmp_path)

    assert tasks[0]["task_status"] == "open"
    assert tasks[0]["promoted_from_provisional"] is True
    assert tasks[0]["eligible_for_adjudication"] is True
    assert rows[0]["score_phase"] == "post_semantic"
    assert rows[0]["promoted_from_provisional"] is True


def test_post_semantic_empty_candidate_has_executable_route(tmp_path) -> None:
    task = {
        "task_id": "TASK_2",
        "status": "open",
        "task_status": "open",
        "score_phase": "post_semantic",
        "type": "candidate_generation",
        "object_type": "call_edge",
        "target": "E_MISSING",
        "candidates": [],
    }

    tasks, rows = apply_triage_to_tasks([task], uo_root=tmp_path)

    assert rows[0]["category"] == "candidate_generation_required"
    assert tasks[0]["route"] == "uo-semantic-resolve"
    assert tasks[0]["eligible_for_adjudication"] is True

    payload = write_semantic_task_triage(tmp_path, tasks=tasks, run_id="RUN_TEST")
    assert payload["stats"]["post_semantic_provisional_count"] == 0
    assert payload["stats"]["blocking_route_none_count"] == 0
