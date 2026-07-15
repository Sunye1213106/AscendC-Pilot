from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml

from understand_operator._operator.artifacts import init_operator_contract_layout, operator_root
from understand_operator._operator.identity import resolve_identity
from understand_operator._operator.reference_paths import reference_declarations
from understand_operator._operator.spec import load_spec, spec_bundle_hash
from understand_operator.scripts.compile_candidate_facts import compile_candidate_facts
from understand_operator.scripts.prepare_fact_file import prepare_fact_file
from understand_operator.scripts.validate_candidate_batch import validate_candidate_batch
from understand_operator.scripts.validate_facts import validate_facts
from understand_operator.scripts.validate_spec_consistency import validate_spec_consistency


def _ready_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "op_host").mkdir()
    (repo / "op_kernel").mkdir()
    (repo / "op_host" / "demo.cpp").write_text("int x = 1;\nTilingData tile;\n", encoding="utf-8")
    (repo / "op_kernel" / "demo.cpp").write_text("void DemoKernel() { TilingData tile; }\nDataCopy(dst, src, len);\n", encoding="utf-8")
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    manifest = yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["current_run_id"] = "UO_RUN_TEST"
    (root / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    receipt = {
        "status": "pass",
        "snapshot": {
            "run_id": "UO_RUN_TEST",
            "source_snapshot_id": "SOURCE_TEST",
            "source_revision": "unknown",
            "spec_bundle_hash": spec_bundle_hash(),
        },
    }
    phase0 = root / "runs" / "UO_RUN_TEST" / "phase0"
    phase0.mkdir(parents=True)
    (phase0 / "receipt.yaml").write_text(yaml.safe_dump(receipt, sort_keys=False), encoding="utf-8")
    return repo, root


def _loc(file: str = "op_host/demo.cpp", line: int = 1, symbol: str = "demo") -> dict[str, Any]:
    return {"file": file, "symbol": symbol, "start_line": line, "end_line": line, "anchor_kind": "definition"}


def _batch(target: str, section: str, owner: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 2,
        "task": {"run_id": "UO_RUN_TEST", "stage": "step2", "owner": owner, "task_id": "TEST"},
        "target": {"path": target, "section": section},
        "items": items,
        "relations": [],
        "unresolved": [],
    }


def _ref(local_id: str) -> dict[str, str]:
    return {"ref_type": "local", "local_id": local_id}


def _entity_ref(kind: str, identity: dict[str, Any]) -> dict[str, Any]:
    return {"ref_type": "entity", "kind": kind, "identity": identity}


def test_spec_consistency_passes() -> None:
    assert validate_spec_consistency(Path(__file__).resolve().parents[1]) == []


def test_identity_has_no_hardcoded_kind_prefix_table() -> None:
    source = (Path(__file__).resolve().parents[1] / "understand_operator" / "_operator" / "identity.py").read_text(encoding="utf-8")
    assert "KIND_TO_PREFIX" not in source


def test_identity_strategy_normalized_fields_match_spec(tmp_path: Path) -> None:
    repo, _root = _ready_repo(tmp_path)
    spec = load_spec()["entity_types"]["entity_types"]
    samples = {
        "kernel_slice": {
            "kernel_entry_ref": "KERNEL_ENTRY",
            "template_binding_signature": "generic",
            "structural_flow_signature": "read-compute-write",
            "tilingdata_read_signature": "tile",
            "output_signature": "out0",
        },
        "dataflow_edge": {"source_ref": "SRC", "target_ref": "DST", "order_index": 1, "condition_ref": "COND", "qualifier": "ignored"},
        "branch_outcome": {"parent_branch_ref": "BRANCH_PARENT", "outcome": "true"},
        "slice_interface": {"source_slice_ref": "KERNEL_A", "target_slice_ref": "KERNEL_B", "interface_kind": "data", "position": "0"},
        "kernel_entry": {"qualified_entry_symbol": "DemoKernel", "signature": "void()", "discriminator": "generic"},
        "compute_operation": {"compute_scope": "DemoKernel", "operation_type": "copy", "output_identity": "dst", "source_span": {"start_line": 2, "end_line": 2}},
        "memory_resource": {"source_file": "op_kernel/demo.cpp", "scope_symbol": "DemoKernel", "source_name": "tile", "declaration_span": {"start_line": 1, "end_line": 1}, "resource_kind": "buffer"},
        "sync_event": {"source_file": "op_kernel/demo.cpp", "scope_symbol": "DemoKernel", "event_kind": "setflag", "event_identifier": "flag0", "source_span": {"start_line": 1, "end_line": 1}},
    }
    for kind, identity in samples.items():
        resolved = resolve_identity(kind, identity, repo_root=repo)
        assert set(resolved.normalized_identity) == set(spec[kind]["required_identity_fields"])


def test_all_schema_required_refs_are_declared() -> None:
    spec = load_spec()
    errors = validate_spec_consistency(Path(__file__).resolve().parents[1])
    assert not [error for error in errors if error.code.startswith("SPEC_REQUIRED_REFERENCE")]
    assert "source_anchor_ref" not in reference_declarations(spec["entity_types"], "kernel_entry")


def test_source_file_hash_is_compiler_generated(tmp_path: Path) -> None:
    repo, root = _ready_repo(tmp_path)
    batch = {
        "version": 2,
        "task": {"run_id": "UO_RUN_TEST", "stage": "step1", "owner": "uo-boundary-agent", "task_id": "SRC"},
        "target": {"path": "facts/operator/source_files.yaml"},
        "items": [
            {
                "local_id": "src",
                "kind": "source_file",
                "identity": {"path": "op_host/demo.cpp"},
                "fields": {"path": "op_host/demo.cpp", "role": "host", "include_reason": "operator source"},
                "source_locations": [_loc()],
            }
        ],
        "relations": [],
        "unresolved": [],
    }
    assert compile_candidate_facts(repo, "DemoOp", batch) == []
    item = yaml.safe_load((root / "facts" / "operator" / "source_files.yaml").read_text(encoding="utf-8"))["items"][0]
    expected = "sha256:" + hashlib.sha256((repo / "op_host" / "demo.cpp").read_bytes()).hexdigest()
    assert item["file_hash"] == expected


def test_candidate_file_hash_is_rejected(tmp_path: Path) -> None:
    repo, _root = _ready_repo(tmp_path)
    batch = {
        "version": 2,
        "task": {"run_id": "UO_RUN_TEST", "stage": "step1", "owner": "uo-boundary-agent", "task_id": "SRC"},
        "target": {"path": "facts/operator/source_files.yaml"},
        "items": [
            {
                "local_id": "src",
                "kind": "source_file",
                "identity": {"path": "op_host/demo.cpp"},
                "fields": {"path": "op_host/demo.cpp", "role": "host", "include_reason": "operator source", "file_hash": "sha256:bad"},
                "source_locations": [_loc()],
            }
        ],
        "relations": [],
        "unresolved": [],
    }
    assert any(error.code == "CANDIDATE_FIELD_FORBIDDEN" for error in validate_candidate_batch(repo, "DemoOp", batch))


def test_formal_fact_without_identity_fails(tmp_path: Path) -> None:
    repo, root = _ready_repo(tmp_path)
    (root / "facts").mkdir(exist_ok=True)
    (root / "facts" / "host.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "artifact": {"type": "host.partition", "schema_version": 1, "owner": "uo-host-extraction"},
                "snapshot": {"run_id": "UO_RUN_TEST", "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()},
                "sections": {"variables": {"items": [{"id": "VAR_X", "kind": "runtime_variable", "status": "confirmed", "sources": []}], "relations": [], "unresolved": []}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    errors = validate_facts(repo, "DemoOp", stage="step2", scope="host")
    assert any(error.code == "IDENTITY_MISSING" for error in errors)


def test_source_anchor_ref_is_not_a_fact_reference(tmp_path: Path) -> None:
    repo, _root = _ready_repo(tmp_path)
    item = {
        "local_id": "entry",
        "kind": "kernel_entry",
        "identity": {"qualified_entry_symbol": "DemoKernel", "signature": "()", "discriminator": "global"},
        "fields": {"source_anchor_ref": _ref("entry")},
        "source_locations": [_loc("op_kernel/demo.cpp", 1)],
    }
    batch = _batch("facts/kernel/overview.yaml", "entries", "uo-kernel-overview-agent", [item])
    errors = validate_candidate_batch(repo, "DemoOp", batch)
    assert any(error.code == "REFERENCE_FIELD_UNDECLARED" and "source_anchor_ref" in error.field for error in errors)


def test_nested_execution_path_refs_compile(tmp_path: Path) -> None:
    repo, root = _ready_repo(tmp_path)
    expr_identity = {"source_file": "op_kernel/demo.cpp", "scope_symbol": "DemoKernel", "source_span": {"start_line": 1, "end_line": 1}}
    call_identity = {"source_file": "op_kernel/demo.cpp", "scope_symbol": "DemoKernel", "callee_symbol": "DataCopy", "call_span": {"start_line": 2, "end_line": 2}}
    key_identity = {"source_file": "op_host/demo.cpp", "scope_symbol": "demo", "source_span": {"start_line": 2, "end_line": 2}}
    assert compile_candidate_facts(repo, "DemoOp", _batch("facts/kernel/slices/main.yaml", "expressions", "uo-kernel-slice-agent", [{"local_id": "cond", "kind": "kernel_expression", "identity": expr_identity, "fields": {"expression_text": "x", "expression_kind": "predicate"}, "source_locations": [_loc("op_kernel/demo.cpp", 1, "DemoKernel")]}])) == []
    assert compile_candidate_facts(repo, "DemoOp", _batch("facts/kernel/slices/main.yaml", "calls", "uo-kernel-slice-agent", [{"local_id": "api", "kind": "compute_api_call", "identity": call_identity, "fields": {"callee_symbol": "DataCopy"}, "source_locations": [_loc("op_kernel/demo.cpp", 2, "DemoKernel")]}])) == []
    assert compile_candidate_facts(repo, "DemoOp", _batch("facts/host.yaml", "tiling_key", "uo-host-extraction", [{"local_id": "key", "kind": "tiling_key_field", "identity": key_identity, "fields": {"field_order": 0, "domain": "int"}, "source_locations": [_loc("op_host/demo.cpp", 2)]}])) == []
    compute_identity = {"compute_scope": "DemoKernel", "operation_type": "copy", "output_identity": "dst", "source_span": {"start_line": 2, "end_line": 2}}
    compute = {
        "local_id": "op",
        "kind": "compute_operation",
        "identity": compute_identity,
        "fields": {
            "execution": {"paths": [{"condition_refs": [_entity_ref("kernel_expression", expr_identity)], "api_refs": [_entity_ref("compute_api_call", call_identity)], "tiling_key_refs": [_entity_ref("tiling_key_field", key_identity)]}]}
        },
        "source_locations": [_loc("op_kernel/demo.cpp", 2, "DemoKernel")],
    }
    assert compile_candidate_facts(repo, "DemoOp", _batch("facts/compute.yaml", "operations", "uo-flow-extraction", [compute])) == []
    item = yaml.safe_load((root / "facts" / "compute.yaml").read_text(encoding="utf-8"))["sections"]["operations"]["items"][0]
    refs = item["execution"]["paths"][0]
    assert refs["condition_refs"][0].startswith("EXPR_")
    assert refs["api_refs"][0].startswith("API_")
    assert refs["tiling_key_refs"][0].startswith("KEY_")


def test_wrong_reference_kind_fails(tmp_path: Path) -> None:
    repo, _root = _ready_repo(tmp_path)
    identity = {"compute_scope": "DemoKernel", "operation_type": "copy", "output_identity": "dst", "source_span": {"start_line": 2, "end_line": 2}}
    batch = _batch(
        "facts/compute.yaml",
        "operations",
        "uo-flow-extraction",
        [{"local_id": "op", "kind": "compute_operation", "identity": identity, "fields": {"execution": {"paths": [{"api_refs": [_ref("op")]}]}}, "source_locations": [_loc("op_kernel/demo.cpp", 2, "DemoKernel")]}],
    )
    assert any(error.code == "REFERENCE_KIND_NOT_ALLOWED" for error in validate_candidate_batch(repo, "DemoOp", batch))


def test_relation_fields_have_no_legacy_linker_fallback(tmp_path: Path) -> None:
    repo, _root = _ready_repo(tmp_path)
    batch = {
        "version": 2,
        "task": {"run_id": "UO_RUN_TEST", "stage": "step2", "owner": "uo-host-extraction", "task_id": "REL"},
        "target": {"path": "facts/host.yaml", "section": "variables"},
        "items": [
            {
                "local_id": "var_x",
                "kind": "runtime_variable",
                "identity": {"source_file": "op_host/demo.cpp", "scope_symbol": "demo", "source_name": "x", "declaration_span": {"start_line": 1, "end_line": 1}},
                "fields": {"declared_type": "int", "scope_symbol": "demo", "definition_kind": "definition", "value_source_text": "literal", "domain": "integer", "affects": ["dispatch"]},
                "source_locations": [_loc()],
            }
        ],
        "relations": [
            {
                "type": "derived_from",
                "source": _ref("var_x"),
                "target": _ref("var_x"),
                "fields": {"source_ref": _ref("var_x")},
                "source_locations": [_loc()],
            }
        ],
        "unresolved": [],
    }
    errors = validate_candidate_batch(repo, "DemoOp", batch)
    assert any(error.code == "REFERENCE_FIELD_UNDECLARED" and "source_ref" in error.field for error in errors)


def test_partition_snapshot_does_not_overwrite_existing_sections(tmp_path: Path) -> None:
    repo, root = _ready_repo(tmp_path)
    stale = {
        "version": 1,
        "artifact": {"type": "host.partition", "schema_version": 1, "owner": "uo-host-extraction"},
        "snapshot": {"run_id": "OLD"},
        "sections": {"variables": {"items": [{"id": "VAR_X"}], "relations": [], "unresolved": []}},
    }
    target = root / "facts" / "host.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(stale, sort_keys=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="FACT_FILE_SNAPSHOT_STALE"):
        prepare_fact_file(repo, "DemoOp", "facts/host.yaml")
    assert yaml.safe_load(target.read_text(encoding="utf-8"))["sections"]["variables"]["items"][0]["id"] == "VAR_X"


def test_tilingdata_write_field_link_compiles(tmp_path: Path) -> None:
    repo, root = _ready_repo(tmp_path)
    field_identity = {"qualified_struct_name": "TilingData", "field_name": "tile"}
    write_identity = {"source_file": "op_host/demo.cpp", "scope_symbol": "demo", "struct_name": "TilingData", "field_name": "tile", "write_span": {"start_line": 2, "end_line": 2}}
    batch = _batch(
        "facts/host.yaml",
        "tilingdata_writes",
        "uo-host-extraction",
        [
            {"local_id": "field", "kind": "tilingdata_field", "identity": field_identity, "fields": {"field_type": "uint32_t"}, "source_locations": [_loc("op_host/demo.cpp", 2)]},
            {"local_id": "write", "kind": "tilingdata_write", "identity": write_identity, "fields": {"field_ref": _ref("field"), "field_type": "uint32_t"}, "source_locations": [_loc("op_host/demo.cpp", 2)]},
        ],
    )
    assert compile_candidate_facts(repo, "DemoOp", batch) == []
    items = yaml.safe_load((root / "facts" / "host.yaml").read_text(encoding="utf-8"))["sections"]["tilingdata_writes"]["items"]
    write = next(item for item in items if item["kind"] == "tilingdata_write")
    assert write["field_ref"].startswith("TDATA_")


def test_tilingdata_read_field_link_compiles(tmp_path: Path) -> None:
    repo, root = _ready_repo(tmp_path)
    field_identity = {"qualified_struct_name": "TilingData", "field_name": "tile"}
    assert compile_candidate_facts(repo, "DemoOp", _batch("facts/host.yaml", "tilingdata_writes", "uo-host-extraction", [{"local_id": "field", "kind": "tilingdata_field", "identity": field_identity, "fields": {"field_type": "uint32_t"}, "source_locations": [_loc("op_host/demo.cpp", 2)]}])) == []
    read_identity = {"source_file": "op_kernel/demo.cpp", "scope_symbol": "DemoKernel", "struct_name": "TilingData", "field_name": "tile", "read_span": {"start_line": 1, "end_line": 1}}
    batch = _batch(
        "facts/kernel/slices/main.yaml",
        "tilingdata_reads",
        "uo-kernel-slice-agent",
        [{"local_id": "read", "kind": "tilingdata_read", "identity": read_identity, "fields": {"field_ref": _entity_ref("tilingdata_field", field_identity), "field_type": "uint32_t"}, "source_locations": [_loc("op_kernel/demo.cpp", 1, "DemoKernel")]}],
    )
    assert compile_candidate_facts(repo, "DemoOp", batch) == []
    items = yaml.safe_load((root / "facts" / "kernel" / "slices" / "main.yaml").read_text(encoding="utf-8"))["sections"]["tilingdata_reads"]["items"]
    assert items[0]["field_ref"].startswith("TDATA_")


def test_formal_reference_kind_validation_rejects_wrong_kind(tmp_path: Path) -> None:
    repo, root = _ready_repo(tmp_path)
    expr = resolve_identity("kernel_expression", {"source_file": "op_kernel/demo.cpp", "scope_symbol": "DemoKernel", "source_span": {"start_line": 1, "end_line": 1}}, repo_root=repo)
    op = resolve_identity("compute_operation", {"compute_scope": "DemoKernel", "operation_type": "copy", "output_identity": "dst", "source_span": {"start_line": 2, "end_line": 2}}, repo_root=repo)
    doc = {
        "version": 1,
        "artifact": {"type": "compute.partition", "schema_version": 1, "owner": "uo-flow-extraction"},
        "snapshot": {"run_id": "UO_RUN_TEST", "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()},
        "sections": {
            "operations": {
                "items": [
                    {"id": expr.stable_id, "kind": "kernel_expression", "status": "confirmed", "identity": {"version": 1, "canonical_key": expr.canonical_key, "normalized": expr.normalized_identity}, "sources": []},
                    {"id": op.stable_id, "kind": "compute_operation", "status": "confirmed", "identity": {"version": 1, "canonical_key": op.canonical_key, "normalized": op.normalized_identity}, "execution": {"paths": [{"api_refs": [expr.stable_id]}]}, "sources": []},
                ],
                "relations": [],
                "unresolved": [],
            }
        },
    }
    target = root / "facts" / "compute.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    errors = validate_facts(repo, "DemoOp", stage="step2", scope="compute")
    assert any(error.code == "FORMAL_REFERENCE_KIND_NOT_ALLOWED" for error in errors)
