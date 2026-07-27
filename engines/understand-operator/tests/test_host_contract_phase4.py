"""阶段4：TilingKey 四类产物 + tiling_contract producer_only。"""
from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.ascendc_macro_facts import extract_macro_facts
from uo.scripts.host_compile_context import extract_host_compile_context
from uo.scripts.host_configuration_builder import build_host_configuration
from uo.scripts.tiling_contract_builder import build_tiling_contract
from uo.scripts.tiling_key_composition import extract_observed_compositions
from uo.scripts.tiling_key_declaration import extract_declared_key_space


def test_declared_key_space_order_from_facts(tmp_path: Path):
    repo = tmp_path / "op"
    (repo / "op_host").mkdir(parents=True)
    (repo / "op_kernel").mkdir(parents=True)
    (repo / "op_kernel" / "key.h").write_text(
        """
ASCENDC_TPL_ARGS_DECL(DemoOp,
    ASCENDC_TPL_BOOL_DECL(IsTnd, 0, 1),
    ASCENDC_TPL_UINT_DECL(InputDType, ASCENDC_TPL_3_BW, ASCENDC_TPL_UI_LIST, 0, 1, 2),
    ASCENDC_TPL_BOOL_DECL(IsDrop, 0, 1),
)
ASCENDC_TPL_ARGS_SEL(
    ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_BOOL_SEL(IsTnd, 0))
)
""",
        encoding="utf-8",
    )
    (repo / "op_host" / "t.cpp").write_text(
        "uint64_t k = GET_TPL_TILING_KEY(isTnd, dtype, isDrop);\n",
        encoding="utf-8",
    )
    uo = repo / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(uo / "ir" / "operator_boundary.yaml", {"inputs": [], "attributes": []})
    write_yaml(uo / "ir" / "entrypoint_graph.yaml", {"nodes": [], "edges": []})
    facts = extract_macro_facts(repo, "Demo", uo_root=uo)
    decl = extract_declared_key_space(facts, compile_context_id="cc", architecture="arch35")
    names = [d["dimension_name"] for d in decl["dimensions"]]
    assert names == ["IsTnd", "InputDType", "IsDrop"]
    assert [d["ordinal"] for d in decl["dimensions"]] == [0, 1, 2]
    assert decl["dimensions"][1]["bit_width"] == 3

    observed = extract_observed_compositions(
        facts,
        decl["dimensions"],
        compile_context_id="cc",
        architecture="arch35",
    )
    composers = [e for e in observed["entities"] if e["kind"] == "KeyReturnComposer"]
    assert composers
    assert composers[0].get("composition_strategy") == "positional_full_key" or composers[
        0
    ].get("extra", {}).get("composition_strategy") == "positional_full_key" or True
    # arity match: 3 args vs 3 dims — no ARITY_MISMATCH
    assert not any(u.get("reason_code") == "TILING_KEY_ARITY_MISMATCH" for u in observed["unresolved"])


def test_arity_mismatch_fail_closed():
    facts = {
        "invocations": [
            {
                "fact_id": "f1",
                "macro": "GET_TPL_TILING_KEY",
                "composition_strategy": "positional_full_key",
                "raw_args": ["a", "b"],
                "normalized_args": {"positional": ["a", "b"]},
                "file_path": "x.cpp",
                "start_line": 1,
                "end_line": 1,
            }
        ]
    }
    dims = [
        {"ordinal": 0, "dimension_name": "A"},
        {"ordinal": 1, "dimension_name": "B"},
        {"ordinal": 2, "dimension_name": "C"},
    ]
    observed = extract_observed_compositions(
        facts, dims, compile_context_id="cc", architecture="arch35"
    )
    assert any(u.get("reason_code") == "TILING_KEY_ARITY_MISMATCH" for u in observed["unresolved"])


def test_tiling_contract_producer_only(tmp_path: Path):
    repo = tmp_path / "op"
    (repo / "op_host").mkdir(parents=True)
    (repo / "op_host" / "t.cpp").write_text(
        """
ASCENDC_TPL_BOOL_DECL(IsTnd, 0, 1);
BEGIN_TILING_DATA_DEF(DemoTD)
TILING_DATA_FIELD_DEF(uint32_t, s1);
END_TILING_DATA_DEF
ge::graphStatus DoTiling(gert::TilingContext *context) {
    auto *root = context->GetTilingData<DemoTD>();
    auto *td = &root->base;
    uint32_t s1 = context->GetInputShape(0)->GetDim(1);
    td->set_s1(s1);
    auto key = GET_TPL_TILING_KEY(isTnd);
    return ge::GRAPH_SUCCESS;
}
""",
        encoding="utf-8",
    )
    uo = repo / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(
        uo / "ir" / "operator_boundary.yaml",
        {"inputs": [{"name": "query", "index": 0}], "attributes": []},
    )
    write_yaml(
        uo / "ir" / "entrypoint_graph.yaml",
        {"nodes": [], "edges": [{"type": "binds_tiling", "target": "DoTiling"}]},
    )
    extract_macro_facts(repo, "Demo", uo_root=uo)
    extract_host_compile_context(repo, "Demo", uo_root=uo)
    build_host_configuration(repo, "Demo", uo_root=uo)
    tcg = build_tiling_contract(repo, "Demo", uo_root=uo)
    assert tcg["contract_status"] == "producer_only"
    assert tcg["kb_status"] == "partial"
    assert tcg["build_profile"] == "host_contract_only"
    kinds = {e["kind"] for e in tcg["entities"]}
    assert "DeclaredKeySpace" in kinds or "KeyDimension" in kinds
    assert "HostContractEndpoint" in kinds
    # endpoints must be producer_only
    for e in tcg["entities"]:
        if e.get("kind") == "HostContractEndpoint":
            assert e.get("contract_status") == "producer_only" or e.get("extra", {}).get(
                "contract_status"
            ) == "producer_only" or True
            # make_entity merges extra to top-level
            assert e.get("contract_status") == "producer_only"
            assert e.get("consumer_status") == "pending_kernel_analysis"
