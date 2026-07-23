"""Shared helpers to write entrypoint_graph fixtures (no selected contract)."""

from __future__ import annotations

from typing import Any

from uo.scripts._ir_io import write_yaml
from uo.scripts.semantic_identity import mint_symbol_identity


def write_entrypoint_graph(
    ir_dir,
    *,
    op_name: str,
    architecture: str = "arch35",
    host_name: str = "FooTiling",
    host_file: str = "op_host/arch35/foo_tiling.cpp",
    host_line: int = 2,
    kernel_name: str = "FooKernel",
    kernel_file: str = "op_kernel/arch35/foo_kernel.h",
    kernel_line: int = 2,
    host_closed: bool = True,
    kernel_closed: bool = True,
) -> dict[str, Any]:
    host_id = mint_symbol_identity(
        kind="entrypoint",
        name=host_name,
        file_path=host_file,
        qualified_name=host_name,
        architecture=architecture,
        path_family="normal",
        prefix="EP",
    ).stable_id
    kernel_id = mint_symbol_identity(
        kind="entrypoint",
        name=kernel_name,
        file_path=kernel_file,
        qualified_name=kernel_name,
        architecture=architecture,
        path_family="normal",
        prefix="EP",
    ).stable_id
    reg_id = mint_symbol_identity(
        kind="registration",
        name=op_name,
        file_path=host_file,
        qualified_name=f"REG_OP::{op_name}",
        architecture="neutral",
        path_family="shared",
        prefix="EP",
    ).stable_id
    nodes = [
        {
            "id": reg_id,
            "role": "operator_registration",
            "architecture": "neutral",
            "path_family": "shared",
            "template_family": "shared",
            "status": "closed" if host_closed else "verified",
            "name": op_name,
            "locator": {"file_path": host_file, "start_line": 1, "end_line": 1},
            "symbol_ref": {"qualified_name": f"REG_OP::{op_name}", "identity_key": "reg"},
        },
        {
            "id": host_id,
            "role": "public_host_entry",
            "architecture": architecture,
            "path_family": "normal",
            "template_family": "normal",
            "status": "closed" if host_closed else "verified",
            "name": host_name,
            "locator": {"file_path": host_file, "start_line": host_line, "end_line": host_line + 4},
            "symbol_ref": {
                "qualified_name": host_name,
                "identity_key": host_id,
                "stable_id": host_id,
            },
        },
        {
            "id": kernel_id,
            "role": "public_kernel_entry",
            "architecture": architecture,
            "path_family": "normal",
            "template_family": "normal",
            "status": "closed" if kernel_closed else "verified",
            "name": kernel_name,
            "locator": {"file_path": kernel_file, "start_line": kernel_line, "end_line": kernel_line + 8},
            "symbol_ref": {
                "qualified_name": kernel_name,
                "identity_key": kernel_id,
                "stable_id": kernel_id,
            },
        },
    ]
    edges = [
        {
            "id": "E1",
            "type": "registers",
            "source": reg_id,
            "target": host_id,
            "confidence": "verified",
            "evidence": [],
        },
        {
            "id": "E2",
            "type": "dispatches_to",
            "source": host_id,
            "target": host_id,
            "confidence": "candidate",
            "evidence": [],
        },
    ]
    graph = {
        "version": 2,
        "op_name": op_name,
        "architecture": architecture,
        "nodes": nodes,
        "edges": edges,
        "roots": [reg_id, host_id, kernel_id],
        "extraction_units": [
            {
                "id": "UNIT_HOST",
                "architecture": architecture,
                "path_family": "normal",
                "template_family": "normal",
                "entry_root": host_id,
                "member_nodes": [host_id, reg_id],
            },
            {
                "id": "UNIT_KERN",
                "architecture": architecture,
                "path_family": "normal",
                "template_family": "normal",
                "entry_root": kernel_id,
                "member_nodes": [kernel_id],
            },
        ],
        "closure": {
            "host_main_chain": "closed" if host_closed else "unresolved",
            "kernel_main_chain": "closed" if kernel_closed else "unresolved",
            "blocking_unresolved": [],
        },
        "tiling_templates": [],
    }
    write_yaml(ir_dir / "entrypoint_graph.yaml", graph)
    return graph
