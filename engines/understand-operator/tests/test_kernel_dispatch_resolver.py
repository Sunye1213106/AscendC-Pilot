from __future__ import annotations

from uo.scripts.kernel_dispatch_resolver import resolve_kernel_dispatch_semantics


def test_fag_kernel_dispatch_closes_real_aicore_chain_and_demotes_false_entries() -> None:
    graph = {
        "version": 2,
        "nodes": [
            {
                "id": "KEY_SCHEMA_FALSE_PUBLIC",
                "role": "public_kernel_entry",
                "name": "FlashAttentionScoreGrad",
                "macro": "ASCENDC_TPL_ARGS_DECL",
                "locator": {
                    "file_path": "op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h",
                    "start_line": 51,
                },
            },
            {
                "id": "API_FALSE_PUBLIC",
                "role": "public_kernel_entry",
                "name": "FlashAttentionScoreGrad",
                "locator": {
                    "file_path": "op_api/flash_attention_score_grad.cpp",
                    "start_line": 10,
                },
            },
        ],
        "edges": [],
    }
    sources = {
        "op_kernel/arch35/flash_attention_score_grad_entry_regbase.h": r'''
#define INVOKE_FAG_GENERAL_IMPL(INPUT_TYPE) \
    do { \
        FlashAttentionScoreGradKernel<CubeBlockType, VecBlockType> op; \
        op.Process(); \
    } while (0)

template <uint8_t splitAxis>
inline __aicore__ void RegbaseFAG(__gm__ uint8_t *query)
{
    INVOKE_FAG_GENERAL_IMPL(half);
}
''',
        "op_kernel/flash_attention_score_grad.cpp": r'''
template <uint8_t splitAxis>
__global__ __aicore__ void flash_attention_score_grad(__gm__ uint8_t *query)
{
    RegbaseFAG<splitAxis>(query);
}
''',
    }

    resolved, facts = resolve_kernel_dispatch_semantics(
        graph,
        sources,
        op_name="flash_attention_score_grad",
        architecture="arch35",
    )

    by_id = {node["id"]: node for node in resolved["nodes"]}
    assert by_id["KEY_SCHEMA_FALSE_PUBLIC"]["role"] == "template_key_schema"
    assert by_id["API_FALSE_PUBLIC"]["role"] == "public_api_wrapper"

    roles = [node.get("role") for node in resolved["nodes"]]
    assert roles.count("public_kernel_entry") == 1
    assert "template_dispatcher" in roles
    assert "concrete_kernel_impl" in roles

    edge_types = {edge.get("type") for edge in resolved["edges"]}
    assert "dispatches_to" in edge_types
    assert "instantiates" in edge_types
    assert all(
        edge.get("confidence") == "source_verified"
        for edge in resolved["edges"]
        if edge.get("type") in {"dispatches_to", "instantiates"}
    )
    assert resolved["closure"]["kernel_main_chain"] == "closed"
    assert facts["stats"]["demoted_false_public_count"] == 2
    assert facts["stats"]["dispatch_edge_count"] == 1
