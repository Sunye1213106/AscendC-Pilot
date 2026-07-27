"""P0-P2 semantic closure: task contract, auto mark_missing, routes, scope, KEY false."""

from __future__ import annotations

from pathlib import Path

from uo.scripts.llm_tasks import can_auto_mark_missing, validate_task_patch
from uo.scripts.scope_expansion import audit_scope_expansion_request
from uo.scripts.semantic_patches import validate_typed_patch
from uo.scripts.semantic_task_triage import (
    CATEGORY_TO_EFFECTIVE_TYPE,
    effective_task_type_for,
    validate_semantic_task_contract,
)


def test_effective_task_type_mapping() -> None:
    for cat, expected in CATEGORY_TO_EFFECTIVE_TYPE.items():
        assert effective_task_type_for({"triage_category": cat, "type": "mark_missing"}) == expected


def test_contract_rejects_mark_missing_on_candidate_generation() -> None:
    task = {
        "task_id": "t1",
        "type": "mark_missing",
        "triage_category": "candidate_generation_required",
        "effective_task_type": "mark_missing",
        "route": "uo-semantic-resolve",
    }
    result = validate_semantic_task_contract(task)
    assert result["ok"] is False
    assert result["error"] == "SEMANTIC_TASK_CONTRACT_CONFLICT"


def test_can_auto_mark_missing_requires_negative_evidence() -> None:
    empty = {
        "type": "mark_missing",
        "effective_task_type": "mark_missing",
        "candidates": [],
    }
    assert can_auto_mark_missing(empty) is False
    ok = {
        **empty,
        "negative_evidence": {
            "absence_kind": "project_definition_absent",
            "queries": ["Foo"],
            "inspected_windows": [{"path": "a.cpp", "sha256": "x"}],
            "scope_snapshot_sha256": "abc",
        },
    }
    assert can_auto_mark_missing(ok) is True


def test_can_auto_mark_missing_forbids_generation_categories() -> None:
    task = {
        "type": "mark_missing",
        "effective_task_type": "mark_missing",
        "triage_category": "candidate_generation_required",
        "candidates": [],
        "negative_evidence": {
            "absence_kind": "project_definition_absent",
            "queries": ["Foo"],
            "inspected_windows": [{"path": "a.cpp"}],
            "scope_snapshot_sha256": "abc",
        },
    }
    assert can_auto_mark_missing(task) is False


def test_candidate_enrichment_typed_patch() -> None:
    bad = validate_typed_patch({"patch_type": "candidate_enrichment"}, patch_type="candidate_enrichment")
    assert bad["ok"] is False
    good = validate_typed_patch(
        {"patch_type": "candidate_enrichment", "candidates": [{"id": "cand_1"}]},
        patch_type="candidate_enrichment",
    )
    assert good["ok"] is True


def test_scope_expansion_audit_accepts_reachable(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    host = op / "op_host"
    host.mkdir(parents=True)
    (host / "extra.cpp").write_text("// x\n", encoding="utf-8")
    audit = audit_scope_expansion_request(
        op,
        "DemoOp",
        {"proposed_files": ["op_host/extra.cpp"], "missing_symbol": "X"},
    )
    assert audit["ok"] is True
    assert "op_host/extra.cpp" in audit["accepted_files"]


def test_scope_expansion_rejects_missing(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    audit = audit_scope_expansion_request(
        op,
        "DemoOp",
        {"proposed_files": ["op_host/missing.cpp"]},
    )
    assert audit["ok"] is False


def test_recoveries_for_task_routes_macro_and_key() -> None:
    from ascendc_pilot.recovery import (
        KEY_DERIVATION_REWORK,
        MACRO_MATERIALIZE_REWORK,
        recoveries_for_task_routes,
    )

    routed = recoveries_for_task_routes(
        [
            {"effective_task_type": "macro_semantics", "route": "macro_semantic_materializer"},
            {"effective_task_type": "key_derivation", "triage_category": "key_derivation_gap"},
        ]
    )
    assert MACRO_MATERIALIZE_REWORK in routed["reason_codes"]
    assert KEY_DERIVATION_REWORK in routed["reason_codes"]


def test_no_progress_is_human_required() -> None:
    from ascendc_pilot.recovery import NO_PROGRESS_RECHECK, recoveries_for_closure_gaps, resolve_recovery

    resolved = resolve_recovery(NO_PROGRESS_RECHECK)
    assert resolved["ok"] is True
    assert resolved["recovery"]["type"] == "human_required"
    routed = recoveries_for_closure_gaps(
        host_closed=True,
        kernel_closed=True,
        blocking_gap_count=1,
        unconsumed_patch_count=0,
        no_progress=True,
        blocking_tasks=[{"effective_task_type": "choose_edge", "route": "uo-semantic-resolve"}],
    )
    assert routed.get("human_required") is True
    assert NO_PROGRESS_RECHECK in routed["reason_codes"]


def test_validate_task_patch_candidate_enrichment() -> None:
    doc = {
        "tasks": [
            {
                "task_id": "TASK_x",
                "run_id": "r1",
                "type": "candidate_generation",
                "effective_task_type": "candidate_generation",
                "task_status": "open",
                "status": "open",
                "candidates": [],
                "candidate_set_hash": "deadbeefdeadbeef",
                "source_snapshot_hash": "snap1",
                "allowed_actions": ["candidate_enrichment"],
            }
        ]
    }
    patch = {
        "task_id": "TASK_x",
        "run_id": "r1",
        "action": "candidate_enrichment",
        "patch_type": "candidate_enrichment",
        "candidates": [{"id": "cand_a", "symbol_ref": "Foo"}],
        "candidate_set_hash": "deadbeefdeadbeef",
        "source_snapshot_hash": "snap1",
        "accepted_candidate_ids": [],
        "rejected_candidate_ids": [],
    }
    result = validate_task_patch(doc, patch, current_source_hash="snap1", current_run_id="r1")
    assert result["ok"] is True
    assert result["action"] == "candidate_enrichment"
