"""Serial vs parallel host/kernel (and kernel file) extraction must be equivalent."""

from __future__ import annotations

import json
from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.build_layered_kb import build_layered_kb
from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph
from uo.scripts.parallel_layer_extract import extract_host_kernel_parallel
from tests._entrypoint_fixtures import write_entrypoint_graph


def _normalize_graph(graph: dict) -> dict:
    out = dict(graph)
    for key in ("nodes", "edges", "unresolved"):
        items = list(out.get(key) or [])
        if key == "nodes":
            items.sort(
                key=lambda n: (
                    str(n.get("layer") or ""),
                    str(n.get("role") or n.get("node_type") or ""),
                    str(n.get("file_path") or ""),
                    int(n.get("start_line") or 0),
                    str(n.get("id") or ""),
                )
            )
        elif key == "edges":
            items.sort(
                key=lambda e: (
                    str(e.get("type") or ""),
                    str(e.get("source") or ""),
                    str(e.get("target") or ""),
                    str(e.get("id") or ""),
                )
            )
        else:
            items.sort(
                key=lambda u: (
                    str(u.get("kind") or ""),
                    str(u.get("file_path") or ""),
                    str(u.get("id") or ""),
                )
            )
        out[key] = items
    stats = dict(out.get("stats") or {})
    for drop in (
        "timing_ms",
        "macro_materialization",
        "build_mode",
        "host_kernel_parallel",
        "parallel_enabled",
        "parallel_used",
        "parallel_fallback",
        "parallel_fallback_reason",
        "host_kernel_wall_ms",
        "rebuild_input_fingerprint",
        "layer_input_fingerprints",
    ):
        stats.pop(drop, None)
    out["stats"] = stats
    out.pop("rebuild_layers", None)
    return out


def _normalize_subgraph(payload: dict) -> dict:
    out = dict(payload)
    for key in ("nodes", "edges", "unresolved", "branches"):
        items = list(out.get(key) or [])
        items.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))
        out[key] = items
    out.pop("timing_ms", None)
    out.pop("_worker_ms", None)
    return out


def _setup_multi_file_op(tmp_path: Path) -> tuple[Path, str]:
    op = "demo_parallel_op"
    repo = tmp_path / op
    host = repo / "op_host" / "arch35"
    kernel = repo / "op_kernel" / "arch35"
    host.mkdir(parents=True)
    kernel.mkdir(parents=True)

    (host / "demo_tiling.cpp").write_text(
        """
void DemoTiling() {
  SaveStuff();
  GetTilingKey();
}

void SaveStuff() {
  blob_->set_x(1);
}

void GetTilingKey() {
  context->SetTilingKey(1);
}
""",
        encoding="utf-8",
    )
    (kernel / "demo_a_kernel.h").write_text(
        """
class DemoKernelA {
  void Process() {
    auto v = tilingData->base.layout;
    if (v) { DoA(); }
  }
  void DoA() {}
};
""",
        encoding="utf-8",
    )
    (kernel / "demo_b_kernel.h").write_text(
        """
class DemoKernelB {
  void Process() {
    auto w = tilingData->base.mode;
    for (int i = 0; i < n; ++i) { DoB(); }
  }
  void DoB() {}
};
""",
        encoding="utf-8",
    )

    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    ir = root / "ir"
    write_entrypoint_graph(
        ir,
        op_name=op,
        host_name="DemoTiling",
        host_file="op_host/arch35/demo_tiling.cpp",
        host_line=2,
        kernel_name="DemoKernelA",
        kernel_file="op_kernel/arch35/demo_a_kernel.h",
        kernel_line=2,
    )
    # Second kernel entry so file-level parallel has ≥2 files via seeds + glob.
    eg = __import__("uo.scripts._ir_io", fromlist=["read_yaml"]).read_yaml(ir / "entrypoint_graph.yaml")
    from uo.scripts.semantic_identity import mint_symbol_identity

    kb = mint_symbol_identity(
        kind="entrypoint",
        name="DemoKernelB",
        file_path="op_kernel/arch35/demo_b_kernel.h",
        qualified_name="DemoKernelB",
        architecture="arch35",
        path_family="normal",
        prefix="EP",
    )
    nodes = list(eg.get("nodes") or [])
    nodes.append(
        {
            "id": kb.stable_id,
            "role": "public_kernel_entry",
            "architecture": "arch35",
            "path_family": "normal",
            "template_family": "normal",
            "status": "closed",
            "name": "DemoKernelB",
            "locator": {
                "file_path": "op_kernel/arch35/demo_b_kernel.h",
                "start_line": 2,
                "end_line": 10,
            },
            "symbol_ref": {**kb.as_dict(), "stable_id": kb.stable_id},
        }
    )
    eg["nodes"] = nodes
    units = list(eg.get("extraction_units") or [])
    units.append(
        {
            "id": "UNIT_B",
            "architecture": "arch35",
            "path_family": "normal",
            "template_family": "normal",
            "entry_root": kb.stable_id,
            "member_nodes": [kb.stable_id],
        }
    )
    eg["extraction_units"] = units
    write_yaml(ir / "entrypoint_graph.yaml", eg)
    write_yaml(
        ir / "extract_plan.yaml",
        {
            "version": 1,
            "confirmed_by": "test",
            "writers": [],
            "receivers": [],
            "aliases": [],
            "non_sink_roots": [],
            "extra_host_entries": [],
        },
    )
    write_yaml(ir / "tilingkey_space.yaml", {"nodes": [], "edges": [], "dimensions": [], "template_blocks": []})
    write_yaml(ir / "operator_boundary.yaml", {"inputs": [], "attributes": [], "outputs": []})
    return repo, op


def test_kernel_file_parallel_determinism(tmp_path: Path) -> None:
    repo, op = _setup_multi_file_op(tmp_path)
    serial = extract_kernel_subgraph(repo, op, architecture="arch35", file_parallel=False)
    parallel = extract_kernel_subgraph(repo, op, architecture="arch35", file_parallel=True)
    assert json.dumps(_normalize_subgraph(serial), sort_keys=True, default=str) == json.dumps(
        _normalize_subgraph(parallel), sort_keys=True, default=str
    )
    fn_nodes = [n for n in serial.get("nodes") or [] if n.get("node_type") in {"FunctionDefinition", "Process"}]
    assert len(fn_nodes) >= 2


def test_host_kernel_layer_parallel_determinism(tmp_path: Path) -> None:
    repo, op = _setup_multi_file_op(tmp_path)
    host_s, kernel_s, timing_s = extract_host_kernel_parallel(
        repo, op, architecture="arch35", allow_empty_plan=True, parallel=False
    )
    host_p, kernel_p, timing_p = extract_host_kernel_parallel(
        repo, op, architecture="arch35", allow_empty_plan=True, parallel=True
    )
    assert timing_s.get("parallel_used") is False
    assert "parallel_fallback" in timing_p
    assert timing_p.get("parallel_fallback_reason") == "" or timing_p.get("parallel_fallback") is True
    assert json.dumps(_normalize_subgraph(host_s), sort_keys=True, default=str) == json.dumps(
        _normalize_subgraph(host_p), sort_keys=True, default=str
    )
    assert json.dumps(_normalize_subgraph(kernel_s), sort_keys=True, default=str) == json.dumps(
        _normalize_subgraph(kernel_p), sort_keys=True, default=str
    )


def test_build_layered_kb_parallel_determinism(tmp_path: Path) -> None:
    repo, op = _setup_multi_file_op(tmp_path)
    serial_graph = build_layered_kb(
        repo, op, layers={"host", "kernel", "bridge"}, allow_empty_plan=True, mode="structural", parallel=False
    )
    parallel_graph = build_layered_kb(
        repo, op, layers={"host", "kernel", "bridge"}, allow_empty_plan=True, mode="structural", parallel=True
    )
    assert json.dumps(_normalize_graph(serial_graph), sort_keys=True, default=str) == json.dumps(
        _normalize_graph(parallel_graph), sort_keys=True, default=str
    )
    ir = operator_root(repo, op) / "ir"
    for name in ("host_subgraph.yaml", "kernel_subgraph.yaml", "bridge.yaml", "operator_graph.yaml", "unresolved.yaml"):
        assert (ir / name).is_file()
