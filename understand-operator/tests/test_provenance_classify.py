"""Provenance classification: TilingKey / TilingData vs unbound symbols."""

from __future__ import annotations

from pathlib import Path

import yaml

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph
from uo.scripts.kb_query_export import _build_testcase_contract
from uo.scripts.provenance import (
    bind_symbol_to_key,
    classify_compile_determinant,
    load_key_dimension_index,
    norm_symbol,
)


def test_norm_and_bind_is_drop_alias() -> None:
    index = load_key_dimension_index(
        {"dimensions": [{"name": "IsDrop", "values": [0, 1]}, {"name": "IsTnd", "values": [0, 1]}]}
    )
    assert bind_symbol_to_key("IS_DROP", index) is not None
    assert bind_symbol_to_key("IS_DROP", index).name == "IsDrop"
    assert bind_symbol_to_key("IsDrop", index).name == "IsDrop"
    assert bind_symbol_to_key("IS_LOCAL_FLAG", index) is None
    assert norm_symbol("IS_DROP") == norm_symbol("IsDrop")


def test_classify_compile_requires_key_bind() -> None:
    index = load_key_dimension_index({"dimensions": [{"name": "IsFoo", "values": [0, 1]}]})
    source, ref, domain = classify_compile_determinant("IS_FOO", index)
    assert source == "TilingKey"
    assert ref == "IsFoo"
    assert domain == [0, 1]

    source2, _, domain2 = classify_compile_determinant("IS_LOCAL_FLAG", index)
    assert source2 == "UnboundTemplateSymbol"
    assert domain2 is None


def test_extract_promotes_tdf_bool_not_unbound_is(tmp_path: Path) -> None:
    repo = tmp_path / "demo_op"
    arch = repo / "op_kernel" / "arch35"
    arch.mkdir(parents=True)
    (arch / "demo_op_template_tiling_key.h").write_text(
        """
ASCENDC_TPL_ARGS_DECL(DemoOp,
  ASCENDC_TPL_BOOL_DECL(IsFoo, 0, 1),
);
""",
        encoding="utf-8",
    )
    (arch / "demo_op_kernel.h").write_text(
        """
class DemoKernel {
  void Process() {
    if constexpr (IS_FOO) { DoFoo(); }
    if constexpr (IS_LOCAL_FLAG) { DoLocal(); }
    enablePreSfmg = tilingData->base.enablePreSfmg;
    if (unlikely(tilingData->base.enablePreSfmg)) { Pre(); }
    if (unlikely(enablePreSfmg)) { Pre2(); }
    if (constInfo.localOnly) { Skip(); }
  }
};
""",
        encoding="utf-8",
    )
    (arch / "demo_op_entry.h").write_text("// entry\n", encoding="utf-8")

    root = operator_root(repo, "demo_op")
    init_operator_contract_layout(root, "demo_op", repo)
    ir = root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    (ir / "entrypoints.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "roles": {
                    "kernel_entry": {
                        "selected": {
                            "name": "DemoKernel",
                            "file_path": "op_kernel/arch35/demo_op_kernel.h",
                            "start_line": 1,
                            "end_line": 20,
                        }
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (ir / "tilingkey_space.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "status": "ok",
                "dimensions": [{"name": "IsFoo", "values": [0, 1]}],
                "template_blocks": [],
                "nodes": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    payload = extract_kernel_subgraph(repo, "demo_op", architecture="arch35")
    by_source = {}
    for b in payload["branches"]:
        by_source.setdefault(b.get("determinant_source"), []).append(b)

    assert any(b.get("determinant_ref") == "IsFoo" for b in by_source.get("TilingKey", []))
    assert any(b.get("determinant_source") == "UnboundTemplateSymbol" for b in payload["branches"])

    kvar = {
        str(n.get("name")): n
        for n in payload["nodes"]
        if n.get("node_type") == "KernelVariable" and n.get("domain")
    }
    assert "enablePreSfmg" in kvar
    assert kvar["enablePreSfmg"]["determinant_source"] == "TilingDataField"
    assert "localOnly" not in kvar


def test_export_rvs_only_from_real_kvar_no_ghost_is() -> None:
    kvar_nodes = [
        {
            "id": "KVAR_enablePreSfmg",
            "name": "enablePreSfmg",
            "domain": [0, 1],
            "determinant_source": "TilingDataField",
        }
    ]
    contract = _build_testcase_contract(
        {"op_name": "demo", "nodes": []},
        key_fields=[{"id": "KEY_IsFoo", "name": "IsFoo", "values": [0, 1]}],
        branch_rows=[
            {
                "id": "KBR_1",
                "binding_time": "compile_time",
                "determinant_source": "TilingKey",
                "determinant_ref": "IsFoo",
                "domain": [0, 1],
            },
            {
                "id": "KBR_2",
                "binding_time": "runtime",
                "determinant_source": "TilingDataField",
                "determinant_ref": "enablePreSfmg",
                "domain": [0, 1],
            },
        ],
        template_blocks=[],
        golden={},
        kvar_nodes=kvar_nodes,
    )
    rvs = contract["coverage_obligations"]["runtime_variable_state"]
    refs = {r for item in rvs for r in item.get("target_refs") or []}
    assert refs == {"KVAR_ENABLEPRESFMG"}
    assert not any("KVAR_IS_" in r for r in refs)
    assert any(v["id"] == "VAR_KEY_IsFoo" for v in contract["variables"])


def test_export_skips_kernel_derived_kvar() -> None:
    from uo.scripts import kb_query_export as mod

    graph = {"op_name": "demo", "nodes": []}
    kvar_nodes = [
        {
            "id": "KVAR_enablePreSfmg",
            "name": "enablePreSfmg",
            "domain": [0, 1],
            "determinant_source": "TilingDataField",
        },
    ]
    # KernelDerivedField must not be passed into kvar_nodes by materialize filter.
    contract = mod._build_testcase_contract(
        graph,
        key_fields=[{"id": "KEY_IsFoo", "name": "IsFoo", "values": [0, 1]}],
        branch_rows=[],
        template_blocks=[],
        golden={},
        kvar_nodes=kvar_nodes,
    )
    rvs_refs = {r for item in contract["coverage_obligations"]["runtime_variable_state"] for r in item["target_refs"]}
    assert rvs_refs == {"KVAR_ENABLEPRESFMG"}


def test_export_key_determinants_and_roles() -> None:
    from uo.scripts import kb_query_export as mod

    contract = mod._build_testcase_contract(
        {
            "op_name": "demo",
            "nodes": [
                {"id": "VAR_OPTIONAL_pse", "node_type": "OptionalInputPresence", "name": "pse"},
                {"id": "NUM_InputLayout", "node_type": "InputLayout", "name": "InputLayout"},
            ],
        },
        key_fields=[
            {"id": "KEY_ISTND", "name": "IsTnd", "values": [0, 1]},
            {"id": "KEY_ISPSE", "name": "IsPse", "values": [0, 1]},
            {"id": "KEY_S1TEMPLATENUM", "name": "S1TemplateNum", "values": [0, 128]},
        ],
        branch_rows=[],
        template_blocks=[],
        golden={
            "input_case_keys": ["input_layout", "pse_shape", "B"],
            "dtype_layout_literals": {"input_layout": ["BNSD", "TND"]},
        },
        kvar_nodes=[
            {
                "id": "KVAR_B",
                "name": "B",
                "domain": [0, 1],
                "domain_entries": [{"name": "0", "value": 0}, {"name": "1", "value": 1}],
                "determinant_source": "TilingDataField",
            }
        ],
    )
    dets = contract["key_determinants"]
    assert dets["KEY_ISTND"]["role"] == "layout_flag"
    assert dets["KEY_ISTND"]["primary_layout_field"] == "input_layout"
    assert dets["KEY_ISTND"]["csv_determinants"][0]["column"] == "input_layout"
    assert dets["KEY_ISPSE"]["role"] == "optional_presence"
    assert dets["KEY_S1TEMPLATENUM"]["role"] == "shape"
    assert contract["interface"]["primary_layout_field"] == "input_layout"
    assert any(f["name"] == "input_layout" for f in contract["interface"]["producible_fields"])
    opt = contract["interface"]["optional_inputs"][0]
    assert opt["semantic_role"] == "optional_presence"
    kvar = next(v for v in contract["variables"] if v["id"].startswith("VAR_KVAR_"))
    assert kvar.get("semantic_role") == "switch"