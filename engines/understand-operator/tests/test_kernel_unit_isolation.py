"""Kernel subgraph must scope markers/branches per extraction unit, not one global entry."""

from __future__ import annotations

from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph
from uo.scripts.semantic_identity import mint_symbol_identity


def _write_multi_unit_graph(ir_dir: Path, *, arch: str = "arch35") -> None:
    normal_k = mint_symbol_identity(
        kind="entrypoint",
        name="DemoKernelNormal",
        file_path="op_kernel/arch35/demo_normal.h",
        qualified_name="DemoKernelNormal",
        path_family="normal",
        architecture=arch,
        prefix="EP",
    )
    varlen_k = mint_symbol_identity(
        kind="entrypoint",
        name="DemoKernelVarlen",
        file_path="op_kernel/arch35/demo_varlen.h",
        qualified_name="DemoKernelVarlen",
        path_family="varlen",
        architecture=arch,
        prefix="EP",
    )
    empty_k = mint_symbol_identity(
        kind="entrypoint",
        name="DemoKernelEmpty",
        file_path="op_kernel/arch35/demo_empty.h",
        qualified_name="DemoKernelEmpty",
        path_family="empty",
        architecture=arch,
        prefix="EP",
    )

    def _node(ident, role: str, name: str, fp: str, family: str) -> dict:
        return {
            "id": ident.stable_id,
            "role": role,
            "architecture": arch,
            "path_family": family,
            "template_family": family,
            "status": "verified",
            "name": name,
            "locator": {"file_path": fp, "start_line": 2, "end_line": 20},
            "symbol_ref": {**ident.as_dict(), "stable_id": ident.stable_id},
        }

    nodes = [
        _node(normal_k, "public_kernel_entry", "DemoKernelNormal", "op_kernel/arch35/demo_normal.h", "normal"),
        _node(varlen_k, "public_kernel_entry", "DemoKernelVarlen", "op_kernel/arch35/demo_varlen.h", "varlen"),
        _node(empty_k, "public_kernel_entry", "DemoKernelEmpty", "op_kernel/arch35/demo_empty.h", "empty"),
    ]
    write_yaml(
        ir_dir / "entrypoint_graph.yaml",
        {
            "version": 2,
            "architecture": arch,
            "nodes": nodes,
            "edges": [],
            "extraction_units": [
                {
                    "id": "UNIT_NORMAL",
                    "architecture": arch,
                    "path_family": "normal",
                    "template_family": "normal",
                    "entry_root": normal_k.stable_id,
                    "member_nodes": [normal_k.stable_id],
                },
                {
                    "id": "UNIT_VARLEN",
                    "architecture": arch,
                    "path_family": "varlen",
                    "template_family": "varlen",
                    "entry_root": varlen_k.stable_id,
                    "member_nodes": [varlen_k.stable_id],
                },
                {
                    "id": "UNIT_EMPTY",
                    "architecture": arch,
                    "path_family": "empty",
                    "template_family": "empty",
                    "entry_root": empty_k.stable_id,
                    "member_nodes": [empty_k.stable_id],
                },
            ],
            "closure": {"host_main_chain": "closed", "kernel_main_chain": "closed", "blocking_unresolved": []},
        },
    )


def test_kernel_subgraph_multiple_entries_not_single_kpath(tmp_path: Path) -> None:
    op = "demo_multi_kernel"
    repo = tmp_path / op
    kdir = repo / "op_kernel" / "arch35"
    kdir.mkdir(parents=True)
    (kdir / "demo_normal.h").write_text(
        "class DemoKernelNormal { void Process() { if (x) {} } void Init() {} };\n",
        encoding="utf-8",
    )
    (kdir / "demo_varlen.h").write_text(
        "class DemoKernelVarlen { void Process() { for (int i=0;i<n;++i) {} } };\n",
        encoding="utf-8",
    )
    (kdir / "demo_empty.h").write_text(
        "class DemoKernelEmpty { void Process() {} };\n",
        encoding="utf-8",
    )

    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    ir = root / "ir"
    _write_multi_unit_graph(ir)
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

    payload = extract_kernel_subgraph(repo, op, architecture="arch35")
    entries = [n for n in payload["nodes"] if n.get("node_type") == "KernelEntry"]
    entry_ids = {n["id"] for n in entries}
    assert "KPATH_ENTRY" not in entry_ids
    assert len(entries) >= 2

    process_nodes = [n for n in payload["nodes"] if n.get("name") == "Process" and n.get("node_type") == "Process"]
    assert len(process_nodes) >= 2
    proc_entry_sources = set()
    for pn in process_nodes:
        pid = pn["id"]
        for e in payload["edges"]:
            if e.get("target") == pid and e.get("type") == "contains":
                proc_entry_sources.add(e.get("source"))
    assert len(proc_entry_sources) >= 2
