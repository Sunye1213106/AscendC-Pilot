from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from understand_operator._operator.artifacts import init_operator_contract_layout, operator_root
from understand_operator._operator.spec import catalog_entries, load_spec, spec_bundle_hash
from understand_operator.scripts.build_compile_gate import build_compile_gate
from understand_operator.scripts.materialize_derived_graph import materialize_derived_graph
from understand_operator.scripts.source_graph_compiler import compile_source_graph
from understand_operator.scripts.uo_query_readonly import query_readonly
from understand_operator.scripts.validate_facts import validate_facts
from understand_operator.scripts.write_step2_receipt import write_step2_receipt
from understand_operator.scripts.write_step3_receipt import write_step3_receipt


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = operator_root(repo, "DemoOp")
    init_operator_contract_layout(base, "DemoOp", repo)
    return repo, base


def _hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _valid_source() -> tuple[str, dict]:
    text = "void DemoOpHost() {}"
    return text, {
        "id": "SRC_DEMO_HOST",
        "file": "op_host/demo.cpp",
        "symbol": "DemoOpHost",
        "span": {"start_line": 1, "end_line": 1},
        "source_text": text,
        "code_hash": _hash_text(text),
        "anchor_kind": "definition",
    }


def _valid_interface_doc(source: dict) -> dict:
    return {
        "version": 1,
        "artifact": {"type": "operator.interface", "schema_version": 1, "owner": "uo-boundary-agent"},
        "snapshot": {
            "run_id": "UO_RUN_TEST",
            "source_snapshot_id": "SOURCE_TEST",
            "source_revision": "abc123",
            "spec_bundle_hash": spec_bundle_hash(),
        },
        "items": [
            {
                "id": "ARG_DEMO_X",
                "kind": "input_tensor",
                "name": "x",
                "origin": "source",
                "status": "confirmed",
                "sources": [source],
            }
        ],
        "relations": [],
        "unresolved": [],
    }


def _fact_doc(artifact_type: str, owner: str, item_id: str, source: dict, *, kind: str = "source_fact") -> dict:
    return {
        "version": 1,
        "artifact": {"type": artifact_type, "schema_version": 1, "owner": owner},
        "snapshot": {
            "run_id": "UO_RUN_TEST",
            "source_snapshot_id": "SOURCE_TEST",
            "source_revision": "abc123",
            "spec_bundle_hash": spec_bundle_hash(),
        },
        "items": [
            {
                "id": item_id,
                "kind": kind,
                "name": item_id.lower(),
                "origin": "source",
                "status": "confirmed",
                "sources": [source],
            }
        ],
        "relations": [],
        "unresolved": [],
    }


def _report(status: str, artifact_type: str) -> dict:
    return {
        "version": 1,
        "artifact": {"type": artifact_type, "schema_version": 1, "owner": "facts-validator"},
        "snapshot": {
            "run_id": "UO_RUN_TEST",
            "source_snapshot_id": "SOURCE_TEST",
            "source_revision": "abc123",
            "spec_bundle_hash": spec_bundle_hash(),
        },
        "status": status,
        "errors": [],
        "items": [],
        "relations": [],
        "unresolved": [],
    }


def _review(status: str = "pass") -> dict:
    return {
        "version": 1,
        "artifact": {"type": "checks.step2.review", "schema_version": 1, "owner": "uo-review-agent"},
        "snapshot": {
            "run_id": "UO_RUN_TEST",
            "source_snapshot_id": "SOURCE_TEST",
            "source_revision": "abc123",
            "spec_bundle_hash": spec_bundle_hash(),
        },
        "status": status,
        "blocking_findings": [],
        "warnings": [],
        "items": [],
        "relations": [],
        "unresolved": [],
    }


def _step3_review(status: str = "pass") -> dict:
    return {
        "version": 1,
        "artifact": {"type": "checks.step3.review", "schema_version": 1, "owner": "uo-step3-fact-review-agent"},
        "snapshot": {
            "run_id": "UO_RUN_TEST",
            "source_snapshot_id": "SOURCE_TEST",
            "source_revision": "abc123",
            "spec_bundle_hash": spec_bundle_hash(),
        },
        "status": status,
        "blocking_findings": [],
        "warnings": [],
        "items": [],
        "relations": [],
        "unresolved": [],
    }


def _seed_source(repo: Path) -> dict:
    source_text, source_anchor = _valid_source()
    source_path = repo / "op_host" / "demo.cpp"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(source_text + "\n", encoding="utf-8")
    return source_anchor


def _seed_step2_receipt(base: Path) -> None:
    _write_yaml(base / "checks" / "step2" / "receipt.yaml", _report("pass", "checks.step2.receipt"))


def _seed_step3_planner(base: Path, source: dict) -> None:
    _write_yaml(
        base / "facts" / "kernel" / "slice_manifest.yaml",
        _fact_doc("kernel.slice_manifest", "uo-kernel-slice-planner", "KERNEL_SLICE_MAIN", source, kind="kernel_slice"),
    )
    _write_yaml(
        base / "facts" / "kernel" / "slice_interfaces.yaml",
        _fact_doc("kernel.slice_interfaces", "uo-kernel-slice-planner", "REL_SLICE_INTERFACE", source, kind="slice_interface"),
    )


def _seed_kernel_slice(base: Path, source: dict, slice_id: str = "main") -> None:
    files = {
        "variables.yaml": ("kernel.slice.variables", "VAR_KERNEL_SLICE_MAIN"),
        "expressions.yaml": ("kernel.slice.expressions", "EXPR_KERNEL_SLICE_MAIN"),
        "branches.yaml": ("kernel.slice.branches", "BRANCH_KERNEL_SLICE_MAIN"),
        "loops.yaml": ("kernel.slice.loops", "LOOP_KERNEL_SLICE_MAIN"),
        "tilingdata_reads.yaml": ("kernel.slice.tilingdata_reads", "TDREAD_KERNEL_SLICE_MAIN"),
        "calls.yaml": ("kernel.slice.calls", "CALL_KERNEL_SLICE_MAIN"),
        "dataflow.yaml": ("kernel.slice.dataflow", "REL_KERNEL_SLICE_FLOW"),
        "memory.yaml": ("kernel.slice.memory", "BUF_KERNEL_SLICE_MAIN"),
        "synchronization.yaml": ("kernel.slice.synchronization", "SYNC_KERNEL_SLICE_MAIN"),
    }
    for filename, (artifact_type, item_id) in files.items():
        _write_yaml(base / "facts" / "kernel" / "slices" / slice_id / filename, _fact_doc(artifact_type, "uo-kernel-slice-agent", item_id, source))


def test_spec_catalog_has_owner_and_schema_for_every_yaml_artifact() -> None:
    spec = load_spec()
    owners = set((spec["ownership"].get("owners") or {}).keys())
    for entry in catalog_entries(spec):
        assert entry["owner"] in owners, entry["path"]
        schema = entry.get("schema")
        if schema:
            assert (spec["root"] / schema).exists(), entry["path"]


def test_contract_layout_is_idempotent_and_has_no_embedded_spec(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    before = {path.relative_to(base).as_posix(): path.read_text(encoding="utf-8") for path in base.rglob("*.yaml")}
    source = repo / "op_host" / "demo.cpp"
    source.parent.mkdir()
    source.write_text("void DemoOpHost() {}\n", encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    init_operator_contract_layout(base, "DemoOp", repo)

    after = {path.relative_to(base).as_posix(): path.read_text(encoding="utf-8") for path in base.rglob("*.yaml")}
    assert before == after
    for forbidden in ("spec", "_spec", "reference", "references", "exports", "proposal", "proposals", "archive"):
        assert not (base / forbidden).exists()
    assert (base / "facts" / "operator" / "interface.yaml").exists()
    assert (base / "graphs" / "raw").is_dir()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash


def test_boundary_yaml_validates_with_source_anchor(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    source_text, source_anchor = _valid_source()
    source_path = repo / "op_host" / "demo.cpp"
    source_path.parent.mkdir()
    source_path.write_text(source_text + "\n", encoding="utf-8")
    _write_yaml(base / "facts" / "operator" / "interface.yaml", _valid_interface_doc(source_anchor))

    errors = validate_facts(repo, "DemoOp", stage="step1")

    assert errors == []


def test_missing_source_anchor_fails(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write_yaml(
        base / "facts" / "operator" / "interface.yaml",
        {
            **_valid_interface_doc(_valid_source()[1]),
            "items": [{"id": "ARG_DEMO_X", "kind": "input_tensor", "name": "x", "status": "confirmed"}],
        },
    )

    errors = validate_facts(repo, "DemoOp", stage="step1")

    assert any(error.code == "SOURCE_MISSING" for error in errors)


def test_source_text_mismatch_fails(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    source_text, source_anchor = _valid_source()
    source_path = repo / "op_host" / "demo.cpp"
    source_path.parent.mkdir()
    source_path.write_text(source_text + "\n", encoding="utf-8")
    source_anchor["source_text"] = "void Other() {}"
    source_anchor["code_hash"] = _hash_text("void Other() {}")
    _write_yaml(base / "facts" / "operator" / "interface.yaml", _valid_interface_doc(source_anchor))

    errors = validate_facts(repo, "DemoOp", stage="step1")

    assert any(error.code == "SOURCE_TEXT_MISMATCH" for error in errors)


def test_agent_owner_cannot_write_forbidden_path(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    source_text, source_anchor = _valid_source()
    source_path = repo / "op_host" / "demo.cpp"
    source_path.parent.mkdir()
    source_path.write_text(source_text + "\n", encoding="utf-8")
    doc = _valid_interface_doc(source_anchor)
    doc["artifact"]["owner"] = "uo-host-tiling-agent"
    _write_yaml(base / "facts" / "operator" / "interface.yaml", doc)

    errors = validate_facts(repo, "DemoOp", stage="step1")

    assert any(error.code in {"OWNER_MISMATCH", "OWNER_PATH_FORBIDDEN"} for error in errors)


def test_invalid_relation_type_fails(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    source_text, source_anchor = _valid_source()
    source_path = repo / "op_host" / "demo.cpp"
    source_path.parent.mkdir()
    source_path.write_text(source_text + "\n", encoding="utf-8")
    doc = _valid_interface_doc(source_anchor)
    doc["relations"] = [
        {
            "id": "REL_BAD",
            "type": "made_up_relation",
            "source_id": "ARG_DEMO_X",
            "target_id": "ARG_DEMO_X",
            "status": "confirmed",
            "sources": [source_anchor],
        }
    ]
    _write_yaml(base / "facts" / "operator" / "interface.yaml", doc)

    errors = validate_facts(repo, "DemoOp", stage="step1")

    assert any(error.code == "RELATION_TYPE_INVALID" for error in errors)


def test_step2_scoped_validators_run_independently(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    source_text, source_anchor = _valid_source()
    source_path = repo / "op_host" / "demo.cpp"
    source_path.parent.mkdir()
    source_path.write_text(source_text + "\n", encoding="utf-8")

    host_files = {
        "facts/host/variables.yaml": ("host.variables", "VAR_HOST_X"),
        "facts/host/expressions.yaml": ("host.expressions", "EXPR_HOST_X"),
        "facts/host/control_flow.yaml": ("host.control_flow", "BRANCH_HOST_X"),
        "facts/host/calls.yaml": ("host.calls", "CALL_HOST_X"),
        "facts/host/tiling_key.yaml": ("host.tiling_key", "KEY_HOST_X"),
        "facts/host/tiling_key_enumeration.yaml": ("host.tiling_key_enumeration", "KEYBLOCK_HOST_X"),
        "facts/host/tiling_key_constraints.yaml": ("host.tiling_key_constraints", "REL_HOST_X"),
        "facts/host/tilingdata_writes.yaml": ("host.tilingdata_writes", "TDWRITE_HOST_X"),
    }
    for rel, (artifact_type, item_id) in host_files.items():
        _write_yaml(base / rel, _fact_doc(artifact_type, "uo-host-tiling-agent", item_id, source_anchor))

    compute_files = {
        "facts/compute/tensors.yaml": ("compute.tensors", "TENSOR_COMPUTE_X"),
        "facts/compute/operations.yaml": ("compute.operations", "OPR_COMPUTE_X"),
        "facts/compute/dataflow.yaml": ("compute.dataflow", "REL_COMPUTE_X"),
        "facts/compute/numerical_semantics.yaml": ("compute.numerical_semantics", "ATTR_COMPUTE_X"),
    }
    for rel, (artifact_type, item_id) in compute_files.items():
        _write_yaml(base / rel, _fact_doc(artifact_type, "uo-compute-agent", item_id, source_anchor))

    kernel_files = {
        "facts/kernel/overview/entries.yaml": ("kernel.overview.entries", "KERNEL_OVERVIEW_X"),
        "facts/kernel/overview/functions.yaml": ("kernel.overview.functions", "SYM_KERNEL_X"),
        "facts/kernel/overview/call_graph.yaml": ("kernel.overview.call_graph", "CALL_KERNEL_X"),
        "facts/kernel/overview/frontier.yaml": ("kernel.overview.frontier", "BRANCH_KERNEL_X"),
        "facts/kernel/overview/global_resources.yaml": ("kernel.overview.global_resources", "BUF_KERNEL_X"),
    }
    for rel, (artifact_type, item_id) in kernel_files.items():
        _write_yaml(base / rel, _fact_doc(artifact_type, "uo-kernel-overview-agent", item_id, source_anchor))

    assert validate_facts(repo, "DemoOp", stage="step2", scope="host") == []
    assert validate_facts(repo, "DemoOp", stage="step2", scope="compute") == []
    assert validate_facts(repo, "DemoOp", stage="step2", scope="kernel-overview") == []


def test_step2_receipt_requires_three_python_gates_and_review(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write_yaml(base / "checks" / "step2" / "host_validation.yaml", _report("pass", "checks.step2.host_validation"))
    _write_yaml(base / "checks" / "step2" / "compute_validation.yaml", _report("pass", "checks.step2.compute_validation"))
    _write_yaml(base / "checks" / "step2" / "kernel_overview_validation.yaml", _report("pass", "checks.step2.kernel_overview_validation"))

    code, messages = write_step2_receipt(repo, "DemoOp")

    assert code == 2
    assert any("review.yaml" in message for message in messages)

    _write_yaml(base / "checks" / "step2" / "review.yaml", _review("fail"))
    code, messages = write_step2_receipt(repo, "DemoOp")
    assert code == 2
    assert any("status is not pass" in message for message in messages)

    _write_yaml(base / "checks" / "step2" / "review.yaml", _review("pass"))
    code, messages = write_step2_receipt(repo, "DemoOp")
    assert code == 0
    receipt = yaml.safe_load((base / "checks" / "step2" / "receipt.yaml").read_text(encoding="utf-8"))
    assert receipt["status"] == "pass"
    assert receipt["input_hashes"]["checks/step2/review.yaml"].startswith("sha256:")


def test_step3_planner_yaml_validates_with_planner_owner(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    source_anchor = _seed_source(repo)
    _seed_step3_planner(base, source_anchor)

    errors = validate_facts(repo, "DemoOp", stage="step3", scope="kernel-slice-planner")

    assert errors == []


def test_step3_slice_validation_requires_slice_directory(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    source_anchor = _seed_source(repo)
    _seed_step3_planner(base, source_anchor)

    errors = validate_facts(repo, "DemoOp", stage="step3", scope="kernel-slice")

    assert any(error.code == "KERNEL_SLICE_MISSING" for error in errors)


def test_step3_slice_yaml_requires_complete_nine_file_set(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    source_anchor = _seed_source(repo)
    _seed_step3_planner(base, source_anchor)
    _seed_kernel_slice(base, source_anchor)

    errors = validate_facts(repo, "DemoOp", stage="step3", scope="kernel-slice")

    assert errors == []


def test_step3_receipt_requires_step2_receipt_slice_validation_and_review(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write_yaml(base / "checks" / "step3" / "slice_validations.yaml", _report("pass", "checks.step3.slice_validations"))
    _write_yaml(base / "checks" / "step3" / "review.yaml", _step3_review("pass"))

    code, messages = write_step3_receipt(repo, "DemoOp")

    assert code == 2
    assert any("step2/receipt.yaml" in message for message in messages)

    _seed_step2_receipt(base)
    _write_yaml(base / "checks" / "step3" / "review.yaml", _step3_review("fail"))
    code, messages = write_step3_receipt(repo, "DemoOp")
    assert code == 2
    assert any("review.yaml status is not pass" in message for message in messages)

    _write_yaml(base / "checks" / "step3" / "review.yaml", _step3_review("pass"))
    code, messages = write_step3_receipt(repo, "DemoOp")
    assert code == 0
    receipt = yaml.safe_load((base / "checks" / "step3" / "receipt.yaml").read_text(encoding="utf-8"))
    assert receipt["status"] == "pass"
    assert receipt["input_hashes"]["checks/step2/receipt.yaml"].startswith("sha256:")


def test_compile_gate_freezes_facts_before_raw_graph_compile(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    source_anchor = _seed_source(repo)
    doc = _valid_interface_doc(source_anchor)
    doc["relations"] = [
        {
            "id": "REL_DEMO_FLOW",
            "type": "data_dependency",
            "source_id": "ARG_DEMO_X",
            "target_id": "ARG_DEMO_X",
            "status": "confirmed",
            "sources": [source_anchor],
        }
    ]
    _write_yaml(base / "facts" / "operator" / "interface.yaml", doc)
    _write_yaml(base / "checks" / "step3" / "receipt.yaml", _report("pass", "checks.step3.receipt"))

    code, messages = build_compile_gate(repo, "DemoOp")
    assert code == 0, messages
    code, messages = compile_source_graph(repo, "DemoOp")
    assert code == 0, messages
    assert (base / "graphs" / "raw" / "nodes.yaml").exists()
    assert (base / "indexes" / "graph_to_yaml.yaml").exists()

    doc["items"][0]["name"] = "changed_after_gate"
    _write_yaml(base / "facts" / "operator" / "interface.yaml", doc)
    code, messages = compile_source_graph(repo, "DemoOp")
    assert code == 2
    assert any("facts changed after compile gate" in message for message in messages)


def test_derived_graph_materializer_requires_reversible_rules_and_query_is_readonly(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    source_anchor = _seed_source(repo)
    _write_yaml(base / "facts" / "operator" / "interface.yaml", _valid_interface_doc(source_anchor))
    _write_yaml(base / "checks" / "step3" / "receipt.yaml", _report("pass", "checks.step3.receipt"))
    assert build_compile_gate(repo, "DemoOp")[0] == 0
    assert compile_source_graph(repo, "DemoOp")[0] == 0

    _write_yaml(
        base / "graphs" / "derived" / "abstraction_rules.yaml",
        {
            "version": 1,
            "artifact": {"type": "graph.derived.abstraction_rules", "schema_version": 1, "owner": "derived-graph-materializer"},
            "snapshot": {
                "run_id": "UO_RUN_TEST",
                "source_snapshot_id": "SOURCE_TEST",
                "source_revision": "abc123",
                "spec_bundle_hash": spec_bundle_hash(),
            },
            "rules": [
                {
                    "id": "ARULE_DEMO_ABSTRACT",
                    "reversible": True,
                    "node_id": "DVIEW_DEMO_INPUT",
                    "abstract_type": "operator_input",
                    "abstract_name": "x",
                    "raw_node_refs": ["ARG_DEMO_X"],
                    "raw_edge_refs": [],
                    "yaml_refs": ["facts/operator/interface.yaml#/items/0"],
                    "reason": "single input fact abstraction",
                }
            ],
            "items": [],
            "relations": [],
            "unresolved": [],
        },
    )

    code, messages = materialize_derived_graph(repo, "DemoOp")
    assert code == 0, messages
    result = query_readonly(repo, "DemoOp", "DVIEW_DEMO_INPUT")
    assert result["query"]["order"] == ["derived", "raw", "yaml", "source"]
    assert result["writes"] == []
    assert result["cbm_writes"] == []
    assert result["yaml_items"][0]["ref"] == "facts/operator/interface.yaml#/items/0"
