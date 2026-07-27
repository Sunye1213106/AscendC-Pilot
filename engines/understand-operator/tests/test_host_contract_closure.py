"""通用闭合优化单测：调用分类、闭包宏发现、Key 作用域（无算子名）。"""
from __future__ import annotations

from uo.scripts.host_configuration_builder import classify_callee
from uo.scripts.receiver_binding import (
    build_get_tiling_data_index,
    build_macro_discovery_index,
    extract_receiver_bindings_from_text,
)
from uo.scripts.tiling_key_declaration import extract_declared_key_space
from uo.scripts.tiling_key_composition import extract_observed_compositions


def test_classify_callee_external_vs_internal():
    assert classify_callee("to_string") == "external_stdlib"
    assert classify_callee("c_str") == "external_stdlib"
    assert classify_callee("OP_CHECK_IF") == "external_macro"
    assert classify_callee("GetDim") == "modeled_local"
    assert classify_callee("GetStorageShape") == "modeled_local"
    assert classify_callee("set_coreNum") == "modeled_local"
    assert classify_callee("DoTiling") == "internal_candidate"


def test_macro_index_cross_text_binding():
    header = """
#define DEMO_TILING_BIND(ROOT) params_ = &(ROOT)->baseParams
"""
    body = """
auto *tilingData = GetTilingData<DemoTiling>();
DEMO_TILING_BIND(tilingData);
params_->set_coreNum(1);
"""
    macro_index = build_macro_discovery_index([header])
    assert "DEMO_TILING_BIND" in macro_index
    gtd = build_get_tiling_data_index([body])
    assert gtd.get("tilingData") == "DemoTiling"
    bindings = extract_receiver_bindings_from_text(
        body, macro_index=macro_index, gtd_index=gtd
    )
    real = [b for b in bindings if b.get("receiver") == "params_"]
    assert real
    assert real[0].get("canonical") is True
    assert real[0].get("nested_path") == "baseParams"
    assert real[0].get("root_schema_variant") == "DemoTiling"


def test_key_arity_uses_dimension_group_not_global_flatten():
    facts = {
        "invocations": [
            {
                "fact_id": "d1",
                "macro": "ASCENDC_TPL_ARGS_DECL",
                "file_path": "a.h",
                "start_line": 1,
                "raw_args": ["Op"],
                "normalized_args": {"positional": ["Op"]},
            },
            {
                "fact_id": "b1",
                "macro": "ASCENDC_TPL_BOOL_DECL",
                "file_path": "a.h",
                "start_line": 2,
                "raw_args": ["IsA"],
                "normalized_args": {"positional": ["IsA"]},
            },
            {
                "fact_id": "b2",
                "macro": "ASCENDC_TPL_BOOL_DECL",
                "file_path": "a.h",
                "start_line": 3,
                "raw_args": ["IsB"],
                "normalized_args": {"positional": ["IsB"]},
            },
            {
                "fact_id": "d2",
                "macro": "ASCENDC_TPL_ARGS_DECL",
                "file_path": "b.h",
                "start_line": 1,
                "raw_args": ["Op2"],
                "normalized_args": {"positional": ["Op2"]},
            },
            {
                "fact_id": "b3",
                "macro": "ASCENDC_TPL_BOOL_DECL",
                "file_path": "b.h",
                "start_line": 2,
                "raw_args": ["IsC"],
                "normalized_args": {"positional": ["IsC"]},
            },
            {
                "fact_id": "k1",
                "macro": "GET_TPL_TILING_KEY",
                "composition_strategy": "positional_full_key",
                "file_path": "a.cpp",
                "start_line": 10,
                "raw_args": ["0", "1"],
                "normalized_args": {"positional": ["0", "1"]},
            },
        ]
    }
    decl = extract_declared_key_space(
        facts, compile_context_id="cc", architecture="arch35"
    )
    assert len(decl["dimensions"]) == 3
    assert len(decl["dimension_groups"]) == 2
    # 2-arg key should match the largest group (2 dims), not global 3
    observed = extract_observed_compositions(
        facts,
        decl["dimensions"],
        compile_context_id="cc",
        architecture="arch35",
        dimension_groups=decl["dimension_groups"],
    )
    arity = [
        u
        for u in observed["unresolved"]
        if u.get("reason_code") == "TILING_KEY_ARITY_MISMATCH"
    ]
    assert not arity, arity
