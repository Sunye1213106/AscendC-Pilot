from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from testcase_agent import init as init_mod
from testcase_agent.hashing import semantic_snapshot_hash
from testcase_agent.init import TgInitError, tg_init
from testcase_agent.io import read_json, read_yaml, write_json, write_yaml
from testcase_agent.planner import build_plan, tg_plan
from testcase_agent.solve import tg_solve
from testcase_agent.understand import UnderstandExportError, add_understand_to_path, export_testcase_contract


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
            "tiling/coverage_model.yaml": coverage or {"family_obligations": [], "key_field_obligations": {}, "key_relation_obligations": []},
            "kernel/branches.yaml": {"branches": []},
            "cross_layer/impact_graph.yaml": {"nodes": [], "edges": [], "impacts": []},
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
        "tiling/key_space.yaml": {"fields": [{"id": "KEY_SPLIT_AXIS", "kind": "key", "data_type": "int", "values": [0, 1, 2]}]},
        "tiling/families.yaml": {"families": [{"id": "FAM_MAIN"}]},
        "kernel/paths.yaml": {"kernel_paths": [{"id": "KPATH_MAIN"}]},
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
        "registry/evidence.yaml": {"evidence": [{"id": "EV_OPERATOR", "file": "operator.yaml", "lines": [1, 3], "kind": "manual", "source_hash": "x"}]},
        "tiling/variables.yaml": {"variables": [{"id": "VAR_KEY_SPLIT_AXIS", "data_type": "int"}], "tiling_mechanism": "key"},
        "tiling/constraints.yaml": {"relations": [], "variable_constraints": [{"id": "CON_AXIS_DOMAIN", "var": "VAR_KEY_SPLIT_AXIS", "domain": {"min": 0, "max": 1}}], "input_realization": []},
        "tiling/key_space.yaml": {"fields": [{"id": "KEY_SPLIT_AXIS", "kind": "key", "data_type": "int", "values": [0, 1]}], "derived_fields": [], "constants": []},
        "tiling/families.yaml": {"families": [{"id": "FAM_MAIN", "name": "main"}], "dispatch_tree": {"root": "FAM_MAIN"}},
        "tiling/data_model.yaml": {"structs": {"S": {"fields": {"splitAxis": {"id": "TDF_SPLIT_AXIS", "canonical_name": "splitAxis"}}}}, "family_to_struct": {"FAM_MAIN": "S"}, "numeric_overlay": []},
        "tiling/coverage_model.yaml": {"coverage_policy": "minimal", "family_obligations": [{"id": "COV_FAM_MAIN", "family_id": "FAM_MAIN"}], "key_field_obligations": {}, "key_relation_obligations": []},
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
        "kernel/variables.yaml": {"runtime_variables": [{"id": "KVAR_AXIS", "data_type": "int"}], "tilingdata_reads": [{"id": "TDF_READ_SPLIT_AXIS", "field_id": "TDF_SPLIT_AXIS"}], "path_decision_points": []},
        "kernel/branches.yaml": {"branches": [{"id": "KBR_HAS_TAIL", "condition": "tail"}], "path_semantics": [], "dataflow_links": [], "resource_links": []},
        "kernel/paths.yaml": {"kernel_paths": [{"id": "KPATH_MAIN", "template_binding_ids": ["KTPL_MAIN"], "runtime_variable_ids": ["KVAR_AXIS"], "branch_ids": ["KBR_HAS_TAIL"], "implements_compute_steps": ["CL_STEP_MAIN"]}]},
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
            variables=[{"id": "VAR_KEY_SPLIT_AXIS", "type": "int", "domain": {"min": 0, "max": 1}}],
            interface={"required_inputs": [], "optional_inputs": [], "outputs": [], "attrs": [], "dtype_layout_domains": [{"id": "FP16_ND"}]},
            coverage_obligations={
                "families": [{"id": "COV_FAM_MAIN", "target_refs": ["FAM_MAIN"]}],
                "tiling_keys": [
                    {"id": "COV_AXIS_VALID", "field": "split_axis", "values": [1]},
                    {"id": "COV_AXIS_INVALID", "field": "split_axis", "values": [2]},
                ],
                "kernel_paths": [{"id": "COV_PATH_MAIN", "target_refs": ["KPATH_MAIN"]}],
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

    first = tg_plan(repo, "DemoOp")
    second = tg_plan(repo, "DemoOp")

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
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    fields = [item for item in plan["obligations"] if item["kind"] == "tiling_key_field_value"]
    assert len(fields) == 1
    assert fields[0]["target_refs"] == ["layout"]
    assert fields[0]["target_value"] == "ND"


def test_unreachable_and_reachable_are_distinguished(tmp_path: Path) -> None:
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

    by_target = {item["target_refs"][0]: item for item in plan["obligations"] if item["kind"] == "family"}
    assert by_target["FAM_REACH"]["status"] == "pending"
    assert by_target["FAM_DEAD"]["status"] == "proof_required"
    assert by_target["FAM_DEAD"]["reachability"] == "unreachable"


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
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    assert len([item for item in plan["obligations"] if item["kind"] == "family"]) == 2
    assert len([item for item in plan["obligations"] if item["kind"] == "optional_input_mode"]) == 4


def test_key_field_values_expand_to_atomic_obligations() -> None:
    files = _payload(
        coverage={
            "family_obligations": [],
            "key_field_obligations": {"split_axis": {"id": "KEY_SPLIT_AXIS", "values": [0, 1, 2], "independent": True}},
            "key_relation_obligations": [],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

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
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

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


def test_dtype_layout_class_generates_atomic_obligations() -> None:
    contract = _contract(interface={"optional_inputs": [], "dtype_layout_domains": [{"id": "FP16_TND"}, {"id": "BF16_ND"}]})
    plan = build_plan({"op_name": "DemoOp", "files": _payload(contract)["files"], "snapshot_hash": "s"})

    assert [item["target_refs"][0] for item in plan["obligations"] if item["kind"] == "dtype_layout_class"] == ["BF16_ND", "FP16_TND"]


def test_export_view_and_context_slice_are_merged(tmp_path: Path) -> None:
    repo, uo = _repo(tmp_path)
    _real_uo_fixture(uo)

    payload = export_testcase_contract(repo, "DemoOp", uo)

    assert set(payload["files"]) >= {
        "contracts/testcase.yaml",
        "test/contract.yaml",
        "tiling/coverage_model.yaml",
        "kernel/branches.yaml",
        "cross_layer/impact_graph.yaml",
        "quality.yaml",
    }
    assert payload["context_slice"]["entities"]
    assert payload["context_slice"]["testcase_contract"] == payload["files"]["contracts/testcase.yaml"]


def test_contract_view_context_mismatch_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_review_mentions_tiling_key_value_kind() -> None:
    files = _payload(
        coverage={
            "family_obligations": [],
            "key_field_obligations": {"split_axis": {"id": "KEY_SPLIT_AXIS", "values": [0]}},
            "key_relation_obligations": [],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    assert "tiling_key_field_value" in plan["review"]
    assert "TilingKey 原子值义务数" in plan["review"]


def test_real_format_fixture_end_to_end_phase1_phase2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, uo = _repo(tmp_path)
    _real_uo_fixture(uo)
    monkeypatch.setattr(init_mod, "run_final_validation", lambda project_root, op_name, uo_root: _validation())

    init_result = tg_init(repo, "DemoOp")
    plan = tg_plan(repo, "DemoOp")
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
    solve = tg_solve(repo, "DemoOp")

    snapshot = read_json(root / "snapshot" / "understand_contract.json")
    assert "tiling/coverage_model.yaml" in snapshot["files"]
    assert snapshot["context_slice"]["entities"]
    assert plan["unresolved"]["contract_gaps"] == []
    assert len([item for item in plan["obligations"] if item["kind"] == "tiling_key_field_value" and item["target_refs"] == ["KEY_SPLIT_AXIS"]]) == 3
    assert len([item for item in plan["obligations"] if item["kind"] == "kernel_branch" and item["target_refs"] == ["KBR_HAS_TAIL"]]) == 2
    branch_candidates = [item for item in solve["deduped_candidates"] if "KBR_HAS_TAIL" in item["coverage_signature"]["branch_truth"]]
    assert len({item["id"] for item in branch_candidates}) >= 2
    assert any(item["model"].get("VAR_KEY_SPLIT_AXIS") == 2 and item["status"] == "sat" for item in solve["solve_results"])
    assert any(len(item["covered_obligation_ids"]) > 1 for item in solve["deduped_candidates"])
    assert len([item for item in plan["obligations"] if item["kind"] == "tiling_key_relation" and item.get("parent_obligation_id") == "COV_REL_COMPAT"]) == 3
    assert not list(root.rglob("*.csv"))
    assert not (root / "run" / "operator_execution.yaml").exists()


def test_conflicting_hard_obligation_blocks_approval(tmp_path: Path) -> None:
    contract = _contract(
        coverage_obligations={
            "kernel_paths": [
                {
                    "id": "COV_KERNEL_PATH_CONFLICT",
                    "priority": "hard",
                    "status": "conflicting",
                    "target_refs": ["KPATH_A"],
                    "reason": "two entries disagree",
                }
            ]
        }
    )
    files = _payload(contract)["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    assert plan["unresolved"]["status"] == "blocked"
    assert plan["unresolved"]["blocking_hard_obligations"]
    assert "是否允许进入 SMT 阶段: 否" in plan["review"]


def test_testagent_does_not_modify_understand_operator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, uo = _repo(tmp_path)
    _patch_intake(monkeypatch, _payload())
    before = _tree_hash(uo)

    tg_init(repo, "DemoOp")
    tg_plan(repo, "DemoOp")

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
    repo = tmp_path / "repo"
    repo.mkdir()
    _mature_final_uo_fixture(repo)

    init_result = tg_init(repo, "DemoOp")
    plan = tg_plan(repo, "DemoOp")
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
    solve = tg_solve(repo, "DemoOp")
    snapshot = read_json(root / "snapshot" / "understand_contract.json")

    assert init_result["snapshot"]["final_validation"]["status"] == "pass"
    assert "files" in snapshot and "context_slice" in snapshot
    assert snapshot["context_slice"]["entities"]
    assert plan["unresolved"]["contract_gaps"] == []
    assert any(item["status"] == "sat" and item["model"].get("VAR_KEY_SPLIT_AXIS") == 1 for item in solve["solve_results"])
    assert any(item["status"] == "error" and item.get("code") == "OBLIGATION_OUTSIDE_DECLARED_DOMAIN" for item in solve["solve_results"])
    assert not list(root.rglob("*.csv"))
    assert not (root / "run" / "operator_execution.yaml").exists()
