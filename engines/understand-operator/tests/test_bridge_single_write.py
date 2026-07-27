"""Bridge YAML must be written exactly once per build."""

from __future__ import annotations

from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.build_layered_kb import build_layered_kb
from tests._entrypoint_fixtures import write_entrypoint_graph


def test_bridge_single_write(tmp_path: Path, monkeypatch) -> None:
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

    bridge_writes: list[str] = []
    real_write = write_yaml

    def counting_write(path: Path, data):  # type: ignore[no-untyped-def]
        if path.name == "bridge.yaml":
            bridge_writes.append(str(path))
        return real_write(path, data)

    monkeypatch.setattr("uo.scripts.build_layered_kb.write_yaml_if_changed", counting_write)
    monkeypatch.setattr(
        "uo.scripts.build_layered_kb.extract_host_subgraph",
        lambda *a, **k: {"nodes": [], "edges": [], "unresolved": []},
    )
    monkeypatch.setattr(
        "uo.scripts.build_layered_kb.extract_kernel_subgraph",
        lambda *a, **k: {"nodes": [], "edges": [], "unresolved": [], "branches": []},
    )

    payload = {
        "version": 2,
        "bridge_nodes": [],
        "bridge_edges": [],
        "unresolved": [],
        "diagnostics": [],
    }

    def fake_reconcile(*args, persist=True, **kwargs):  # type: ignore[no-untyped-def]
        assert persist is False
        return payload

    monkeypatch.setattr("uo.scripts.build_layered_kb.reconcile_bridge", fake_reconcile)

    build_layered_kb(
        repo,
        op,
        layers={"bridge"},
        allow_empty_plan=True,
        mode="structural",
        parallel=False,
    )
    assert len(bridge_writes) == 1
