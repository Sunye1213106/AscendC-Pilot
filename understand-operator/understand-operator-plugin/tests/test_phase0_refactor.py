from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from understand_operator._operator.artifacts import init_operator_contract_layout, operator_root
from understand_operator._operator.spec import load_spec, spec_bundle_hash
from understand_operator.scripts.finalize_phase0 import finalize_phase0
from understand_operator.scripts.macro_scope_scan import main as macro_scope_scan_main
from understand_operator._operator.cbm_metadata import write_index_meta
from understand_operator.scripts.prepare_operator import _current_scope_meta
from understand_operator.scripts.prepare_fact_file import prepare_fact_file
from understand_operator.scripts.review_checkpoint import main as review_checkpoint_main
from understand_operator.scripts.source_graph_compiler import compile_source_graph
from understand_operator.scripts.build_compile_gate import facts_hashes_for
from understand_operator.scripts.uo_query_readonly import query_readonly
from understand_operator.scripts.validate_facts import validate_facts


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _repo(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = operator_root(repo, "DemoOp")
    init_operator_contract_layout(base, "DemoOp", repo)
    run_id = "UO_RUN_TEST"
    manifest = yaml.safe_load((base / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["current_run_id"] = run_id
    manifest["source"]["revision"] = "unknown"
    manifest["source"]["snapshot_id"] = "SOURCE_TEST"
    (base / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    phase0 = base / "runs" / run_id / "phase0"
    phase0.mkdir(parents=True)
    _write_phase0_doc(phase0 / "context.yaml", "runs.context", {"source_revision": "unknown", "source_snapshot_id": "SOURCE_TEST", "spec_bundle_hash": spec_bundle_hash()})
    _write_phase0_doc(phase0 / "installed_skill_check.yaml", "runs.installed_skill_check", {"consistent": True})
    _write_phase0_doc(
        phase0 / "semantic_enrichment.yaml",
        "runs.semantic_enrichment",
        {
            "status": "complete",
            "architecture_filter": {"included": [], "excluded": []},
            "cbm_queries": [
                {
                    "tool": "search_graph",
                    "payload": {"name_pattern": ".*DemoOp.*"},
                    "candidate": {"symbol": "DemoOpHost", "file": "op_host/demo.cpp"},
                    "result_summary": {"matches_count": 1},
                    "confidence": "medium",
                    "fallback_used": False,
                }
            ],
            "architecture_variants": [],
            "excluded_architectures": [],
            "confirmed_scope_additions": [],
            "unresolved": [],
            "warnings": [],
            "fallback": "",
        },
    )
    (base / "cbm" / "index_meta.json").write_text(
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
    return repo, base, run_id


def _write_phase0_doc(path: Path, artifact_type: str, data: dict) -> None:
    _write_yaml(
        path,
        {
            "version": 1,
            "artifact": {"type": artifact_type, "schema_version": 1, "owner": "uo-orchestrator"},
            "snapshot": {"run_id": "UO_RUN_TEST", "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()},
            **data,
        },
    )


def _hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_anchor() -> dict:
    text = "void DemoOpHost() {}"
    return {
        "id": "SRC_DEMO_HOST",
        "file": "op_host/demo.cpp",
        "symbol": "DemoOpHost",
        "span": {"start_line": 1, "end_line": 1},
        "source_text": text,
        "code_hash": _hash_text(text),
        "anchor_kind": "definition",
    }


def test_macro_scope_scan_writes_phase0_and_dependency_closure(tmp_path: Path) -> None:
    repo, base, run_id = _repo(tmp_path)
    (repo / "op_host").mkdir()
    (repo / "common").mkdir()
    (repo / "tools").mkdir()
    (repo / "op_host" / "demo.cpp").write_text('#include "../common/shared.h"\n#include <vector>\nREGISTER_TILING(DemoOp)\n', encoding="utf-8")
    (repo / "common" / "shared.h").write_text("// shared\n", encoding="utf-8")
    (repo / "op_host" / "helper.py").write_text("import tools.shared_py\n", encoding="utf-8")
    (repo / "tools" / "shared_py.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert macro_scope_scan_main([str(repo), "--op-name", "DemoOp"]) == 0

    new_path = base / "runs" / run_id / "phase0" / "scope_scan.yaml"
    assert new_path.exists()
    assert not (base / "archive" / "runs" / "macro_scope_scan.yaml").exists()
    scan = yaml.safe_load(new_path.read_text(encoding="utf-8"))
    deps = {item["path"] for item in scan["files"]["dependency_files"]}
    assert "common/shared.h" in deps
    assert "tools/shared_py.py" in deps
    assert "vector" in {item["path"] for item in scan["files"]["external_system_files"]}
    assert "vector" not in deps


def test_operator_dir_scope_includes_sibling_common_arch35_and_cbm_meta(tmp_path: Path) -> None:
    workspace = tmp_path / "FAG_test"
    op_dir = workspace / "flash_attention_score_grad"
    common_arch = workspace / "common" / "op_kernel" / "arch35"
    op_dir.mkdir(parents=True)
    common_arch.mkdir(parents=True)
    base = operator_root(op_dir, "flash_attention_score_grad")
    init_operator_contract_layout(base, "flash_attention_score_grad", op_dir)
    run_id = "UO_RUN_TEST"
    manifest = yaml.safe_load((base / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["current_run_id"] = run_id
    manifest["source"]["revision"] = "unknown"
    manifest["source"]["snapshot_id"] = "SOURCE_TEST"
    (base / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    phase0 = base / "runs" / run_id / "phase0"
    phase0.mkdir(parents=True)
    _write_phase0_doc(phase0 / "context.yaml", "runs.context", {"source_revision": "unknown", "source_snapshot_id": "SOURCE_TEST", "spec_bundle_hash": spec_bundle_hash()})
    _write_phase0_doc(phase0 / "installed_skill_check.yaml", "runs.installed_skill_check", {"consistent": True})
    (op_dir / "op_kernel.cpp").write_text('#include "common/op_kernel/arch35/fag_arch35.h"\n__global__ void Kernel() {}\n', encoding="utf-8")
    (common_arch / "fag_arch35.h").write_text("#pragma once\n#define ARCH35_KERNEL 1\n", encoding="utf-8")

    assert macro_scope_scan_main([str(op_dir), "--op-name", "flash_attention_score_grad"]) == 0
    scan = yaml.safe_load((phase0 / "scope_scan.yaml").read_text(encoding="utf-8"))
    deps = {item["path"] for item in scan["files"]["dependency_files"]}
    roots = {item["path"] for item in scan["scope_roots"]}
    assert "common/op_kernel/arch35/fag_arch35.h" in deps
    assert "flash_attention_score_grad" in roots
    assert "common/op_kernel/arch35" in roots

    scope_meta = _current_scope_meta(base)
    write_index_meta(
        base,
        {
            "repo_root": str(op_dir),
            "op_name": "flash_attention_score_grad",
            "cbm_project": "demo",
            "indexed_via": "mcp",
            "indexed_scope_roots": scope_meta["scope_roots"],
            "dependency_roots": scope_meta["dependency_roots"],
            "scope_hash": scope_meta["scope_hash"],
            "cbm_status": {"available": True, "retry_count": 0, "fallback": "", "last_error": ""},
        },
    )
    meta = json.loads((base / "cbm" / "index_meta.json").read_text(encoding="utf-8"))
    meta_roots = {item["path"] for item in meta["indexed_scope_roots"]}
    assert "flash_attention_score_grad" in meta_roots
    assert "common/op_kernel/arch35" in meta_roots
    assert meta["cbm_status"]["available"] is True


def test_operator_dir_scope_resolves_relative_parent_common_include(tmp_path: Path) -> None:
    workspace = tmp_path / "FAG_test"
    op_dir = workspace / "flash_attention_score_grad"
    kernel_dir = op_dir / "op_kernel" / "arch35"
    common_arch = workspace / "common" / "op_kernel" / "arch35"
    kernel_dir.mkdir(parents=True)
    common_arch.mkdir(parents=True)
    base = operator_root(op_dir, "flash_attention_score_grad")
    init_operator_contract_layout(base, "flash_attention_score_grad", op_dir)
    run_id = "UO_RUN_TEST"
    manifest = yaml.safe_load((base / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["current_run_id"] = run_id
    manifest["source"]["revision"] = "unknown"
    manifest["source"]["snapshot_id"] = "SOURCE_TEST"
    (base / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    phase0 = base / "runs" / run_id / "phase0"
    phase0.mkdir(parents=True)
    _write_phase0_doc(phase0 / "context.yaml", "runs.context", {"source_revision": "unknown", "source_snapshot_id": "SOURCE_TEST", "spec_bundle_hash": spec_bundle_hash()})
    _write_phase0_doc(phase0 / "installed_skill_check.yaml", "runs.installed_skill_check", {"consistent": True})
    (kernel_dir / "fag_kernel.h").write_text('#include "../../../common/op_kernel/arch35/util_regbase.h"\n__global__ void Kernel() {}\n', encoding="utf-8")
    (common_arch / "util_regbase.h").write_text("#pragma once\n#define UTIL_REGBASE 1\n", encoding="utf-8")

    assert macro_scope_scan_main([str(op_dir), "--op-name", "flash_attention_score_grad"]) == 0
    scan = yaml.safe_load((phase0 / "scope_scan.yaml").read_text(encoding="utf-8"))
    deps = {item["path"] for item in scan["files"]["dependency_files"]}
    roots = {item["path"] for item in scan["scope_roots"]}
    assert scan["project_root"].replace("\\", "/").endswith("FAG_test")
    assert scan["operator_path"] == "flash_attention_score_grad"
    assert "common/op_kernel/arch35/util_regbase.h" in deps
    assert "common/op_kernel/arch35" in roots


def test_scope_review_continue_does_not_write_pass_receipt(tmp_path: Path) -> None:
    repo, base, run_id = _repo(tmp_path)
    (repo / "op_host").mkdir()
    (repo / "op_host" / "demo.cpp").write_text("REGISTER_TILING(DemoOp)\n", encoding="utf-8")
    assert macro_scope_scan_main([str(repo), "--op-name", "DemoOp"]) == 0

    assert review_checkpoint_main([str(repo), "--op-name", "DemoOp", "--gate", "macro_scope", "--decision", "continue"]) == 0

    review = yaml.safe_load((base / "runs" / run_id / "phase0" / "scope_review.yaml").read_text(encoding="utf-8"))
    assert review["decision"] == "continue"
    receipt = base / "runs" / run_id / "phase0" / "receipt.yaml"
    assert not receipt.exists() or yaml.safe_load(receipt.read_text(encoding="utf-8")).get("status") != "pass"


def test_prepare_fact_file_requires_finalized_phase0(tmp_path: Path) -> None:
    repo, _base, _run_id = _repo(tmp_path)

    with pytest.raises(SystemExit, match="PHASE0_NOT_FINALIZED"):
        prepare_fact_file(repo, "DemoOp", "facts/operator/interface.yaml")


def test_prepare_fact_file_uses_finalized_phase0_snapshot(tmp_path: Path) -> None:
    repo, base, run_id = _repo(tmp_path)
    (repo / "op_host").mkdir()
    (repo / "op_host" / "demo.cpp").write_text("REGISTER_TILING(DemoOp)\n", encoding="utf-8")
    assert macro_scope_scan_main([str(repo), "--op-name", "DemoOp"]) == 0
    assert review_checkpoint_main([str(repo), "--op-name", "DemoOp", "--gate", "macro_scope", "--decision", "continue"]) == 0
    assert finalize_phase0(repo, "DemoOp")[0] == 0

    target = prepare_fact_file(repo, "DemoOp", "facts/operator/interface.yaml")

    doc = yaml.safe_load(target.read_text(encoding="utf-8"))
    receipt = yaml.safe_load((base / "runs" / run_id / "phase0" / "receipt.yaml").read_text(encoding="utf-8"))
    assert doc["snapshot"] == receipt["snapshot"]


def test_finalize_phase0_writes_receipt_and_revision_change_invalidates_validation(tmp_path: Path) -> None:
    repo, base, run_id = _repo(tmp_path)
    (repo / "op_host").mkdir()
    (repo / "op_host" / "demo.cpp").write_text("REGISTER_TILING(DemoOp)\n", encoding="utf-8")
    assert macro_scope_scan_main([str(repo), "--op-name", "DemoOp"]) == 0
    assert review_checkpoint_main([str(repo), "--op-name", "DemoOp", "--gate", "macro_scope", "--decision", "continue"]) == 0

    code, messages = finalize_phase0(repo, "DemoOp")

    assert code == 0, messages
    receipt = yaml.safe_load((base / "runs" / run_id / "phase0" / "receipt.yaml").read_text(encoding="utf-8"))
    assert receipt["status"] == "pass"
    assert receipt["cbm"]["indexed_via"] == "mcp"
    assert receipt["cbm"]["cbm_project"] == "demo"
    receipt["snapshot"]["source_revision"] = "DIFFERENT"
    _write_yaml(base / "runs" / run_id / "phase0" / "receipt.yaml", receipt)
    errors = validate_facts(repo, "DemoOp", stage="step1")
    assert any(error.code == "PHASE0_RECEIPT_STALE" for error in errors)


def test_finalize_phase0_requires_cbm_mcp_metadata_and_query_records(tmp_path: Path) -> None:
    repo, base, run_id = _repo(tmp_path)
    (repo / "op_host").mkdir()
    (repo / "op_host" / "demo.cpp").write_text("REGISTER_TILING(DemoOp)\n", encoding="utf-8")
    assert macro_scope_scan_main([str(repo), "--op-name", "DemoOp"]) == 0
    assert review_checkpoint_main([str(repo), "--op-name", "DemoOp", "--gate", "macro_scope", "--decision", "continue"]) == 0

    meta = json.loads((base / "cbm" / "index_meta.json").read_text(encoding="utf-8"))
    meta["indexed_via"] = "cli"
    (base / "cbm" / "index_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    semantic = yaml.safe_load((base / "runs" / run_id / "phase0" / "semantic_enrichment.yaml").read_text(encoding="utf-8"))
    semantic.pop("cbm_queries")
    _write_yaml(base / "runs" / run_id / "phase0" / "semantic_enrichment.yaml", semantic)

    code, messages = finalize_phase0(repo, "DemoOp")

    assert code == 2
    assert any("indexed_via must be mcp" in message for message in messages)
    assert any("missing cbm_queries list" in message for message in messages)


def test_finalize_phase0_allows_semantic_query_without_confidence(tmp_path: Path) -> None:
    repo, base, run_id = _repo(tmp_path)
    (repo / "op_host").mkdir()
    (repo / "op_host" / "demo.cpp").write_text("REGISTER_TILING(DemoOp)\n", encoding="utf-8")
    assert macro_scope_scan_main([str(repo), "--op-name", "DemoOp"]) == 0
    assert review_checkpoint_main([str(repo), "--op-name", "DemoOp", "--gate", "macro_scope", "--decision", "continue"]) == 0
    semantic = yaml.safe_load((base / "runs" / run_id / "phase0" / "semantic_enrichment.yaml").read_text(encoding="utf-8"))
    semantic["cbm_queries"] = [
        {
            "tool": "search_graph",
            "query": {"name_pattern": ".*DemoOp.*"},
            "result": {"matches_count": 1},
        }
    ]
    _write_yaml(base / "runs" / run_id / "phase0" / "semantic_enrichment.yaml", semantic)

    code, messages = finalize_phase0(repo, "DemoOp")

    assert code == 0, messages


def test_schema_disallows_source_fact_and_owner_split() -> None:
    spec = load_spec()
    owner = spec["ownership"]["owners"]
    assert "graphs/derived/abstraction_rules.yaml" in owner["uo-behavior-abstraction-agent"]["may_write"]
    assert "graphs/derived/abstraction_rules.yaml" not in owner["derived-graph-materializer"]["may_write"]
    assert "checks/step1/validation.yaml" not in owner["uo-boundary-agent"]["may_write"]
    for schema_rel in ("schemas/host/variables.schema.yaml", "schemas/compute/operations.schema.yaml", "schemas/kernel/branches.schema.yaml"):
        schema = yaml.safe_load((spec["root"] / schema_rel).read_text(encoding="utf-8"))
        assert "source_fact" not in schema["item_kind_enum"]
        for key in ("required_top_level", "allowed_top_level", "item_kind_enum", "required_item_fields", "kind_required_fields", "relation_required_fields", "minimum_cardinality"):
            assert key in schema


def test_raw_graph_indexes_cross_edges_paths_and_query_alias(tmp_path: Path) -> None:
    repo, base, run_id = _repo(tmp_path)
    source = _source_anchor()
    (repo / "op_host").mkdir()
    (repo / "op_host" / "demo.cpp").write_text(source["source_text"] + "\n", encoding="utf-8")
    _write_phase0_doc(base / "runs" / run_id / "phase0" / "scope_scan.yaml", "runs.scope_scan", {"status": "complete"})
    _write_yaml(
        base / "runs" / run_id / "phase0" / "scope_review.yaml",
        {"version": 1, "artifact": {"type": "runs.scope_review", "schema_version": 1, "owner": "uo-orchestrator"}, "snapshot": {"run_id": run_id, "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()}, "status": "decided", "decision": "continue", "items": [], "relations": [], "unresolved": []},
    )
    assert finalize_phase0(repo, "DemoOp")[0] == 0
    _write_yaml(
        base / "facts" / "host.yaml",
        _section_doc(
            "facts.host",
            "uo-host-extraction",
            {
                "tilingdata_writes": {
                    "items": [
                        _fact_item("TDATA_DEMO_TILE", "tilingdata_field", source, {"name": "tile count", "struct_ref": "DemoTilingData", "field_ref": "tileN", "field_type": "uint32_t", "aliases": ["tile count"]}),
                        _fact_item("TDWRITE_DEMO_TILE", "tilingdata_write", source, {"struct_ref": "DemoTilingData", "field_ref": "tileN", "field_type": "uint32_t", "write_site_ref": "CALL_WRITE", "value_expression_ref": "EXPR_TILE", "condition_ref": "EXPR_TRUE", "source_variable_refs": ["VAR_N"], "aliases": ["tile count"]}),
                    ],
                    "relations": [{"id": "REL_WRITE_TILE", "type": "writes", "source_id": "TDWRITE_DEMO_TILE", "target_id": "TDATA_DEMO_TILE", "sources": [source]}],
                    "unresolved": [],
                }
            },
        ),
    )
    _write_yaml(
        base / "facts" / "kernel" / "slices" / "main.yaml",
        _section_doc(
            "facts.kernel.slice",
            "uo-kernel-slice-agent",
            {
                "tilingdata_reads": {
                    "items": [_fact_item("TDREAD_DEMO_TILE", "tilingdata_read", source, {"struct_ref": "DemoTilingData", "field_ref": "tileN", "field_type": "uint32_t", "read_site_ref": "CALL_READ", "target_variable_ref": "VAR_KN", "read_condition_ref": "EXPR_TRUE", "host_write_candidate_ref": "TDWRITE_DEMO_TILE"})],
                    "relations": [{"id": "REL_READ_TILE", "type": "reads", "source_id": "TDREAD_DEMO_TILE", "target_id": "TDATA_DEMO_TILE", "sources": [source]}],
                    "unresolved": [],
                },
                "calls": {
                    "items": [_fact_item("CALL_DEMO_ADD", "compute_api_call", source, {"caller_ref": "FUNC_DEMO_KERNEL", "callee_ref": "AscendC::Add", "argument_refs": ["x", "y"], "output_refs": ["z"], "compute_operation_ref": "OPR_DEMO_ADD"})],
                    "relations": [],
                    "unresolved": [],
                },
            },
        ),
    )
    _write_yaml(
        base / "facts" / "compute.yaml",
        _section_doc(
            "facts.compute",
            "uo-flow-extraction",
            {
                "operations": {
                    "items": [
                        _fact_item(
                            "OPR_DEMO_ADD",
                            "compute_operation",
                            source,
                            {
                                "operation_type": "add",
                                "execution_order": 1,
                                "implementation_ref": "CALL_DEMO_ADD",
                                "kernel_api_refs": ["CALL_DEMO_ADD"],
                                "golden_ref": "GOLDEN_DEMO_ADD",
                                "input_tensor_refs": ["x", "y"],
                                "output_tensor_refs": ["z"],
                                "axis_refs": [],
                                "formula": "z = x + y",
                                "dtype_policy": "preserve",
                                "broadcast_policy": "none",
                                "reduction_policy": "none",
                                "numerical_sensitivity": "low",
                                "accumulation_dtype": "same_as_input",
                                "tolerance_ref": "TOL_DEMO_DEFAULT",
                            },
                        )
                    ],
                    "relations": [],
                    "unresolved": [],
                }
            },
        ),
    )
    _write_yaml(base / "checks" / "step3" / "receipt.yaml", {"version": 1, "artifact": {"type": "checks.step3.receipt", "schema_version": 1, "owner": "uo-orchestrator"}, "snapshot": {"run_id": "UO_RUN_TEST", "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()}, "status": "pass", "input_hashes": {}, "items": [], "relations": [], "unresolved": []})
    _write_yaml(base / "checks" / "compile_gate.yaml", {"version": 1, "artifact": {"type": "checks.compile_gate", "schema_version": 1, "owner": "facts-validator"}, "snapshot": {"run_id": "UO_RUN_TEST", "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()}, "status": "pass", "facts_hashes": facts_hashes_for(base), "items": [], "relations": [], "unresolved": []})

    code, messages = compile_source_graph(repo, "DemoOp")

    assert code == 0, messages
    edges = yaml.safe_load((base / "graphs" / "raw" / "edges.yaml").read_text(encoding="utf-8"))["edges"]
    assert any(edge["type"] == "tilingdata_write_to_read" for edge in edges)
    assert any(edge["type"] == "compute_to_kernel" and edge["source_id"] == "OPR_DEMO_ADD" and edge["target_id"] == "CALL_DEMO_ADD" for edge in edges)
    graph_to_yaml = yaml.safe_load((base / "indexes" / "graph_to_yaml.yaml").read_text(encoding="utf-8"))["graph_to_yaml"]
    assert any(edge["id"] in graph_to_yaml for edge in edges)
    paths = yaml.safe_load((base / "graphs" / "raw" / "paths.yaml").read_text(encoding="utf-8"))["paths"]
    assert any(path["path_type"] == "tilingdata_write_to_read" and path["max_depth"] for path in paths)
    result = query_readonly(repo, "DemoOp", "tile count")
    assert result["raw"]["nodes"]


def _fact_doc(artifact_type: str, owner: str, item_id: str, kind: str, source: dict, extra: dict) -> dict:
    item = {"id": item_id, "kind": kind, "name": item_id.lower(), "status": "confirmed", "sources": [source], **extra}
    return {
        "version": 1,
        "artifact": {"type": artifact_type, "schema_version": 1, "owner": owner},
        "snapshot": {"run_id": "UO_RUN_TEST", "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()},
        "items": [item],
        "relations": [],
        "unresolved": [],
    }


def _fact_item(item_id: str, kind: str, source: dict, extra: dict) -> dict:
    return {"id": item_id, "kind": kind, "name": item_id.lower(), "status": "confirmed", "sources": [source], **extra}


def _section_doc(artifact_type: str, owner: str, sections: dict) -> dict:
    return {
        "version": 1,
        "artifact": {"type": artifact_type, "schema_version": 1, "owner": owner},
        "snapshot": {"run_id": "UO_RUN_TEST", "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()},
        "sections": sections,
    }
