"""Serial vs parallel host/kernel extraction must be byte-equivalent after normalization."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.build_layered_kb import build_layered_kb
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
    stats.pop("timing_ms", None)
    stats.pop("macro_materialization", None)
    stats.pop("build_mode", None)
    out["stats"] = stats
    return out


def test_parallel_host_kernel_determinism(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "op"
    repo.mkdir()
    op = "DemoOp"
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    ir = root / "ir"
    write_entrypoint_graph(ir, op_name=op, host_name="Host", kernel_name="Kernel")
    write_yaml(
        ir / "extract_plan.yaml",
        {"version": 1, "op_name": op, "host": {"chain": []}, "kernel": {"roots": []}},
    )
    write_yaml(ir / "tilingkey_space.yaml", {"nodes": [], "edges": [], "dimensions": [], "template_blocks": []})

    host_payload = {"nodes": [{"id": "H1", "layer": "host", "node_type": "Host", "name": "h"}], "edges": [], "unresolved": []}
    kernel_payload = {
        "nodes": [{"id": "K1", "layer": "kernel", "node_type": "Kernel", "name": "k"}],
        "edges": [],
        "unresolved": [],
        "branches": [],
    }

    def fake_parallel(repo_root, op_name, *, architecture="arch35", allow_empty_plan=False, parallel=None):  # type: ignore[no-untyped-def]
        return host_payload, kernel_payload, {"host": 1, "kernel": 1}

    def fake_serial_host(*a, **k):  # type: ignore[no-untyped-def]
        return host_payload

    def fake_serial_kernel(*a, **k):  # type: ignore[no-untyped-def]
        return kernel_payload

    monkeypatch.setattr("uo.scripts.build_layered_kb.reconcile_bridge", lambda *a, **k: {"bridge_nodes": [], "bridge_edges": [], "unresolved": [], "diagnostics": []})
    monkeypatch.setattr(
        "uo.scripts.macro_semantic_materializer.materialize_macro_semantics",
        lambda *a, **k: {
            "macro_materialization": {"status": "skipped", "timing_ms": 0},
            "entrypoint_graph": read_yaml(ir / "entrypoint_graph.yaml"),
        },
    )

    monkeypatch.setattr("uo.scripts.parallel_layer_extract.extract_host_kernel_parallel", fake_parallel)
    parallel_graph = build_layered_kb(
        repo, op, layers={"host", "kernel", "bridge"}, allow_empty_plan=True, mode="structural", parallel=True
    )

    monkeypatch.setattr("uo.scripts.build_layered_kb.extract_host_subgraph", fake_serial_host)
    monkeypatch.setattr("uo.scripts.build_layered_kb.extract_kernel_subgraph", fake_serial_kernel)
    serial_graph = build_layered_kb(
        repo, op, layers={"host", "kernel", "bridge"}, allow_empty_plan=True, mode="structural", parallel=False
    )

    assert json.dumps(_normalize_graph(parallel_graph), sort_keys=True) == json.dumps(
        _normalize_graph(serial_graph), sort_keys=True
    )
