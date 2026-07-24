"""FAG / multi-class isolation checks (integration-friendly)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph
from uo.scripts.semantic_identity import mint_symbol_identity


def _seed(repo: Path, ir: Path) -> None:
    kdir = repo / "op_kernel" / "arch35"
    kdir.mkdir(parents=True)
    (kdir / "demo.h").write_text(
        "\n".join(
            [
                "template<class T>",
                "class DemoKernelA {",
                "  void Process() { if (a) Compute(); }",
                "  void Compute() {}",
                "};",
                "template<class T>",
                "class DemoKernelB {",
                "  void Process() { if (b) Compute(); }",
                "  void Compute() {}",
                "};",
                "",
            ]
        ),
        encoding="utf-8",
    )
    a = mint_symbol_identity(
        kind="entrypoint",
        name="DemoKernelA",
        file_path="op_kernel/arch35/demo.h",
        class_or_namespace="DemoKernelA",
        path_family="normal",
        architecture="arch35",
        prefix="EP",
    )
    b = mint_symbol_identity(
        kind="entrypoint",
        name="DemoKernelB",
        file_path="op_kernel/arch35/demo.h",
        class_or_namespace="DemoKernelB",
        path_family="varlen",
        architecture="arch35",
        prefix="EP",
    )
    write_yaml(
        ir / "entrypoint_graph.yaml",
        {
            "version": 2,
            "architecture": "arch35",
            "nodes": [
                {
                    "id": a.stable_id,
                    "role": "public_kernel_entry",
                    "architecture": "arch35",
                    "path_family": "normal",
                    "name": "DemoKernelA",
                    "locator": {"file_path": "op_kernel/arch35/demo.h", "start_line": 2, "end_line": 5},
                    "symbol_ref": {**a.as_dict(), "class_or_namespace": "DemoKernelA"},
                },
                {
                    "id": b.stable_id,
                    "role": "public_kernel_entry",
                    "architecture": "arch35",
                    "path_family": "varlen",
                    "name": "DemoKernelB",
                    "locator": {"file_path": "op_kernel/arch35/demo.h", "start_line": 7, "end_line": 10},
                    "symbol_ref": {**b.as_dict(), "class_or_namespace": "DemoKernelB"},
                },
            ],
            "edges": [],
            "extraction_units": [
                {
                    "id": "UNIT_A",
                    "architecture": "arch35",
                    "path_family": "normal",
                    "entry_root": a.stable_id,
                    "member_nodes": [a.stable_id],
                },
                {
                    "id": "UNIT_B",
                    "architecture": "arch35",
                    "path_family": "varlen",
                    "entry_root": b.stable_id,
                    "member_nodes": [b.stable_id],
                },
            ],
            "closure": {
                "host_main_chain": "closed",
                "kernel_main_chain": "closed",
                "blocking_unresolved": [],
            },
        },
    )
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


def test_fag_same_short_name_functions_do_not_merge(tmp_path: Path) -> None:
    op = "demo_fag_short"
    repo = tmp_path / op
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    _seed(repo, root / "ir")
    payload = extract_kernel_subgraph(repo, op, architecture="arch35")
    processes = [n for n in payload["nodes"] if n.get("name") == "Process"]
    assert len(processes) >= 2
    assert len({n.get("identity_key") for n in processes}) == len(processes)


def test_fag_branches_have_valid_function_owner(tmp_path: Path) -> None:
    op = "demo_fag_branch"
    repo = tmp_path / op
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    _seed(repo, root / "ir")
    payload = extract_kernel_subgraph(repo, op, architecture="arch35")
    by_id = {n["id"]: n for n in payload["nodes"]}
    for br in payload.get("branches") or []:
        oid = br.get("owning_function_id")
        if not oid:
            continue
        assert oid in by_id


@pytest.mark.integration
def test_fag_repo_kernel_extract_if_present() -> None:
    fag = Path("d:/PR-review/TEST/ops-transformer/attention/flash_attention_score_grad")
    if not fag.is_dir():
        pytest.skip("FAG operator tree not present")
    op = "flash_attention_score_grad"
    uo = fag / ".ascendc-pilot" / "uo"
    if not (uo / "ir" / "entrypoint_graph.yaml").is_file():
        pytest.skip("FAG entrypoint_graph.yaml missing; run full UO first")
    payload = extract_kernel_subgraph(fag, op, architecture="arch35")
    names = {"Process", "Init", "Compute", "CopyIn", "CopyOut"}
    fns = [n for n in payload["nodes"] if n.get("name") in names]
    assert fns
    by_key: dict[str, list] = {}
    for n in fns:
        by_key.setdefault(str(n.get("identity_key")), []).append(n)
    for key, group in by_key.items():
        classes = {(g.get("class_or_namespace"), g.get("normalized_signature")) for g in group}
        assert len(classes) == 1, key
    by_id = {n["id"]: n for n in payload["nodes"]}
    for br in payload.get("branches") or []:
        oid = br.get("owning_function_id")
        if oid and not str(oid).startswith("FSCOPE_"):
            assert oid in by_id
