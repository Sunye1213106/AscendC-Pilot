from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from understand_operator._operator.artifacts import init_operator_contract_layout, operator_root
from understand_operator._operator.spec import spec_bundle_hash
from understand_operator.scripts.phase1_graph import SearchLimits, run_phase1_graph


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    manifest = yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["current_run_id"] = "UO_RUN_TEST"
    manifest["source"]["revision"] = "unknown"
    manifest["source"]["snapshot_id"] = "SOURCE_TEST"
    (root / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    phase0 = root / "runs" / "UO_RUN_TEST" / "phase0"
    snapshot = {"run_id": "UO_RUN_TEST", "source_snapshot_id": "SOURCE_TEST", "source_revision": "unknown", "spec_bundle_hash": spec_bundle_hash()}
    _write_yaml(
        phase0 / "scope_confirmed.yaml",
        {
            "version": 1,
            "artifact": {"type": "runs.scope_confirmed", "schema_version": 1, "owner": "uo-orchestrator"},
            "snapshot": snapshot,
            "status": "confirmed",
            "operator": "DemoOp",
            "confirmed_file_list": [
                {"path": "op_host/demo.cpp", "role": "host"},
                {"path": "op_kernel/demo.cpp", "role": "kernel"},
            ],
            "excluded_files": [],
            "analysis_scope": {"host": ["op_host/demo.cpp"], "kernel": ["op_kernel/demo.cpp"]},
            "cbm": {"indexing_allowed": True, "input": "confirmed_file_list"},
        },
    )
    _write_yaml(
        phase0 / "entry_points.yaml",
        {
            "version": 1,
            "artifact": {"type": "runs.entry_points", "schema_version": 1, "owner": "uo-orchestrator"},
            "snapshot": snapshot,
            "status": "complete",
            "input": {"files": ["op_host/demo.cpp"], "symbols": ["x"], "optional": []},
            "output": {"files": ["op_host/demo.cpp"], "symbols": ["y"]},
            "attributes": {"files": ["op_host/demo.cpp"], "symbols": ["scale"]},
            "host": {"file": ["op_host/demo.cpp"], "entry": ["DemoTiling"]},
            "tiling": {"key": {"file": ["op_host/demo.cpp"]}, "data": {"file": []}},
            "kernel": {"file": ["op_kernel/demo.cpp"], "entry": ["DemoKernel"]},
        },
    )
    _write_yaml(phase0 / "receipt.yaml", {"version": 1, "artifact": {"type": "runs.receipt", "schema_version": 1, "owner": "uo-orchestrator"}, "snapshot": snapshot, "status": "pass", "source": {}, "finalized_at": "2026-01-01T00:00:00+00:00", "frozen_scope": {}, "cbm": {}, "input_hashes": {}})
    (root / "cbm" / "index_meta.json").write_text(
        json.dumps({"repo_root": str(repo), "op_name": "DemoOp", "cbm_project": "demo", "indexed_via": "mcp", "index_input": "confirmed_file_list", "indexed_files": [{"path": "op_host/demo.cpp"}, {"path": "op_kernel/demo.cpp"}], "project_confirmed": True}),
        encoding="utf-8",
    )
    return repo, root


def _raw_graph(path: Path) -> None:
    nodes = [
        {"id": "n_input", "raw_type": "input", "semantic_type": "input", "symbol": "x", "path": "op_host/demo.cpp", "start_line": 1},
        {"id": "n_pred", "raw_type": "predicate", "semantic_type": "predicate", "symbol": "is_arch35", "path": "op_host/demo.cpp", "start_line": 2, "source_text": "ARCH35"},
        {"id": "n_tiling", "raw_type": "tiling_key", "semantic_type": "tiling_key", "symbol": "key35", "path": "op_host/demo.cpp", "start_line": 3, "architecture_context": ["arch35"]},
        {"id": "n_dispatch", "raw_type": "kernel_dispatch", "semantic_type": "kernel_dispatch", "symbol": "DemoKernel", "path": "op_host/demo.cpp", "start_line": 4, "architecture_context": ["arch35"]},
        {"id": "n_arch22", "raw_type": "tiling_key", "semantic_type": "tiling_key", "symbol": "key22", "path": "op_host/arch22.cpp", "start_line": 1, "architecture_context": ["arch22"]},
        {"id": "k_entry", "raw_type": "kernel_entry", "semantic_type": "kernel_entry", "symbol": "DemoKernel", "path": "op_kernel/arch35/demo.cpp", "start_line": 1},
        {"id": "k_copyin", "raw_type": "copy_in", "semantic_type": "copy_in", "symbol": "CopyIn", "path": "op_kernel/arch35/demo.cpp", "start_line": 2},
        {"id": "k_compute", "raw_type": "compute", "semantic_type": "compute", "symbol": "Compute", "path": "op_kernel/arch35/demo.cpp", "start_line": 3},
        {"id": "k_copyout", "raw_type": "copy_out", "semantic_type": "copy_out", "symbol": "CopyOut", "path": "op_kernel/arch35/demo.cpp", "start_line": 4},
        {"id": "k_output", "raw_type": "output", "semantic_type": "output", "symbol": "y", "path": "op_kernel/arch35/demo.cpp", "start_line": 5},
        {"id": "debug", "raw_type": "call", "semantic_type": "function_call", "symbol": "DebugPrint", "path": "op_host/demo.cpp", "start_line": 99},
    ]
    edges = [
        {"id": "e1", "source": "n_input", "target": "n_pred", "raw_type": "data_flow"},
        {"id": "e2", "source": "n_pred", "target": "n_tiling", "raw_type": "control"},
        {"id": "e3", "source": "n_tiling", "target": "n_dispatch", "raw_type": "data_flow"},
        {"id": "e4", "source": "n_input", "target": "debug", "raw_type": "calls"},
        {"id": "e5", "source": "n_tiling", "target": "k_entry", "raw_type": "dispatch"},
        {"id": "e6", "source": "k_entry", "target": "k_copyin", "raw_type": "calls"},
        {"id": "e7", "source": "k_copyin", "target": "k_compute", "raw_type": "data_flow"},
        {"id": "e8", "source": "k_compute", "target": "k_copyout", "raw_type": "data_flow"},
        {"id": "e9", "source": "k_copyout", "target": "k_output", "raw_type": "data_flow"},
        {"id": "e10", "source": "k_compute", "target": "k_copyin", "raw_type": "loop"},
        {"id": "e11", "source": "n_input", "target": "n_arch22", "raw_type": "control"},
    ]
    _write_yaml(path, {"nodes": nodes, "edges": edges})


def test_phase1_graph_prunes_arch_and_preserves_mappings(tmp_path: Path) -> None:
    repo, root = _repo(tmp_path)
    raw = tmp_path / "raw.yaml"
    _raw_graph(raw)

    result = run_phase1_graph(repo, "DemoOp", architecture="arch35", raw_graph_path=raw, limits=SearchLimits(max_depth=20, max_paths_per_root=100, max_total_nodes=1000))

    graph_dir = root / "graph"
    assert (graph_dir / "raw_candidate_nodes.yaml").exists()
    assert (graph_dir / "host_tiling_graph.yaml").exists()
    assert (graph_dir / "kernel_execution_graph.yaml").exists()
    removed = yaml.safe_load((graph_dir / "removed_nodes.yaml").read_text(encoding="utf-8"))["nodes"]
    assert any(item["mcp_node_id"] == "n_arch22" and item["removal_reason"] == "non_arch35_branch" for item in removed)
    assert any(item["mcp_node_id"] == "debug" for item in removed)
    host = yaml.safe_load((graph_dir / "host_tiling_graph.yaml").read_text(encoding="utf-8"))
    kernel = yaml.safe_load((graph_dir / "kernel_execution_graph.yaml").read_text(encoding="utf-8"))
    assert host["node_count"] >= 3
    assert kernel["node_count"] >= 4
    assert all(node["source_nodes"] for node in host["nodes"] + kernel["nodes"])
    assert all(edge["source_edges"] or edge["derived_from_path"] for edge in host["edges"] + kernel["edges"])
    assert result["graph_comparison.yaml"]["kernel_execution_graph"]["paths"] >= 1


def test_phase1_graph_records_mcp_unavailable_without_scope_expansion(tmp_path: Path) -> None:
    repo, root = _repo(tmp_path)
    (repo / "op_host").mkdir()
    (repo / "op_host" / "demo.cpp").write_text("auto input = GetInput();\nSetTilingKey(35);\nLaunchKernel();\n", encoding="utf-8")
    (repo / "op_kernel").mkdir()
    (repo / "op_kernel" / "demo.cpp").write_text("__global__ void DemoKernel() {}\nDataCopy(x, y, z);\nCopyOut();\n", encoding="utf-8")

    run_phase1_graph(repo, "DemoOp", architecture="arch35", raw_graph_path=None, limits=SearchLimits(max_depth=20, max_paths_per_root=100, max_total_nodes=1000))

    issues = yaml.safe_load((root / "graph" / "graph_issues.yaml").read_text(encoding="utf-8"))["issues"]
    assert any(item["issue"] == "mcp_raw_graph_unavailable" for item in issues)
    raw_nodes = yaml.safe_load((root / "graph" / "raw_candidate_nodes.yaml").read_text(encoding="utf-8"))["nodes"]
    assert {node["path"] for node in raw_nodes} <= {"op_host/demo.cpp", "op_kernel/demo.cpp"}
