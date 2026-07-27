"""Incremental layer rebuild mapping tests."""

from __future__ import annotations

from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.semantic_resolution_ledger import PATCH_TYPE_TO_LAYERS, select_layers_for_rebuild


def _uo_with_ledger(tmp_path: Path) -> Path:
    repo = tmp_path / "op"
    repo.mkdir()
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    ir = root / "ir"
    write_yaml(ir / "layer_input_fingerprints.yaml", {"version": 1, "layers": {}})
    write_yaml(
        ir / "semantic_resolution_ledger.yaml",
        {
            "version": 1,
            "semantic_patches": [
                {
                    "task_id": "t1",
                    "run_id": "run-1",
                    "patch_type": "entrypoint_node_resolution",
                    "status": "active",
                }
            ],
        },
    )
    return root


def test_entrypoint_patch_affects_entrypoints_and_bridge(tmp_path: Path) -> None:
    uo = _uo_with_ledger(tmp_path)
    plan = select_layers_for_rebuild(
        uo,
        architecture="arch35",
        source_snapshot="snap",
        current_run_id="run-1",
    )
    layers = set(plan.get("layers") or [])
    assert "entrypoints" in layers
    assert "bridge" in layers
    assert "kernel" not in layers or "entrypoints" in PATCH_TYPE_TO_LAYERS["entrypoint_node_resolution"]


def test_kernel_patch_mapping() -> None:
    mapped = PATCH_TYPE_TO_LAYERS["call_edge_resolution"]
    assert mapped == {"host", "kernel", "bridge", "entrypoints"}


def test_tilingkey_patch_mapping() -> None:
    mapped = PATCH_TYPE_TO_LAYERS["template_instance_resolution"]
    assert mapped == {"tilingkey", "kernel", "bridge"}
