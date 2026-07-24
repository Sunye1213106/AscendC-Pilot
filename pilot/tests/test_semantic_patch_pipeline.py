"""Semantic patch producer?apply pipeline and recommended_next."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.workflows.pipeline import recommend_next_action
from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(obj, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_semantic_patches_contract_registered() -> None:
    assert "semantic-patches-v1" in OUTPUT_CONTRACT_PATHS
    assert "uo/ir/semantic_patches.yaml" in OUTPUT_CONTRACT_PATHS["semantic-patches-v1"]


def test_resolve_auto_mark_missing(tmp_path: Path, monkeypatch) -> None:
    import sys

    eng = Path(__file__).resolve().parents[2] / "engines" / "understand-operator"
    if str(eng) not in sys.path:
        sys.path.insert(0, str(eng))
    from uo.scripts.llm_tasks import resolve_patches_for_apply, apply_patches_batch

    uo = tmp_path / "uo"
    ir = uo / "ir"
    _write(
        ir / "llm_tasks.yaml",
        {
            "version": 1,
            "total_semantic_batches": 0,
            "tasks": [
                {
                    "task_id": "t1",
                    "status": "open",
                    "severity": "blocking",
                    "type": "mark_missing",
                    "candidates": [],
                    "allowed_actions": ["mark_missing"],
                    "source_snapshot_hash": "h1",
                    "candidate_set_hash": "c1",
                }
            ],
        },
    )
    resolved = resolve_patches_for_apply(uo)
    assert resolved["ok"] is True
    assert resolved["source"] == "auto_mark_missing"
    assert len(resolved["patches"]) == 1
    applied = apply_patches_batch(uo, resolved["patches"], current_source_hash="h1")
    assert applied["ok"] is True
    assert (ir / "semantic_resolution_ledger.yaml").is_file()


def test_resolve_requires_producer_when_candidates(tmp_path: Path) -> None:
    import sys

    eng = Path(__file__).resolve().parents[2] / "engines" / "understand-operator"
    if str(eng) not in sys.path:
        sys.path.insert(0, str(eng))
    from uo.scripts.llm_tasks import resolve_patches_for_apply

    uo = tmp_path / "uo"
    ir = uo / "ir"
    _write(
        ir / "llm_tasks.yaml",
        {
            "version": 1,
            "tasks": [
                {
                    "task_id": "t2",
                    "status": "open",
                    "severity": "blocking",
                    "type": "choose_edge",
                    "candidates": [{"id": "cand_a"}],
                    "allowed_actions": ["choose_one", "mark_missing"],
                }
            ],
        },
    )
    resolved = resolve_patches_for_apply(uo)
    assert resolved["ok"] is False
    assert resolved["error"] == "SEMANTIC_PATCHES_REQUIRED"

    _write(
        ir / "semantic_patches.yaml",
        {
            "version": 1,
            "patches": [
                {
                    "task_id": "t2",
                    "action": "choose_one",
                    "accepted_candidate_ids": ["cand_a"],
                    "rejected_candidate_ids": [],
                    "evidence": ["test"],
                }
            ],
        },
    )
    resolved2 = resolve_patches_for_apply(
        uo, patches_doc=yaml.safe_load((ir / "semantic_patches.yaml").read_text(encoding="utf-8"))
    )
    assert resolved2["ok"] is True
    assert resolved2["source"] == "semantic_patches.yaml"


def test_recommend_extract_order(tmp_path: Path) -> None:
    from ascendc_pilot.runs import issue_receipt
    from ascendc_pilot.spec_hashes import workflow_spec_hash
    from ascendc_pilot.state import start_workflow

    root = tmp_path / "op"
    start_workflow(root, "uo-init", phase="extract", force_phase=True)
    allowed = [
        {"id": "detect_score_pre", "label_zh": "pre"},
        {"id": "extract_plan", "label_zh": "plan"},
        {"id": "detect_score_post", "label_zh": "post"},
        {"id": "adjudicate_llm_tasks", "label_zh": "adj"},
        {"id": "apply_semantic_patch", "label_zh": "apply"},
        {"id": "rebuild_from_ledger", "label_zh": "rebuild"},
        {"id": "recheck_closure", "label_zh": "recheck"},
    ]
    rec = recommend_next_action(root, workflow_id="uo-init", phase="extract", allowed_actions=allowed)
    assert rec and rec["id"] == "detect_score_pre"

    issue_receipt(
        root,
        actor_type="deterministic_engine",
        actor_id="deterministic-uo-engine",
        action_id="detect_score_pre",
        workflow_spec_hash=workflow_spec_hash("uo-init"),
        input_hashes={"f": "1"},
        output_hashes={"f": "1"},
        checker_result={"ok": True},
        nonce="pre",
        _internal=True,
    )
    rec2 = recommend_next_action(root, workflow_id="uo-init", phase="extract", allowed_actions=allowed)
    assert rec2 and rec2["id"] == "extract_plan"

    issue_receipt(
        root,
        actor_type="producer",
        actor_id="uo-semantic-resolve",
        action_id="extract_plan",
        workflow_spec_hash=workflow_spec_hash("uo-init"),
        input_hashes={"f": "1"},
        output_hashes={"f": "1"},
        checker_result={"ok": True},
        nonce="plan",
        _internal=True,
    )
    rec3 = recommend_next_action(root, workflow_id="uo-init", phase="extract", allowed_actions=allowed)
    assert rec3 and rec3["id"] == "detect_score_post"
