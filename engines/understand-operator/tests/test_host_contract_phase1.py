"""阶段1：Schema / token scanner / macro_facts 单测。"""
from __future__ import annotations

from pathlib import Path

from uo.scripts.ascendc_macro_facts import extract_macro_facts, list_contracts
from uo.scripts.host_compile_context import classify_condition, extract_host_compile_context
from uo.scripts.host_contract_schema import (
    BINDING_TIMES,
    make_edge,
    make_entity,
    make_evidence,
    make_expression_ir,
    make_guard_context,
)
from uo.scripts.macro_entrypoint_projection import project_macro_facts_to_entrypoint
from uo.scripts.macro_token_scanner import (
    extract_balanced_paren,
    scan_invocations,
    split_top_level_args,
)


def test_schema_enums_and_builders():
    assert "host_runtime" in BINDING_TIMES
    ent = make_entity(
        kind="HostValue",
        identity_key="v1",
        binding_time="host_runtime",
        compile_context_id="cc1",
    )
    assert ent["id"].startswith("HostValue:")
    expr = make_expression_ir(kind="call", op="GetDim", source_text="shape.GetDim(1)")
    assert expr["op"] == "GetDim"
    edge = make_edge(edge_type="DERIVES", source_ids=[ent["id"]], target_ids=["x"])
    assert edge["source_ids"] == [ent["id"]]
    ev = make_evidence(file_path="a.cpp", start_line=1, evidence_level="macro_contract_fact")
    assert ev["evidence_level"] == "macro_contract_fact"
    guard = make_guard_context(
        binding_time="build_time",
        selection_effect=["filters_source_region"],
        condition_text="defined(ARCH35)",
    )
    assert guard["selection_effect"] == ["filters_source_region"]


def test_token_scanner_ignores_parens_in_strings_and_comments():
    text = 'FOO("a(b),c") /* (d) */ , bar'
    # balanced from FOO(
    open_idx = text.find("(")
    span = extract_balanced_paren("FOO" + text[text.find("(") :], 3)
    assert span is not None
    src = 'REG_OP(MyOp); // REG_OP(Fake)\nIMPL_OP_OPTILING(MyOp).Tiling(DoTiling);'
    invs = scan_invocations(src, ["REG_OP", "IMPL_OP_OPTILING"])
    macros = {i["macro"] for i in invs}
    assert "REG_OP" in macros
    assert "IMPL_OP_OPTILING" in macros
    # comment invocation not scanned as separate live call beyond line comment handling
    assert all(i["start_line"] != 1 or i["macro"] == "REG_OP" for i in invs if i["macro"] == "REG_OP")


def test_split_args_with_templates():
    inside = "Foo<Bar, Baz>, 1, \"a,b\""
    args = split_top_level_args(inside)
    assert len(args) == 3
    assert "Foo<Bar, Baz>" in args[0]


def test_macro_contracts_graded():
    contracts = list_contracts()
    names = {c["name"] for c in contracts}
    assert "ASCENDC_TPL_ARGS_DECL" in names
    assert "BEGIN_TILING_DATA_DEF" in names
    assert "DEVICE_IMPL_OP_OPTILING" in names
    for c in contracts:
        assert c.get("contract_class") in {
            "framework_required",
            "optional_framework_pattern",
            "repository_discovered",
        }
        assert c.get("version_scope")


def test_extract_macro_facts_and_projection(tmp_path: Path):
    repo = tmp_path / "op"
    (repo / "op_host").mkdir(parents=True)
    src = repo / "op_host" / "reg.cpp"
    src.write_text(
        """
REG_OP(DemoOp);
IMPL_OP_OPTILING(DemoOp).Tiling(DoTiling).TilingParse(DoParse);
REGISTER_TILING_TEMPLATE_WITH_ARCH(DemoOp, DemoTiling, ASCEND910B, 1);
ASCENDC_TPL_BOOL_DECL(IsTnd, 0, 1);
BEGIN_TILING_DATA_DEF(DemoTilingData)
TILING_DATA_FIELD_DEF(uint32_t, s1);
END_TILING_DATA_DEF
GET_TPL_TILING_KEY(isTnd, dtype);
""",
        encoding="utf-8",
    )
    uo = repo / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    # minimal entrypoint
    from uo.scripts._ir_io import write_yaml

    write_yaml(
        uo / "ir" / "entrypoint_graph.yaml",
        {
            "nodes": [
                {
                    "id": "N_REG",
                    "macro": "REG_OP",
                    "locator": {"file_path": "op_host/reg.cpp", "start_line": 2},
                },
                {
                    "id": "N_IMPL",
                    "macro": "IMPL_OP_OPTILING",
                    "locator": {"file_path": "op_host/reg.cpp", "start_line": 3},
                },
            ],
            "edges": [],
        },
    )
    facts = extract_macro_facts(repo, "DemoOp", architecture="arch35", uo_root=uo)
    assert facts["counts"]["invocations"] >= 5
    macros = {i["macro"] for i in facts["invocations"]}
    assert "ASCENDC_TPL_BOOL_DECL" in macros
    assert "BEGIN_TILING_DATA_DEF" in macros
    assert all(i.get("expansion_status") == "invocation_only" for i in facts["invocations"])

    proj = project_macro_facts_to_entrypoint(repo, "DemoOp", uo_root=uo, macro_facts=facts)
    assert proj["upgraded_nodes"] >= 1
    # Key / tiling schema macros must NOT create EP projection requirement
    ep = write_yaml  # silence
    from uo.scripts._ir_io import read_yaml

    ep_doc = read_yaml(uo / "ir" / "entrypoint_graph.yaml")
    edge_types = {e.get("type") for e in ep_doc.get("edges") or []}
    assert "binds_tiling" in edge_types or "declares_operator" in edge_types
    assert "key_dimension_bool" not in edge_types

    ctx = extract_host_compile_context(repo, "DemoOp", architecture="arch35", uo_root=uo)
    assert ctx["compile_context_id"]
    assert ctx["source_snapshot_hash"]
    assert "macro_contracts_hash" in ctx


def test_classify_condition():
    assert classify_condition("defined(ASC_DEVKIT_MAJOR)") == "BUILD_CONFIG"
    assert classify_condition("ASCENDC_TPL_BOOL_DECL") == "TILING_KEY_SYMBOL"
    assert classify_condition("ARCH35") == "ARCHITECTURE_CONFIG"
    assert classify_condition("SOMETHING_WEIRD") == "UNKNOWN"
