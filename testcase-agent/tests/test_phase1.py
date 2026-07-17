from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from testcase_agent import init as init_mod
from testcase_agent.cli import plan_main
from testcase_agent.constraint_ir import build_constraint_ir
from testcase_agent.hashing import semantic_snapshot_hash
from testcase_agent.init import TgInitError, tg_init
from testcase_agent.io import read_json, read_yaml, write_json, write_yaml
from testcase_agent.planner import build_plan, tg_plan
from testcase_agent.solve import tg_solve
from testcase_agent.understand import UnderstandExportError, add_understand_to_path, export_testcase_contract
from testcase_agent.validation import validate_intake


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    uo = repo / ".understand-operator" / "DemoOp"
    uo.mkdir(parents=True)
    (uo / "marker.yaml").write_text("version: 1\n", encoding="utf-8")
    return repo, uo


def _validation(status: str = "pass") -> dict[str, Any]:
    return {
        "status": status,
        "phase": "final",
        "issues": [],
        "source_artifact_hashes": {
            "contracts/testcase.yaml": "a" * 64,
            "tiling/coverage_model.yaml": "b" * 64,
        },
        "entity_count": 1,
        "relation_count": 0,
        "unresolved_count": 0,
        "conflict_count": 0,
    }


def _contract(**updates: Any) -> dict[str, Any]:
    base = {
        "version": 2,
        "op_name": "DemoOp",
        "source": {
            "understand_phase": "phase7",
            "quality_status": "pass",
            "canonical_hashes": {"contracts/testcase.yaml": "a" * 64},
        },
        "interface": {
            "required_inputs": [],
            "optional_inputs": [],
            "outputs": [],
            "attrs": [],
            "dtype_layout_domains": [],
        },
        "typed_constraints": [],
        "coverage_obligations": {
            "tiling_keys": [],
            "tilingdata": [],
            "kernel_paths": [],
            "numerical": [],
            "negative": [],
        },
        "golden_contract": {"inputs": [], "outputs": [], "generation_policy": [], "tolerance_policy": []},
        "unresolved": [],
        "conflicts": [],
        "evidence_refs": [],
    }
    base.update(updates)
    return base


def _payload(contract: dict[str, Any] | None = None, quality: dict[str, Any] | None = None, coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "op_name": "DemoOp",
        "uo_root": "/tmp/uo",
        "view": "testcase-contract",
        "files": {
            "contracts/testcase.yaml": contract or _contract(),
            "test/contract.yaml": {"input_domain": {}, "typed_constraints": [], "kernel_branch_obligations": []},
            "tiling/variables.yaml": {"variables": []},
            "tiling/key_space.yaml": {"fields": [], "derived_fields": [], "constants": []},
            "tiling/exhaustive_key_space.yaml": {"enumeration_source": "not_applicable", "summary": {}, "template_blocks": []},
            "tiling/constraints.yaml": {"relations": [], "variable_constraints": [], "input_realization": {}},
            "tiling/families.yaml": {"families": []},
            "tiling/data_model.yaml": {"structs": {}, "family_to_struct": {}, "numeric_overlay": []},
            "tiling/coverage_model.yaml": coverage or {"family_obligations": [], "key_field_obligations": {}, "key_relation_obligations": []},
            "kernel/compile_model.yaml": {"template_bindings": [], "compile_time_configs": [], "compile_variables": [], "compile_decisions": []},
            "kernel/variables.yaml": {"runtime_variables": [], "tilingdata_reads": [], "path_decision_points": []},
            "kernel/paths.yaml": {"kernel_paths": []},
            "kernel/branches.yaml": {"branches": []},
            "kernel/pipeline.yaml": {"pipelines": [], "stages": [], "resources": []},
            "kernel/resources.yaml": {"buffers": [], "sync_events": [], "workspaces": [], "resources": []},
            "cross_layer/impact_graph.yaml": {"nodes": [], "edges": [], "impacts": []},
            "cross_layer/tiling_to_kernel.yaml": {"nodes": [], "edges": [], "relations": [], "links": []},
            "flow/golden_model.yaml": {"golden_inputs": [], "golden_outputs": [], "golden_generation_contract": []},
            "flow/numerical_model.yaml": {"dtype_policy": [], "tolerance_policy": [], "randomness_policy": "deterministic"},
            "quality.yaml": quality or {"status": "pass", "decision": "pass"},
        },
    }


def _real_uo_fixture(uo: Path, contract: dict[str, Any] | None = None) -> None:
    contract = contract or _contract(
        coverage_obligations={
            "families": [{"id": "COV_FAM_MAIN", "target_refs": ["FAM_MAIN"], "priority": "hard"}],
            "kernel_paths": [{"id": "COV_PATH_MAIN", "target_refs": ["KPATH_MAIN"], "priority": "hard"}],
            "tiling_keys": [],
            "tilingdata": [],
            "numerical": [],
        },
        variables=[
            {"id": "VAR_FAMILY", "type": "enum", "domain": ["FAM_MAIN"]},
            {"id": "VAR_KERNEL_PATH", "type": "enum", "domain": ["KPATH_MAIN"]},
        ],
    )
    files = {
        "contracts/testcase.yaml": contract,
        "test/contract.yaml": {"input_domain": {}, "typed_constraints": [], "kernel_branch_obligations": []},
        "tiling/coverage_model.yaml": {
            "family_obligations": [{"id": "COV_FAM_MAIN", "family_id": "FAM_MAIN", "priority": "hard"}],
            "key_field_obligations": {"split_axis": {"id": "KEY_SPLIT_AXIS", "values": [0, 1, 2], "independent": True}},
            "key_relation_obligations": [
                {
                    "id": "COV_REL_COMPAT",
                    "relation_type": "compatible_set",
                    "combinations": [
                        {"KEY_SPLIT_AXIS": 0, "KBR_HAS_TAIL": True},
                        {"KEY_SPLIT_AXIS": 1, "KBR_HAS_TAIL": True},
                        {"KEY_SPLIT_AXIS": 2, "KBR_HAS_TAIL": False},
                    ],
                }
            ],
        },
        "kernel/branches.yaml": {"branches": [{"id": "KBR_HAS_TAIL", "priority": "high"}]},
        "cross_layer/impact_graph.yaml": {"nodes": [], "edges": [], "impacts": []},
        "quality.yaml": {"status": "pass", "decision": "pass"},
        "tiling/variables.yaml": {"variables": [{"id": "VAR_KEY_SPLIT_AXIS", "data_type": "int"}]},
        "tiling/key_space.yaml": {"fields": [{"id": "KEY_SPLIT_AXIS", "kind": "key", "data_type": "int", "values": [0, 1, 2]}]},
        "tiling/exhaustive_key_space.yaml": {"enumeration_source": "not_applicable", "summary": {}, "template_blocks": []},
        "tiling/constraints.yaml": {"relations": [], "variable_constraints": [], "input_realization": {}},
        "tiling/families.yaml": {"families": [{"id": "FAM_MAIN"}]},
        "tiling/data_model.yaml": {"structs": {}, "family_to_struct": {}, "numeric_overlay": []},
        "kernel/compile_model.yaml": {"template_bindings": [], "compile_time_configs": [], "compile_variables": [], "compile_decisions": []},
        "kernel/variables.yaml": {"runtime_variables": [], "tilingdata_reads": [], "path_decision_points": []},
        "kernel/paths.yaml": {"kernel_paths": [{"id": "KPATH_MAIN"}]},
        "kernel/pipeline.yaml": {"pipelines": [], "stages": [], "resources": []},
        "kernel/resources.yaml": {"buffers": [], "sync_events": [], "workspaces": [], "resources": []},
        "flow/golden_model.yaml": {"golden_inputs": [], "golden_outputs": [], "golden_generation_contract": []},
        "flow/numerical_model.yaml": {"dtype_policy": [], "tolerance_policy": [], "randomness_policy": "deterministic"},
        "cross_layer/tiling_to_kernel.yaml": {"nodes": [], "edges": [], "relations": [], "links": []},
        "registry/evidence.yaml": {"evidence": []},
    }
    for rel, data in files.items():
        write_yaml(uo / rel, data)


def _mature_final_uo_fixture(repo: Path, op_name: str = "DemoOp") -> Path:
    add_understand_to_path(repo)
    from understand_operator._operator.artifacts import init_operator_layout, operator_root

    uo = operator_root(repo, op_name)
    init_operator_layout(uo, op_name, repo)
    docs = {
        "manifest.yaml": {"artifact_version": 1, "layers": ["registry", "tiling", "flow", "kernel", "cross_layer", "contracts"]},
        "index.yaml": {"canonical_files": ["contracts/testcase.yaml"], "qa_routes": ["testcase-contract"]},
        "operator.yaml": {"scope": "op", "entrypoints": [op_name], "io": {"inputs": ["x"], "outputs": ["y"]}},
        "registry/symbols.yaml": {"symbols": [{"id": "SYM_DEMO", "kind": "symbol", "name": op_name}]},
        "registry/variables.yaml": {"variables": [{"id": "VAR_KEY_SPLIT_AXIS", "kind": "variable", "canonical_name": "split_axis", "data_type": "int"}]},
        "registry/aliases.yaml": {"aliases": [], "conflicts": []},
        "registry/evidence.yaml": {"evidence": [{"id": "EV_OPERATOR", "symbol": "DemoOp", "status": "confirmed", "file": "operator.yaml", "lines": [1, 3], "kind": "manual", "source_hash": "x"}]},
        "tiling/variables.yaml": {"variables": [{"id": "VAR_KEY_SPLIT_AXIS", "data_type": "int"}], "tiling_mechanism": "key"},
        "tiling/constraints.yaml": {"relations": [], "variable_constraints": [{"id": "CON_AXIS_DOMAIN", "var": "VAR_KEY_SPLIT_AXIS", "domain": {"values": [0, 2, 4]}}], "input_realization": []},
        "tiling/key_space.yaml": {"fields": [{"id": "KEY_SPLIT_AXIS", "kind": "key", "data_type": "int", "values": [0, 2, 4]}], "derived_fields": [], "constants": []},
        "tiling/families.yaml": {"families": [{"id": "FAM_MAIN", "name": "main"}, {"id": "FAM_ALT", "name": "alt"}], "dispatch_tree": {"root": "FAM_MAIN", "children": ["FAM_ALT"]}},
        "tiling/data_model.yaml": {"structs": {"S": {"fields": {"splitAxis": {"id": "TDF_SPLIT_AXIS", "canonical_name": "splitAxis"}}}}, "family_to_struct": {"FAM_MAIN": "S", "FAM_ALT": "S"}, "numeric_overlay": []},
        "tiling/coverage_model.yaml": {"coverage_policy": "minimal", "family_obligations": [{"id": "COV_FAM_MAIN", "family_id": "FAM_MAIN"}, {"id": "COV_FAM_ALT", "family_id": "FAM_ALT"}], "key_field_obligations": {}, "key_relation_obligations": []},
        "tiling/evidence_index.yaml": {"symbols": [], "evidence_policy": "manual"},
        "flow/compute_graph.yaml": {"compute_steps": [{"id": "CL_STEP_MAIN", "kind": "compute"}], "outputs": ["y"]},
        "flow/dataflow.yaml": {"dataflow_edges": [{"id": "REL_DATAFLOW", "source": "x", "target": "y"}], "tensor_lifecycle": []},
        "flow/golden_model.yaml": {"golden_inputs": ["x"], "golden_outputs": ["y"], "golden_generation_contract": [{"id": "CON_GOLDEN", "method": "reference"}]},
        "flow/numerical_model.yaml": {"dtype_policy": ["fp16"], "tolerance_policy": [{"dtype": "fp16", "rtol": 0.001}], "randomness_policy": "deterministic"},
        "evidence/fact_index.yaml": {"facts": [], "evidence_refs": []},
        "evidence/source_index.yaml": {"source_spans": [], "symbols": []},
        "evidence/artifact_dependencies.yaml": {"dependencies": [{"id": "REL_DEP_CONTRACT", "source": "contracts/testcase.yaml", "target": "tiling/coverage_model.yaml"}], "artifact_to_source": {"contracts/testcase.yaml": ["operator.yaml"]}},
        "evidence/issues.yaml": {"missing": [], "conflicts": [], "warnings": [], "unknowns": []},
        "kernel/compile_model.yaml": {"template_bindings": [{"id": "KTPL_MAIN", "template": "main"}], "compile_time_configs": [], "compile_variables": [], "compile_decisions": []},
        "kernel/variables.yaml": {"runtime_variables": [{"id": "KVAR_AXIS", "data_type": "int", "values": [0, 2, 4]}], "tilingdata_reads": [{"id": "TDF_READ_SPLIT_AXIS", "field_id": "TDF_SPLIT_AXIS"}], "path_decision_points": []},
        "kernel/branches.yaml": {"branches": [{"id": "KBR_HAS_TAIL", "condition": "tail"}], "path_semantics": [], "dataflow_links": [], "resource_links": []},
        "kernel/paths.yaml": {"kernel_paths": [{"id": "KPATH_MAIN", "template_binding_ids": ["KTPL_MAIN"], "runtime_variable_ids": ["KVAR_AXIS"], "branch_ids": ["KBR_HAS_TAIL"], "implements_compute_steps": ["CL_STEP_MAIN"]}, {"id": "KPATH_ALT", "template_binding_ids": ["KTPL_MAIN"], "runtime_variable_ids": ["KVAR_AXIS"], "branch_ids": ["KBR_HAS_TAIL"], "implements_compute_steps": ["CL_STEP_MAIN"]}]},
        "kernel/pipeline.yaml": {"pipelines": [{"id": "PIPE_MAIN"}], "stages": [{"id": "PIPE_STAGE_MAIN"}], "resources": []},
        "kernel/resources.yaml": {"buffers": [{"id": "BUF_UB"}], "sync_events": [{"id": "SYNC_DONE"}], "workspaces": [], "resources": [{"id": "RES_CORE"}]},
        "cross_layer/input_to_tiling.yaml": {"nodes": [{"id": "VAR_KEY_SPLIT_AXIS"}], "edges": [], "relations": [], "links": []},
        "cross_layer/tiling_to_kernel.yaml": {"nodes": [{"id": "VAR_KEY_SPLIT_AXIS"}], "edges": [], "relations": [], "links": []},
        "cross_layer/variable_lineage.yaml": {"variables": [{"id": "VAR_KEY_SPLIT_AXIS"}], "lineage": [], "relations": [], "edges": []},
        "cross_layer/behavior_graph.yaml": {"nodes": [{"id": "VAR_KEY_SPLIT_AXIS"}], "edges": []},
        "cross_layer/impact_graph.yaml": {"nodes": [{"id": "VAR_KEY_SPLIT_AXIS"}], "edges": [], "impacts": [{"id": "REL_IMPACT_AXIS", "source_id": "VAR_KEY_SPLIT_AXIS", "target_id": "KVAR_AXIS"}]},
        "query/routes.yaml": {"routes": [{"id": "VIEW_TESTCASE", "view": "testcase-contract"}]},
        "query/terminology.yaml": {"terms": [{"term": "split axis", "id": "KEY_SPLIT_AXIS"}], "aliases": []},
        "contracts/query.yaml": {"required_response_fields": ["files"], "routes": ["testcase-contract"]},
        "contracts/code_change.yaml": {"target": op_name, "upstream": ["contracts/testcase.yaml"], "downstream": ["testcase-agent"], "recommended_checks": ["pytest"]},
        "contracts/pr_review.yaml": {"review_slices": ["testcase"], "recommended_checks": ["pytest"]},
        "contracts/testcase.yaml": _contract(
            variables=[{"id": "VAR_KEY_SPLIT_AXIS", "type": "int", "values": [0, 2, 4]}],
            interface={"required_inputs": [], "optional_inputs": [], "outputs": [], "attrs": [], "dtype_layout_domains": [{"id": "FP16_ND"}]},
            coverage_obligations={
                "families": [{"id": "COV_FAM_MAIN", "target_refs": ["FAM_MAIN"]}, {"id": "COV_FAM_ALT", "target_refs": ["FAM_ALT"]}],
                "tiling_keys": [
                    {"id": "COV_AXIS_VALID", "field": "split_axis", "values": [2]},
                    {"id": "COV_AXIS_INVALID", "field": "split_axis", "values": [1]},
                ],
                "kernel_paths": [{"id": "COV_PATH_MAIN", "target_refs": ["KPATH_MAIN"]}, {"id": "COV_PATH_ALT", "target_refs": ["KPATH_ALT"]}],
                "tilingdata": [],
                "numerical": [],
                "negative": [],
            },
            golden_contract={"inputs": ["x"], "outputs": ["y"], "generation_policy": ["reference"], "tolerance_policy": ["fp16"]},
        ),
        "test/contract.yaml": {"input_domain": {"x": "any"}, "typed_constraints": [], "kernel_branch_obligations": [{"id": "KBR_HAS_TAIL"}]},
        "quality.yaml": {"status": "pass", "checks": ["final"], "decision": "pass"},
    }
    for rel, data in docs.items():
        write_yaml(uo / rel, data)
    return uo


def _patch_intake(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], validation: dict[str, Any] | None = None) -> None:
    monkeypatch.setattr(init_mod, "run_final_validation", lambda project_root, op_name, uo_root: validation or _validation())
    monkeypatch.setattr(init_mod, "export_testcase_contract", lambda project_root, op_name, uo_root: payload)


def _snapshot(repo: Path, files: dict[str, Any]) -> None:
    root = repo / ".testcase-generator" / "DemoOp" / "snapshot"
    root.mkdir(parents=True)
    snapshot = {
        "version": 1,
        "op_name": "DemoOp",
        "view": "testcase-contract",
        "files": files,
        "source_artifact_hashes": {"contracts/testcase.yaml": "a" * 64},
    }
    snapshot["snapshot_hash"] = semantic_snapshot_hash(snapshot)
    write_json(root / "understand_contract.json", snapshot)


def _tree_hash(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_contract_version_error_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    payload = _payload(_contract(version=1))
    _patch_intake(monkeypatch, payload)

    with pytest.raises(TgInitError):
        tg_init(repo, "DemoOp")

    report = read_yaml(repo / ".testcase-generator" / "DemoOp" / "intake" / "validation_report.yaml")
    assert report["status"] == "fail"
    assert any(item["code"] == "TESTCASE_CONTRACT_VERSION" for item in report["blocking_issues"])


def test_quality_fail_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    _patch_intake(monkeypatch, _payload(quality={"status": "fail"}))

    with pytest.raises(TgInitError):
        tg_init(repo, "DemoOp")

    report = read_yaml(repo / ".testcase-generator" / "DemoOp" / "intake" / "validation_report.yaml")
    assert any(item["code"] == "QUALITY_FAIL" for item in report["blocking_issues"])


def test_hard_stable_id_reference_missing_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    contract = _contract(
        coverage_obligations={
            "kernel_paths": [
                {
                    "id": "COV_KERNEL_PATH_HARD",
                    "priority": "hard",
                    "target_refs": ["KPATH_MISSING"],
                }
            ]
        }
    )
    _patch_intake(monkeypatch, _payload(contract))

    with pytest.raises(TgInitError):
        tg_init(repo, "DemoOp")

    report = read_yaml(repo / ".testcase-generator" / "DemoOp" / "intake" / "validation_report.yaml")
    assert any(item["code"] == "DANGLING_HARD_REF" for item in report["blocking_issues"])


def test_warning_does_not_block_and_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    payload = _payload(quality={"status": "pass", "warnings": [{"severity": "warning", "message": "minor gap"}]})
    _patch_intake(monkeypatch, payload)

    result = tg_init(repo, "DemoOp")

    assert result["run"]["status"] == "warn"
    report = read_yaml(repo / ".testcase-generator" / "DemoOp" / "intake" / "validation_report.yaml")
    assert report["status"] == "warn"
    assert report["warnings"]


def test_snapshot_hash_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    _patch_intake(monkeypatch, _payload())

    first = tg_init(repo, "DemoOp")["snapshot"]["snapshot_hash"]
    second = tg_init(repo, "DemoOp")["snapshot"]["snapshot_hash"]

    assert first == second
    meta = read_yaml(repo / ".testcase-generator" / "DemoOp" / "snapshot" / "snapshot_meta.yaml")
    assert meta["snapshot_hash"] == first


def test_tg_init_output_tree_is_exact_phase1_intake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    _patch_intake(monkeypatch, _payload())

    tg_init(repo, "DemoOp")

    root = repo / ".testcase-generator" / "DemoOp"
    files = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    assert files == [
        "intake/validation_report.yaml",
        "run.yaml",
        "snapshot/snapshot_meta.yaml",
        "snapshot/understand_contract.json",
    ]
    assert not (root / "intake.yaml").exists()
    assert not (root / "testcase_contract.yaml").exists()
    assert not (root / "coverage_plan.yaml").exists()
    assert not (root / "coverage_obligations.yaml").exists()


def test_flow_metadata_does_not_create_testagent_obligations() -> None:
    base_files = _payload(
        coverage={
            "family_obligations": [{"family_id": "FAM_A"}],
            "key_field_obligations": {},
            "key_relation_obligations": [],
        }
    )["files"]
    with_flow = {
        **base_files,
        "flow/compute_graph.yaml": {
            "compute_steps": [
                {
                    "id": "CL_DEMO_VECTOR_SCALE",
                    "execution_unit": "VECTOR",
                    "depends_on": [],
                    "downstream_steps": [],
                }
            ]
        },
    }

    base_plan = build_plan({"op_name": "DemoOp", "files": base_files, "snapshot_hash": "s"})
    flow_plan = build_plan({"op_name": "DemoOp", "files": with_flow, "snapshot_hash": "s"})

    assert flow_plan["obligations"] == base_plan["obligations"]
    assert flow_plan["matrix"] == base_plan["matrix"]


def test_real_flow_hash_change_updates_snapshot_hash_for_approval_invalidation() -> None:
    files = _payload()["files"]
    first = {
        "version": 1,
        "op_name": "DemoOp",
        "view": "testcase-contract",
        "files": files,
        "source_artifact_hashes": {"contracts/testcase.yaml": "a" * 64, "flow/compute_graph.yaml": "1" * 64},
    }
    second = {
        **first,
        "source_artifact_hashes": {"contracts/testcase.yaml": "a" * 64, "flow/compute_graph.yaml": "2" * 64},
    }

    assert semantic_snapshot_hash(first) != semantic_snapshot_hash(second)


def test_same_input_repeated_plan_is_deterministic(tmp_path: Path) -> None:
    repo, _uo = _repo(tmp_path)
    files = _payload(
        coverage={
            "family_obligations": [{"family_id": "FAM_A", "reachability": "reachable"}],
            "key_field_obligations": {"mode": {"values": [0, 1], "independent": True}},
            "key_relation_obligations": [{"id": "COV_REL_MODE", "relation_type": "pairwise", "fields": ["mode"]}],
        }
    )["files"]
    _snapshot(repo, files)

    first = tg_plan(repo, "DemoOp", reuse_snapshot=True)
    second = tg_plan(repo, "DemoOp", reuse_snapshot=True)

    assert first["plan_hash"] == second["plan_hash"]
    assert first["obligations"] == second["obligations"]


def test_derived_field_is_not_free_obligation(tmp_path: Path) -> None:
    files = _payload(
        coverage={
            "family_obligations": [],
            "key_field_obligations": {
                "derived_mask": {"values": [0, 1], "independent": False, "kind": "derived"},
                "layout": {"values": ["ND"], "independent": True},
            },
            "key_relation_obligations": [],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L0")

    fields = [item for item in plan["obligations"] if item["kind"] == "tiling_key_field_value"]
    assert len(fields) == 1
    assert fields[0]["target_refs"] == ["layout"]
    assert fields[0]["target_value"] == "ND"


def test_l0_ignores_family_reachability_baselines(tmp_path: Path) -> None:
    files = _payload(
        coverage={
            "family_obligations": [
                {"family_id": "FAM_REACH", "reachability": "reachable"},
                {"family_id": "FAM_DEAD", "reachability": "unreachable", "reason": "compile-time folded"},
            ],
            "key_field_obligations": {},
            "key_relation_obligations": [],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    assert not [item for item in plan["obligations"] if item["kind"] == "family"]
    assert plan["unresolved"]["status"] == "ready_for_manual_review"


def test_optional_input_does_not_replicate_all_families(tmp_path: Path) -> None:
    contract = _contract(interface={"optional_inputs": [{"name": "mask"}, {"name": "pse"}], "dtype_layout_domains": []})
    files = _payload(
        contract,
        coverage={
            "family_obligations": [{"family_id": "FAM_A"}, {"family_id": "FAM_B"}],
            "key_field_obligations": {},
            "key_relation_obligations": [],
        },
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L0")

    assert len([item for item in plan["obligations"] if item["kind"] == "family"]) == 0
    assert len([item for item in plan["obligations"] if item["kind"] == "optional_input_mode"]) == 4


def test_key_field_values_expand_to_atomic_obligations() -> None:
    files = _payload(
        coverage={
            "family_obligations": [],
            "key_field_obligations": {"split_axis": {"id": "KEY_SPLIT_AXIS", "values": [0, 1, 2], "independent": True}},
            "key_relation_obligations": [],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L0")

    fields = [item for item in plan["obligations"] if item["kind"] == "tiling_key_field_value"]
    assert [item["target_value"] for item in fields] == [0, 1, 2]
    assert all(item["constraints"]["expr"]["var"] == "VAR_KEY_SPLIT_AXIS" for item in fields)


def test_fixed_key_field_generates_one_obligation() -> None:
    files = _payload(
        coverage={
            "family_obligations": [],
            "key_field_obligations": {"mode": {"id": "KEY_MODE", "values": [1, 2], "compile_time_fixed": True, "value": 2}},
            "key_relation_obligations": [],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L0")

    fields = [item for item in plan["obligations"] if item["kind"] == "tiling_key_field_value"]
    assert len(fields) == 1
    assert fields[0]["target_value"] == 2


def test_kernel_branch_expands_true_false_and_unreachable_side() -> None:
    files = _payload(
        _contract(
            coverage_obligations={
                "kernel_branches": [{"id": "KBR_HAS_TAIL", "unreachable_values": [False]}],
                "tiling_keys": [],
            }
        )
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    branches = [item for item in plan["obligations"] if item["kind"] == "kernel_branch"]
    assert [item["target_value"] for item in branches] == [False, True]
    assert {item["target_value"]: item["status"] for item in branches}[False] == "proof_required"


def test_l0_ignores_dtype_layout_class_baselines() -> None:
    contract = _contract(interface={"optional_inputs": [], "dtype_layout_domains": [{"id": "FP16_TND"}, {"id": "BF16_ND"}]})
    plan = build_plan({"op_name": "DemoOp", "files": _payload(contract)["files"], "snapshot_hash": "s"}, level="L0")

    assert not [item for item in plan["obligations"] if item["kind"] == "dtype_layout_class"]


def test_export_view_and_context_slice_are_merged(tmp_path: Path) -> None:
    pytest.importorskip("understand_operator")
    repo, uo = _repo(tmp_path)
    _real_uo_fixture(uo)

    payload = export_testcase_contract(repo, "DemoOp", uo)

    assert set(payload["files"]) == {
        "contracts/testcase.yaml",
        "test/contract.yaml",
        "tiling/variables.yaml",
        "tiling/key_space.yaml",
        "tiling/exhaustive_key_space.yaml",
        "tiling/constraints.yaml",
        "tiling/families.yaml",
        "tiling/data_model.yaml",
        "tiling/coverage_model.yaml",
        "kernel/compile_model.yaml",
        "kernel/variables.yaml",
        "kernel/paths.yaml",
        "kernel/branches.yaml",
        "kernel/pipeline.yaml",
        "kernel/resources.yaml",
        "cross_layer/impact_graph.yaml",
        "cross_layer/tiling_to_kernel.yaml",
        "flow/golden_model.yaml",
        "flow/numerical_model.yaml",
        "quality.yaml",
    }
    assert payload["context_slice"]["entities"]
    assert payload["context_slice"]["testcase_contract"] == payload["files"]["contracts/testcase.yaml"]


def test_contract_view_context_mismatch_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("understand_operator")
    repo, uo = _repo(tmp_path)

    def view(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"files": {"contracts/testcase.yaml": {"version": 2, "value": "view"}}}

    def context(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"testcase_contract": {"version": 2, "value": "context"}}

    add_understand_to_path(repo)
    import understand_operator.scripts.kb_query_export as export_mod

    monkeypatch.setattr(export_mod, "export_view", view)
    monkeypatch.setattr(export_mod, "export_context_slice", context)

    with pytest.raises(UnderstandExportError, match="CONTRACT_CONTEXT_MISMATCH"):
        export_testcase_contract(repo, "DemoOp", uo)


def test_context_entity_resolves_hard_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    contract = _contract(
        coverage_obligations={
            "kernel_paths": [{"id": "COV_KERNEL_PATH_HARD", "priority": "hard", "target_refs": ["KPATH_CONTEXT"]}],
            "tiling_keys": [],
        }
    )
    payload = _payload(contract)
    payload["context_slice"] = {"entities": [{"id": "KPATH_CONTEXT", "kind": "kernel_path"}], "relations": [], "paths": []}
    _patch_intake(monkeypatch, payload)

    result = tg_init(repo, "DemoOp")

    assert result["validation_report"]["status"] in {"pass", "warn"}


def test_compatible_set_and_must_cover_atomize_combinations() -> None:
    files = _payload(
        coverage={
            "family_obligations": [],
            "key_field_obligations": {},
            "key_relation_obligations": [
                {"id": "COV_COMPAT", "relation_type": "compatible_set", "combinations": [{"KEY_A": 0, "KEY_B": 0}, {"KEY_A": 0, "KEY_B": 0}, {"KEY_A": 1, "KEY_B": 1}]},
                {"id": "COV_MUST", "relation_type": "must_cover", "must_cover": [{"KEY_A": 2}, {"KEY_A": 3}]},
            ],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})
    relation_obligations = [item for item in plan["obligations"] if item["kind"] == "tiling_key_relation"]

    assert len([item for item in relation_obligations if item.get("parent_obligation_id") == "COV_COMPAT"]) == 2
    assert len([item for item in relation_obligations if item.get("parent_obligation_id") == "COV_MUST"]) == 2
    assert all(item.get("target_expr", {}).get("op") == "and" for item in relation_obligations)


def test_unreachable_relation_combination_is_proof_required() -> None:
    files = _payload(
        coverage={
            "family_obligations": [],
            "key_field_obligations": {},
            "key_relation_obligations": [{"id": "COV_COMPAT", "relation_type": "compatible_set", "combinations": [{"KEY_A": 0, "status": "unreachable"}]}],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    relation = next(item for item in plan["obligations"] if item["kind"] == "tiling_key_relation")
    assert relation["status"] == "proof_required"


def test_review_describes_design_by_variables_and_features() -> None:
    files = _payload(
        coverage={
            "family_obligations": [],
            "key_field_obligations": {"split_axis": {"id": "KEY_SPLIT_AXIS", "values": [0]}},
            "key_relation_obligations": [],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L0")

    assert "测试设计覆盖说明" in plan["review"]
    assert "设计 **1** 个 TilingKey 字段取值用例点" in plan["review"]
    assert "`split_axis`=0" in plan["review"]
    assert "算子族 / Family" not in plan["review"]
    assert "Kernel 路径" not in plan["review"]


def test_real_format_fixture_end_to_end_phase1_phase2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, uo = _repo(tmp_path)
    _real_uo_fixture(uo)
    payload = _payload(
        coverage={
            "family_obligations": [{"family_id": "FAM_MAIN", "reachability": "reachable"}],
            "key_field_obligations": {"SPLIT_AXIS": {"id": "KEY_SPLIT_AXIS", "values": [0, 1, 2]}},
            "key_relation_obligations": [
                {
                    "id": "COV_REL_COMPAT",
                    "relation_type": "compatible_set",
                    "combinations": [{"a": 0}, {"a": 1}, {"a": 2}],
                }
            ],
        },
        contract=_contract(
            coverage_obligations={
                "kernel_paths": [{"id": "COV_PATH", "target_refs": ["KPATH_MAIN"]}],
                "kernel_branches": [{"id": "KBR_HAS_TAIL"}],
                "tiling_keys": [],
                "tilingdata": [],
                "numerical": [],
                "negative": [],
            },
            interface={"optional_inputs": [], "dtype_layout_domains": [{"id": "FP16_ND"}]},
        ),
    )
    payload["files"]["kernel/branches.yaml"] = {"branches": [{"id": "KBR_HAS_TAIL", "runtime": True}]}
    payload["files"]["kernel/paths.yaml"] = {"kernel_paths": [{"id": "KPATH_MAIN", "family_refs": ["FAM_MAIN"]}]}
    payload["files"]["tiling/constraints.yaml"] = {
        "relations": [],
        "variable_constraints": [],
        "input_realization": {"CON_IR": {"matches": {"layout": "ND"}, "shape": {"B": 2, "N1": 4, "N2": 2, "S1": 16, "S2": 16, "D": 64}}},
    }
    payload["context_slice"] = {"entities": [{"id": "FAM_MAIN"}, {"id": "KPATH_MAIN"}, {"id": "KEY_SPLIT_AXIS"}], "testcase_contract": payload["files"]["contracts/testcase.yaml"]}
    _patch_intake(monkeypatch, payload)

    init_result = tg_init(repo, "DemoOp")
    plan = tg_plan(repo, "DemoOp", reuse_snapshot=True)
    root = repo / ".testcase-generator" / "DemoOp"
    supplement_path = root / "plan" / "human_supplement.yaml"
    write_yaml(
        supplement_path,
        {
            "version": 1,
            "status": "approved",
            "decision": "approve",
            "approved_snapshot_hash": init_result["snapshot"]["snapshot_hash"],
            "approved_plan_hash": plan["plan_hash"],
            "approved_at": "2026-01-01T00:00:00+00:00",
            "supplements": [],
            "notes": "",
        },
    )
    solve = tg_solve(repo, "DemoOp", allow_legacy_realization=True)

    snapshot = read_json(root / "snapshot" / "understand_contract.json")
    assert "tiling/coverage_model.yaml" in snapshot["files"]
    assert snapshot["context_slice"]["entities"]
    assert plan["unresolved"]["contract_gaps"] == []
    assert not [item for item in plan["obligations"] if item["kind"] == "tiling_key_field_value" and item["target_refs"] == ["KEY_SPLIT_AXIS"]]
    assert len([item for item in plan["obligations"] if item["kind"] == "kernel_branch" and item["target_refs"] == ["KBR_HAS_TAIL"]]) == 2
    branch_candidates = [item for item in solve["deduped_candidates"] if "KBR_HAS_TAIL" in item["coverage_signature"]["branch_truth"]]
    assert len({item["id"] for item in branch_candidates}) >= 2
    assert solve["deduped_candidates"]
    assert not [item for item in plan["obligations"] if item["kind"] == "tiling_key_relation" and item.get("parent_obligation_id") == "COV_REL_COMPAT"]
    assert list(root.rglob("*.csv"))
    assert not (root / "run" / "operator_execution.yaml").exists()


def test_contract_schema_rejects_input_realization_without_id() -> None:
    contract = _contract(
        input_realization=[
            {"IR_TND_VARLEN": {}, "matches": {"isTnd": True}},
        ]
    )
    report = validate_intake(_payload(contract), _validation())
    assert any(item["code"] == "INPUT_REALIZATION_SCHEMA" for item in report.to_dict()["blocking_issues"])


def test_contract_schema_accepts_input_realization_mapping() -> None:
    contract = _contract(
        input_realization={
            "CON_IR_TND_VARLEN": {"matches": {"isTnd": True}, "inputs": {"x": {"layout": "TND"}}}
        }
    )
    report = validate_intake(_payload(contract), _validation())
    assert not any(item["code"] == "INPUT_REALIZATION_SCHEMA" for item in report.to_dict()["blocking_issues"])


def test_comp_and_gold_stable_ids_are_legal_and_hard_refs_resolve() -> None:
    contract = _contract(
        coverage_obligations={
            "kernel_paths": [
                {"id": "COV_COMPUTE_GOLD", "priority": "hard", "target_refs": ["COMP_MAIN", "GOLD_MAIN"]}
            ],
            "tiling_keys": [],
            "tilingdata": [],
            "numerical": [],
            "negative": [],
        }
    )
    payload = _payload(contract)
    payload["files"]["flow/compute_graph.yaml"] = {"compute_steps": [{"id": "COMP_MAIN"}]}
    payload["files"]["flow/golden_model.yaml"] = {"golden_steps": [{"id": "GOLD_MAIN"}]}

    report = validate_intake(payload, _validation())

    codes = [item["code"] for item in report.to_dict()["blocking_issues"]]
    assert "INVALID_STABLE_ID" not in codes
    assert "INVALID_HARD_REF_ID" not in codes
    assert "DANGLING_HARD_REF" not in codes


def test_dangling_comp_and_gold_hard_refs_fail() -> None:
    contract = _contract(
        coverage_obligations={
            "kernel_paths": [
                {"id": "COV_COMPUTE_GOLD", "priority": "hard", "target_refs": ["COMP_MISSING", "GOLD_MISSING"]}
            ],
            "tiling_keys": [],
            "tilingdata": [],
            "numerical": [],
            "negative": [],
        }
    )
    report = validate_intake(_payload(contract), _validation())

    dangling = [item["target"] for item in report.to_dict()["blocking_issues"] if item["code"] == "DANGLING_HARD_REF"]
    assert dangling == ["COMP_MISSING", "GOLD_MISSING"]


def test_intake_requires_full_testcase_contract_view() -> None:
    payload = _payload()
    del payload["files"]["tiling/constraints.yaml"]

    report = validate_intake(payload, _validation())

    assert any(
        item["code"] == "MISSING_CANONICAL_FILE" and item["target"] == "tiling/constraints.yaml"
        for item in report.to_dict()["blocking_issues"]
    )


def test_top_level_kernel_branch_variants_expand_into_plan_obligations() -> None:
    contract = _contract(
        kernel_branch_obligations=[
            {"branch_id": "KPATH_POST_NZ", "variants": ["FP16 Nz", "BF16 Nz"]}
        ]
    )
    plan = build_plan({"op_name": "DemoOp", "files": _payload(contract)["files"], "snapshot_hash": "s"})
    variants = {
        item["target_value"]
        for item in plan["obligations"]
        if item["kind"] == "kernel_branch" and item["target_refs"] == ["KPATH_POST_NZ"]
    }
    assert variants == {"FP16 Nz", "BF16 Nz"}


def test_l0_covers_functional_attributes_not_just_one_smoke() -> None:
    files = _payload(
        contract=_contract(
            interface={"optional_inputs": [{"name": "mask"}], "dtype_layout_domains": [{"id": "FP16_ND"}, {"id": "BF16_TND"}]},
            coverage_obligations={
                "families": [{"id": "COV_FAM_MAIN", "target_refs": ["FAM_MAIN"]}, {"id": "COV_FAM_ALT", "target_refs": ["FAM_ALT"]}],
                "kernel_paths": [{"id": "COV_PATH_MAIN", "target_refs": ["KPATH_MAIN"]}, {"id": "COV_PATH_ALT", "target_refs": ["KPATH_ALT"]}],
                "tiling_keys": [],
                "tilingdata": [],
                "numerical": [],
                "negative": [],
            },
        )
    )["files"]
    files["tiling/coverage_model.yaml"] = {
        "family_obligations": [{"id": "COV_FAM_MAIN", "family_id": "FAM_MAIN"}],
        "key_field_obligations": {
            "IsDrop": {"id": "KEY_ISDROP", "values": [0, 1], "independent": True},
            "IsPse": {"id": "KEY_ISPSE", "values": [0, 1], "independent": True},
            "DerivedBound": {"id": "KEY_DERIVED", "values": [0, 1], "independent": False},
        },
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L0")

    assert {item["test_level"] for item in plan["obligations"]} == {"L0"}
    assert not [item for item in plan["obligations"] if item["kind"] == "kernel_branch"]
    kinds = {item["kind"] for item in plan["obligations"]}
    assert "family" not in kinds
    assert "kernel_path" not in kinds
    assert "dtype_layout_class" not in kinds
    assert "optional_input_mode" in kinds
    assert "tiling_key_field_value" in kinds
    assert len([item for item in plan["obligations"] if item["kind"] == "optional_input_mode"]) == 2
    assert len([item for item in plan["obligations"] if item["kind"] == "tiling_key_field_value"]) == 4
    assert not any(item.get("field") == "DerivedBound" for item in plan["obligations"])
    assert "测试设计覆盖说明" in plan["review"]
    assert "功能属性冒烟" in plan["review"]
    assert plan["matrix"]["test_points"]
    # Missing input_realization must not hard-block L0
    assert not any(g.get("field") == "tiling/constraints.yaml.input_realization" for g in plan["unresolved"]["contract_gaps"])


def test_l0_ignores_family_path_baselines() -> None:
    files = _payload(
        contract=_contract(
            interface={"dtype_layout_domains": [{"id": "FP16_ND", "dtype": "FP16", "layout": "ND"}]},
            coverage_obligations={
                "families": [{"id": "COV_FAM_MAIN", "target_refs": ["FAM_MAIN"]}],
                "kernel_paths": [{"id": "COV_PATH_MAIN", "target_refs": ["KPATH_MAIN"]}],
                "tiling_keys": [],
                "tilingdata": [],
                "numerical": [],
                "negative": [],
            },
        )
    )["files"]
    files["tiling/constraints.yaml"]["input_realization"] = {
        "CON_IR_MAIN": {"matches": {"family_refs": ["FAM_MAIN"], "kernel_path_refs": ["KPATH_MAIN"], "dtype": "FP16", "layout": "ND"}}
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L0")

    assert plan["unresolved"]["status"] != "blocked"
    assert not any(item["id"] == "L0_FEATURE_VALUE_COVERAGE_BLOCKED" for item in plan["obligations"])
    assert not any(item["kind"] in {"family", "kernel_path", "dtype_layout_class"} for item in plan["obligations"])


def test_l0_does_not_depend_on_kernel_paths_yaml_compatibility() -> None:
    files = _payload(
        contract=_contract(
            interface={"dtype_layout_domains": [{"id": "FP16_ND", "dtype": "FP16", "layout": "ND"}]},
            coverage_obligations={
                "families": [{"id": "COV_FAM_MAIN", "target_refs": ["FAM_MAIN"]}],
                "kernel_paths": [{"id": "COV_PATH_MAIN", "target_refs": ["KPATH_MAIN"]}],
                "tiling_keys": [],
                "tilingdata": [],
                "numerical": [],
                "negative": [],
            },
        )
    )["files"]
    files["kernel/paths.yaml"] = {"kernel_paths": [{"id": "KPATH_MAIN", "family_refs": ["FAM_MAIN"]}]}
    files["tiling/constraints.yaml"]["input_realization"] = {
        "CON_IR_MAIN": {"matches": {"family_refs": ["FAM_MAIN"], "kernel_path_refs": ["KPATH_MAIN"], "dtype": "FP16", "layout": "ND"}}
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L0")

    assert plan["unresolved"]["status"] != "blocked"
    assert not any(item["kind"] in {"family", "kernel_path"} for item in plan["obligations"])


def test_l0_does_not_depend_on_tiling_to_kernel_relation() -> None:
    files = _payload(
        contract=_contract(
            interface={"dtype_layout_domains": [{"id": "FP16_ND", "dtype": "FP16", "layout": "ND"}]},
            coverage_obligations={
                "families": [{"id": "COV_FAM_MAIN", "target_refs": ["FAM_MAIN"]}],
                "kernel_paths": [{"id": "COV_PATH_MAIN", "target_refs": ["KPATH_MAIN"]}],
                "tiling_keys": [],
                "tilingdata": [],
                "numerical": [],
                "negative": [],
            },
        )
    )["files"]
    files["cross_layer/tiling_to_kernel.yaml"] = {"edges": [{"source": "FAM_MAIN", "target": "KPATH_MAIN", "relation": "dispatches_to"}]}
    files["tiling/constraints.yaml"]["input_realization"] = {
        "CON_IR_MAIN": {"matches": {"family_refs": ["FAM_MAIN"], "kernel_path_refs": ["KPATH_MAIN"], "dtype": "FP16", "layout": "ND"}}
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L0")

    assert plan["unresolved"]["status"] != "blocked"
    assert not any(item["kind"] in {"family", "kernel_path"} for item in plan["obligations"])


def test_l1_covers_reachable_runtime_branch_sides_and_skips_compile_fixed() -> None:
    files = _payload()["files"]
    files["kernel/branches.yaml"] = {
        "branches": [
            {"id": "KBR_RUNTIME", "priority": "high"},
            {"id": "KBR_COMPILE_FIXED", "compile_time_fixed": True},
            {"id": "KBR_DERIVED", "derived": True},
        ]
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L1")

    branches = [item for item in plan["obligations"] if item["kind"] == "kernel_branch"]
    assert {(item["target_refs"][0], item["target_value"]) for item in branches} == {("KBR_RUNTIME", True), ("KBR_RUNTIME", False)}
    assert all(item["test_level"] == "L1" for item in branches)
    assert all(item["coverage_origin"]["artifact"] == "kernel/branches.yaml" for item in branches)


def test_l1_excludes_boundaries_and_expected_rejects() -> None:
    files = _payload()["files"]
    files["tiling/constraints.yaml"] = {
        "relations": [],
        "variable_constraints": [{"id": "CON_M", "var": "VAR_SHAPE_M", "boundary_values": [1, 1024]}],
        "input_realization": {},
        "key_unreachable": [{"id": "COV_BAD_KEY", "matches": {"KEY_MODE": "bad"}, "reason": "host rejects"}],
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L1")

    assert not any(item["test_level"] == "L1" and item.get("target_value") == 1 for item in plan["obligations"])
    rejects = [item for item in plan["obligations"] if item.get("expected_behavior") == "reject"]
    assert rejects == []


def test_l2_expands_template_blocks_applies_pruning_and_realizes_keys() -> None:
    files = _payload()["files"]
    files["tiling/exhaustive_key_space.yaml"] = {
        "field_order": ["layout", "post_nz", "axis"],
        "template_blocks": [
            {
                "id": "KEY_BLOCK_MAIN",
                "fixed_fields": {"layout": "TND"},
                "field_domains": {"post_nz": [True, False], "axis": [0, 1]},
                "product_count": 4,
            }
        ],
        "reverse_realization_index": {},
    }
    files["tiling/constraints.yaml"] = {
        "relations": [],
        "variable_constraints": [],
        "input_realization": {"CON_IR_TND": {"matches": {"layout": "TND"}}},
        "tiling_key_pruning": {
            "performed": True,
            "pruned_combinations": [{"id": "PRUNE_POST_FALSE_AXIS_1", "pattern": {"post_nz": False, "axis": 1}}],
        },
        "tiling_key_merging": {"performed": False, "merged_groups": []},
    }
    files["registry/aliases.yaml"] = {"aliases": [{"alias": "PostNz", "target_id": "KBR_POST_NZ"}], "conflicts": []}
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L2", focus="只测试 TND 场景中 PostNz 分支的所有 TilingKey")

    stats = plan["semantic_focus"]["tiling_key_coverage"]
    assert stats["raw_expanded_count"] == 4
    assert stats["reachable_key_count"] == 2
    assert stats["realized_key_count"] == 2
    assert all(item["expected_tiling_key"]["layout"] == "TND" for item in plan["obligations"])
    assert all(item["expected_tiling_key"]["post_nz"] is True for item in plan["obligations"])


def test_l2_blocks_when_key_has_no_realization() -> None:
    files = _payload()["files"]
    files["tiling/exhaustive_key_space.yaml"] = {
        "field_order": ["axis"],
        "template_blocks": [{"id": "KEY_BLOCK_MAIN", "field_domains": {"axis": [0, 1]}, "product_count": 2}],
    }
    files["tiling/constraints.yaml"] = {"relations": [], "variable_constraints": [], "input_realization": {}}
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L2")

    assert plan["unresolved"]["status"] == "blocked"
    assert plan["semantic_focus"]["tiling_key_coverage"]["unrealized_key_count"] == 2


def test_cli_rejects_l3_without_topic() -> None:
    assert plan_main([".", "--op-name", "DemoOp", "--level", "L3"]) == 1


def test_cli_rejects_unknown_level() -> None:
    assert plan_main([".", "--op-name", "DemoOp", "--level", "L9"]) == 1


def test_l3_topic_determinism_filters_obligations() -> None:
    files = _payload(
        coverage={
            "family_obligations": [{"family_id": "FAM_A"}],
            "key_field_obligations": {
                "DETERTYPE": {"id": "KEY_DETERTYPE", "values": [0, 1, 2]},
                "ISTND": {"id": "KEY_ISTND", "values": [0, 1]},
            },
            "key_relation_obligations": [],
        }
    )["files"]
    files["tiling/key_cards/KEY_DETERTYPE.yaml"] = {"id": "KEY_DETERTYPE", "key": "DeterType", "domain": [0, 1, 2], "set_by": {"status": "missing"}, "hit_recipe": {"status": "unknown"}}
    from testcase_agent.topics import DEFAULT_TOPICS

    plan = build_plan(
        {"op_name": "DemoOp", "files": files, "snapshot_hash": "s"},
        level="L3",
        topic="determinism",
        topic_manifest=DEFAULT_TOPICS["determinism"],
    )
    refs = {ref for item in plan["obligations"] for ref in item.get("target_refs") or []}
    assert any("DETER" in ref.upper() for ref in refs)
    assert plan["test_level"] == "L3"


def test_focus_false_literal_does_not_become_true() -> None:
    files = _payload()["files"]
    files["registry/aliases.yaml"] = {"aliases": [{"alias": "PostNz", "target_id": "KBR_POST_NZ"}], "conflicts": []}
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L1", focus="不走 PostNz")

    assert plan["semantic_focus"]["branch_predicates"] == [{"branch_ref": "KBR_POST_NZ", "state": False}]


def test_l2_realization_matches_each_key_independently() -> None:
    files = _payload()["files"]
    files["tiling/exhaustive_key_space.yaml"] = {
        "summary": {"expanded_key_count": 2},
        "field_order": ["layout"],
        "template_blocks": [{"id": "B", "field_domains": {"layout": ["TND", "ND"]}, "product_count": 2}],
    }
    files["tiling/constraints.yaml"] = {
        "relations": [],
        "variable_constraints": [],
        "input_realization": {"CON_IR_TND": {"matches": {"key_pattern": {"layout": "TND"}}}},
        "tiling_key_pruning": {"performed": True, "pruned_combinations": []},
        "tiling_key_merging": {"performed": False, "merged_groups": []},
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L2")

    by_layout = {item["expected_tiling_key"]["layout"]: item["realization"]["status"] for item in plan["obligations"] if item.get("expected_tiling_key")}
    assert by_layout == {"TND": "realized", "ND": "unrealized"}


def test_direct_matches_layout_only_matches_tnd_key() -> None:
    files = _payload()["files"]
    files["tiling/exhaustive_key_space.yaml"] = {
        "summary": {"expanded_key_count": 3},
        "field_order": ["layout"],
        "template_blocks": [{"id": "B", "field_domains": {"layout": ["TND", "ND", "NZ"]}, "product_count": 3}],
    }
    files["tiling/constraints.yaml"] = {
        "relations": [],
        "variable_constraints": [],
        "input_realization": {"CON_IR_TND": {"matches": {"layout": "TND"}}},
        "tiling_key_pruning": {"performed": True, "pruned_combinations": []},
        "tiling_key_merging": {"performed": False, "merged_groups": []},
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L2")

    by_layout = {item["expected_tiling_key"]["layout"]: item["realization"]["status"] for item in plan["obligations"] if item.get("expected_tiling_key")}
    assert by_layout == {"TND": "realized", "ND": "unrealized", "NZ": "unrealized"}


def test_empty_matches_is_not_wildcard() -> None:
    files = _payload()["files"]
    files["tiling/exhaustive_key_space.yaml"] = {
        "summary": {"expanded_key_count": 2},
        "field_order": ["layout"],
        "template_blocks": [{"id": "B", "field_domains": {"layout": ["TND", "ND"]}, "product_count": 2}],
    }
    files["tiling/constraints.yaml"] = {
        "relations": [],
        "variable_constraints": [],
        "input_realization": {"CON_IR_EMPTY": {"matches": {}}},
        "tiling_key_pruning": {"performed": True, "pruned_combinations": []},
        "tiling_key_merging": {"performed": False, "merged_groups": []},
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L2")

    assert plan["semantic_focus"]["tiling_key_coverage"]["realized_key_count"] == 0
    assert plan["semantic_focus"]["tiling_key_coverage"]["unrealized_key_count"] == 2


def test_l2_ambiguous_realization_blocks() -> None:
    files = _payload()["files"]
    files["tiling/exhaustive_key_space.yaml"] = {
        "summary": {"expanded_key_count": 1},
        "field_order": ["layout"],
        "template_blocks": [{"id": "B", "field_domains": {"layout": ["TND"]}, "product_count": 1}],
    }
    files["tiling/constraints.yaml"] = {
        "relations": [],
        "variable_constraints": [],
        "input_realization": {
            "CON_IR_TND_A": {"matches": {"key_pattern": {"layout": "TND"}}},
            "CON_IR_TND_B": {"matches": {"key_pattern": {"layout": "TND"}}},
        },
        "tiling_key_pruning": {"performed": True, "pruned_combinations": []},
        "tiling_key_merging": {"performed": False, "merged_groups": []},
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L2")

    assert plan["semantic_focus"]["tiling_key_coverage"]["ambiguous_key_count"] == 1
    assert plan["unresolved"]["status"] == "blocked"


def test_l2_applies_relations_and_merging_and_count_blockers() -> None:
    files = _payload()["files"]
    files["tiling/exhaustive_key_space.yaml"] = {
        "summary": {"expanded_key_count": 4},
        "field_order": ["a", "b"],
        "template_blocks": [{"id": "B", "field_domains": {"a": [False, True], "b": [False, True]}, "product_count": 4}],
    }
    files["tiling/constraints.yaml"] = {
        "relations": [{"id": "REL_MUTEX", "relation_type": "mutex", "fields": ["a", "b"]}],
        "variable_constraints": [],
        "input_realization": {"CON_IR_BOOL": {"matches": {"key_pattern": {"a": False}}}},
        "tiling_key_pruning": {"performed": True, "pruned_combinations": []},
        "tiling_key_merging": {
            "performed": True,
            "merged_groups": [
                {"id": "CON_MERGE_ZERO", "merged_into": {"a": False, "b": False}, "source_combinations": [{"a": False, "b": False}]}
            ],
        },
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L2")
    stats = plan["semantic_focus"]["tiling_key_coverage"]

    assert stats["relation_rejected_count"] == 1
    assert stats["semantic_merge_group_count"] == 1
    assert stats["reachable_key_count"] == 3


def test_l2_product_and_summary_count_mismatch_block() -> None:
    files = _payload()["files"]
    files["tiling/exhaustive_key_space.yaml"] = {
        "summary": {"expanded_key_count": 99},
        "field_order": ["axis"],
        "template_blocks": [{"id": "B", "field_domains": {"axis": [0, 1]}, "product_count": 3}],
    }
    files["tiling/constraints.yaml"] = {
        "relations": [],
        "variable_constraints": [],
        "input_realization": {"CON_IR_AXIS": {"matches": {"key_pattern": {"axis": 0}}}},
        "tiling_key_pruning": {"performed": True, "pruned_combinations": []},
        "tiling_key_merging": {"performed": False, "merged_groups": []},
    }
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"}, level="L2")
    blocker_ids = {item["id"] for item in plan["unresolved"]["blocking_hard_obligations"]}

    assert "L2_BLOCK_PRODUCT_COUNT_MISMATCH_B" in blocker_ids
    assert "L2_SUMMARY_COUNT_MISMATCH" in blocker_ids


def test_focus_unresolved_term_blocks_without_guessing() -> None:
    plan = build_plan({"op_name": "DemoOp", "files": _payload()["files"], "snapshot_hash": "s"}, level="L1", focus="Only MysteryBranch")

    assert plan["unresolved"]["status"] == "blocked"
    assert plan["semantic_focus"]["unresolved_terms"]


def test_level_or_focus_changes_plan_hash() -> None:
    snapshot = {"op_name": "DemoOp", "files": _payload()["files"], "snapshot_hash": "s"}
    l1 = build_plan(snapshot, level="L1")
    l2 = build_plan(snapshot, level="L2")
    focused = build_plan(snapshot, level="L1", focus="TND")

    assert l1["plan_hash"] != l2["plan_hash"]
    assert l1["plan_hash"] != focused["plan_hash"]


def test_changed_focus_invalidates_previous_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    _patch_intake(monkeypatch, _payload())
    init_result = tg_init(repo, "DemoOp")
    first = tg_plan(repo, "DemoOp", level="L1", reuse_snapshot=True)
    root = repo / ".testcase-generator" / "DemoOp"
    write_yaml(
        root / "plan" / "human_supplement.yaml",
        {
            "version": 1,
            "status": "approved",
            "decision": "approve",
            "approved_snapshot_hash": init_result["snapshot"]["snapshot_hash"],
            "approved_plan_hash": first["plan_hash"],
            "approved_at": "2026-01-01T00:00:00+00:00",
            "supplements": [],
            "notes": "",
        },
    )

    second = tg_plan(repo, "DemoOp", level="L1", focus="TND", reuse_snapshot=True)

    assert second["plan_hash"] != first["plan_hash"]
    supplement = read_yaml(root / "plan" / "human_supplement.yaml")
    assert supplement["status"] == "reapproval_required"


def test_conflicting_hard_obligation_blocks_approval(tmp_path: Path) -> None:
    contract = _contract(
        coverage_obligations={
            "kernel_branches": [
                {
                    "id": "KBR_CONFLICT",
                    "priority": "hard",
                    "status": "conflicting",
                    "target_refs": ["KBR_CONFLICT"],
                    "reason": "two entries disagree",
                }
            ]
        }
    )
    files = _payload(contract)["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    assert plan["unresolved"]["status"] == "blocked"
    assert plan["unresolved"]["blocking_hard_obligations"]
    assert "Allow solve: no" in plan["review"] or "是否允许进入 solve" in plan["review"]
    assert "否" in plan["review"]


def test_testagent_does_not_modify_understand_operator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, uo = _repo(tmp_path)
    _patch_intake(monkeypatch, _payload())
    before = _tree_hash(uo)

    tg_init(repo, "DemoOp")
    tg_plan(repo, "DemoOp", reuse_snapshot=True)

    assert _tree_hash(uo) == before


def test_export_missing_has_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    monkeypatch.setattr(init_mod, "run_final_validation", lambda project_root, op_name, uo_root: _validation())

    def missing_export(project_root: Path, op_name: str, uo_root: Path) -> dict[str, Any]:
        raise FileNotFoundError("testcase-contract export failed: Missing canonical files for view 'testcase-contract': contracts/testcase.yaml")

    monkeypatch.setattr(init_mod, "export_testcase_contract", missing_export)

    with pytest.raises(TgInitError) as exc:
        tg_init(repo, "DemoOp")

    assert "testcase-contract export failed" in str(exc.value)
    report = read_yaml(repo / ".testcase-generator" / "DemoOp" / "intake" / "validation_report.yaml")
    assert "Missing canonical files" in report["blocking_issues"][0]["message"]


def test_relation_combination_status_conflict_is_hard_blocker_and_keeps_valid_combinations() -> None:
    files = _payload(
        coverage={
            "family_obligations": [],
            "key_field_obligations": {},
            "key_relation_obligations": [
                {
                    "id": "REL_CONFLICT",
                    "relation_type": "compatible_set",
                    "combinations": [
                        {"KEY_A": 0, "status": "reachable"},
                        {"KEY_A": 1, "status": "reachable"},
                        {"KEY_A": 0, "status": "unreachable"},
                    ],
                }
            ],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})
    relations = [item for item in plan["obligations"] if item["kind"] == "tiling_key_relation"]
    conflict = next(item for item in relations if item["status"] == "conflicting")

    assert any(item.get("target_value") == {"KEY_A": 1} for item in relations)
    assert conflict["priority"] == "hard"
    assert conflict["unresolved_reason"] == "RELATION_COMBINATION_STATUS_CONFLICT"
    assert plan["unresolved"]["status"] == "blocked"
    assert plan["unresolved"]["blocking_hard_obligations"]


def test_nested_relation_item_is_not_treated_as_key_field() -> None:
    files = _payload(
        contract=_contract(
            coverage_obligations={
                "tiling_keys": [
                    {
                        "id": "REL_NESTED",
                        "constraints": {
                            "relation_type": "compatible_set",
                            "combinations": [{"KEY_A": 0}],
                        },
                    }
                ],
                "tilingdata": [],
                "kernel_paths": [],
                "numerical": [],
                "negative": [],
            }
        ),
        coverage={"family_obligations": [], "key_field_obligations": {}, "key_relation_obligations": []},
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    assert len([item for item in plan["obligations"] if item["kind"] == "tiling_key_relation"]) == 1
    assert not [item for item in plan["obligations"] if item["kind"] == "tiling_key_field_value"]


def test_real_final_validation_export_and_phase2_without_mocks(tmp_path: Path) -> None:
    pytest.importorskip("understand_operator")
    repo = tmp_path / "repo"
    repo.mkdir()
    _mature_final_uo_fixture(repo)

    init_result = tg_init(repo, "DemoOp")
    plan = tg_plan(repo, "DemoOp", reuse_snapshot=True)
    root = repo / ".testcase-generator" / "DemoOp"
    write_yaml(
        root / "plan" / "human_supplement.yaml",
        {
            "version": 1,
            "status": "approved",
            "decision": "approve",
            "approved_snapshot_hash": init_result["snapshot"]["snapshot_hash"],
            "approved_plan_hash": plan["plan_hash"],
            "approved_at": "2026-01-01T00:00:00+00:00",
            "supplements": [],
            "notes": "",
        },
    )
    solve = tg_solve(repo, "DemoOp", allow_legacy_realization=True)
    snapshot = read_json(root / "snapshot" / "understand_contract.json")

    assert init_result["snapshot"]["final_validation"]["status"] == "pass"
    assert "files" in snapshot and "context_slice" in snapshot
    assert snapshot["context_slice"]["entities"]
    entity_ids = {str(item.get("id") or item.get("stable_id")) for item in snapshot["context_slice"]["entities"]}
    assert {"FAM_MAIN", "FAM_ALT", "KPATH_MAIN", "KPATH_ALT"} <= entity_ids
    assert plan["unresolved"]["contract_gaps"] == []
    ir_result = build_constraint_ir(snapshot, read_yaml(root / "plan" / "coverage_obligations.yaml"), {"decision": "approve"})
    variables = {item["id"]: item for item in ir_result.ir["variables"]}
    assert variables["VAR_FAMILY"]["domain"] == ["FAM_ALT", "FAM_MAIN"]
    assert variables["VAR_KERNEL_PATH"]["domain"] == ["KPATH_ALT", "KPATH_MAIN"]
    assert variables["VAR_KEY_SPLIT_AXIS"]["domain"]["kind"] == "discrete"
    assert variables["VAR_KEY_SPLIT_AXIS"]["domain"]["values"] == [0, 2, 4]
    assert not any(error["code"] == "DOMAIN_CONFLICT" for error in ir_result.errors)
    assert any(item["status"] == "sat" and item["model"].get("VAR_KEY_SPLIT_AXIS") == 2 for item in solve["solve_results"])
    assert any(item["status"] == "error" and item.get("code") == "OBLIGATION_OUTSIDE_DECLARED_DOMAIN" for item in solve["solve_results"])
    assert (root / "cases" / "cases.csv").exists() or (root / "cases" / "realize_report.yaml").exists()
    assert not (root / "run" / "operator_execution.yaml").exists()
