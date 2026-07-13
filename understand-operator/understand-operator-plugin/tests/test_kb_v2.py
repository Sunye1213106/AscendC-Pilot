from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from understand_operator._operator.artifacts import init_operator_layout, operator_root, resolve_existing_operator_root
from understand_operator._operator import kb_compiler
from understand_operator._operator.kb_compiler import compile_kb, promote_kb, validate_kb
from understand_operator.scripts.kb_query_export import export_context_slice, export_view
from understand_operator.scripts.update_operator import _build_stale_artifacts, _build_update_plan


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = operator_root(repo, "DemoOp")
    init_operator_layout(base, "DemoOp", repo)
    return repo, base


def _normalized_docs(docs: dict[str, dict]) -> dict[str, dict]:
    payload = {key: yaml.safe_load(yaml.safe_dump(value)) for key, value in docs.items()}
    kb_compiler._normalize_candidate(payload)
    return payload


def _by_legacy_or_id(steps: list[dict], legacy_id: str) -> dict:
    for step in steps:
        if step.get("id") == legacy_id or legacy_id in (step.get("legacy_ids") or []) or legacy_id in (step.get("aliases") or []):
            return step
    raise AssertionError(f"step not found: {legacy_id}")


def test_layout_creates_v2_slices_and_query_exports(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)

    for rel in (
        "manifest.yaml",
        "registry/variables.yaml",
        "kernel/compile_model.yaml",
        "cross_layer/impact_graph.yaml",
        "query/routes.yaml",
        "contracts/code_change.yaml",
        "contracts/testcase.yaml",
    ):
        assert (base / rel).exists(), rel

    payload = export_view(base, "DemoOp", "code-change")
    assert payload["view"] == "code-change"
    assert "contracts/code_change.yaml" in payload["files"]


def test_layout_seeds_operator_initialism_alias(tmp_path: Path) -> None:
    repo = tmp_path / "FAG_test"
    repo.mkdir()
    base = operator_root(repo, "flash_attention_score_grad")
    init_operator_layout(base, "flash_attention_score_grad", repo)

    aliases_doc = yaml.safe_load((base / "registry" / "aliases.yaml").read_text(encoding="utf-8"))
    aliases = {item["alias"].lower(): item for item in aliases_doc["aliases"]}

    assert "fasg" in aliases
    assert "fag" in aliases
    assert aliases["fasg"]["target_id"] == "SYM_OPERATOR_FLASH_ATTENTION_SCORE_GRAD"
    assert resolve_existing_operator_root(repo, "fasg") == ("flash_attention_score_grad", base)


def test_kernel_flow_normalizes_vector_cube_datamove_sync_steps() -> None:
    docs = _normalized_docs(
        {
            "flow/compute_graph.yaml": {
                "version": 1,
                "op_name": "DemoOp",
                "compute_steps": [
                    {
                        "id": "STEP_LOAD",
                        "name": "Load query tile",
                        "calls": ["DataCopy"],
                        "inputs": ["query_gm"],
                        "outputs": ["query_ub"],
                        "source_location": {"file": "kernel.cpp", "function": "CopyIn", "line_start": 10, "line_end": 14},
                    },
                    {
                        "id": "STEP_QK",
                        "name": "Compute Q K matrix multiplication",
                        "calls": ["matmul.Iterate"],
                        "inputs": ["query_tile", "key_tile"],
                        "outputs": ["score_tile"],
                        "source_location": {"file": "kernel.cpp", "function": "Compute", "line_start": 20, "line_end": 30},
                    },
                    {
                        "id": "STEP_SCALE",
                        "name": "Scale matrix multiplication result",
                        "calls": ["AscendC::Mul"],
                        "inputs": ["score_tile"],
                        "outputs": ["scaled_score_tile"],
                        "source_location": {"file": "kernel.cpp", "function": "PostProcess", "line_start": 31, "line_end": 34},
                    },
                    {"id": "STEP_SYNC", "name": "Wait for vector output", "calls": ["WaitFlag"], "inputs": ["scaled_score_tile"], "outputs": ["ready_score_tile"]},
                ],
            }
        }
    )
    steps = docs["flow/compute_graph.yaml"]["compute_steps"]

    assert [step["execution_unit"] for step in steps] == ["DATA_MOVE", "CUBE", "VECTOR", "SYNC"]
    assert [step["operation"] for step in steps] == ["copy", "matmul", "mul", "sync"]
    assert steps[0]["name"].startswith("[DataMove]")
    assert steps[1]["name"].startswith("[Cube]")
    assert steps[2]["name"].startswith("[Vector]")
    assert steps[3]["name"].startswith("[Sync]")
    assert steps[1]["inputs"] == ["query_tile", "key_tile"]
    assert steps[1]["outputs"] == ["score_tile"]
    assert steps[1]["source_location"]["line_start"] == 20
    assert any("CUBE API" in item for item in steps[1]["evidence"])
    assert steps[2]["depends_on"] == []
    assert steps[2]["dependency_status"] == "unspecified"
    assert steps[2]["is_root"] is False
    assert "execution_transition" not in steps[2]
    assert docs["flow/compute_graph.yaml"]["cube_steps"] == [steps[1]["id"]]
    assert docs["flow/compute_graph.yaml"]["vector_steps"] == [steps[2]["id"]]
    assert docs["flow/compute_graph.yaml"]["data_move_steps"] == [steps[0]["id"]]
    assert all(step["id"].startswith("CL_") for step in steps)
    assert "computation_steps" not in docs["flow/compute_graph.yaml"]
    assert "calls" not in steps[0]


def test_vector_preprocess_then_cube_dependency_is_recorded() -> None:
    docs = _normalized_docs(
        {
            "flow/compute_graph.yaml": {
                "compute_steps": [
                    {"id": "STEP_CAST", "calls": ["AscendC::Cast"], "inputs": ["query_fp16"], "outputs": ["query_fp32"]},
                    {"id": "STEP_MATMUL", "calls": ["Mmad"], "inputs": ["query_fp32", "key_tile"], "outputs": ["score_tile"]},
                ]
            }
        }
    )
    steps = docs["flow/compute_graph.yaml"]["compute_steps"]

    assert steps[0]["execution_unit"] == "VECTOR"
    assert steps[1]["execution_unit"] == "CUBE"
    assert steps[1]["depends_on"] == []
    assert steps[1]["dependency_status"] == "unspecified"
    assert steps[1]["is_root"] is False


def test_indirect_wrapper_cube_detection_and_matmul_name_not_enough() -> None:
    docs = _normalized_docs(
        {
            "flow/compute_graph.yaml": {
                "functions": [
                    {"name": "ComputeScore", "calls": ["matmul.Iterate"], "evidence": ["Calls matmul.Iterate()"]},
                    {"name": "MaybeMatmulHelper", "calls": ["UpdateOffset"], "evidence": ["updates scalar offset only"]},
                ],
                "compute_steps": [
                    {"id": "STEP_WRAPPED", "name": "Run score wrapper", "calls": ["ComputeScore"], "inputs": ["q", "k"], "outputs": ["score"]},
                    {"id": "STEP_NOT_CUBE", "name": "Matmul shaped bookkeeping", "calls": ["MaybeMatmulHelper"], "inputs": ["offset"], "outputs": ["next_offset"]},
                ],
            }
        }
    )
    steps = docs["flow/compute_graph.yaml"]["compute_steps"]
    wrapped = _by_legacy_or_id(steps, "STEP_WRAPPED")
    not_cube = _by_legacy_or_id(steps, "STEP_NOT_CUBE")

    assert wrapped["execution_unit"] == "CUBE"
    assert wrapped["confidence"] == "medium"
    assert any("ComputeScore" in item for item in wrapped["evidence"])
    assert not_cube["execution_unit"] == "UNKNOWN"
    assert not not_cube["name"].startswith("[Cube]")


def test_unknown_and_legacy_compute_steps_get_safe_defaults() -> None:
    docs = _normalized_docs({"flow/compute_graph.yaml": {"compute_steps": {"legacy": {"name": "Handle tensor"}}}})
    step = docs["flow/compute_graph.yaml"]["compute_steps"][0]

    assert step["id"].startswith("CL_")
    assert "legacy" in step["legacy_ids"]
    assert step["execution_unit"] == "UNKNOWN"
    assert step["operation"] == "unknown"
    assert step["name"].startswith("[Unknown]")
    assert step["inputs"] == []
    assert step["outputs"] == []
    assert step["source_location"] == {}
    assert step["evidence"] == ["Insufficient API or data-shape evidence for execution unit"]


def test_kernel_path_computation_steps_are_classified_without_cross_path_merge() -> None:
    docs = _normalized_docs(
        {
            "kernel/paths.yaml": {
                "kernel_paths": [
                    {
                        "id": "KPATH_VECTOR",
                        "tiling_keys": ["KEY_VECTOR"],
                        "computation_steps": [{"id": "VEC_STEP", "calls": ["AscendC::Exp"], "inputs": ["x"], "outputs": ["y"]}],
                    },
                    {
                        "id": "KPATH_CUBE",
                        "tiling_keys": ["KEY_CUBE"],
                        "computation_steps": [{"id": "CUBE_STEP", "calls": ["Mmad"], "inputs": ["a", "b"], "outputs": ["c"]}],
                    },
                ]
            }
        }
    )
    paths = {item["id"]: item for item in docs["kernel/paths.yaml"]["kernel_paths"]}

    assert paths["KPATH_VECTOR"]["tiling_keys"] == ["KEY_VECTOR"]
    assert paths["KPATH_CUBE"]["tiling_keys"] == ["KEY_CUBE"]
    assert paths["KPATH_VECTOR"]["vector_steps"] == [paths["KPATH_VECTOR"]["computation_steps"][0]["id"]]
    assert paths["KPATH_VECTOR"]["cube_steps"] == []
    assert paths["KPATH_CUBE"]["cube_steps"] == [paths["KPATH_CUBE"]["computation_steps"][0]["id"]]
    assert paths["KPATH_CUBE"]["vector_steps"] == []
    assert paths["KPATH_VECTOR"]["computation_steps"][0]["execution_unit"] == "VECTOR"
    assert paths["KPATH_CUBE"]["computation_steps"][0]["execution_unit"] == "CUBE"
    assert paths["KPATH_VECTOR"]["computation_steps"][0]["id"].startswith("KSTEP_")


def test_flow_dependencies_are_explicit_dag_not_list_adjacency() -> None:
    docs = _normalized_docs(
        {
            "flow/compute_graph.yaml": {
                "compute_steps": [
                    {"id": "STEP_A", "calls": ["AscendC::Cast"], "outputs": ["a"]},
                    {"id": "STEP_B", "calls": ["AscendC::Exp"], "outputs": ["b"]},
                    {"id": "STEP_C", "calls": ["Mmad"], "depends_on": ["STEP_A"], "inputs": ["a", "k"], "outputs": ["c"]},
                ]
            }
        }
    )
    steps = docs["flow/compute_graph.yaml"]["compute_steps"]
    a = _by_legacy_or_id(steps, "STEP_A")
    b = _by_legacy_or_id(steps, "STEP_B")
    c = _by_legacy_or_id(steps, "STEP_C")

    assert b["depends_on"] == []
    assert c["depends_on"] == [a["id"]]
    assert a["downstream_steps"] == [c["id"]]
    assert b["downstream_steps"] == []
    assert c["execution_transitions"][0]["from_step"] == a["id"]
    assert c["execution_transition"] == c["execution_transitions"][0]
    assert c["execution_transition"]["from_unit"] == "VECTOR"
    assert c["execution_transition"]["to_unit"] == "CUBE"
    assert c["execution_transition"]["sync_semantics"]["status"] == "unknown"
    assert c["execution_transition"]["data_move_semantics"]["status"] == "unknown"


def test_explicit_root_and_multi_root_dag_dependencies_are_resolved() -> None:
    docs = _normalized_docs(
        {
            "flow/compute_graph.yaml": {
                "compute_steps": [
                    {"id": "CL_LOAD_A", "depends_on": [], "calls": ["DataCopy"], "outputs": ["a"]},
                    {"id": "CL_LOAD_B", "depends_on": [], "calls": ["DataCopy"], "outputs": ["b"]},
                    {"id": "CL_MERGE", "depends_on": ["CL_LOAD_A", "CL_LOAD_B"], "calls": ["AscendC::Add"], "outputs": ["merged"]},
                ]
            }
        }
    )
    steps = docs["flow/compute_graph.yaml"]["compute_steps"]
    load_a = _by_legacy_or_id(steps, "CL_LOAD_A")
    load_b = _by_legacy_or_id(steps, "CL_LOAD_B")
    merge = _by_legacy_or_id(steps, "CL_MERGE")

    assert load_a["depends_on"] == []
    assert load_a["dependency_status"] == "root"
    assert load_a["is_root"] is True
    assert load_b["dependency_status"] == "root"
    assert load_b["is_root"] is True
    assert merge["depends_on"] == [load_a["id"], load_b["id"]]
    assert merge["dependency_status"] == "resolved"
    assert merge["is_root"] is False
    assert load_a["downstream_steps"] == [merge["id"]]
    assert load_b["downstream_steps"] == [merge["id"]]
    assert len(merge["execution_transitions"]) == 2


def test_unspecified_dependencies_are_not_roots_or_auto_linearized() -> None:
    docs = _normalized_docs(
        {
            "flow/compute_graph.yaml": {
                "compute_steps": [
                    {"id": "CL_A", "calls": ["AscendC::Cast"], "outputs": ["a"]},
                    {"id": "CL_B", "calls": ["AscendC::Exp"], "outputs": ["b"]},
                ]
            }
        }
    )
    steps = docs["flow/compute_graph.yaml"]["compute_steps"]
    a = _by_legacy_or_id(steps, "CL_A")
    b = _by_legacy_or_id(steps, "CL_B")

    assert a["depends_on"] == []
    assert a["dependency_status"] == "unspecified"
    assert a["is_root"] is False
    assert b["depends_on"] == []
    assert b["dependency_status"] == "unspecified"
    assert b["is_root"] is False
    assert a["downstream_steps"] == []
    assert b["downstream_steps"] == []


def test_missing_dependency_marks_step_unresolved_with_missing_list() -> None:
    result = kb_compiler.CompileResult(op_name="DemoOp")
    docs = {
        "flow/compute_graph.yaml": {
            "compute_steps": [
                {"id": "CL_A", "depends_on": ["CL_MISSING"], "calls": ["AscendC::Cast"], "outputs": ["a"]},
            ]
        }
    }
    kb_compiler._normalize_candidate(docs, result=result, op_name="DemoOp")
    step = docs["flow/compute_graph.yaml"]["compute_steps"][0]

    assert step["dependency_status"] == "unresolved"
    assert step["is_root"] is False
    assert step["missing_dependencies"] == ["CL_MISSING"]
    assert any(issue.code == "FLOW_UNKNOWN_DEPENDENCY" for issue in result.issues)


def test_ordered_sequence_is_opt_in_for_legacy_linearization() -> None:
    docs = _normalized_docs(
        {
            "flow/compute_graph.yaml": {
                "dependency_policy": "ordered_sequence",
                "compute_steps": [
                    {"id": "STEP_A", "calls": ["AscendC::Cast"], "outputs": ["a"]},
                    {"id": "STEP_B", "calls": ["AscendC::Exp"], "outputs": ["b"]},
                ],
            }
        }
    )
    steps = docs["flow/compute_graph.yaml"]["compute_steps"]
    assert steps[0]["depends_on"] == []
    assert steps[0]["dependency_status"] == "root"
    assert steps[0]["is_root"] is True
    assert steps[1]["depends_on"] == [steps[0]["id"]]
    assert steps[1]["dependency_status"] == "resolved"
    assert steps[1]["is_root"] is False


def test_cycle_dependencies_mark_nodes_invalid_and_fail_validation() -> None:
    result = kb_compiler.CompileResult(op_name="DemoOp")
    docs = {
        "flow/compute_graph.yaml": {
            "compute_steps": [
                {"id": "CL_A", "depends_on": ["CL_B"]},
                {"id": "CL_B", "depends_on": ["CL_A"]},
            ]
        }
    }
    kb_compiler._normalize_candidate(docs, result=result, op_name="DemoOp")
    steps = docs["flow/compute_graph.yaml"]["compute_steps"]
    a = _by_legacy_or_id(steps, "CL_A")
    b = _by_legacy_or_id(steps, "CL_B")

    assert a["dependency_status"] == "invalid"
    assert b["dependency_status"] == "invalid"
    assert a["is_root"] is False
    assert b["is_root"] is False
    assert result.status == "fail"
    assert any(issue.code == "FLOW_DEPENDENCY_CYCLE" for issue in result.issues)


def test_bad_dependency_format_marks_step_invalid() -> None:
    result = kb_compiler.CompileResult(op_name="DemoOp")
    docs = {"flow/compute_graph.yaml": {"compute_steps": [{"id": "CL_A", "depends_on": "CL_B"}]}}
    kb_compiler._normalize_candidate(docs, result=result, op_name="DemoOp")
    step = docs["flow/compute_graph.yaml"]["compute_steps"][0]

    assert step["depends_on"] == []
    assert step["dependency_status"] == "invalid"
    assert step["is_root"] is False
    assert result.status == "fail"
    assert any(issue.code == "FLOW_BAD_DEPENDENCY_FORMAT" for issue in result.issues)


def test_kernel_path_dependency_status_uses_same_state_machine() -> None:
    result = kb_compiler.CompileResult(op_name="DemoOp")
    docs = {
        "kernel/paths.yaml": {
            "kernel_paths": [
                {
                    "id": "KPATH_A",
                    "computation_steps": [
                        {"id": "KSTEP_ROOT", "depends_on": [], "calls": ["DataCopy"], "outputs": ["a"]},
                        {"id": "KSTEP_UNSPECIFIED", "calls": ["AscendC::Exp"], "outputs": ["b"]},
                        {"id": "KSTEP_MISSING", "depends_on": ["KSTEP_NOPE"], "calls": ["Mmad"], "outputs": ["c"]},
                    ],
                }
            ]
        }
    }
    kb_compiler._normalize_candidate(docs, result=result, op_name="DemoOp")
    steps = docs["kernel/paths.yaml"]["kernel_paths"][0]["computation_steps"]
    root = _by_legacy_or_id(steps, "KSTEP_ROOT")
    unspecified = _by_legacy_or_id(steps, "KSTEP_UNSPECIFIED")
    missing = _by_legacy_or_id(steps, "KSTEP_MISSING")

    assert root["dependency_status"] == "root"
    assert root["is_root"] is True
    assert unspecified["dependency_status"] == "unspecified"
    assert unspecified["is_root"] is False
    assert missing["dependency_status"] == "unresolved"
    assert missing["missing_dependencies"] == ["KSTEP_NOPE"]
    assert any(issue.code == "FLOW_UNKNOWN_DEPENDENCY" and issue.artifact == "kernel/paths.yaml" for issue in result.issues)


def test_flow_dependency_validation_reports_unknown_and_cycle() -> None:
    docs = {
        "flow/compute_graph.yaml": {
            "compute_steps": [
                {"id": "CL_DEMO_A", "depends_on": ["CL_DEMO_B", "CL_MISSING"]},
                {"id": "CL_DEMO_B", "depends_on": ["CL_DEMO_A"]},
            ]
        }
    }
    result = kb_compiler.CompileResult(op_name="DemoOp")
    kb_compiler._validate_flow_step_graph(docs, result)
    codes = [issue.code for issue in result.issues]
    assert "FLOW_UNKNOWN_DEPENDENCY" in codes
    assert "FLOW_DEPENDENCY_CYCLE" in codes


def test_compute_steps_is_canonical_and_export_adds_compat_alias(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    flow_path = base / "flow" / "compute_graph.yaml"
    flow_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "computation_steps": [{"id": "STEP_OLD", "depends_on": [], "calls": ["AscendC::Cast"], "outputs": ["y"]}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    docs = _normalized_docs({"flow/compute_graph.yaml": yaml.safe_load(flow_path.read_text(encoding="utf-8"))})
    assert "compute_steps" in docs["flow/compute_graph.yaml"]
    assert "computation_steps" not in docs["flow/compute_graph.yaml"]

    flow_path.write_text(yaml.safe_dump(docs["flow/compute_graph.yaml"], sort_keys=False), encoding="utf-8")
    for rel in ("flow/dataflow.yaml", "flow/golden_model.yaml", "flow/numerical_model.yaml", "quality.yaml"):
        (base / rel).write_text(yaml.safe_dump({"status": "not_applicable", "reason": "unit test", "evidence_refs": ["EV_NONE"]}), encoding="utf-8")
    payload = export_view(base, "DemoOp", "golden-gen")
    exported_flow = payload["files"]["flow/compute_graph.yaml"]
    assert exported_flow["computation_steps"] == exported_flow["compute_steps"]
    assert exported_flow["compute_steps"][0]["dependency_status"] == "root"
    assert exported_flow["compute_steps"][0]["is_root"] is True
    assert exported_flow["computation_steps"][0]["dependency_status"] == "root"
    assert "computation_steps" not in yaml.safe_load(flow_path.read_text(encoding="utf-8"))


def test_flow_alias_mismatch_and_stable_id_collision_are_reported() -> None:
    result = kb_compiler.CompileResult(op_name="DemoOp")
    docs = {
        "flow/compute_graph.yaml": {
            "compute_steps": [{"id": "CL_A"}],
            "computation_steps": [{"id": "CL_B"}],
        }
    }
    kb_compiler._normalize_candidate(docs, result=result, op_name="DemoOp")
    assert any(issue.code == "FLOW_STEP_ALIAS_MISMATCH" for issue in result.issues)

    collision = kb_compiler.CompileResult(op_name="DemoOp")
    docs = {"flow/compute_graph.yaml": {"compute_steps": [{"id": "CL_DUP"}, {"id": "CL_DUP"}]}}
    kb_compiler._validate_flow_step_graph(docs, collision)
    assert any(issue.code == "FLOW_STEP_ID_COLLISION" for issue in collision.issues)


def test_classifier_avoids_broad_substring_false_positives() -> None:
    docs = _normalized_docs(
        {
            "flow/compute_graph.yaml": {
                "compute_steps": [
                    {"id": "STEP_RESTORE", "name": "restore_state", "outputs": ["state"]},
                    {"id": "STEP_PAYLOAD", "name": "payload_update", "outputs": ["payload"]},
                    {"id": "STEP_DOWNLOAD", "name": "download_metadata", "outputs": ["meta"]},
                    {"id": "STEP_INDEX", "name": "index_map", "outputs": ["idx"]},
                    {"id": "STEP_BRANCHLESS", "name": "branchless_compute", "outputs": ["value"]},
                ]
            }
        }
    )
    steps = docs["flow/compute_graph.yaml"]["compute_steps"]
    assert {step["execution_unit"] for step in steps} == {"UNKNOWN"}
    assert all(step["confidence"] == "low" for step in steps)


def test_function_classification_uses_qualified_identity_and_ambiguous_simple_names() -> None:
    docs = _normalized_docs(
        {
            "flow/compute_graph.yaml": {
                "functions": [
                    {"name": "Helper", "file": "a.cpp", "class": "A", "calls": ["Mmad"]},
                    {"name": "Helper", "file": "b.cpp", "class": "B", "calls": ["AscendC::Exp"]},
                ],
                "compute_steps": [
                    {"id": "STEP_AMBIG", "calls": ["Helper"], "outputs": ["x"]},
                    {"id": "STEP_QUAL", "calls": ["Helper"], "outputs": ["y"], "source_location": {"file": "a.cpp", "class": "A"}},
                ],
            }
        }
    )
    steps = docs["flow/compute_graph.yaml"]["compute_steps"]
    ambiguous = _by_legacy_or_id(steps, "STEP_AMBIG")
    qualified = _by_legacy_or_id(steps, "STEP_QUAL")
    assert ambiguous["execution_unit"] == "UNKNOWN"
    assert any("AMBIGUOUS_CALLEE_CLASSIFICATION" in item for item in ambiguous["evidence"])
    assert qualified["execution_unit"] == "CUBE"


def test_non_flow_promotion_does_not_rewrite_flow_or_kernel_paths(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    flow_path = base / "flow" / "compute_graph.yaml"
    kernel_path = base / "kernel" / "paths.yaml"
    for rel in kb_compiler.PHASE_FILES["phase2"]:
        path = base / rel
        if rel in {"flow/compute_graph.yaml", "kernel/paths.yaml", "registry/evidence.yaml"}:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {"status": "not_applicable", "reason": "promotion scope regression", "evidence_refs": ["EV_PROMO"]},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    flow_path.write_text("version: 1\ncompute_steps:\n- id: CL_DEMO_LEGACY\n  name: Handle tensor\n", encoding="utf-8")
    kernel_path.write_text("version: 1\nkernel_paths:\n  path_a:\n    id: KPATH_A\n", encoding="utf-8")
    before_flow = flow_path.read_text(encoding="utf-8")
    before_kernel = kernel_path.read_text(encoding="utf-8")
    proposal = {
        "version": 1,
        "op_name": "DemoOp",
        "proposal_id": "PROP_EVIDENCE_ONLY",
        "producer": {"agent": "uo-host-extraction", "phase": "phase2"},
        "canonical_updates": [
            {
                "target": "registry/evidence.yaml",
                "section": "evidence",
                "merge_mode": "by_id",
                    "entries": [{"id": "EV_PROMO", "file": "op_host/foo.cpp", "lines": [1, 1], "symbol": "Foo", "kind": "source_span"}],
                }
            ],
        }
    p1 = base / "archive" / "proposals" / "evidence.yaml"
    p1.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")

    result = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[p1])

    assert result.promotion_report["status"] == "promoted"
    assert result.promotion_report["normalization"]["flow_artifacts"] == []
    assert "flow/compute_graph.yaml" not in result.promotion_report["changed_artifacts"]
    assert "kernel/paths.yaml" not in result.promotion_report["changed_artifacts"]
    assert flow_path.read_text(encoding="utf-8") == before_flow
    assert kernel_path.read_text(encoding="utf-8") == before_kernel


def test_compiler_detects_alias_conflict_and_dangling_evidence(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    (base / "registry" / "variables.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "variables": [
                    {
                        "id": "VAR_MASK_PRESENT",
                        "kind": "derived_variable",
                        "canonical_name": "mask_present",
                        "scope": "host",
                        "data_type": "bool",
                        "aliases": ["hasMask"],
                    },
                    {
                        "id": "VAR_OTHER_MASK",
                        "kind": "derived_variable",
                        "canonical_name": "other_mask",
                        "scope": "host",
                        "data_type": "bool",
                        "aliases": ["hasMask"],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (base / "cross_layer" / "input_to_tiling.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "relations": [
                    {
                        "id": "REL_MASK_TO_KEY",
                        "type": "implies",
                        "expression": {"op": "eq", "var": "VAR_MASK_PRESENT", "value": True},
                        "evidence_refs": ["EV_MISSING"],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = compile_kb(base, "DemoOp", write_outputs=True)

    codes = {issue.code for issue in result.issues}
    assert result.status == "fail"
    assert "ALIAS_CONFLICT" in codes
    assert "DANGLING_EVIDENCE_REF" in codes
    assert (base / "archive" / "runs" / "kb_compile_report.yaml").exists()


def test_update_plan_marks_v2_dependencies_stale() -> None:
    plan = _build_update_plan(
        {
            "status": "ok",
            "changed_files": ["op_kernel/foo_kernel.cpp", "op_host/foo_tiling.cpp"],
            "changed_symbols": ["Process", "SetTilingKey"],
        }
    )
    stale = _build_stale_artifacts(plan)

    invalidated = {
        item
        for values in plan["artifact_invalidations"].values()
        for item in values
    }
    stale_paths = {item["path"] for item in stale["stale_artifacts"]}
    assert "kernel/compile_model.yaml" in invalidated
    assert "cross_layer/tiling_to_kernel.yaml" in stale_paths
    assert "contracts/code_change.yaml" in stale_paths
    assert "phase4" in plan["phases_to_rerun"]
    assert plan["dependency_hash"]


def test_compiler_accepts_registry_evidence_line_formats(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    (base / "registry" / "variables.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "variables": [
                    {
                        "id": "VAR_ATTEN_MASK_PRESENT",
                        "kind": "derived_variable",
                        "canonical_name": "atten_mask_present",
                        "scope": "host",
                        "data_type": "bool",
                        "aliases": ["hasMask"],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (base / "registry" / "evidence.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "evidence": [
                    {
                        "id": "EV_HOST_017",
                        "file": "op_host/foo.cpp",
                        "lines": {"start": 10, "end": 12},
                        "symbol": "Foo",
                        "kind": "source_span",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (base / "cross_layer" / "input_to_tiling.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "relations": [
                    {
                        "id": "REL_MASK_TO_KEY",
                        "type": "implies",
                        "expression": {"op": "eq", "var": "VAR_ATTEN_MASK_PRESENT", "value": True},
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = compile_kb(base, "DemoOp", write_outputs=False)
    assert not any(issue.code == "BAD_EVIDENCE_LINES" for issue in result.issues)
    assert not any(issue.code == "DANGLING_EVIDENCE_REF" for issue in result.issues)


def test_proposal_promotion_success_and_deterministic(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    for rel in ("flow/compute_graph.yaml", "flow/dataflow.yaml"):
        (base / rel).write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "op_name": "DemoOp",
                    "status": "not_applicable",
                    "reason": "minimal promotion unit test",
                    "evidence_refs": ["EV_HOST_017"],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
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
                "target": "registry/symbols.yaml",
                "section": "symbols",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "SYM_HOST_FOO",
                        "kind": "function",
                        "canonical_name": "Foo",
                        "scope": "host",
                        "evidence_refs": ["EV_HOST_017"],
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
                        "kind": "derived_variable",
                        "canonical_name": "atten_mask_present",
                        "scope": "host",
                        "data_type": "bool",
                        "aliases": ["hasMask"],
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
            {
                "target": "tiling/key_space.yaml",
                "section": "fields",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "KEY_MASK_MODE",
                        "kind": "tiling_key_field",
                        "canonical_name": "mask_mode",
                        "scope": "tiling",
                        "domain": [0, 1],
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
            {
                "target": "tiling/constraints.yaml",
                "section": "relations",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "REL_MASK_CONSTRAINT",
                        "type": "implies",
                        "source_ids": ["VAR_ATTEN_MASK_PRESENT"],
                        "target_ids": ["KEY_MASK_MODE"],
                        "expression": {"op": "implies", "args": []},
                        "status": "confirmed",
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
            {
                "target": "cross_layer/input_to_tiling.yaml",
                "section": "relations",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "REL_MASK_TO_KEY",
                        "type": "implies",
                        "source_ids": ["VAR_ATTEN_MASK_PRESENT"],
                        "target_ids": ["KEY_MASK_MODE"],
                        "expression": {"op": "eq", "var": "VAR_ATTEN_MASK_PRESENT", "value": False},
                        "status": "confirmed",
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
        ],
        "unresolved": [],
        "conflicts": [],
    }
    p1 = base / "archive" / "proposals" / "host.yaml"
    p1.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")

    result1 = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[p1])
    result2 = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[p1])
    content_after_second = {
        rel: (base / rel).read_text(encoding="utf-8")
        for rel in ("registry/variables.yaml", "cross_layer/behavior_graph.yaml", "cross_layer/impact_graph.yaml")
    }
    result3 = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[p1])
    content_after_third = {
        rel: (base / rel).read_text(encoding="utf-8")
        for rel in ("registry/variables.yaml", "cross_layer/behavior_graph.yaml", "cross_layer/impact_graph.yaml")
    }

    assert not any(issue.code == "BAD_PROMOTION_TARGET" for issue in result1.issues)
    assert result1.promotion_report["status"] == "promoted"
    assert result2.promotion_report["status"] == "promoted"
    assert result3.promotion_report["status"] == "promoted"
    assert content_after_second == content_after_third
    variables = yaml.safe_load((base / "registry" / "variables.yaml").read_text(encoding="utf-8"))
    assert variables["variables"][0]["id"] == "VAR_ATTEN_MASK_PRESENT"


def test_promotion_rejects_bad_target_and_is_atomic(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    original = (base / "registry" / "variables.yaml").read_text(encoding="utf-8")
    proposal = {
        "version": 1,
        "op_name": "DemoOp",
        "proposal_id": "PROP_BAD",
        "producer": {"agent": "uo-host-extraction", "phase": "phase2"},
        "canonical_updates": [
            {
                "target": "../skills/bad.yaml",
                "section": "variables",
                "merge_mode": "by_id",
                "entries": [{"id": "VAR_BAD"}],
            }
        ],
    }
    p1 = base / "archive" / "proposals" / "bad.yaml"
    p1.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")
    result = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[p1])
    assert result.status == "fail"
    assert any(issue.code == "BAD_PROMOTION_TARGET" for issue in result.issues)
    assert (base / "registry" / "variables.yaml").read_text(encoding="utf-8") == original


def test_phase_validation_is_phase_aware(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    phase2 = validate_kb(base, "DemoOp", phase="phase2", write_outputs=False)
    assert not any(issue.artifact.startswith("kernel/") for issue in phase2.issues)
    phase5 = validate_kb(base, "DemoOp", phase="phase5", write_outputs=False)
    assert any(issue.code == "PLACEHOLDER_ARTIFACT" and issue.artifact.startswith("kernel/") for issue in phase5.issues)


def test_query_context_slice_variable_trace(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    (base / "registry" / "variables.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "variables": [
                    {
                        "id": "VAR_ATTEN_MASK_PRESENT",
                        "kind": "derived_variable",
                        "canonical_name": "atten_mask_present",
                        "scope": "host",
                        "data_type": "bool",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (base / "cross_layer" / "behavior_graph.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "nodes": [{"id": "VAR_ATTEN_MASK_PRESENT", "kind": "variable", "label": "mask"}],
                "edges": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    payload = export_context_slice(base, "DemoOp", "variable-trace", "VAR_ATTEN_MASK_PRESENT")
    assert payload["query"]["intent"] == "variable-trace"
    assert payload["entities"][0]["stable_id"] == "VAR_ATTEN_MASK_PRESENT"


def test_query_trace_requires_entity(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    with pytest.raises(ValueError) as exc:
        export_context_slice(base, "DemoOp", "variable-trace")
    assert "ENTITY_REQUIRED" in str(exc.value)


def test_transactional_write_rolls_back_existing_and_new_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "uo"
    (base / "registry").mkdir(parents=True)
    (base / "tiling").mkdir()
    (base / "registry" / "a.yaml").write_text("version: 1\nvalue: old_a\n", encoding="utf-8")
    (base / "tiling" / "b.yaml").write_text("version: 1\nvalue: old_b\n", encoding="utf-8")
    previous = {
        "registry/a.yaml": {"version": 1, "value": "old_a"},
        "tiling/b.yaml": {"version": 1, "value": "old_b"},
    }
    candidate = {
        "registry/a.yaml": {"version": 1, "value": "new_a"},
        "tiling/b.yaml": {"version": 1, "value": "new_b"},
        "tiling/new.yaml": {"version": 1, "value": "new"},
    }
    real_replace = kb_compiler.os.replace

    def fail_second_tmp_replace(src: object, dst: object) -> None:
        if str(src).endswith(".tmp") and str(dst).endswith("b.yaml"):
            raise OSError("injected replace failure")
        real_replace(src, dst)

    monkeypatch.setattr(kb_compiler.os, "replace", fail_second_tmp_replace)
    tx = kb_compiler._transactional_write_docs(base, candidate, previous)

    assert tx.transaction_status == "rolled_back"
    assert "registry/a.yaml" in tx.rolled_back_artifacts
    assert (base / "registry" / "a.yaml").read_text(encoding="utf-8") == "version: 1\nvalue: old_a\n"
    assert (base / "tiling" / "b.yaml").read_text(encoding="utf-8") == "version: 1\nvalue: old_b\n"
    assert not (base / "tiling" / "new.yaml").exists()


def test_entity_alias_validation_is_order_independent() -> None:
    docs = {
        "registry/aliases.yaml": {
            "version": 1,
            "aliases": [{"alias": "mask", "target_id": "VAR_MASK", "scope": "host"}],
        },
        "registry/variables.yaml": {
            "version": 1,
            "variables": [{"id": "VAR_MASK", "canonical_name": "atten_mask", "scope": "host"}],
        },
    }
    result = kb_compiler.CompileResult(op_name="DemoOp")
    index = kb_compiler.build_entity_index(docs, result)
    assert "VAR_MASK" in index
    assert "mask" in index["VAR_MASK"]["aliases"]
    assert not any(issue.code == "DANGLING_ALIAS" for issue in result.issues)


def test_behavior_graph_does_not_guess_direction() -> None:
    docs = {
        "registry/variables.yaml": {
            "version": 1,
            "variables": [
                {"id": "VAR_A", "canonical_name": "a"},
                {"id": "VAR_B", "canonical_name": "b"},
            ],
        },
        "cross_layer/input_to_tiling.yaml": {
            "version": 1,
            "relations": [{"id": "REL_A_B", "type": "affects", "expression": {"vars": ["VAR_A", "VAR_B"]}}],
        },
        "cross_layer/behavior_graph.yaml": {"version": 1, "nodes": [], "edges": []},
        "cross_layer/impact_graph.yaml": {"version": 1, "nodes": [], "edges": []},
    }
    result = kb_compiler.CompileResult(op_name="DemoOp")
    kb_compiler._build_graphs(docs, "DemoOp", result)
    behavior = docs["cross_layer/behavior_graph.yaml"]
    assert behavior["edges"] == []
    assert behavior["unresolved"][0]["reason"] == "relation_direction_missing"
    assert any(issue.code == "RELATION_DIRECTION_MISSING" for issue in result.issues)


def test_impact_graph_diamond_is_not_cycle_but_real_cycle_is() -> None:
    diamond_edges = {
        "ab": {"id": "REL_AB", "source_id": "VAR_A", "target_id": "VAR_B", "status": "proposed"},
        "ac": {"id": "REL_AC", "source_id": "VAR_A", "target_id": "VAR_C", "status": "proposed"},
        "bd": {"id": "REL_BD", "source_id": "VAR_B", "target_id": "VAR_D", "status": "proposed"},
        "cd": {"id": "REL_CD", "source_id": "VAR_C", "target_id": "VAR_D", "status": "proposed"},
    }
    impacts = kb_compiler._derive_impact_edges(diamond_edges)
    assert not any(edge["impact_kind"] == "cycle" for edge in impacts)
    shortest = [edge for edge in impacts if edge["source_id"] == "VAR_A" and edge["target_id"] == "VAR_D"]
    assert min(edge["depth"] for edge in shortest) == 2

    cycle_edges = {
        "ab": {"id": "REL_AB", "source_id": "VAR_A", "target_id": "VAR_B", "status": "proposed"},
        "ba": {"id": "REL_BA", "source_id": "VAR_B", "target_id": "VAR_A", "status": "proposed"},
    }
    cycle_impacts = kb_compiler._derive_impact_edges(cycle_edges)
    assert any(edge["impact_kind"] == "cycle" for edge in cycle_impacts)


def test_tilingdata_without_dependency_proof_reruns_kernel() -> None:
    plan = _build_update_plan(
        {
            "status": "ok",
            "changed_files": ["op_host/foo_tilingdata.cpp"],
            "changed_symbols": ["SetTilingData"],
        }
    )
    assert "kernel_impacted_by_tiling" in plan["impacted_areas"]
    assert "phase4" in plan["phases_to_rerun"]
    assert plan["stale_classification"]["safe_to_preserve"] == []
