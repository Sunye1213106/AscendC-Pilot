from __future__ import annotations

from pathlib import Path

import yaml

from understand_operator._operator.artifacts import init_operator_contract_layout, operator_root
from understand_operator._operator.fact_registry import build_fact_registry
from understand_operator._operator.identity import IdentityError, resolve_identity
from understand_operator._operator.source_reader import SourceReadError, SourceReader
from understand_operator._operator.spec import spec_bundle_hash
from understand_operator.scripts.compile_candidate_facts import compile_candidate_facts
from understand_operator.scripts.build_fact_registry import build_registry_cache
from understand_operator.scripts.validate_candidate_batch import validate_candidate_batch


def _ready_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"; repo.mkdir(); (repo / "op_host").mkdir(); (repo / "op_host" / "demo.cpp").write_text("int x = 1;\nif (x) { return; }\nif (!x) { return; }\nbool CheckBn2();\n", encoding="utf-8")
    root = operator_root(repo, "DemoOp"); init_operator_contract_layout(root, "DemoOp", repo)
    manifest = yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8")); manifest["current_run_id"] = "UO_RUN_TEST"; (root / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    phase0 = root / "runs" / "UO_RUN_TEST" / "phase0"; phase0.mkdir(parents=True)
    (phase0 / "receipt.yaml").write_text(yaml.safe_dump({"status": "pass", "snapshot": {"run_id": "UO_RUN_TEST", "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()}}, sort_keys=False), encoding="utf-8")
    return repo, root


def _batch() -> dict:
    return {"version": 2, "task": {"run_id": "UO_RUN_TEST", "stage": "step2", "owner": "uo-host-extraction", "task_id": "HOST_X"}, "target": {"path": "facts/host.yaml", "section": "variables"}, "items": [{"local_id": "var_x", "kind": "runtime_variable", "name": "x", "identity": {"source_file": "op_host/demo.cpp", "scope_symbol": "demo", "source_name": "x", "declaration_span": {"start_line": 1, "end_line": 1}}, "fields": {"declared_type": "int", "scope_symbol": "demo", "definition_kind": "definition", "value_source_text": "literal", "domain": "integer", "affects": ["dispatch"]}, "source_locations": [{"file": "op_host/demo.cpp", "symbol": "demo", "start_line": 1, "end_line": 1, "anchor_kind": "definition"}]}], "relations": [], "unresolved": []}


def test_compiler_materializes_deterministic_fact_and_replaces_same_key(tmp_path: Path) -> None:
    repo, root = _ready_repo(tmp_path); batch = _batch()
    assert validate_candidate_batch(repo, "DemoOp", batch) == []; assert compile_candidate_facts(repo, "DemoOp", batch) == []
    batch["items"][0]["fields"]["domain"] = "updated"; assert compile_candidate_facts(repo, "DemoOp", batch) == []
    items = yaml.safe_load((root / "facts" / "host.yaml").read_text(encoding="utf-8"))["sections"]["variables"]["items"]
    assert len(items) == 1 and items[0]["id"].startswith("VAR_") and items[0]["domain"] == "updated"
    assert items[0]["identity"]["canonical_key"].startswith("runtime_variable:op_host/demo.cpp:demo:x:1:1")
    assert items[0]["identity"]["normalized"]["source_name"] == "x"
    assert items[0]["sources"][0]["source_text"] == "int x = 1;"
    assert not (root / "indexes" / "entity_registry.json").exists()
    assert build_registry_cache(repo, "DemoOp")[0] == 0
    assert (root / "indexes" / "entity_registry.json").exists()
    assert not (root / "indexes" / "fact_keys.json").exists()


def test_local_validator_rejects_model_identity_fields(tmp_path: Path) -> None:
    repo, _ = _ready_repo(tmp_path); batch = _batch(); batch["items"][0]["fact_key"] = "host:demo:x"
    assert any(error.code == "CANDIDATE_LEGACY_IDENTITY_FIELD" for error in validate_candidate_batch(repo, "DemoOp", batch))


def test_identity_ignores_display_name_and_rejects_unknown_kind(tmp_path: Path) -> None:
    repo, _ = _ready_repo(tmp_path)
    identity = {"source_file": "op_host/demo.cpp", "scope_symbol": "demo", "source_name": "x", "declaration_span": {"start_line": 1, "end_line": 1}}
    first = resolve_identity("runtime_variable", identity, repo_root=repo)
    second = resolve_identity("runtime_variable", dict(identity), repo_root=repo)
    assert first.stable_id == second.stable_id
    assert resolve_identity("runtime_variable", {**identity, "scope_symbol": "other"}, repo_root=repo).stable_id != first.stable_id
    try:
        resolve_identity("mystery_kind", identity, repo_root=repo)
    except IdentityError as exc:
        assert exc.code == "IDENTITY_KIND_UNSUPPORTED"
    else:
        raise AssertionError("unknown kind must fail")


def test_local_relation_resolves_and_does_not_leak_local_id(tmp_path: Path) -> None:
    repo, root = _ready_repo(tmp_path)
    batch = {"version": 2, "task": {"run_id": "UO_RUN_TEST", "stage": "step2", "owner": "uo-host-extraction", "task_id": "HOST_CF"}, "target": {"path": "facts/host.yaml", "section": "control_flow"}, "items": [
        {"local_id": "branch_1", "kind": "if_branch", "name": "branch A", "identity": {"source_file": "op_host/demo.cpp", "scope_symbol": "demo", "predicate_span": {"start_line": 2, "end_line": 2}}, "fields": {"outcome_refs": [], "scope_symbol": "demo", "controlled_item_refs": [], "reachability": "reachable"}, "source_locations": [{"file": "op_host/demo.cpp", "symbol": "demo", "start_line": 2, "end_line": 2, "anchor_kind": "control_flow"}]},
        {"local_id": "branch_2", "kind": "if_branch", "name": "branch B", "identity": {"source_file": "op_host/demo.cpp", "scope_symbol": "demo", "predicate_span": {"start_line": 3, "end_line": 3}}, "fields": {"outcome_refs": [], "scope_symbol": "demo", "controlled_item_refs": [], "reachability": "reachable"}, "source_locations": [{"file": "op_host/demo.cpp", "symbol": "demo", "start_line": 3, "end_line": 3, "anchor_kind": "control_flow"}]},
    ], "relations": [{"type": "requires", "source": {"ref_type": "local", "local_id": "branch_1"}, "target": {"ref_type": "local", "local_id": "branch_2"}, "fields": {}, "source_locations": [{"file": "op_host/demo.cpp", "symbol": "demo", "start_line": 2, "end_line": 2, "anchor_kind": "control_flow"}]}], "unresolved": []}
    assert compile_candidate_facts(repo, "DemoOp", batch) == []
    unit = yaml.safe_load((root / "facts" / "host.yaml").read_text(encoding="utf-8"))["sections"]["control_flow"]
    assert unit["relations"][0]["source_id"].startswith("BRANCH_")
    assert unit["relations"][0]["id"].startswith("REL_")
    assert "local_id" not in yaml.safe_dump(unit)


def test_registry_rebuilds_from_formal_facts(tmp_path: Path) -> None:
    repo, root = _ready_repo(tmp_path)
    assert compile_candidate_facts(repo, "DemoOp", _batch()) == []
    registry = build_fact_registry(root)
    assert len(registry.facts_by_id) == 1
    assert next(iter(registry.canonical_to_id)).startswith("runtime_variable:")


def test_source_reader_strict_span_and_encoding(tmp_path: Path) -> None:
    repo, _ = _ready_repo(tmp_path); reader = SourceReader(repo)
    assert reader.read("op_host/demo.cpp").span(1, 1) == "int x = 1;"
    try: reader.read("op_host/demo.cpp").span(99, 99)
    except SourceReadError as exc: assert exc.code == "SOURCE_SPAN_OUT_OF_RANGE"
    else: raise AssertionError("out-of-range span must fail")
