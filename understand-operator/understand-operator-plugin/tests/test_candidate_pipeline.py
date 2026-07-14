from __future__ import annotations

from pathlib import Path

import yaml

from understand_operator._operator.artifacts import init_operator_contract_layout, operator_root
from understand_operator._operator.source_reader import SourceReadError, SourceReader
from understand_operator._operator.spec import spec_bundle_hash
from understand_operator.scripts.compile_candidate_facts import compile_candidate_facts
from understand_operator.scripts.validate_candidate_batch import validate_candidate_batch


def _ready_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"; repo.mkdir(); (repo / "op_host").mkdir(); (repo / "op_host" / "demo.cpp").write_text("int x = 1;\n", encoding="utf-8")
    root = operator_root(repo, "DemoOp"); init_operator_contract_layout(root, "DemoOp", repo)
    manifest = yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8")); manifest["current_run_id"] = "UO_RUN_TEST"; (root / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    phase0 = root / "runs" / "UO_RUN_TEST" / "phase0"; phase0.mkdir(parents=True)
    (phase0 / "receipt.yaml").write_text(yaml.safe_dump({"status": "pass", "snapshot": {"run_id": "UO_RUN_TEST", "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()}}, sort_keys=False), encoding="utf-8")
    return repo, root


def _batch() -> dict:
    return {"version": 1, "task": {"run_id": "UO_RUN_TEST", "stage": "step2", "owner": "uo-host-extraction", "task_id": "HOST_X"}, "target": "facts/host/variables.yaml", "items": [{"fact_key": "host:demo:x", "kind": "runtime_variable", "name": "x", "fields": {"declared_type": "int", "scope_ref": "demo", "definition_kind": "definition", "value_source_ref": "literal", "domain": "integer", "affects": ["dispatch"]}, "source_locations": [{"file": "op_host/demo.cpp", "symbol": "demo", "start_line": 1, "end_line": 1, "anchor_kind": "definition"}]}], "relations": [], "unresolved": []}


def test_compiler_materializes_deterministic_fact_and_replaces_same_key(tmp_path: Path) -> None:
    repo, root = _ready_repo(tmp_path); batch = _batch()
    assert validate_candidate_batch(repo, "DemoOp", batch) == []; assert compile_candidate_facts(repo, "DemoOp", batch) == []
    batch["items"][0]["fields"]["domain"] = "updated"; assert compile_candidate_facts(repo, "DemoOp", batch) == []
    items = yaml.safe_load((root / "facts" / "host" / "variables.yaml").read_text(encoding="utf-8"))["items"]
    assert len(items) == 1 and items[0]["id"].startswith("VAR_") and items[0]["domain"] == "updated"
    assert items[0]["sources"][0]["source_text"] == "int x = 1;"


def test_local_validator_rejects_model_identity_fields(tmp_path: Path) -> None:
    repo, _ = _ready_repo(tmp_path); batch = _batch(); batch["items"][0]["id"] = "VAR_STOLEN"
    assert any(error.code == "CANDIDATE_FIELD_FORBIDDEN" for error in validate_candidate_batch(repo, "DemoOp", batch))


def test_source_reader_strict_span_and_encoding(tmp_path: Path) -> None:
    repo, _ = _ready_repo(tmp_path); reader = SourceReader(repo)
    assert reader.read("op_host/demo.cpp").span(1, 1) == "int x = 1;"
    try: reader.read("op_host/demo.cpp").span(2, 2)
    except SourceReadError as exc: assert exc.code == "SOURCE_SPAN_OUT_OF_RANGE"
    else: raise AssertionError("out-of-range span must fail")
