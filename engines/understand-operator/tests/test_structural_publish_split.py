"""Tests for structural vs full build_layered_kb and publish split."""

from __future__ import annotations

from pathlib import Path

import pytest

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.build_layered_kb import build_layered_kb
from tests._entrypoint_fixtures import write_entrypoint_graph


@pytest.fixture()
def layered_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "op"
    repo.mkdir()
    op = "DemoOp"
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    ir = root / "ir"
    write_entrypoint_graph(
        ir,
        op_name=op,
        host_name="DoOpTiling",
        kernel_name="DemoKernel",
    )
    write_yaml(
        ir / "extract_plan.yaml",
        {
            "version": 1,
            "op_name": op,
            "host": {"chain": []},
            "kernel": {"roots": []},
            "tilingkey": {},
        },
    )
    write_yaml(
        ir / "tilingkey_space.yaml",
        {"nodes": [], "edges": [], "unresolved": [], "dimensions": [], "template_blocks": []},
    )
    write_yaml(ir / "host_subgraph.yaml", {"nodes": [], "edges": [], "unresolved": []})
    write_yaml(
        ir / "kernel_subgraph.yaml",
        {"nodes": [], "edges": [], "unresolved": [], "branches": []},
    )
    write_yaml(
        ir / "bridge.yaml",
        {"bridge_nodes": [], "bridge_edges": [], "unresolved": [], "diagnostics": []},
    )
    return repo, op


def test_structural_mode_skips_publish_products(layered_repo: tuple[Path, str], monkeypatch) -> None:
    repo, op = layered_repo
    uo = operator_root(repo, op)
    sqlite = uo / "indexes" / "kb_graph.sqlite"
    human = uo / "summary" / "keys_table.yaml"
    if sqlite.is_file():
        sqlite.unlink()
    if human.is_file():
        human.unlink()

    monkeypatch.setattr(
        "uo.scripts.build_layered_kb.extract_host_subgraph",
        lambda *a, **k: {"nodes": [], "edges": [], "unresolved": []},
    )
    monkeypatch.setattr(
        "uo.scripts.build_layered_kb.extract_kernel_subgraph",
        lambda *a, **k: {"nodes": [], "edges": [], "unresolved": [], "branches": []},
    )
    monkeypatch.setattr(
        "uo.scripts.build_layered_kb.reconcile_bridge",
        lambda *a, **k: {"bridge_nodes": [], "bridge_edges": [], "unresolved": [], "diagnostics": []},
    )

    graph = build_layered_kb(
        repo,
        op,
        layers={"host", "kernel", "bridge"},
        allow_empty_plan=True,
        mode="structural",
        parallel=False,
    )
    assert (uo / "ir" / "operator_graph.yaml").is_file()
    assert (uo / "ir" / "closure_summary.yaml").is_file()
    assert not sqlite.is_file()
    assert graph.get("stats", {}).get("build_mode") == "structural"


def test_full_mode_publishes_products(layered_repo: tuple[Path, str], monkeypatch) -> None:
    repo, op = layered_repo
    uo = operator_root(repo, op)

    monkeypatch.setattr(
        "uo.scripts.build_layered_kb.extract_host_subgraph",
        lambda *a, **k: {"nodes": [], "edges": [], "unresolved": []},
    )
    monkeypatch.setattr(
        "uo.scripts.build_layered_kb.extract_kernel_subgraph",
        lambda *a, **k: {"nodes": [], "edges": [], "unresolved": [], "branches": []},
    )
    monkeypatch.setattr(
        "uo.scripts.build_layered_kb.reconcile_bridge",
        lambda *a, **k: {"bridge_nodes": [], "bridge_edges": [], "unresolved": [], "diagnostics": []},
    )
    publish_calls: list[dict] = []

    def _fake_publish(*a, **k):  # type: ignore[no-untyped-def]
        publish_calls.append({"args": a, "kwargs": k})
        return {
            "ok": True,
            "kb_graph": {"status": "ok", "entity_count": 1, "relation_count": 0},
            "human_views": {"keys_table": {"key_count": 0}, "ktpl_count": 0},
        }

    monkeypatch.setattr("uo.scripts.publish_kb_products.publish_kb_products", _fake_publish)

    graph = build_layered_kb(
        repo,
        op,
        layers={"host", "kernel", "bridge"},
        allow_empty_plan=True,
        mode="full",
        parallel=False,
    )
    # Publish stats live in publish_receipt.yaml, not structural operator_graph.stats.
    assert publish_calls, "full mode must call publish_kb_products"
    assert "kb_graph" not in (graph.get("stats") or {})
    assert graph.get("stats", {}).get("build_mode") == "full"
