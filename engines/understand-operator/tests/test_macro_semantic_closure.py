"""Phase A: macro contracts, triage, mark_missing Gate, no-op rebuild."""

from __future__ import annotations

from pathlib import Path

import pytest

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.evidence_score import score_entrypoint_node
from uo.scripts.llm_tasks import (
    open_blocking_tasks,
    validate_mark_missing_patch,
    validate_task_patch,
)
from uo.scripts.macro_semantic_materializer import (
    load_macro_contracts,
    materialize_macro_semantics,
    scan_macro_invocations,
)
from uo.scripts.semantic_resolution_ledger import (
    compute_rebuild_input_fingerprint,
    materializable_delta_count,
    should_skip_layered_rebuild,
)
from uo.scripts.semantic_task_triage import classify_task, write_semantic_task_triage

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fag_macro_semantic_failure"
RUN_ID = "RUN_20260726_121719_0d48474d"


def test_fixture_baseline_present() -> None:
    expected = read_yaml(FIXTURE / "expected_triage.yaml") or {}
    assert (expected.get("baseline") or {}).get("run_id") == RUN_ID
    assert (FIXTURE / "llm_tasks_pre.yaml").is_file()
    assert (FIXTURE / "macro_invocations.yaml").is_file()


def test_macro_contracts_cover_registration_macros() -> None:
    names = {c["name"] for c in load_macro_contracts()}
    assert "REG_OP" in names
    assert "IMPL_OP_OPTILING" in names
    assert "REGISTER_TILING_TEMPLATE" in names
    assert "GET_TILING_DATA" in names


def test_scan_chained_impl_op() -> None:
    text = """
IMPL_OP_OPTILING(FlashAttentionScoreGrad)
    .Tiling(TilingFlashAttentionGradScore)
    .TilingParse(TilingPrepareFlashAttentionScoreGrad);
"""
    contracts = load_macro_contracts()
    invs = scan_macro_invocations("op_host/x.cpp", text, contracts)
    impl = [i for i in invs if i["macro"] == "IMPL_OP_OPTILING"]
    assert impl
    methods = {m["name"] for m in impl[0].get("chained_methods") or []}
    assert "Tiling" in methods
    assert "TilingParse" in methods


def test_score_entrypoint_macro_not_zero() -> None:
    node = {
        "id": "EP_REG_1",
        "role": "operator_registration",
        "macro": "REG_OP",
        "status": "verified",
        "confidence": None,
        "architecture": "neutral",
        "locator": {"file_path": "op_graph/x.h", "start_line": 10},
        "symbol_ref": {"qualified_name": "REG_OP::Foo"},
    }
    scored = score_entrypoint_node(node, architecture="arch35")
    assert scored["disposition"] == "auto_accept"
    assert float(scored["score"]) >= 0.8


def test_triage_macro_not_llm_and_key_not_extract_blocking() -> None:
    macro_task = {
        "task_id": "T1",
        "candidates": [{"symbol_ref": "REGISTER_TILING_TEMPLATE::Foo", "file_path": "a.cpp", "start_line": 1}],
        "checkpoint": "extract.pre_semantic",
        "score_phase": "pre_semantic",
    }
    row = classify_task(macro_task)
    assert row["category"] == "macro_contract_resolvable"
    assert row["eligible_for_adjudication"] is False

    key_task = {
        "task_id": "T2",
        "object_type": "tilingkey_binding",
        "type": "tilingkey_schema_bind",
        "candidates": [{"symbol_ref": "GET_TPL_TILING_KEY", "file_path": "k.cpp", "start_line": 2, "snippet": "x"}],
        "score_phase": "post_semantic",
    }
    krow = classify_task(key_task)
    assert krow["category"] == "key_derivation_gap"
    assert krow["blocks_extract_advance"] is False
    assert krow["route"] == "uo-key-resolve"


def test_fixture_triage_and_open_blocking(tmp_path: Path) -> None:
    uo = tmp_path / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(uo / "manifest.yaml", {"current_run_id": RUN_ID, "op_name": "flash_attention_score_grad"})
    pre = read_yaml(FIXTURE / "llm_tasks_pre.yaml") or {}
    write_yaml(uo / "ir" / "llm_tasks.yaml", pre)
    triage = write_semantic_task_triage(uo, run_id=RUN_ID)
    assert int((triage.get("stats") or {}).get("task_count") or 0) >= 5
    # Pre macro tasks must not be adjudicable.
    assert open_blocking_tasks(uo, current_run_id=RUN_ID) == []


def test_mark_missing_score_only_rejected() -> None:
    task = {
        "task_id": "TASK_x",
        "status": "open",
        "task_status": "open",
        "run_id": RUN_ID,
        "source_snapshot_hash": "abc",
        "candidate_set_hash": "def",
        "allowed_actions": ["mark_missing"],
        "candidates": [],
        "triage_category": "true_multi_candidate",
    }
    patch = {
        "task_id": "TASK_x",
        "run_id": RUN_ID,
        "action": "mark_missing",
        "candidate_set_hash": "def",
        "source_snapshot_hash": "abc",
        "accepted_candidate_ids": [],
        "evidence": ["评分为 0.0，低于 auto_accept 阈值 0.8"],
    }
    err = validate_mark_missing_patch(task, patch)
    assert err is not None
    assert err["error"] == "mark_missing_score_only_forbidden"

    task["triage_category"] = "macro_contract_resolvable"
    err2 = validate_mark_missing_patch(task, patch)
    assert err2 is not None
    assert err2["error"] == "mark_missing_forbidden_macro_contract"


def test_mark_missing_with_negative_evidence_ok() -> None:
    task = {
        "task_id": "TASK_y",
        "status": "open",
        "task_status": "open",
        "run_id": RUN_ID,
        "source_snapshot_hash": "snap1",
        "candidate_set_hash": "cset1",
        "allowed_actions": ["mark_missing"],
        "candidates": [{"id": "cand_1"}],
        "triage_category": "true_multi_candidate",
    }
    patch = {
        "task_id": "TASK_y",
        "run_id": RUN_ID,
        "action": "mark_missing",
        "candidate_set_hash": "cset1",
        "source_snapshot_hash": "snap1",
        "accepted_candidate_ids": [],
        "evidence": ["searched confirmed scope; definition absent"],
        "negative_evidence": {
            "scope_snapshot_sha256": "snap1",
            "include_closure_status": "incomplete",
            "queries": [{"symbol": "FooBar", "search_mode": "exact", "result_count": 0}],
            "inspected_windows": [
                {"file": "op_host/a.cpp", "lines": [1, 20], "window_sha256": "deadbeef"}
            ],
            "absence_kind": "project_definition_absent",
        },
    }
    doc = {"version": 1, "tasks": [task]}
    result = validate_task_patch(doc, patch, current_source_hash="snap1", current_run_id=RUN_ID)
    assert result.get("ok") is True


def test_materialize_upgrades_fixture_entrypoint(tmp_path: Path) -> None:
    op = "flash_attention_score_grad"
    root = tmp_path / op
    uo = root / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(uo / "manifest.yaml", {"op_name": op, "current_run_id": RUN_ID})
    ep = read_yaml(FIXTURE / "entrypoint_graph.yaml") or {}
    write_yaml(uo / "ir" / "entrypoint_graph.yaml", ep)
    # Minimal fake sources so scan can find macros.
    host = root / "op_host"
    host.mkdir(parents=True)
    (host / "reg.cpp").write_text(
        "REG_OP(FlashAttentionScoreGrad);\n"
        "IMPL_OP_OPTILING(FlashAttentionScoreGrad).Tiling(TilingFn).TilingParse(ParseFn);\n"
        "REGISTER_TILING_TEMPLATE(FlashAttentionScoreGrad, FooTmpl, AscendC::Architecture::ASCEND_V220, 0);\n",
        encoding="utf-8",
    )
    result = materialize_macro_semantics(root, op, architecture="arch35", uo_root=uo)
    assert result.get("ok")
    stats = result.get("macro_materialization") or {}
    assert int(stats.get("invocation_count") or 0) >= 1
    out_ep = read_yaml(uo / "ir" / "entrypoint_graph.yaml") or {}
    macro_nodes = [n for n in (out_ep.get("nodes") or []) if n.get("macro")]
    assert macro_nodes
    assert all(n.get("confidence") == "source_verified" for n in macro_nodes)
    assert (uo / "ir" / "macro_semantics.yaml").is_file()


def test_skip_rebuild_when_fingerprint_stable(tmp_path: Path) -> None:
    uo = tmp_path / ".ascendc-pilot" / "uo"
    ir = uo / "ir"
    ir.mkdir(parents=True)
    for name in (
        "entrypoint_graph.yaml",
        "host_subgraph.yaml",
        "kernel_subgraph.yaml",
        "bridge.yaml",
        "operator_graph.yaml",
        "extract_plan.yaml",
    ):
        write_yaml(ir / name, {"version": 1, "nodes": [], "edges": []})
    write_yaml(
        uo / "ir" / "semantic_resolution_ledger.yaml",
        {
            "version": 1,
            "semantic_patches": [
                {
                    "run_id": RUN_ID,
                    "task_id": "T1",
                    "action": "mark_missing",
                    "patch_type": "mark_missing",
                    "apply_status": "recorded",
                }
            ],
        },
    )
    assert materializable_delta_count(
        read_yaml(ir / "semantic_resolution_ledger.yaml") or {}, current_run_id=RUN_ID
    ) == 0
    fp = compute_rebuild_input_fingerprint(
        uo, architecture="arch35", source_snapshot="snap", current_run_id=RUN_ID
    )
    write_yaml(ir / "rebuild_input_fingerprint.yaml", {"version": 1, **fp})
    decision = should_skip_layered_rebuild(
        uo, architecture="arch35", source_snapshot="snap", current_run_id=RUN_ID
    )
    assert decision["skip"] is True
    assert decision["materializable_delta_count"] == 0
