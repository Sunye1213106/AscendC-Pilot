"""TilingDataField owning-type identity and TilingKey mapping tests."""

from __future__ import annotations

from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.build_layered_kb import _MERGE_NODE_DIAGNOSTICS, _merge_nodes
from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph
from uo.scripts.function_body import iter_function_definitions
from uo.scripts.reconcile_bridge import _bridge_tilingdata
from uo.scripts.semantic_identity import (
    mint_field_identity,
    mint_method_identity,
    mint_scoped_node_id,
    mint_symbol_identity,
)


def test_same_leaf_different_tiling_types_not_merged() -> None:
    a = mint_field_identity(owning_type="NormalTilingData", field_path="blockSize")
    b = mint_field_identity(owning_type="VarlenTilingData", field_path="blockSize")
    assert a.stable_id != b.stable_id
    assert a.qualified_name == "NormalTilingData::blockSize"


def test_bridge_requires_owning_type_for_field_alignment() -> None:
    bridges, _unresolved, _diags = _bridge_tilingdata(
        [{"name": "blockSize", "field_path": "blockSize", "owning_type": "", "id": "H1", "node": {}}],
        [
            {
                "name": "blockSize",
                "field_path": "blockSize",
                "owning_type": "NormalTilingData",
                "id": "K1",
                "node": {},
            }
        ],
    )
    assert bridges and bridges[0]["status"] == "candidate"
    assert bridges[0].get("reason") == "owning_type_missing_unique_leaf_fallback"

    bridges2, unresolved2, _ = _bridge_tilingdata(
        [{"name": "blockSize", "field_path": "blockSize", "owning_type": "", "id": "H1", "node": {}}],
        [
            {
                "name": "blockSize",
                "field_path": "blockSize",
                "owning_type": "NormalTilingData",
                "id": "K1",
                "node": {},
            },
            {
                "name": "blockSize",
                "field_path": "blockSize",
                "owning_type": "VarlenTilingData",
                "id": "K2",
                "node": {},
            },
        ],
    )
    assert not bridges2
    assert any(u.get("code") == "tilingdata_bridge_ambiguous" for u in unresolved2)


def _write_entry(ir: Path, *, name: str, fp: str, family: str) -> str:
    ident = mint_symbol_identity(
        kind="entrypoint",
        name=name,
        file_path=fp,
        qualified_name=name,
        class_or_namespace=name,
        path_family=family,
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
                    "id": ident.stable_id,
                    "role": "public_kernel_entry",
                    "architecture": "arch35",
                    "path_family": family,
                    "name": name,
                    "locator": {"file_path": fp, "start_line": 1, "end_line": 20},
                    "symbol_ref": {**ident.as_dict(), "class_or_namespace": name},
                }
            ],
            "edges": [],
            "extraction_units": [
                {
                    "id": f"UNIT_{family}",
                    "architecture": "arch35",
                    "path_family": family,
                    "entry_root": ident.stable_id,
                    "member_nodes": [ident.stable_id],
                }
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
    return ident.stable_id


def test_tilingkey_selects_specific_template_instance(tmp_path: Path) -> None:
    op = "demo_tk_sel"
    repo = tmp_path / op
    kdir = repo / "op_kernel" / "arch35"
    kdir.mkdir(parents=True)
    (kdir / "demo.h").write_text("class DemoKernelNormal { void Process() {} };\n", encoding="utf-8")
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    entry_id = _write_entry(
        root / "ir", name="DemoKernelNormal", fp="op_kernel/arch35/demo.h", family="normal"
    )
    write_yaml(
        root / "ir" / "tilingkey_space.yaml",
        {
            "version": 1,
            "architecture": "arch35",
            "source": "op_host/tpl.h",
            "dimensions": [{"name": "isTnd", "values": [True, False], "line": 1}],
            "template_aliases": [
                {
                    "name": "DemoKernelNormal",
                    "flags": {"isTnd": False},
                    "condition": "isTnd==false",
                    "line": 2,
                    "file_path": "op_host/tpl.h",
                    "path_family": "normal",
                }
            ],
            "nodes": [],
            "edges": [],
        },
    )
    payload = extract_kernel_subgraph(repo, op, architecture="arch35")
    assert not any(e.get("source") == "KEY_TILINGKEY" for e in payload["edges"])
    assert not any(
        e.get("type") == "selects"
        and e.get("target") == entry_id
        and e.get("source") == "KEY_TILINGKEY"
        for e in payload["edges"]
    )
    tpl_nodes = [n for n in payload["nodes"] if n.get("node_type") == "TemplateInstance"]
    assert tpl_nodes


def test_ambiguous_tilingkey_mapping_is_candidate_set(tmp_path: Path) -> None:
    op = "demo_tk_ambig"
    repo = tmp_path / op
    kdir = repo / "op_kernel" / "arch35"
    kdir.mkdir(parents=True)
    (kdir / "demo.h").write_text("class DemoKernel { void Process() {} };\n", encoding="utf-8")
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    _write_entry(root / "ir", name="DemoKernel", fp="op_kernel/arch35/demo.h", family="normal")
    write_yaml(
        root / "ir" / "tilingkey_space.yaml",
        {
            "version": 1,
            "architecture": "arch35",
            "source": "op_host/tpl.h",
            "dimensions": [{"name": "isTnd", "values": [True], "line": 1}],
            "template_aliases": [
                {
                    "name": "InstA",
                    "flags": {"isTnd": True},
                    "condition": "a",
                    "line": 2,
                    "file_path": "op_host/tpl.h",
                },
                {
                    "name": "InstB",
                    "flags": {"isTnd": True},
                    "condition": "b",
                    "line": 3,
                    "file_path": "op_host/tpl.h",
                },
            ],
            "nodes": [],
            "edges": [],
        },
    )
    payload = extract_kernel_subgraph(repo, op, architecture="arch35")
    cand = [
        e
        for e in payload["edges"]
        if e.get("type") == "selects" and e.get("target_status") == "candidate_set"
    ]
    assert cand
    assert any(
        u.get("unresolved_reason") == "tilingkey_template_instance_ambiguous"
        for u in payload.get("unresolved") or []
    )


def test_no_global_key_selects_all_entries_fallback(tmp_path: Path) -> None:
    op = "demo_no_global_key"
    repo = tmp_path / op
    kdir = repo / "op_kernel" / "arch35"
    kdir.mkdir(parents=True)
    (kdir / "a.h").write_text("class A { void Process() {} };\n", encoding="utf-8")
    (kdir / "b.h").write_text("class B { void Process() {} };\n", encoding="utf-8")
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    a = mint_symbol_identity(
        kind="entrypoint",
        name="A",
        file_path="op_kernel/arch35/a.h",
        path_family="normal",
        architecture="arch35",
        prefix="EP",
    )
    b = mint_symbol_identity(
        kind="entrypoint",
        name="B",
        file_path="op_kernel/arch35/b.h",
        path_family="varlen",
        architecture="arch35",
        prefix="EP",
    )
    write_yaml(
        root / "ir" / "entrypoint_graph.yaml",
        {
            "version": 2,
            "architecture": "arch35",
            "nodes": [
                {
                    "id": a.stable_id,
                    "role": "public_kernel_entry",
                    "architecture": "arch35",
                    "path_family": "normal",
                    "name": "A",
                    "locator": {"file_path": "op_kernel/arch35/a.h", "start_line": 1, "end_line": 2},
                    "symbol_ref": a.as_dict(),
                },
                {
                    "id": b.stable_id,
                    "role": "public_kernel_entry",
                    "architecture": "arch35",
                    "path_family": "varlen",
                    "name": "B",
                    "locator": {"file_path": "op_kernel/arch35/b.h", "start_line": 1, "end_line": 2},
                    "symbol_ref": b.as_dict(),
                },
            ],
            "edges": [],
            "extraction_units": [
                {
                    "id": "UA",
                    "architecture": "arch35",
                    "path_family": "normal",
                    "entry_root": a.stable_id,
                    "member_nodes": [a.stable_id],
                },
                {
                    "id": "UB",
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
        root / "ir" / "extract_plan.yaml",
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
    assert not any(e.get("source") == "KEY_TILINGKEY" for e in payload["edges"])
    by_src: dict[str, set[str]] = {}
    for e in payload["edges"]:
        if e.get("type") != "selects" or e.get("target_status") == "candidate_set":
            continue
        if e.get("target"):
            by_src.setdefault(str(e.get("source")), set()).add(str(e.get("target")))
    for _src, tgts in by_src.items():
        assert not ({a.stable_id, b.stable_id} <= tgts)


def test_function_id_stable_after_leading_comment_insert(tmp_path: Path) -> None:
    (tmp_path / "k.h").write_text(
        "class K {\n  void Process() { if (x) {} }\n};\n",
        encoding="utf-8",
    )
    before = iter_function_definitions(tmp_path, "k.h")[0]
    (tmp_path / "k.h").write_text(
        "// leading comment\n\nclass K {\n  void Process() { if (x) {} }\n};\n",
        encoding="utf-8",
    )
    after = iter_function_definitions(tmp_path, "k.h")[0]
    assert before.stable_id == after.stable_id
    assert after.start_line != before.start_line


def test_branch_id_stable_after_unrelated_file_line_shift() -> None:
    owner = mint_method_identity(name="Process", file_path="k.h", class_or_namespace="K")
    id1 = mint_scoped_node_id(
        "KBR",
        owner.identity_key,
        "k.h",
        line=10,
        extra="runtime",
        ordinal=1,
        normalized_expression="x",
    )
    id2 = mint_scoped_node_id(
        "KBR",
        owner.identity_key,
        "k.h",
        line=99,
        extra="runtime",
        ordinal=1,
        normalized_expression="x",
    )
    assert id1 == id2


def test_merge_rejects_same_id_different_identity_key() -> None:
    a = {"id": "N1", "identity_key": "aaa", "name": "A", "qualified_name": "A"}
    b = {"id": "N1", "identity_key": "bbb", "name": "B", "qualified_name": "B"}
    merged = _merge_nodes([a], [b])
    assert len(merged) == 1
    assert merged[0]["identity_key"] == "aaa"
    assert any(d.get("code") == "SEMANTIC_ID_COLLISION" for d in _MERGE_NODE_DIAGNOSTICS)


def test_merge_combines_same_identity_multiple_locators() -> None:
    a = {
        "id": "N1",
        "identity_key": "same",
        "name": "A",
        "locator": {"file_path": "a.h", "start_line": 1},
    }
    b = {
        "id": "N1",
        "identity_key": "same",
        "name": "A",
        "locator": {"file_path": "a.h", "start_line": 20},
    }
    merged = _merge_nodes([a], [b])
    assert len(merged) == 1
    assert len(merged[0].get("locators") or []) == 2
