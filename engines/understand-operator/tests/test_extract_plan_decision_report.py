"""Tests for extract-plan decision_report / worklist / role evidence / slim IR."""
from __future__ import annotations

from pathlib import Path

from ascendc_pilot.ownership import (
    ACTION_FINALIZER_WRITE_PATHS,
    ACTION_PRODUCER_WRITE_PATHS,
    action_producer_write_paths,
    path_matches_patterns,
)
from uo.scripts.extract_plan_decision import (
    assert_canonical_plan_slim,
    build_decision_worklist,
    classify_candidate_kind,
    materialize_plan_from_decision_report,
    report_extract_plan_coverage,
    slim_extract_plan,
    validate_decision_coverage,
    validate_decision_report_schema,
    validate_extract_plan_staging,
)
from uo.scripts.receiver_binding import extract_receiver_bindings
from uo.scripts.role_evidence import validate_role_evidence


def test_common_assign_not_auto_reject_kind() -> None:
    kind = classify_candidate_kind(
        {"name": "TND_TILING_DATA_COMMON_ASSIGN", "score": 0.95},
        section="writer_candidates",
    )
    assert kind == "macro_binding"
    kind2 = classify_candidate_kind(
        {"name": "BASE_TILING_DATA_COMMON_ASSIGN"},
        section="writer_candidates",
    )
    assert kind2 == "macro_binding"


def test_receiver_binding_from_addr_assign() -> None:
    text = """
    FlashAttentionScoreGradTilingDataRegbase *tilingData =
        context_->GetTilingData<FlashAttentionScoreGradTilingDataRegbase>();
    s1s2BNGS1S2BaseParams_ = &tilingData->s1s2BNGS1S2BaseParams;
    """
    bindings = extract_receiver_bindings(text, file_path="op_host/x.cpp")
    assert bindings
    assert bindings[0]["receiver"] == "s1s2BNGS1S2BaseParams_"
    assert bindings[0]["nested_field"] == "s1s2BNGS1S2BaseParams"
    assert "FlashAttentionScoreGradTilingDataRegbase" in (
        bindings[0].get("root_tiling_types") or []
    )


def test_role_evidence_writer_without_set_fails() -> None:
    item = {
        "role": "tiling_writer",
        "evidence_snippet": "int AlignTo(int x) { return (x + 15) & ~15; }",
    }
    r = validate_role_evidence(item, role="tiling_writer")
    assert r["authentic"] is True
    assert r["sufficient"] is False
    assert r["reason_code"] == "writer_evidence_insufficient"


def test_role_evidence_key_writer_needs_key_construct() -> None:
    item = {
        "role": "key_writer",
        "evidence_snippet": "bool drop = keepProb < 1; // input condition only",
    }
    r = validate_role_evidence(item, role="key_writer")
    assert r["sufficient"] is False
    assert r["reason_code"] == "key_writer_evidence_insufficient"

    item2 = {
        "role": "key_writer",
        "evidence_snippet": "uint64_t key = GET_TPL_TILING_KEY(...); return key;",
    }
    r2 = validate_role_evidence(item2, role="key_writer")
    assert r2["sufficient"] is True


def test_decision_report_missing_candidate_id_fails() -> None:
    errs = validate_decision_report_schema(
        {"version": 1, "accepted": [{"role": "tiling_writer"}], "rejected": [], "deferred": []}
    )
    assert any("candidate_id" in e for e in errs)


def test_coverage_incomplete_fails() -> None:
    worklist = {
        "work_items": [
            {"candidate_id": "CAND_a", "required_decision": True},
            {"candidate_id": "CAND_b", "required_decision": True},
        ]
    }
    report = {
        "version": 1,
        "accepted": [{"candidate_id": "CAND_a", "role": "tiling_writer"}],
        "rejected": [],
        "deferred": [],
    }
    errs = validate_decision_coverage(report, worklist)
    assert any("CAND_b" in e for e in errs)


def test_canonical_ir_no_evidence_snippet() -> None:
    plan = {
        "architecture": "arch35",
        "candidates_sha256": "a" * 64,
        "writers": [
            {
                "name": "Save",
                "role": "tiling_writer",
                "candidate_id": "CAND_1",
                "file_path": "a.cpp",
                "evidence_snippet": "blob_->set_x(1);",
                "decision_reason": "has set",
                "score": 0.9,
            }
        ],
        "receivers": [{"name": "blob_", "is_tiling_sink": True, "candidate_id": "CAND_2"}],
        "aliases": [{"local": "L", "tdf_leaf": "x", "score": 0.9, "evidence": ["tdf_assign"]}],
        "receiver_bindings": [
            {
                "receiver": "blob_",
                "nested_field": "nested",
                "member_type": "Params",
                "root_tiling_types": ["Root"],
                "candidate_id": "CAND_3",
                "canonical_owner_key": {
                    "root_type": "Root",
                    "nested_path": "nested",
                    "member_type": "Params",
                },
            }
        ],
    }
    slim, aliases, bindings = slim_extract_plan(plan)
    assert "evidence_snippet" not in str(slim.get("writers"))
    errs = assert_canonical_plan_slim(slim)
    assert not errs, errs
    assert aliases["aliases"]["L"] == "x"
    assert "RB_001" in bindings["bindings"]
    assert slim["aliases_ref"]["path"] == "extract_plan_aliases.yaml"
    assert slim["receiver_bindings_ref"]["path"] == "receiver_bindings.yaml"


def test_sidecar_refs_present() -> None:
    slim, _, _ = slim_extract_plan(
        {
            "writers": [],
            "receivers": [],
            "aliases": [{"local": "a", "tdf_leaf": "b"}],
            "receiver_bindings": [],
            "candidates_sha256": "b" * 64,
        }
    )
    assert slim["aliases_ref"]["count"] == 1
    assert slim["receiver_bindings_ref"]["count"] == 0


def test_producer_cannot_write_canonical_ir() -> None:
    rows = ACTION_PRODUCER_WRITE_PATHS["uo-init"]["extract_plan"]
    assert any("relation_parts" in p for p in rows)
    assert not any(p.endswith("semantic_relations.yaml") and "staging" not in p for p in rows)
    assert not any(p == "uo/ir/extract_plan.yaml" for p in rows)
    fin = ACTION_FINALIZER_WRITE_PATHS["uo-init"]["extract_plan"]
    assert "uo/ir/extract_plan.yaml" in fin
    assert "uo/ir/receiver_bindings.yaml" in fin
    assert "uo/ir/semantic_relations.yaml" in fin
    patterns = action_producer_write_paths("uo-init", "extract_plan", run_id="RUN_x")
    assert not path_matches_patterns("uo/ir/extract_plan.yaml", patterns)
    assert path_matches_patterns(
        "runs/RUN_x/actions/extract_plan/staging/relation_parts/part_000.yaml",
        patterns,
    )
    assert not path_matches_patterns(
        "uo/ir/semantic_relations.yaml",
        patterns,
    )


def test_wrong_role_with_real_snippet_fails_sufficiency() -> None:
    """Setter-only text must not support COMPOSES_KEY."""
    from uo.scripts.relation_evidence import validate_relation_evidence

    text = (
        "void SaveToTilingData() {\n"
        "  baseParams_->set_b(1);\n"
        "  baseParams_->set_n2(2);\n"
        "}\n"
    )
    r = validate_relation_evidence("COMPOSES_KEY", text=text, authentic=True)
    assert r["authentic"] is True
    assert r["supported"] is False


def test_materialize_and_staging_gate() -> None:
    cands = {
        "architecture": "arch35",
        "writer_candidates": [
            {
                "candidate_id": "CAND_w1",
                "name": "SaveStuff",
                "file_path": "op_host/a.cpp",
                "start_line": 10,
                "role_suggested": "tiling_writer",
                "score": 0.9,
                "source_window": {
                    "text": "void SaveStuff() { blob_->set_x(1); }",
                    "sha256": "c" * 64,
                    "start_line": 10,
                    "end_line": 12,
                },
            }
        ],
        "receiver_candidates": [],
        "alias_candidates": [],
        "receiver_binding_candidates": [],
    }
    worklist = build_decision_worklist(cands, architecture="arch35")
    required = [w for w in worklist["work_items"] if w.get("required_decision")]
    assert any(w["candidate_id"] == "CAND_w1" for w in required)

    report = {
        "version": 1,
        "candidates_sha256": "d" * 64,
        "accepted": [{"candidate_id": "CAND_w1", "role": "tiling_writer"}],
        "rejected": [],
        "deferred": [
            {"candidate_id": w["candidate_id"], "reason_code": "out_of_scope"}
            for w in required
            if w["candidate_id"] != "CAND_w1"
        ],
    }
    # Cover all required
    covered = {r["candidate_id"] for r in report["accepted"]} | {
        r["candidate_id"] for r in report["deferred"]
    }
    for w in required:
        if w["candidate_id"] not in covered:
            report["deferred"].append(
                {"candidate_id": w["candidate_id"], "reason_code": "pad"}
            )

    errs = validate_extract_plan_staging(report=report, worklist=worklist)
    assert not errs, errs

    plan = materialize_plan_from_decision_report(report, cands)
    assert plan["writers"]
    assert plan["writers"][0]["name"] == "SaveStuff"
    cov = report_extract_plan_coverage(worklist, report)
    assert cov["ok"] is True
