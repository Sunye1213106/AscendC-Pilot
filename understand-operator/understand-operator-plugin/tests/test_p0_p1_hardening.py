from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from understand_operator._operator import kb_compiler
from understand_operator._operator.artifacts import init_operator_layout, operator_root
from understand_operator._operator.kb_compiler import promote_kb, validate_kb
from understand_operator.scripts.kb_query_export import export_context_slice
from understand_operator.scripts.macro_scope_scan import main as macro_scope_scan_main
from understand_operator.scripts.update_operator import (
    _build_stale_artifacts,
    _build_update_plan,
    _tilingdata_numeric_only_proven,
)


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = operator_root(repo, "DemoOp")
    init_operator_layout(base, "DemoOp", repo)
    for rel in (
        "registry/symbols.yaml",
        "tiling/constraints.yaml",
        "tiling/key_space.yaml",
        "tiling/families.yaml",
        "tiling/data_model.yaml",
        "tiling/coverage_model.yaml",
        "tiling/variables.yaml",
        "flow/compute_graph.yaml",
        "flow/dataflow.yaml",
        "flow/golden_model.yaml",
        "flow/numerical_model.yaml",
        "evidence/fact_index.yaml",
        "evidence/source_index.yaml",
        "evidence/artifact_dependencies.yaml",
        "evidence/issues.yaml",
        "tiling/evidence_index.yaml",
        "registry/aliases.yaml",
    ):
        path = base / rel
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            data = {}
        data.update(
            {
                "status": "not_applicable",
                "reason": "minimal hardening unit test fixture",
                "evidence_refs": ["EV_HOST_017"],
            }
        )
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return repo, base


def test_macro_scope_scan_artifact_initialized(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    scan_path = base / "archive" / "runs" / "macro_scope_scan.yaml"
    assert scan_path.exists()
    scan = yaml.safe_load(scan_path.read_text(encoding="utf-8"))
    assert scan["version"] == 1
    assert scan["op_name"] == "DemoOp"
    assert scan["scan_method"]["ignore_rules_applied"] is True
    assert scan["large_files"] == []
    assert "macro_scope_scan.yaml" in (base / "index.yaml").read_text(encoding="utf-8")


def test_tool_selection_prompts_scope_scan_before_semantic_cbm() -> None:
    rule = (ROOT / "prompts" / "00_cbm_first_rule.md").read_text(encoding="utf-8")
    review = (ROOT / "prompts" / "01a_macro_scope_human_review.md").read_text(encoding="utf-8")
    boundary = (ROOT / "prompts" / "02_macro_boundary_agent.md").read_text(encoding="utf-8")

    assert "Repository structure, file boundaries" in rule
    assert "CBM MCP first" in rule
    assert "Tool Decision Table" in rule
    assert "Phase 0.5-A: Deterministic Scope Scan" in review
    assert "archive/runs/macro_scope_scan.yaml" in review
    assert "Phase 1 must not rescan the whole repository from scratch" in boundary
    assert "Never open source files " + "before" not in rule
    assert "Never " + "Grep" not in rule


def test_macro_scope_scan_script_generates_deterministic_candidates(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    host = repo / "op_host" / "demo_tiling.cpp"
    kernel = repo / "op_kernel" / "arch35" / "demo_kernel.cpp"
    host.parent.mkdir(parents=True, exist_ok=True)
    kernel.parent.mkdir(parents=True, exist_ok=True)
    host.write_text("REGISTER_TILING(DemoOp)\nTILING_KEY_IS(1)\n", encoding="utf-8")
    kernel.write_text("__global__ void DemoOpKernel() {}\n// arch35\n", encoding="utf-8")
    large = repo / "op_host" / "large.cpp"
    large.write_text("x" * (513 * 1024), encoding="utf-8")

    assert macro_scope_scan_main([str(repo), "--op-name", "DemoOp"]) == 0
    scan = yaml.safe_load((base / "archive" / "runs" / "macro_scope_scan.yaml").read_text(encoding="utf-8"))

    assert scan["files"]["host"] == ["op_host/demo_tiling.cpp", "op_host/large.cpp"]
    assert scan["files"]["kernel"] == ["op_kernel/arch35/demo_kernel.cpp"]
    assert scan["architecture_variants"][0]["name"] == "arch35"
    assert {item["item"] for item in scan["entry_candidates"]} >= {
        "REGISTER_TILING",
        "TILING_KEY_IS",
        "__global__",
    }
    assert scan["large_files"] == [
        {"path": "op_host/large.cpp", "size_bytes": 513 * 1024, "read_policy": "line_scoped_only"}
    ]


def _minimal_proposal(**overrides: object) -> dict:
    proposal = {
        "version": 1,
        "op_name": "DemoOp",
        "proposal_id": "PROP_HOST_001",
        "producer": {"agent": "uo-host-extraction", "phase": "phase2"},
        "generated_at": "2026-01-01T00:00:00Z",
        "status": "proposed",
        "canonical_updates": [
            {
                "target": "registry/evidence.yaml",
                "section": "evidence",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "EV_HOST_017",
                        "file": "op_host/foo.cpp",
                        "lines": [10, 12],
                        "symbol": "Foo",
                        "kind": "source_span",
                    }
                ],
            },
            {
                "target": "registry/variables.yaml",
                "section": "variables",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "VAR_ATTEN_MASK_PRESENT",
                        "kind": "variable",
                        "canonical_name": "atten_mask_present",
                        "scope": "host",
                        "data_type": "bool",
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
        ],
        "unresolved": [],
        "conflicts": [],
    }
    proposal.update(overrides)
    return proposal


def test_proposal_hash_no_explicit_uses_computed(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    proposal = _minimal_proposal()
    computed = kb_compiler._computed_proposal_hash(proposal)
    path = base / "archive" / "proposals" / "no_hash.yaml"
    path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")
    result = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[path], run_id="run_no_hash")
    assert result.promotion_report["status"] == "promoted"
    assert result.promotion_report["proposal_hashes"]["PROP_HOST_001"] == computed
    assert not any(issue.code == "PROPOSAL_HASH_MISMATCH" for issue in result.issues)


def test_proposal_hash_correct_explicit_accepted(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    proposal = _minimal_proposal()
    computed = kb_compiler._computed_proposal_hash(proposal)
    proposal["proposal_hash"] = computed
    path = base / "archive" / "proposals" / "ok_hash.yaml"
    path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")
    result = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[path], run_id="run_ok_hash")
    assert result.promotion_report["status"] == "promoted"
    assert not any(issue.code == "PROPOSAL_HASH_MISMATCH" for issue in result.issues)


def test_proposal_hash_wrong_explicit_blocks_promotion(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    proposal = _minimal_proposal(proposal_hash="deadbeef" * 8)
    path = base / "archive" / "proposals" / "bad_hash.yaml"
    path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")
    result = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[path], run_id="run_bad_hash")
    assert result.status == "fail"
    assert any(issue.code == "PROPOSAL_HASH_MISMATCH" for issue in result.issues)
    assert result.promotion_report["status"] == "failed"


def test_same_proposal_id_different_content_conflicts(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    first = _minimal_proposal()
    p1 = base / "archive" / "proposals" / "first.yaml"
    p1.write_text(yaml.safe_dump(first, sort_keys=False), encoding="utf-8")
    promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[p1], run_id="run_a")

    second = _minimal_proposal()
    second["canonical_updates"][1]["entries"][0]["canonical_name"] = "changed_name"
    p2 = base / "archive" / "proposals" / "second.yaml"
    p2.write_text(yaml.safe_dump(second, sort_keys=False), encoding="utf-8")
    result = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[p2], run_id="run_b")
    assert any(issue.code == "PROPOSAL_ID_REUSED_WITH_DIFFERENT_CONTENT" for issue in result.issues)


def test_same_proposal_id_same_content_already_promoted(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    proposal = _minimal_proposal()
    path = base / "archive" / "proposals" / "same.yaml"
    path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")
    first = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[path], run_id="run_same")
    second = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[path], run_id="run_same")
    assert first.promotion_report["status"] == "promoted"
    assert any(item.get("code") == "ALREADY_PROMOTED" for item in second.promotion_report.get("skipped_proposals") or [])


def test_transaction_first_file_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "uo"
    (base / "registry").mkdir(parents=True)
    payloads = {"registry/a.yaml": "version: 1\nvalue: new\n"}
    real_mkstemp = kb_compiler.tempfile.mkstemp

    def fail_mkstemp(*args: object, **kwargs: object):
        raise OSError("injected first write failure")

    monkeypatch.setattr(kb_compiler.tempfile, "mkstemp", fail_mkstemp)
    tx = kb_compiler._transactional_write_texts(base, payloads)
    assert tx.transaction_status == "rolled_back"
    assert "injected first write failure" in tx.failure_reason
    monkeypatch.setattr(kb_compiler.tempfile, "mkstemp", real_mkstemp)


def test_transaction_mid_replace_failure_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "uo"
    (base / "registry").mkdir(parents=True)
    (base / "tiling").mkdir()
    (base / "registry" / "a.yaml").write_text("version: 1\nvalue: old_a\n", encoding="utf-8")
    (base / "tiling" / "b.yaml").write_text("version: 1\nvalue: old_b\n", encoding="utf-8")
    payloads = {
        "registry/a.yaml": "version: 1\nvalue: new_a\n",
        "tiling/b.yaml": "version: 1\nvalue: new_b\n",
    }
    real_replace = kb_compiler.os.replace

    def fail_second(src: object, dst: object) -> None:
        if str(dst).endswith("b.yaml"):
            raise OSError("injected replace failure")
        real_replace(src, dst)

    monkeypatch.setattr(kb_compiler.os, "replace", fail_second)
    tx = kb_compiler._transactional_write_texts(base, payloads)
    assert tx.transaction_status == "rolled_back"
    assert (base / "registry" / "a.yaml").read_text(encoding="utf-8") == "version: 1\nvalue: old_a\n"
    assert (base / "tiling" / "b.yaml").read_text(encoding="utf-8") == "version: 1\nvalue: old_b\n"


def test_canonical_success_receipt_failure_marks_metadata_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_root, base = _repo(tmp_path)
    proposal = _minimal_proposal()
    path = base / "archive" / "proposals" / "meta.yaml"
    path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")

    real_exec = kb_compiler._execute_promotion_transaction

    def wrap(uo_root, op_name, payloads, *, phase, run_id, proposal_hashes):
        tx = real_exec(uo_root, op_name, payloads, phase=phase, run_id=run_id, proposal_hashes=proposal_hashes)
        # Simulate receipt/metadata failure after canonical commit.
        if tx.transaction_status == "commit_complete":
            tx.transaction_status = "metadata_pending"
            tx.failure_reason = "injected receipt write failure"
            tx.recovery_status = "metadata_pending"
            # Drop receipt so consumption must rely on transaction state.
            receipt = uo_root / "archive" / "promoted" / (run_id or "manual") / "promotion_receipt.yaml"
            if receipt.exists():
                receipt.unlink()
            state_path = uo_root / "archive" / "runs" / "transactions" / tx.transaction_id / "state.yaml"
            if state_path.exists():
                state = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
                state["transaction_status"] = "metadata_pending"
                state["proposal_hashes"] = proposal_hashes
                state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
            commit = uo_root / "archive" / "runs" / "transactions" / tx.transaction_id / "commit.yaml"
            if commit.exists():
                commit.unlink()
        return tx

    monkeypatch.setattr(kb_compiler, "_execute_promotion_transaction", wrap)
    result = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[path], run_id="run_meta")
    assert result.promotion_report["transaction_status"] == "metadata_pending"
    assert any(issue.code == "PROMOTION_METADATA_PENDING" for issue in result.issues)
    variables = yaml.safe_load((base / "registry" / "variables.yaml").read_text(encoding="utf-8"))
    assert any(item.get("id") == "VAR_ATTEN_MASK_PRESENT" for item in variables.get("variables") or [])

    again = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[path], run_id="run_meta2")
    assert any(item.get("code") == "ALREADY_PROMOTED" for item in again.promotion_report.get("skipped_proposals") or [])


def test_stale_unchanged_but_validated(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    digest = hashlib.sha256(b"same").hexdigest()
    stale = {
        "version": 1,
        "stale_artifacts": [
            {
                "path": "tiling/data_model.yaml",
                "stale": True,
                "owner_phase": "phase2",
                "expected_refresh_run_id": "run_validate",
                "dependency_hash": "dep1",
                "old_artifact_hash": digest,
            }
        ],
        "resolution_history": [],
    }
    (base / "archive" / "runs" / "stale_artifacts.yaml").write_text(yaml.safe_dump(stale), encoding="utf-8")
    resolved = kb_compiler._resolve_stale_after_success(
        base,
        phase="phase2",
        run_id="run_validate",
        changed_artifacts=[],
        artifact_hashes={"tiling/data_model.yaml": digest},
        validation_status="pass",
        dependency_hash="dep1",
    )
    assert "tiling/data_model.yaml" in resolved
    data = yaml.safe_load((base / "archive" / "runs" / "stale_artifacts.yaml").read_text(encoding="utf-8"))
    entry = data["stale_artifacts"][0]
    assert entry["stale"] is False
    assert entry["resolution_reason"] == "unchanged_but_validated"


def test_stale_requires_expected_run_id(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    digest = "abc"
    stale = {
        "version": 1,
        "stale_artifacts": [
            {
                "path": "tiling/data_model.yaml",
                "stale": True,
                "owner_phase": "phase2",
                "expected_refresh_run_id": "run_expected",
                "old_artifact_hash": digest,
            }
        ],
        "resolution_history": [],
    }
    (base / "archive" / "runs" / "stale_artifacts.yaml").write_text(yaml.safe_dump(stale), encoding="utf-8")
    resolved = kb_compiler._resolve_stale_after_success(
        base,
        phase="phase2",
        run_id=None,
        changed_artifacts=["tiling/data_model.yaml"],
        artifact_hashes={"tiling/data_model.yaml": "new"},
        validation_status="pass",
    )
    assert resolved == []


def test_entity_index_covers_test_entities() -> None:
    docs = {
        "tiling/data_model.yaml": {
            "structs": {"S": {"fields": {"tileN": {"id": "TDF_S_TILEN", "impact_class": "numeric_only"}}}}
        },
        "tiling/coverage_model.yaml": {"family_obligations": [{"id": "COV_FAM_1", "name": "fam1"}]},
        "kernel/compile_model.yaml": {
            "compile_variables": [{"id": "KVAR_COMPILE_X", "kind": "compile_variable"}],
            "compile_decisions": [{"id": "KDEC_COMPILE_Y"}],
        },
        "kernel/variables.yaml": {
            "runtime_variables": [{"id": "KVAR_RUNTIME_Z", "kind": "kernel_runtime_variable"}],
            "tilingdata_reads": [{"id": "TDF_READ_TILEN", "field": "tileN"}],
            "path_decision_points": [{"id": "KDEC_PATH_1"}],
        },
        "kernel/pipeline.yaml": {"stages": [{"id": "PIPE_LOAD"}]},
        "flow/numerical_model.yaml": {"dtype_policy": [{"id": "NUM_DTYPE_FP16", "name": "fp16"}]},
    }
    result = kb_compiler.CompileResult(op_name="DemoOp")
    index = kb_compiler.build_entity_index(docs, result)
    for eid in (
        "TDF_S_TILEN",
        "COV_FAM_1",
        "KVAR_COMPILE_X",
        "KDEC_COMPILE_Y",
        "KVAR_RUNTIME_Z",
        "TDF_READ_TILEN",
        "KDEC_PATH_1",
        "PIPE_LOAD",
        "NUM_DTYPE_FP16",
    ):
        assert eid in index, eid


def test_behavior_graph_unresolved_dedup_is_deterministic() -> None:
    docs = {
        "registry/variables.yaml": {
            "variables": [{"id": "VAR_A", "canonical_name": "a"}, {"id": "VAR_B", "canonical_name": "b"}]
        },
        "cross_layer/input_to_tiling.yaml": {
            "relations": [{"id": "REL_A_B", "type": "affects", "expression": {"vars": ["VAR_A", "VAR_B"]}}]
        },
        "cross_layer/behavior_graph.yaml": {
            "unresolved": [
                {
                    "id": "REL_A_B",
                    "artifact": "cross_layer/input_to_tiling.yaml",
                    "section": "relations",
                    "reason": "relation_direction_missing",
                    "source_ids": [],
                    "target_ids": [],
                }
            ],
            "conflicts": [{"id": "C1"}, {"id": "C1"}],
        },
        "cross_layer/impact_graph.yaml": {"nodes": [], "edges": []},
    }
    result = kb_compiler.CompileResult(op_name="DemoOp")
    first = copy.deepcopy(docs)
    second = copy.deepcopy(docs)
    kb_compiler._build_graphs(first, "DemoOp", result)
    kb_compiler._build_graphs(second, "DemoOp", result)
    assert first["cross_layer/behavior_graph.yaml"]["unresolved"] == second["cross_layer/behavior_graph.yaml"]["unresolved"]
    assert len(first["cross_layer/behavior_graph.yaml"]["unresolved"]) == 1
    assert kb_compiler._canonical_json(first["cross_layer/behavior_graph.yaml"]) == kb_compiler._canonical_json(
        second["cross_layer/behavior_graph.yaml"]
    )


def test_impact_cycle_does_not_emit_self_transitive() -> None:
    cycle_edges = {
        "ab": {"id": "REL_AB", "source_id": "VAR_A", "target_id": "VAR_B", "status": "proposed"},
        "ba": {"id": "REL_BA", "source_id": "VAR_B", "target_id": "VAR_A", "status": "proposed"},
    }
    impacts = kb_compiler._derive_impact_edges(cycle_edges)
    assert any(edge["impact_kind"] == "cycle" for edge in impacts)
    assert not any(
        edge["impact_kind"] in {"direct", "transitive"} and edge["source_id"] == edge["target_id"] for edge in impacts
    )


def test_impact_diamond_alternative_paths_and_best_depth() -> None:
    diamond_edges = {
        "ab": {"id": "REL_AB", "source_id": "VAR_A", "target_id": "VAR_B", "status": "proposed"},
        "ac": {"id": "REL_AC", "source_id": "VAR_A", "target_id": "VAR_C", "status": "proposed"},
        "bd": {"id": "REL_BD", "source_id": "VAR_B", "target_id": "VAR_D", "status": "proposed"},
        "cd": {"id": "REL_CD", "source_id": "VAR_C", "target_id": "VAR_D", "status": "proposed"},
    }
    impacts = kb_compiler._derive_impact_edges(diamond_edges)
    a_to_d = [edge for edge in impacts if edge["source_id"] == "VAR_A" and edge["target_id"] == "VAR_D"]
    assert a_to_d
    best = min(a_to_d, key=lambda e: e["depth"])
    assert best["depth"] == 2
    assert best.get("alternative_paths") or any(edge.get("alternative_paths") for edge in a_to_d)


def test_consumability_rejects_empty_golden_unless_not_applicable(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    docs = {
        rel: yaml.safe_load((base / rel).read_text(encoding="utf-8"))
        for rel in kb_compiler.TEST_CONSUMABLE_FILES
        if (base / rel).exists()
    }
    docs["flow/golden_model.yaml"] = {
        "version": 1,
        "op_name": "DemoOp",
        "golden_inputs": [],
        "golden_outputs": [],
        "golden_generation_contract": [],
    }
    result = kb_compiler.CompileResult(op_name="DemoOp", phase="final")
    result.maturity = {rel: "valid" for rel in docs}
    consumability = kb_compiler._validate_consumability(docs, result)
    assert consumability["flow/golden_model.yaml"]["test_consumable"] is False
    assert "golden_inputs_empty" in consumability["flow/golden_model.yaml"]["blockers"]

    docs["flow/golden_model.yaml"] = {
        "status": "not_applicable",
        "reason": "no golden for this op",
        "evidence_refs": ["EV_1"],
        "golden_inputs": [],
        "golden_outputs": [],
        "golden_generation_contract": [],
    }
    result2 = kb_compiler.CompileResult(op_name="DemoOp", phase="final")
    result2.maturity = {rel: "valid" for rel in docs}
    result2.maturity["flow/golden_model.yaml"] = "not_applicable"
    ok = kb_compiler._validate_consumability(docs, result2)
    assert ok["flow/golden_model.yaml"]["test_consumable"] is True
    assert ok["flow/golden_model.yaml"]["blockers"] == []


def test_testcase_contract_v2_layout_and_query_export(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    contract = yaml.safe_load((base / "contracts" / "testcase.yaml").read_text(encoding="utf-8"))
    assert contract["version"] == 2
    assert "source" in contract
    assert "interface" in contract
    assert "coverage_obligations" in contract
    assert "golden_contract" in contract

    (base / "tiling" / "data_model.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "structs": {"S": {"fields": {"tileN": {"id": "TDF_S_TILEN", "canonical_name": "tileN"}}}},
            }
        ),
        encoding="utf-8",
    )
    payload = export_context_slice(base, "DemoOp", "testcase-contract", detail_level="full")
    assert "testcase_contract" in payload
    assert payload["testcase_contract"]["version"] == 2
    assert any(item.get("stable_id") == "TDF_S_TILEN" for item in payload["entities"])


def test_tilingdata_numeric_only_field_level_proof(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    (base / "tiling" / "data_model.yaml").write_text(
        yaml.safe_dump(
            {
                "structs": {
                    "S": {
                        "fields": {
                            "tileN": {
                                "id": "TDF_S_TILEN",
                                "impact_class": "numeric_only",
                                "downstream_control_refs": [],
                                "downstream_kernel_refs": [],
                                "source": {"file": "op_host/foo_tilingdata.cpp", "symbol": "SetTilingData"},
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (base / "cross_layer" / "impact_graph.yaml").write_text(
        yaml.safe_dump({"edges": [], "impacts": []}),
        encoding="utf-8",
    )
    (base / "cross_layer" / "variable_lineage.yaml").write_text(
        yaml.safe_dump({"edges": [], "lineage": []}),
        encoding="utf-8",
    )
    (base / "cross_layer" / "behavior_graph.yaml").write_text(
        yaml.safe_dump({"edges": []}),
        encoding="utf-8",
    )
    change_set = {
        "changed_files": ["op_host/foo_tilingdata.cpp"],
        "changed_symbols": ["SetTilingData"],
    }
    assert _tilingdata_numeric_only_proven(base, change_set) is True
    plan = _build_update_plan(change_set, base=base)
    assert "tilingdata_numeric_local" in plan["impacted_areas"]
    assert "kernel_impacted_by_tiling" not in plan["impacted_areas"]


def test_tilingdata_without_proof_is_conservative(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    plan = _build_update_plan(
        {
            "status": "ok",
            "changed_files": ["op_host/foo_tilingdata.cpp"],
            "changed_symbols": ["SetTilingData"],
        },
        base=base,
    )
    assert "kernel_impacted_by_tiling" in plan["impacted_areas"]
    stale = _build_stale_artifacts(plan)
    entry = stale["stale_artifacts"][0]
    assert "validation_status" in entry
    assert "dependency_hash" in entry
    assert "resolution_reason" in entry
