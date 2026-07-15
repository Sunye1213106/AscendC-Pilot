from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from understand_operator._operator.artifacts import init_operator_contract_layout, operator_root
from understand_operator._operator.fact_hashes import step2_fact_hashes
from understand_operator._operator.spec import load_spec, spec_bundle_hash
from understand_operator.scripts.finalize_phase0 import finalize_phase0


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PLUGIN_ROOT / "skills" / "understand-operator"


def _run(script: str, *args: str, cwd: Path | None = None) -> None:
    result = subprocess_run(script, *args, cwd=cwd)
    assert result.returncode == 0, result.stderr or result.stdout


def subprocess_run(script: str, *args: str, cwd: Path | None = None):
    import subprocess

    return subprocess.run([sys.executable, str(SCRIPT_DIR / script), *args], cwd=cwd or PLUGIN_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "op_host").mkdir()
    (repo / "op_kernel").mkdir()
    (repo / "op_host" / "demo.cpp").write_text("void DemoOpHost() { int x = 1; TilingData tile; tile.v = x; }\n", encoding="utf-8")
    (repo / "op_kernel" / "demo.cpp").write_text("void DemoKernel() { TilingData tile; }\nDataCopy(dst, src, len);\n", encoding="utf-8")
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    manifest = yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["current_run_id"] = "UO_RUN_TEST"
    manifest["source"]["revision"] = "unknown"
    manifest["source"]["snapshot_id"] = "SOURCE_TEST"
    (root / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    phase0 = root / "runs" / "UO_RUN_TEST" / "phase0"
    phase0.mkdir(parents=True)
    _write_phase0_doc(phase0 / "context.yaml", "runs.context", {"source_revision": "unknown", "source_snapshot_id": "SOURCE_TEST", "spec_bundle_hash": spec_bundle_hash()})
    _write_phase0_doc(phase0 / "installed_skill_check.yaml", "runs.installed_skill_check", {"consistent": True})
    _write_phase0_doc(phase0 / "ignore_rules.yaml", "runs.ignore_rules", {"patterns": []})
    _write_phase0_doc(phase0 / "scope_scan.yaml", "runs.scope_scan", {"status": "complete"})
    _write_phase0_doc(
        phase0 / "semantic_enrichment.yaml",
        "runs.semantic_enrichment",
        {
            "status": "complete",
            "cbm_queries": [
                {
                    "tool": "search_graph",
                    "payload": {"name_pattern": ".*DemoOp.*"},
                    "result_summary": {"matches_count": 1},
                }
            ],
        },
    )
    _write_yaml(
        phase0 / "scope_review.yaml",
        {
            "version": 1,
            "artifact": {"type": "runs.scope_review", "schema_version": 1, "owner": "uo-orchestrator"},
            "snapshot": _snapshot(),
            "status": "decided",
            "decision": "continue",
            "approved_scope": {
                "initial_operator_files": [{"path": "op_host/demo.cpp"}],
                "dependency_files": [],
                "generated_files": [],
                "excluded_files": [],
                "uncertain_files": [],
            },
            "items": [
                {
                    "id": "OP_PHASE0_SCOPE_REVIEW",
                    "kind": "scope_review",
                    "status": "recorded",
                    "identity": {"gate": "macro_scope"},
                    "sources": [{"kind": "runtime", "path": "scope_review.yaml"}],
                }
            ],
            "relations": [],
            "unresolved": [],
        },
    )
    (root / "cbm" / "index_meta.json").write_text(
        json.dumps(
            {
                "repo_root": str(repo.resolve()),
                "op_name": "DemoOp",
                "cbm_project": "demo",
                "indexed_via": "mcp",
                "cbm_mode": "fast",
                "indexed_at": "2026-01-01T00:00:00+00:00",
                "project_confirmed": True,
            }
        ),
        encoding="utf-8",
    )
    code, messages = finalize_phase0(repo, "DemoOp")
    assert code == 0, messages
    return repo, root


def _snapshot() -> dict[str, str]:
    return {"run_id": "UO_RUN_TEST", "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _write_phase0_doc(path: Path, artifact_type: str, data: dict[str, Any]) -> None:
    _write_yaml(
        path,
        {
            "version": 1,
            "artifact": {"type": artifact_type, "schema_version": 1, "owner": "uo-orchestrator"},
            "snapshot": _snapshot(),
            "items": [
                {
                    "id": "OP_PHASE0_ITEM",
                    "kind": "phase0_item",
                    "status": "recorded",
                    "identity": {"artifact": artifact_type},
                    "sources": [{"kind": "runtime", "path": path.name}],
                    "data": data,
                }
            ],
            "relations": [],
            "unresolved": [],
        },
    )


def _candidate(path: Path, batch: dict[str, Any]) -> None:
    path.write_text(json.dumps(batch), encoding="utf-8")


def _loc() -> dict[str, Any]:
    return {"file": "op_host/demo.cpp", "symbol": "DemoOpHost", "start_line": 1, "end_line": 1, "anchor_kind": "definition"}


def _batch(target: dict[str, str], item: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 2,
        "task": {"run_id": "UO_RUN_TEST", "stage": "step1", "owner": "uo-boundary-agent", "task_id": "BOUNDARY"},
        "target": target,
        "items": [item],
        "relations": [],
        "unresolved": [],
    }


def _candidate_batch(target: dict[str, str], owner: str, stage: str, task_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"version": 2, "task": {"run_id": "UO_RUN_TEST", "stage": stage, "owner": owner, "task_id": task_id}, "target": target, "items": items, "relations": [], "unresolved": []}


def _unresolved_candidate(target: dict[str, str], owner: str, stage: str, task_id: str) -> dict[str, Any]:
    return {
        "version": 2,
        "task": {"run_id": "UO_RUN_TEST", "stage": stage, "owner": owner, "task_id": task_id},
        "target": target,
        "items": [],
        "relations": [],
        "unresolved": [
            {
                "local_id": f"unresolved_{task_id.lower()}",
                "category": "missing_external_source",
                "description": f"{task_id} has no additional source-backed fact in this minimal candidate E2E fixture",
                "related_refs": [],
                "source_locations": [_loc()],
            }
        ],
    }


def _compile_candidate(repo: Path, path: Path, batch: dict[str, Any]) -> None:
    _candidate(path, batch)
    _run("validate_candidate_batch.py", str(repo), "--op-name", "DemoOp", "--batch", str(path))
    _run("compile_candidate_facts.py", str(repo), "--op-name", "DemoOp", "--batch", str(path))


def _compile_phase2_phase3_unresolved_candidates(repo: Path, batch_dir: Path) -> None:
    phase2_targets = [
        ("host_variables", {"path": "facts/host.yaml", "section": "variables"}, "uo-host-extraction"),
        ("host_expressions", {"path": "facts/host.yaml", "section": "expressions"}, "uo-host-extraction"),
        ("host_control_flow", {"path": "facts/host.yaml", "section": "control_flow"}, "uo-host-extraction"),
        ("host_calls", {"path": "facts/host.yaml", "section": "calls"}, "uo-host-extraction"),
        ("host_tiling_key", {"path": "facts/host.yaml", "section": "tiling_key"}, "uo-host-extraction"),
        ("host_tiling_key_enumeration", {"path": "facts/host.yaml", "section": "tiling_key_enumeration"}, "uo-host-extraction"),
        ("host_tiling_key_constraints", {"path": "facts/host.yaml", "section": "tiling_key_constraints"}, "uo-host-extraction"),
        ("host_tilingdata_writes", {"path": "facts/host.yaml", "section": "tilingdata_writes"}, "uo-host-extraction"),
        ("compute_tensors", {"path": "facts/compute.yaml", "section": "tensors"}, "uo-flow-extraction"),
        ("compute_operations", {"path": "facts/compute.yaml", "section": "operations"}, "uo-flow-extraction"),
        ("compute_dataflow", {"path": "facts/compute.yaml", "section": "dataflow"}, "uo-flow-extraction"),
        ("compute_numerical", {"path": "facts/compute.yaml", "section": "numerical_semantics"}, "uo-flow-extraction"),
        ("kernel_entries", {"path": "facts/kernel/overview.yaml", "section": "entries"}, "uo-kernel-overview-agent"),
        ("kernel_functions", {"path": "facts/kernel/overview.yaml", "section": "functions"}, "uo-kernel-overview-agent"),
        ("kernel_call_graph", {"path": "facts/kernel/overview.yaml", "section": "call_graph"}, "uo-kernel-overview-agent"),
        ("kernel_frontier", {"path": "facts/kernel/overview.yaml", "section": "frontier"}, "uo-kernel-overview-agent"),
        ("kernel_resources", {"path": "facts/kernel/overview.yaml", "section": "global_resources"}, "uo-kernel-overview-agent"),
    ]
    phase3_targets = [
        ("slice_manifest", {"path": "facts/kernel/slice_manifest.yaml"}, "uo-kernel-slice-planner"),
        ("slice_interfaces", {"path": "facts/kernel/slice_interfaces.yaml"}, "uo-kernel-slice-planner"),
        *[(f"slice_{section}", {"path": "facts/kernel/slices/main.yaml", "section": section}, "uo-kernel-slice-agent") for section in ["variables", "expressions", "branches", "loops", "tilingdata_reads", "calls", "dataflow", "memory", "synchronization"]],
    ]
    for task_id, target, owner in phase2_targets:
        _compile_candidate(repo, batch_dir / f"{task_id}.json", _unresolved_candidate(target, owner, "step2", task_id.upper()))
    for task_id, target, owner in phase3_targets:
        _compile_candidate(repo, batch_dir / f"{task_id}.json", _unresolved_candidate(target, owner, "step3", task_id.upper()))


def _compile_minimal_phase2_phase3_candidates(repo: Path, batch_dir: Path) -> None:
    host_loc = _loc()
    kernel_loc = {"file": "op_kernel/demo.cpp", "symbol": "DemoKernel", "start_line": 1, "end_line": 1, "anchor_kind": "definition"}
    kernel_call_loc = {"file": "op_kernel/demo.cpp", "symbol": "DemoKernel", "start_line": 2, "end_line": 2, "anchor_kind": "call"}
    field_identity = {"qualified_struct_name": "TilingData", "field_name": "v"}
    batches = {
        "host_tiling_field.json": _candidate_batch({"path": "facts/host.yaml", "section": "tilingdata_writes"}, "uo-host-extraction", "step2", "HOST_FIELD", [
            {"local_id": "field", "kind": "tilingdata_field", "identity": field_identity, "fields": {"field_type": "uint32_t"}, "source_locations": [host_loc]},
        ]),
        "compute_op.json": _candidate_batch({"path": "facts/compute.yaml", "section": "operations"}, "uo-flow-extraction", "step2", "COMPUTE_OP", [{"local_id": "op", "kind": "compute_operation", "identity": {"compute_scope": "DemoKernel", "operation_type": "copy", "output_identity": "dst", "source_span": {"start_line": 2, "end_line": 2}}, "fields": {"semantic": {"operation_type": "copy", "formula": "dst=src"}, "input_tensor_refs": [], "output_tensor_refs": [], "execution": {"classification": "data_movement", "paths": [{"engine": "vector", "condition_refs": [], "api_refs": [], "architecture_variants": [], "dtype_conditions": [], "layout_conditions": [], "shape_conditions": [], "tiling_key_refs": []}]}}, "source_locations": [kernel_call_loc]}]),
        "kernel_entry.json": _candidate_batch({"path": "facts/kernel/overview.yaml", "section": "entries"}, "uo-kernel-overview-agent", "step2", "KERNEL_ENTRY", [{"local_id": "entry", "kind": "kernel_entry", "identity": {"qualified_entry_symbol": "DemoKernel", "signature": "void()", "discriminator": "generic"}, "fields": {"name": "DemoKernel", "file": "op_kernel/demo.cpp", "symbol": "DemoKernel", "entry_kind": "kernel_entry", "called_by_refs": [], "call_refs": [], "architecture_variant": "generic", "template_binding": "none"}, "source_locations": [kernel_loc]}]),
        "slice_manifest.json": _candidate_batch({"path": "facts/kernel/slice_manifest.yaml"}, "uo-kernel-slice-planner", "step3", "SLICE_MANIFEST", [{"local_id": "slice", "kind": "kernel_slice", "identity": {"kernel_entry_ref": "DemoKernel", "template_binding_signature": "generic", "structural_flow_signature": "read-call", "tilingdata_read_signature": "v", "output_signature": "dst"}, "fields": {"slice_id": "main", "functions": ["DemoKernel"], "primary_owner": "uo-kernel-slice-agent"}, "source_locations": []}]),
        "slice_memory.json": _candidate_batch({"path": "facts/kernel/slices/main.yaml", "section": "memory"}, "uo-kernel-slice-agent", "step3", "SLICE_MEMORY", [{"local_id": "mem", "kind": "memory_resource", "identity": {"source_file": "op_kernel/demo.cpp", "scope_symbol": "DemoKernel", "source_name": "tile", "declaration_span": {"start_line": 1, "end_line": 1}, "resource_kind": "local"}, "fields": {"resource_kind": "local", "allocation_site_ref": {"ref_type": "symbol", "kind": "kernel_entry", "qualified_symbol": "DemoKernel"}, "producer_refs": [], "consumer_refs": [], "lifetime_start_ref": {"ref_type": "symbol", "kind": "kernel_entry", "qualified_symbol": "DemoKernel"}, "lifetime_end_ref": {"ref_type": "symbol", "kind": "kernel_entry", "qualified_symbol": "DemoKernel"}, "reuse_refs": [], "queue_operation_refs": []}, "source_locations": [kernel_loc]}]),
    }
    for name, batch in batches.items():
        _compile_candidate(repo, batch_dir / name, batch)
    occupied = {
        ("facts/host.yaml", "tilingdata_writes"),
        ("facts/compute.yaml", "operations"),
        ("facts/kernel/overview.yaml", "entries"),
        ("facts/kernel/slices/main.yaml", "memory"),
        ("facts/kernel/slice_manifest.yaml", ""),
    }
    phase2_targets = [
        ("host_variables", {"path": "facts/host.yaml", "section": "variables"}, "uo-host-extraction"),
        ("host_expressions", {"path": "facts/host.yaml", "section": "expressions"}, "uo-host-extraction"),
        ("host_control_flow", {"path": "facts/host.yaml", "section": "control_flow"}, "uo-host-extraction"),
        ("host_calls", {"path": "facts/host.yaml", "section": "calls"}, "uo-host-extraction"),
        ("host_tiling_key", {"path": "facts/host.yaml", "section": "tiling_key"}, "uo-host-extraction"),
        ("host_tiling_key_enumeration", {"path": "facts/host.yaml", "section": "tiling_key_enumeration"}, "uo-host-extraction"),
        ("host_tiling_key_constraints", {"path": "facts/host.yaml", "section": "tiling_key_constraints"}, "uo-host-extraction"),
        ("compute_tensors", {"path": "facts/compute.yaml", "section": "tensors"}, "uo-flow-extraction"),
        ("compute_dataflow", {"path": "facts/compute.yaml", "section": "dataflow"}, "uo-flow-extraction"),
        ("compute_numerical", {"path": "facts/compute.yaml", "section": "numerical_semantics"}, "uo-flow-extraction"),
        ("kernel_functions", {"path": "facts/kernel/overview.yaml", "section": "functions"}, "uo-kernel-overview-agent"),
        ("kernel_call_graph", {"path": "facts/kernel/overview.yaml", "section": "call_graph"}, "uo-kernel-overview-agent"),
        ("kernel_frontier", {"path": "facts/kernel/overview.yaml", "section": "frontier"}, "uo-kernel-overview-agent"),
        ("kernel_resources", {"path": "facts/kernel/overview.yaml", "section": "global_resources"}, "uo-kernel-overview-agent"),
    ]
    phase3_targets = [
        ("slice_interfaces", {"path": "facts/kernel/slice_interfaces.yaml"}, "uo-kernel-slice-planner"),
        *[(f"slice_{section}", {"path": "facts/kernel/slices/main.yaml", "section": section}, "uo-kernel-slice-agent") for section in ["variables", "expressions", "branches", "loops", "tilingdata_reads", "calls", "dataflow", "synchronization"]],
    ]
    for task_id, target, owner in phase2_targets + phase3_targets:
        key = (target["path"], target.get("section", ""))
        if key not in occupied:
            _compile_candidate(repo, batch_dir / f"{task_id}.json", _unresolved_candidate(target, owner, "step3" if target["path"].startswith("facts/kernel/slice") else "step2", task_id.upper()))


def _unresolved_doc(artifact_type: str, owner: str, *, partition_sections: list[str] | None = None) -> dict[str, Any]:
    base = {"version": 1, "artifact": {"type": artifact_type, "schema_version": 1, "owner": owner}, "snapshot": _snapshot()}
    unresolved = [{"question": "minimal fixture placeholder", "reason": "not_applicable", "owner": owner}]
    if partition_sections:
        base["sections"] = {section: {"items": [], "relations": [], "unresolved": list(unresolved)} for section in partition_sections}
    else:
        base.update({"items": [], "relations": [], "unresolved": unresolved})
    return base


def _review_from_trigger(root: Path, step: str) -> None:
    trigger = yaml.safe_load((root / "checks" / step / "review_trigger.yaml").read_text(encoding="utf-8"))
    _write_yaml(
        root / "checks" / step / "review.yaml",
        {
            "version": 1,
            "artifact": {"type": f"checks.{step}.review", "schema_version": 1, "owner": f"uo-{step}-fact-review-agent" if step == "step3" else "uo-step2-fact-review-agent"},
            "snapshot": trigger["snapshot"],
            "status": "pass",
            "input_hashes": trigger["input_hashes"],
            "items": [],
            "relations": [],
            "unresolved": [],
            "blocking_findings": [],
            "warnings": [],
            "errors": [],
        },
    )


def _graph_review_from_trigger(root: Path, status: str = "pass") -> None:
    trigger = yaml.safe_load((root / "checks" / "graph_review_trigger.yaml").read_text(encoding="utf-8"))
    _write_yaml(root / "checks" / "graph_review.yaml", {"version": 1, "artifact": {"type": "checks.graph_review", "schema_version": 1, "owner": "uo-graph-review-agent"}, "snapshot": trigger["snapshot"], "status": status, "input_hashes": trigger["input_hashes"], "review_scope": {}, "sampled_nodes": [], "sampled_edges": [], "blocking_findings": [], "warnings": ["mock warning"] if status == "warn" else [], "observations": [], "items": [], "relations": [], "unresolved": []})


def _seed_phase2_and_phase3_placeholders(root: Path) -> None:
    _write_yaml(root / "facts" / "host.yaml", _unresolved_doc("host.partition", "uo-host-extraction", partition_sections=["variables", "expressions", "control_flow", "calls", "tiling_key", "tiling_key_enumeration", "tiling_key_constraints", "tilingdata_writes"]))
    _write_yaml(root / "facts" / "compute.yaml", _unresolved_doc("compute.partition", "uo-flow-extraction", partition_sections=["tensors", "operations", "dataflow", "numerical_semantics"]))
    _write_yaml(root / "facts" / "kernel" / "overview.yaml", _unresolved_doc("kernel.overview.partition", "uo-kernel-overview-agent", partition_sections=["entries", "functions", "call_graph", "frontier", "global_resources"]))
    _write_yaml(root / "facts" / "kernel" / "slice_manifest.yaml", _unresolved_doc("kernel.slice_manifest", "uo-kernel-slice-planner"))
    _write_yaml(root / "facts" / "kernel" / "slice_interfaces.yaml", _unresolved_doc("kernel.slice_interfaces", "uo-kernel-slice-planner"))
    _write_yaml(root / "facts" / "kernel" / "slices" / "main.yaml", _unresolved_doc("kernel.slice.partition", "uo-kernel-slice-agent", partition_sections=["variables", "expressions", "branches", "loops", "tilingdata_reads", "calls", "dataflow", "memory", "synchronization"]))


def _write_abstraction_rule(root: Path) -> str:
    nodes = yaml.safe_load((root / "graphs" / "raw" / "nodes.yaml").read_text(encoding="utf-8"))["nodes"]
    raw = nodes[0]
    rules = yaml.safe_load((root / "graphs" / "derived" / "abstraction_rules.yaml").read_text(encoding="utf-8"))
    rules["rules"] = [
        {
            "id": "ARULE_DEMO_MINIMAL",
            "reversible": True,
            "node_id": "DVIEW_DEMO_MINIMAL",
            "abstract_type": "minimal",
            "abstract_name": "Demo minimal",
            "raw_node_refs": [raw["id"]],
            "raw_edge_refs": [],
            "yaml_refs": [raw["detail_ref"]],
        }
    ]
    _write_yaml(root / "graphs" / "derived" / "abstraction_rules.yaml", rules)
    return "DVIEW_DEMO_MINIMAL"


def test_all_uo_init_script_entrypoints_exist() -> None:
    required = {
        "validate_candidate_batch.py",
        "compile_candidate_facts.py",
        "validate_fact_stage.py",
        "build_fact_registry.py",
        "evaluate_review_trigger.py",
        "build_query_index.py",
        "validate_spec_consistency.py",
    }
    assert required <= {path.name for path in SCRIPT_DIR.glob("*.py")}


def test_all_uo_init_script_entrypoints_support_help() -> None:
    assert subprocess_run("verify_required_scripts.py", "--plugin-root", str(PLUGIN_ROOT)).returncode == 0


def test_validation_failure_stops_before_review_trigger(tmp_path: Path) -> None:
    repo, root = _repo(tmp_path)
    _write_yaml(root / "facts" / "host.yaml", {"version": 1, "artifact": {"type": "host.partition", "schema_version": 1, "owner": "uo-host-extraction"}, "snapshot": _snapshot(), "sections": {}})
    result = subprocess_run("validate_fact_stage.py", str(repo), "--op-name", "DemoOp", "--stage", "step2", "--scope", "host", "--write-report")
    assert result.returncode != 0
    assert not (root / "checks" / "step2" / "review_trigger.yaml").exists()


def test_skipped_review_does_not_require_review_file(tmp_path: Path) -> None:
    repo, root = _repo(tmp_path)
    for name, artifact in [("host_validation", "host_validation"), ("compute_validation", "compute_validation"), ("kernel_overview_validation", "kernel_overview_validation")]:
        _write_yaml(root / "checks" / "step2" / f"{name}.yaml", {"version": 1, "artifact": {"type": f"checks.step2.{artifact}", "schema_version": 1, "owner": "facts-validator"}, "snapshot": _snapshot(), "status": "pass", "input_hashes": {}, "items": [], "relations": [], "unresolved": []})
    _run("evaluate_review_trigger.py", str(repo), "--op-name", "DemoOp", "--step", "step2")
    assert yaml.safe_load((root / "checks" / "step2" / "review_trigger.yaml").read_text(encoding="utf-8"))["status"] == "skipped"
    _run("write_step2_receipt.py", str(repo), "--op-name", "DemoOp")
    assert not (root / "checks" / "step2" / "review.yaml").exists()


def test_triggered_review_requires_matching_review(tmp_path: Path) -> None:
    repo, root = _repo(tmp_path)
    _seed_phase2_and_phase3_placeholders(root)
    input_hashes = step2_fact_hashes(root)
    for name, artifact in [("host_validation", "host_validation"), ("compute_validation", "compute_validation"), ("kernel_overview_validation", "kernel_overview_validation")]:
        _write_yaml(root / "checks" / "step2" / f"{name}.yaml", {"version": 1, "artifact": {"type": f"checks.step2.{artifact}", "schema_version": 1, "owner": "facts-validator"}, "snapshot": _snapshot(), "status": "pass", "input_hashes": input_hashes, "items": [], "relations": [], "unresolved": []})
    _run("evaluate_review_trigger.py", str(repo), "--op-name", "DemoOp", "--step", "step2")
    _write_yaml(root / "checks" / "step2" / "review.yaml", {"version": 1, "artifact": {"type": "checks.step2.review", "schema_version": 1, "owner": "uo-step2-fact-review-agent"}, "snapshot": _snapshot(), "status": "pass", "input_hashes": {"facts/bad.yaml": "sha256:bad"}, "items": [], "relations": [], "unresolved": [], "blocking_findings": [], "warnings": [], "errors": []})
    result = subprocess_run("write_step2_receipt.py", str(repo), "--op-name", "DemoOp")
    assert result.returncode != 0
    assert "review trigger" in result.stderr


def test_relation_kind_groups_are_all_defined() -> None:
    spec = load_spec()
    groups = set(spec["entity_types"]["kind_groups"])
    kinds = set(spec["entity_types"]["entity_types"])
    for name, rule in spec["relation_types"]["relation_types"].items():
        for endpoint in [rule, *rule.get("endpoint_signatures", [])]:
            assert endpoint["source"] in groups | kinds | {"any"}, name
            assert endpoint["target"] in groups | kinds | {"any"}, name


def test_callsite_calls_function_passes() -> None:
    spec = load_spec()["relation_types"]["relation_types"]["calls"]["endpoint_signatures"]
    assert {"source": "call_like", "target": "function_like"} in spec


def test_branch_has_outcome_passes() -> None:
    spec = load_spec()["relation_types"]["relation_types"]["has_outcome"]["endpoint_signatures"]
    assert {"source": "branch_like", "target": "branch_outcome_like"} in spec


def test_tilingdata_write_to_read_passes() -> None:
    spec = load_spec()["relation_types"]["relation_types"]["tilingdata_write_to_read"]["endpoint_signatures"]
    assert {"source": "tilingdata_write_like", "target": "tilingdata_read"} in spec


def test_step3_report_is_written_once() -> None:
    text = (PLUGIN_ROOT / "skills" / "uo-init" / "SKILL.md").read_text(encoding="utf-8")
    planner = 'validate_fact_stage.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step3 --scope kernel-slice-planner'
    final = 'validate_fact_stage.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --stage step3 --scope all --write-report'
    assert planner in text and planner + " --write-report" not in text
    assert text.count(final) == 1


def test_final_builds_sqlite_before_gate() -> None:
    text = (PLUGIN_ROOT / "skills" / "uo-init" / "SKILL.md").read_text(encoding="utf-8")
    assert text.index("build_query_index.py") < text.index("quality_gate.py")


def test_minimal_uo_init_entrypoint_e2e_reaches_final(tmp_path: Path) -> None:
    repo, root = _repo(tmp_path)
    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    batches = {
        "source.json": _batch({"path": "facts/operator/source_files.yaml"}, {"local_id": "src", "kind": "source_file", "identity": {"path": "op_host/demo.cpp"}, "fields": {"path": "op_host/demo.cpp", "role": "host", "include_reason": "minimal"}, "source_locations": [_loc()]}),
        "interface.json": _batch({"path": "facts/operator/interface.yaml"}, {"local_id": "x", "kind": "input_tensor", "identity": {"operator_name": "DemoOp", "direction": "input", "index": 0}, "fields": {"name": "x", "dtype": ["float16"], "layout": ["ND"], "rank": 1, "shape_symbols": ["N"]}, "source_locations": [_loc()]}),
        "entry.json": _batch({"path": "facts/operator/entrypoints.yaml"}, {"local_id": "entry", "kind": "host_entry", "identity": {"qualified_symbol": "DemoOpHost"}, "fields": {"name": "DemoOpHost", "file": "op_host/demo.cpp", "symbol": "DemoOpHost", "entry_kind": "host_entry"}, "source_locations": [_loc()]}),
    }
    for name, batch in batches.items():
        batch_path = batch_dir / name
        _candidate(batch_path, batch)
        _run("validate_candidate_batch.py", str(repo), "--op-name", "DemoOp", "--batch", str(batch_path))
        _run("compile_candidate_facts.py", str(repo), "--op-name", "DemoOp", "--batch", str(batch_path))
    _run("validate_fact_stage.py", str(repo), "--op-name", "DemoOp", "--stage", "step1", "--write-report")
    _compile_minimal_phase2_phase3_candidates(repo, batch_dir)
    for scope in ("host", "compute", "kernel-overview"):
        _run("validate_fact_stage.py", str(repo), "--op-name", "DemoOp", "--stage", "step2", "--scope", scope, "--write-report")
    _run("build_fact_registry.py", str(repo), "--op-name", "DemoOp")
    _run("evaluate_review_trigger.py", str(repo), "--op-name", "DemoOp", "--step", "step2")
    _review_from_trigger(root, "step2")
    _run("write_step2_receipt.py", str(repo), "--op-name", "DemoOp")
    _run("validate_fact_stage.py", str(repo), "--op-name", "DemoOp", "--stage", "step3", "--scope", "kernel-slice-planner")
    _run("validate_fact_stage.py", str(repo), "--op-name", "DemoOp", "--stage", "step3", "--scope", "all", "--write-report")
    _run("build_fact_registry.py", str(repo), "--op-name", "DemoOp")
    _run("evaluate_review_trigger.py", str(repo), "--op-name", "DemoOp", "--step", "step3")
    _review_from_trigger(root, "step3")
    _run("write_step3_receipt.py", str(repo), "--op-name", "DemoOp")
    _run("build_fact_registry.py", str(repo), "--op-name", "DemoOp")
    _run("validate_semantic_completeness.py", str(repo), "--op-name", "DemoOp")
    _run("build_compile_gate.py", str(repo), "--op-name", "DemoOp")
    _run("source_graph_compiler.py", str(repo), "--op-name", "DemoOp")
    _run("verify_raw_graph.py", str(repo), "--op-name", "DemoOp")
    _run("prepare_abstraction_rules.py", str(repo), "--op-name", "DemoOp")
    _write_abstraction_rule(root)
    _run("materialize_derived_graph.py", str(repo), "--op-name", "DemoOp")
    _run("verify_derived_graph.py", str(repo), "--op-name", "DemoOp")
    _run("prepare_graph_review.py", str(repo), "--op-name", "DemoOp")
    _graph_review_from_trigger(root)
    _run("validate_graph_review.py", str(repo), "--op-name", "DemoOp")
    _run("build_query_index.py", str(repo), "--op-name", "DemoOp")
    smoke = subprocess_run("uo_query_readonly.py", str(repo), "--op-name", "DemoOp", "--smoke")
    assert smoke.returncode == 0, smoke.stderr or smoke.stdout
    assert json.loads(smoke.stdout)["query"]["query_trace"] == ["terminology", "symbol_index", "derived", "raw", "yaml", "source"]
    _run("quality_gate.py", str(repo), "--op-name", "DemoOp")
    assert yaml.safe_load((root / "checks" / "final.yaml").read_text(encoding="utf-8"))["status"] == "pass"
    assert (root / "indexes" / "operator_kb.sqlite").exists()
    assert (root / "graphs" / "raw" / "nodes.yaml").exists()
    assert (root / "graphs" / "derived" / "nodes.yaml").exists()


def test_real_phase2_phase3_candidate_e2e_reaches_final(tmp_path: Path) -> None:
    repo, root = _repo(tmp_path)
    batch_dir = tmp_path / "candidate_e2e_batches"
    batch_dir.mkdir()
    for name, batch in {
        "source.json": _batch({"path": "facts/operator/source_files.yaml"}, {"local_id": "src", "kind": "source_file", "identity": {"path": "op_host/demo.cpp"}, "fields": {"path": "op_host/demo.cpp", "role": "host", "include_reason": "minimal"}, "source_locations": [_loc()]}),
        "interface.json": _batch({"path": "facts/operator/interface.yaml"}, {"local_id": "x", "kind": "input_tensor", "identity": {"operator_name": "DemoOp", "direction": "input", "index": 0}, "fields": {"name": "x", "dtype": ["float16"], "layout": ["ND"], "rank": 1, "shape_symbols": ["N"]}, "source_locations": [_loc()]}),
        "entry.json": _batch({"path": "facts/operator/entrypoints.yaml"}, {"local_id": "entry", "kind": "host_entry", "identity": {"qualified_symbol": "DemoOpHost"}, "fields": {"name": "DemoOpHost", "file": "op_host/demo.cpp", "symbol": "DemoOpHost", "entry_kind": "host_entry"}, "source_locations": [_loc()]}),
    }.items():
        _compile_candidate(repo, batch_dir / name, batch)
    _run("validate_fact_stage.py", str(repo), "--op-name", "DemoOp", "--stage", "step1", "--write-report")
    _compile_minimal_phase2_phase3_candidates(repo, batch_dir)
    for scope in ("host", "compute", "kernel-overview"):
        _run("validate_fact_stage.py", str(repo), "--op-name", "DemoOp", "--stage", "step2", "--scope", scope, "--write-report")
    _run("build_fact_registry.py", str(repo), "--op-name", "DemoOp")
    _run("evaluate_review_trigger.py", str(repo), "--op-name", "DemoOp", "--step", "step2")
    _review_from_trigger(root, "step2")
    _run("write_step2_receipt.py", str(repo), "--op-name", "DemoOp")
    _run("validate_fact_stage.py", str(repo), "--op-name", "DemoOp", "--stage", "step3", "--scope", "kernel-slice-planner")
    _run("validate_fact_stage.py", str(repo), "--op-name", "DemoOp", "--stage", "step3", "--scope", "all", "--write-report")
    _run("build_fact_registry.py", str(repo), "--op-name", "DemoOp")
    _run("evaluate_review_trigger.py", str(repo), "--op-name", "DemoOp", "--step", "step3")
    _review_from_trigger(root, "step3")
    _run("write_step3_receipt.py", str(repo), "--op-name", "DemoOp")
    _run("build_fact_registry.py", str(repo), "--op-name", "DemoOp")
    _run("validate_semantic_completeness.py", str(repo), "--op-name", "DemoOp")
    _run("build_compile_gate.py", str(repo), "--op-name", "DemoOp")
    _run("source_graph_compiler.py", str(repo), "--op-name", "DemoOp")
    _run("verify_raw_graph.py", str(repo), "--op-name", "DemoOp")
    _run("prepare_abstraction_rules.py", str(repo), "--op-name", "DemoOp")
    _write_abstraction_rule(root)
    _run("materialize_derived_graph.py", str(repo), "--op-name", "DemoOp")
    _run("verify_derived_graph.py", str(repo), "--op-name", "DemoOp")
    _run("prepare_graph_review.py", str(repo), "--op-name", "DemoOp")
    _graph_review_from_trigger(root)
    _run("validate_graph_review.py", str(repo), "--op-name", "DemoOp")
    _run("build_query_index.py", str(repo), "--op-name", "DemoOp")
    smoke = subprocess_run("uo_query_readonly.py", str(repo), "--op-name", "DemoOp", "--smoke")
    assert smoke.returncode == 0, smoke.stderr or smoke.stdout
    assert json.loads(smoke.stdout)["query"]["query_trace"] == ["terminology", "symbol_index", "derived", "raw", "yaml", "source"]
    _run("quality_gate.py", str(repo), "--op-name", "DemoOp")
    assert yaml.safe_load((root / "checks" / "final.yaml").read_text(encoding="utf-8"))["status"] == "pass"
    assert (root / "indexes" / "operator_kb.sqlite").exists()
    assert (root / "graphs" / "raw" / "nodes.yaml").exists()
    assert (root / "graphs" / "derived" / "nodes.yaml").exists()
