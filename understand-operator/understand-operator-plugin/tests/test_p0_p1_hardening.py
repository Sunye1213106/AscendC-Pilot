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
from understand_operator._operator.evidence import validate_evidence_closure
from understand_operator._operator.install_check import compare_installed_skill
from understand_operator._operator.kb_compiler import promote_kb, validate_kb
from understand_operator._operator.yaml_gate import (
    artifact_owner,
    allowed_canonical_writers,
    compare_semantic_summaries,
    semantic_summary,
    serialize_yaml_checked,
    syntax_only_repair,
    write_yaml_checked,
)
from understand_operator.scripts.kb_query_export import export_context_slice, export_view
from understand_operator.scripts.kb_query_export import main as kb_query_export_main
from understand_operator.scripts.macro_scope_scan import main as macro_scope_scan_main
from understand_operator.scripts.quality_gate import main as quality_gate_main
from understand_operator.scripts.update_operator import (
    _build_stale_artifacts,
    _build_update_plan,
    _tilingdata_numeric_only_proven,
)
from understand_operator.scripts.verify_subagent_barrier import (
    _id_contract_problems,
    _is_placeholder,
    _proposal_contract_problems,
    _semantic_contract_problems,
    _yaml_problem,
    verify_kernel_path_barrier,
)
from understand_operator.scripts.quality_gate import (
    _check_cross_layer_graph_completeness,
    _check_text_encoding,
    _has_compute_golden_mapping,
    _has_resource_flow,
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
        "tiling/exhaustive_key_space.yaml",
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


def test_read_only_tools_do_not_create_empty_kb_for_unknown_op(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    assert kb_query_export_main([str(repo), "--op-name", "fasg", "--view", "human"]) == 2
    assert quality_gate_main([str(repo), "--op-name", "fasg"]) == 2
    assert not (repo / ".understand-operator" / "fasg").exists()


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


def test_dispatch_variables_placeholder_check_matches_top_level_variables_only() -> None:
    complete_with_unknowns = """version: 1
status: analyzed

variables:
  - name: IsEmptyTensor
    kind: optional_io_gate

unknown_variables: []
"""
    empty_top_level_variables = """version: 1
status: analyzed

variables: []
unknown_variables: []
"""

    rel = "tiling/archive/dispatch_variables.yaml"
    assert _is_placeholder(rel, complete_with_unknowns) is False
    assert _is_placeholder(rel, empty_top_level_variables) is True


def test_exhaustive_key_space_placeholder_and_count_validation() -> None:
    rel = "tiling/exhaustive_key_space.yaml"
    assert _is_placeholder(rel, "version: 1\nstatus: pending\ntemplate_blocks: []\n") is True

    valid = """version: 1
status: analyzed
enumeration_source:
  files: [op_kernel/arch35/demo_template_tiling_key.h]
summary:
  block_count: 2
  expanded_key_count: 5
template_blocks:
  - id: KTPL_TILING_KEY_BLOCK_001
    field_domains: {IsDrop: [0, 1]}
    fixed_fields: {InputDType: 3}
    product_count: 2
  - id: KTPL_TILING_KEY_BLOCK_002
    field_domains: {DTemplateNum: [64, 128, 192]}
    fixed_fields: {InputDType: 2}
    product_count: 3
reverse_realization_index: {}
"""
    assert _semantic_contract_problems(rel, valid) == []

    invalid = valid.replace("expanded_key_count: 5", "expanded_key_count: 4")
    assert any("product sum=5" in problem for problem in _semantic_contract_problems(rel, invalid))


def test_exhaustive_key_space_not_applicable_requires_evidence() -> None:
    rel = "tiling/exhaustive_key_space.yaml"
    valid = """version: 1
status: not_applicable
reason: no template tiling key file
evidence_refs: [EV_HOST_017]
"""
    assert _semantic_contract_problems(rel, valid) == []
    invalid = "version: 1\nstatus: not_applicable\nreason: no template tiling key file\n"
    assert any("not_applicable requires" in problem for problem in _semantic_contract_problems(rel, invalid))


def test_barrier_rejects_invalid_or_non_mapping_yaml() -> None:
    rel = "tiling/archive/dispatch_variables.yaml"
    assert _yaml_problem(rel, "variables: [")
    assert _yaml_problem(rel, "- a\n- b\n") == "YAML root must be a mapping"
    assert _yaml_problem(rel, "variables:\n  - name: IsEmptyTensor\n") is None


def test_barrier_rejects_bad_stable_id_and_sp_evidence_ref() -> None:
    text = """branches:
  - id: BF001
    evidence_refs: [SP001]
"""
    problems = _id_contract_problems("kernel/branches.yaml", text)
    assert any("invalid stable id" in problem for problem in problems)
    assert any("invalid evidence ref" in problem for problem in problems)
    assert _id_contract_problems(
        "flow/compute_graph.yaml",
        "compute_steps:\n  COMP_MAIN:\n    id: COMP_MAIN\n    golden_step_ref: GOLD_MAIN\n",
    ) == []


def test_barrier_rejects_obsolete_proposal_update_fields() -> None:
    text = """version: 1
op_name: DemoOp
proposal_id: PROP_DEMO
producer: uo-host-extraction
canonical_updates:
  - target: tiling/variables.yaml
    section: variables
    mode: by_id
    items: []
"""
    problems = _proposal_contract_problems("archive/proposals/host_tiling_proposal.yaml", text)
    assert any("producer must be a mapping" in problem for problem in problems)

    text = text.replace("producer: uo-host-extraction", "producer: {agent: uo-host-extraction, phase: phase2}")
    problems = _proposal_contract_problems("archive/proposals/host_tiling_proposal.yaml", text)
    assert any("obsolete mode/items" in problem for problem in problems)
    assert any("missing evidence merge target" in problem for problem in problems)


def test_compiler_rejects_non_stable_evidence_ref(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    proposal = _minimal_proposal()
    proposal["canonical_updates"][1]["entries"][0]["evidence_refs"] = ["op_host/foo.cpp:10"]
    path = base / "archive" / "proposals" / "bad_evidence_ref.yaml"
    path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")

    result = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[path], run_id="bad_evidence_ref")

    assert any(issue.code == "BAD_EVIDENCE_REF_FORMAT" for issue in result.issues)


def test_syntax_only_repair_preserves_resource_scalars() -> None:
    text = '- name: "dqGm (KP_001)", direction: out, dtype: "T"\n'
    repaired, errors = syntax_only_repair(text, "kernel/resources.yaml", phase="kernel_path")

    assert repaired == text
    assert any(error.code == "YAML_ROOT_NOT_MAPPING" for error in errors)


def test_syntax_only_repair_accepts_complete_resources_mapping() -> None:
    text = """
buffers:
  - id: BUF_DQ_GM
    name: dqGm
    producer: gm
    consumer: compute
    condition: always
    direction: out
    dtype: T
    evidence_refs: [EV_RESOURCE]
workspaces: []
sync_events: []
resources: []
"""
    repaired, errors = syntax_only_repair(text, "kernel/resources.yaml", phase="kernel_path")

    assert errors == []
    after = yaml.safe_load(repaired)
    assert after["buffers"][0]["name"] == "dqGm"
    assert after["buffers"][0]["dtype"] == "T"


def test_semantic_summary_reports_condition_dropped() -> None:
    before = {
        "buffers": [
            {"id": "BUF_ROPE", "name": "rope", "producer": "P", "consumer": "C", "condition": "isRope"},
            {"id": "BUF_SINK", "name": "sink", "producer": "P", "consumer": "C", "condition": "isSink"},
            {"id": "BUF_PRE", "name": "pre", "producer": "P", "consumer": "C", "condition": "enablePreSfmg"},
        ]
    }
    after = copy.deepcopy(before)
    after["buffers"] = after["buffers"][:2]

    errors = compare_semantic_summaries(
        semantic_summary(before),
        semantic_summary(after),
        "kernel/resources.yaml",
        phase="kernel_path",
    )

    assert any(error.code in {"CONDITION_DROPPED", "SEMANTIC_DRIFT", "ENTRY_COUNT_CHANGED"} for error in errors)


def test_checked_yaml_blocks_direct_canonical_write_and_preserves_old_file(tmp_path: Path) -> None:
    path = tmp_path / "kernel" / "resources.yaml"
    path.parent.mkdir()
    path.write_text("version: 1\nresources: []\n", encoding="utf-8")

    with pytest.raises(PermissionError):
        write_yaml_checked(path, {"version": 1}, artifact="kernel/resources.yaml", writer="orchestrator")

    assert path.read_text(encoding="utf-8") == "version: 1\nresources: []\n"

    with pytest.raises(ValueError):
        write_yaml_checked(path, {"version": 1, "resources": ""}, artifact="kernel/resources.yaml", writer="promoter")

    assert path.read_text(encoding="utf-8") == "version: 1\nresources: []\n"


def test_orchestrator_proposal_cannot_write_owned_canonical(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    proposal = _minimal_proposal(
        proposal_id="PROP_ORCH_WRITE",
        producer={"agent": "orchestrator", "phase": "phase2"},
    )
    proposal["canonical_updates"][1]["target"] = "tiling/variables.yaml"
    proposal["canonical_updates"][1]["section"] = "variables"
    path = base / "archive" / "proposals" / "orchestrator.yaml"
    path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")

    result = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[path], run_id="run_orchestrator")

    assert result.status == "fail"
    assert any(issue.code == "CANONICAL_DIRECT_WRITE" for issue in result.issues)


def test_malformed_kernel_resources_routes_retry_to_kernel_owner(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    (base / "kernel" / "paths.yaml").write_text(
        yaml.safe_dump({"kernel_paths": [{"id": "KPATH_MAIN", "task_id": "TASK_1"}]}, sort_keys=False),
        encoding="utf-8",
    )
    (base / "kernel" / "pipeline.yaml").write_text(
        yaml.safe_dump(
            {
                "pipelines": {"KPATH_MAIN": {"stages": [{"id": "PIPE_LOAD"}]}},
                "stages": [{"id": "PIPE_LOAD"}],
                "resources": [],
                "compute_step_alignment": [{"id": "CL_TO_PIPE", "compute_step_id": "COMP_MAIN", "pipeline_stage_id": "PIPE_LOAD"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (base / "kernel" / "resources.yaml").write_text(
        '- name: "dqGm (KP_001)", direction: out, dtype: "T"\n',
        encoding="utf-8",
    )

    result = verify_kernel_path_barrier(base, ["TASK_1"])

    assert result.ok is False
    assert any(error.get("owner") == "uo-kernel-path" for error in result.errors or [])
    assert any(error.get("error_code") == "YAML_SYNTAX_ERROR" for error in result.errors or [])
    assert artifact_owner("kernel/resources.yaml") == "uo-kernel-path"
    assert "host-compiler" in allowed_canonical_writers("kernel/resources.yaml")
    assert "kb-promoter" in allowed_canonical_writers("kernel/resources.yaml")


def test_placeholder_registry_variables_fails_then_real_proposal_clears_placeholder(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    result = validate_kb(base, "DemoOp", phase="final", write_outputs=False)
    assert any(issue.code == "PLACEHOLDER_ARTIFACT" and issue.artifact == "registry/variables.yaml" for issue in result.issues)

    proposal = _minimal_proposal()
    path = base / "archive" / "proposals" / "registry_variable.yaml"
    path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")
    promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[path], run_id="registry_variable")

    result_after = validate_kb(base, "DemoOp", phase="phase2", write_outputs=False)
    assert not any(issue.code == "PLACEHOLDER_ARTIFACT" and issue.artifact == "registry/variables.yaml" for issue in result_after.issues)


def test_evidence_registry_closure_requires_registry_entry() -> None:
    docs = {
        "registry/evidence.yaml": {"evidence": []},
        "evidence/fact_index.yaml": {
            "facts": {"FACT_TILING": {"evidence_refs": ["EV_TILING_KEY_SETTER"], "source_locator": "op_host/foo.cpp:1"}},
            "evidence_refs": {"EV_TILING_KEY_SETTER": {"registry_ref": "EV_TILING_KEY_SETTER"}},
        },
        "evidence/source_index.yaml": {
            "source_spans": {"SRC_TILING_KEY_SETTER": {"registry_ref": "SRC_TILING_KEY_SETTER"}}
        },
    }
    issues = validate_evidence_closure(docs)
    assert {issue.code for issue in issues} >= {"DANGLING_EVIDENCE_REF", "EVIDENCE_REGISTRY_MISSING_ENTRY", "FACT_INDEX_REGISTRY_MISMATCH", "SOURCE_INDEX_REGISTRY_MISMATCH"}

    bad_source_docs = {
        "registry/evidence.yaml": {"evidence": []},
        "evidence/fact_index.yaml": {"facts": {}, "evidence_refs": {}},
        "evidence/source_index.yaml": {"source_spans": {"EV_BAD": {"registry_ref": "EV_BAD"}}},
    }
    bad_source_issues = validate_evidence_closure(bad_source_docs)
    assert any(issue.code == "SOURCE_INDEX_BAD_PREFIX" and issue.target == "EV_BAD" for issue in bad_source_issues)

    docs["registry/evidence.yaml"]["evidence"] = [
        {
            "id": "EV_TILING_KEY_SETTER",
            "file": "op_host/foo.cpp",
            "lines": [1, 3],
            "symbol": "SetTilingKey",
            "kind": "host_tiling",
            "status": "confirmed",
        },
        {
            "id": "SRC_TILING_KEY_SETTER",
            "file": "op_host/foo.cpp",
            "lines": [1, 3],
            "symbol": "SetTilingKey",
            "kind": "source_span",
            "status": "confirmed",
        },
    ]
    assert validate_evidence_closure(docs) == []


def test_quality_and_compiler_both_fail_dangling_evidence(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    (base / "evidence" / "fact_index.yaml").write_text(
        yaml.safe_dump(
            {
                "facts": {"FACT_BAD": {"evidence_refs": ["EV_MISSING"], "source_locator": "op_host/foo.cpp:1"}},
                "evidence_refs": {"EV_MISSING": {"registry_ref": "EV_MISSING"}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = validate_kb(base, "DemoOp", phase="final", write_outputs=False)
    assert any(issue.code in {"DANGLING_EVIDENCE_REF", "EVIDENCE_REGISTRY_MISSING_ENTRY"} for issue in result.issues)

    assert quality_gate_main([str(base.parents[1]), "--op-name", "DemoOp"]) == 2
    quality = yaml.safe_load((base / "quality.yaml").read_text(encoding="utf-8"))
    assert quality["checks"]["evidence_refs_resolve"] == "fail"
    assert quality["checks"]["kb_compiler_passed"] == "fail"
    queue = yaml.safe_load((base / "archive" / "runs" / "red_gate_repair_queue.yaml").read_text(encoding="utf-8"))
    assert queue["error_code"] == "RED_GATE_REMEDIATION_INCOMPLETE"
    assert queue["groups"]


def test_canonical_proposal_rejects_bad_and_intermediate_ids(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    proposal = _minimal_proposal(proposal_id="PROP_BAD_IDS")
    proposal["canonical_updates"].extend(
        [
            {
                "target": "registry/evidence.yaml",
                "section": "evidence",
                "merge_mode": "by_id",
                "entries": [{"id": "EV_T_host_entry", "file": "op_host/foo.cpp", "lines": [1], "symbol": "Foo", "kind": "source_span"}],
            },
        ]
    )
    proposal["canonical_updates"].append(
        {
            "target": "tiling/families.yaml",
            "section": "families",
            "merge_mode": "by_id",
            "entries": [{"id": "TF_MAIN"}],
        }
    )
    proposal["canonical_updates"].append(
        {
            "target": "tiling/constraints.yaml",
            "section": "relations",
            "merge_mode": "by_id",
            "entries": [{"id": "FRO_001", "type": "implies"}],
        }
    )
    path = base / "archive" / "proposals" / "bad_ids.yaml"
    path.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")

    result = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[path], run_id="bad_ids")

    assert result.status == "fail"
    assert any(issue.code == "BAD_STABLE_ID" and issue.target == "EV_T_host_entry" for issue in result.issues)
    assert any(issue.code == "BAD_STABLE_ID" and issue.target == "TF_MAIN" for issue in result.issues)
    assert any(issue.code == "INTERMEDIATE_ID_IN_CANONICAL" and issue.target == "FRO_001" for issue in result.issues)


def test_structured_id_migration_updates_refs_without_rewriting_prose() -> None:
    docs = {
        "tiling/families.yaml": {
            "families": [{"id": "TF_MAIN", "description": "Do not rewrite prose TF_MAIN"}],
        },
        "kernel/paths.yaml": {
            "kernel_paths": [{"id": "KPATH_MAIN", "source_family": "TF_MAIN", "notes": "source excerpt mentions TF_MAIN"}],
        },
        "contracts/testcase.yaml": {
            "coverage_obligations": {"families": [{"id": "COV_MAIN", "family_id": "TF_MAIN"}]},
        },
    }
    result = kb_compiler.CompileResult(op_name="DemoOp")
    migrated = kb_compiler.migrate_stable_ids(
        docs,
        [{"old_id": "TF_MAIN", "new_id": "FAM_MAIN", "kind": "family", "reason": "canonical namespace migration"}],
        result,
    )

    assert migrated["tiling/families.yaml"]["families"][0]["id"] == "FAM_MAIN"
    assert migrated["tiling/families.yaml"]["families"][0]["legacy_ids"] == ["TF_MAIN"]
    assert migrated["kernel/paths.yaml"]["kernel_paths"][0]["source_family"] == "FAM_MAIN"
    assert migrated["kernel/paths.yaml"]["kernel_paths"][0]["notes"] == "source excerpt mentions TF_MAIN"
    assert migrated["contracts/testcase.yaml"]["coverage_obligations"]["families"][0]["family_id"] == "FAM_MAIN"


def test_structured_id_migration_renames_id_keyed_mapping_without_rewriting_prose() -> None:
    docs = {
        "tiling/families.yaml": {
            "families": {
                "TF_MAIN": {
                    "id": "TF_MAIN",
                    "description": "prose mentions TF_MAIN",
                }
            }
        }
    }
    result = kb_compiler.CompileResult(op_name="DemoOp", phase="phase2")

    migrated = kb_compiler.migrate_stable_ids(
        docs,
        [{"old_id": "TF_MAIN", "new_id": "FAM_MAIN", "kind": "family"}],
        result,
    )

    assert "FAM_MAIN" in migrated["tiling/families.yaml"]["families"]
    family = migrated["tiling/families.yaml"]["families"]["FAM_MAIN"]
    assert family["id"] == "FAM_MAIN"
    assert family["legacy_ids"] == ["TF_MAIN"]
    assert family["description"] == "prose mentions TF_MAIN"


def test_structured_id_migration_rejects_kind_prefix_mismatch() -> None:
    docs = {"tiling/families.yaml": {"families": [{"id": "TF_MAIN"}]}}
    result = kb_compiler.CompileResult(op_name="DemoOp", phase="phase2")

    kb_compiler.migrate_stable_ids(
        docs,
        [{"old_id": "TF_MAIN", "new_id": "VAR_MAIN", "kind": "family"}],
        result,
    )

    assert any(issue.code == "BAD_ID_MIGRATION_KIND" for issue in result.issues)


def test_unicode_yaml_round_trip_preserves_math_symbols() -> None:
    data = {"expression": "A → B, x ∈ [0, 10), a ≠ b, y ≥ 0"}
    text, errors = serialize_yaml_checked("scratch.yaml", data)
    assert errors == []
    loaded = yaml.safe_load(text)
    assert loaded["expression"] == data["expression"]
    assert "->" not in text
    assert " in " not in text


def test_installed_skill_version_mismatch_reports(tmp_path: Path) -> None:
    repo_plugin = tmp_path / "repo_plugin"
    installed = tmp_path / "skills" / "understand-operator"
    (repo_plugin / "skills" / "understand-operator").mkdir(parents=True)
    (repo_plugin / "understand_operator" / "_operator").mkdir(parents=True)
    (repo_plugin / "prompts").mkdir()
    installed.mkdir(parents=True)
    (installed.parent / "understand-operator-plugin" / "understand_operator" / "_operator").mkdir(parents=True)
    (installed.parent / "understand-operator-plugin" / "prompts").mkdir(parents=True)
    for rel in (
        "skills/understand-operator/quality_gate.py",
        "skills/understand-operator/prepare_operator.py",
        "skills/understand-operator/verify_subagent_barrier.py",
        "skills/understand-operator/SKILL.md",
        "understand_operator/_operator/kb_compiler.py",
        "prompts/08_evidence_consistency_agent.md",
        "prompts/10_quality_gate_agent.md",
    ):
        repo_path = repo_plugin / rel
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        repo_path.write_text("repo", encoding="utf-8")
    (installed / "quality_gate.py").write_text("installed-old", encoding="utf-8")

    report = compare_installed_skill(repo_plugin, installed)

    assert report["consistent"] is False
    assert report["error_code"] == "INSTALLED_SKILL_VERSION_MISMATCH"


def _minimal_proposal(**overrides: object) -> dict:
    proposal = {
        "version": 1,
        "op_name": "DemoOp",
        "proposal_id": "PROP_HOST_001",
        "producer": {"agent": "kb-promoter", "phase": "phase2"},
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
    view = export_view(base, "DemoOp", "testcase-contract")
    assert set(view["files"]) == {
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


def test_barrier_rejects_wrong_tiling_shape_but_accepts_shared_relation_types() -> None:
    bad_variables = yaml.safe_dump(
        {
            "variables": [{"id": "VAR_X"}],
            "tiling_mechanism": {"entry": "Foo"},
            "impact_classification": {"tiling_key": ["VAR_X"]},
        }
    )
    assert any("non-empty mapping" in item for item in _semantic_contract_problems("tiling/variables.yaml", bad_variables))

    constraints = yaml.safe_dump(
        {
            "relations": [
                {"id": "REL_X", "type": "determines", "expr": "A determines B", "case_impact": "narrow_domain"}
            ],
            "tiling_key_pruning": {"performed": False},
            "tiling_key_merging": {"performed": "unknown"},
        }
    )
    assert _semantic_contract_problems("tiling/constraints.yaml", constraints) == []


def test_quality_rejects_short_cross_layer_graph_and_constant_dispatch_conflict(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    (base / "tiling" / "variables.yaml").write_text(
        yaml.safe_dump(
            {
                "variables": {
                    "splitAxis": {"kind": "hard_dispatch"},
                    "inputDtype": {"kind": "hard_dispatch"},
                    "isEmptyTensor": {"kind": "constant", "value": False},
                },
                "tiling_mechanism": {"entry_function": "DoTiling"},
                "impact_classification": {
                    "dispatch": ["splitAxis", "isEmptyTensor"],
                    "constant": ["isEmptyTensor"],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (base / "cross_layer" / "behavior_graph.yaml").write_text(
        yaml.safe_dump({"version": 2, "nodes": [{"id": "PIPE_EMPTY"}], "edges": []}),
        encoding="utf-8",
    )
    (base / "cross_layer" / "impact_graph.yaml").write_text(
        yaml.safe_dump({"version": 2, "nodes": [{"id": "VAR_LAYOUT"}], "edges": [], "impacts": []}),
        encoding="utf-8",
    )
    warnings: list[str] = []
    blockers: list[str] = []
    checks = _check_cross_layer_graph_completeness(base, warnings, blockers)
    assert checks["cross_layer_graph_schema"] == "fail"
    assert checks["cross_layer_graph_coverage"] == "fail"
    assert any("not generated by deterministic graph builder" in item for item in blockers)
    assert any("constant and non-constant" in item for item in blockers)


def test_quality_warns_on_mojibake_markers(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    (base / "tiling" / "decision_tree.md").write_text("A 鈫? B\n", encoding="utf-8")
    warnings: list[str] = []
    checks = _check_text_encoding(base, warnings)
    assert checks["canonical_text_encoding"] == "warn"
    assert any("possible mojibake" in item for item in warnings)


def test_structured_golden_and_kernel_resource_checks() -> None:
    assert _has_compute_golden_mapping(
        {"compute_steps": {"COV_COMPUTE_X": {"golden_step_ref": "GOLDEN_X"}}},
        {"golden_outputs": {}},
    )
    assert not _has_compute_golden_mapping({"compute_steps": {"COV_COMPUTE_X": {}}}, {})
    assert _has_resource_flow(
        {
            "buffers": {"BUF_X": {"producer": "PIPE_LOAD", "consumer": "PIPE_COMPUTE"}},
            "sync_events": {"SYNC_X": {"from": "PIPE_LOAD", "to": "PIPE_COMPUTE"}},
        }
    )
    assert not _has_resource_flow(
        {"buffers": {"BUF_X": {"producer": "PIPE_LOAD"}}, "sync_events": {"SYNC_X": {}}}
    )


def test_entity_default_scope_separates_tiling_and_kernel_names() -> None:
    docs = {
        "tiling/key_space.yaml": {
            "fields": {"KEY_BLOCK_SIZE": {"id": "KEY_BLOCK_SIZE", "canonical_name": "block_size"}}
        },
        "kernel/compile_model.yaml": {
            "template_bindings": {
                "KTPL_BLOCK_SIZE": {"id": "KTPL_BLOCK_SIZE", "canonical_name": "block_size"}
            }
        },
    }
    result = kb_compiler.CompileResult(op_name="DemoOp")
    index = kb_compiler.collect_entity_definitions(docs, result)
    kb_compiler.validate_entity_references(docs, index, result)
    assert index["KEY_BLOCK_SIZE"]["scope"] == "tiling"
    assert index["KTPL_BLOCK_SIZE"]["scope"] == "kernel"
    assert not any(issue.code == "DUPLICATE_CANONICAL_NAME" for issue in result.issues)
