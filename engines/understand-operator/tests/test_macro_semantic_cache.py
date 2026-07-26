from __future__ import annotations

from pathlib import Path

import yaml

from uo.scripts.macro_semantic_materializer import materialize_macro_semantics


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_macro_materializer_reuses_single_scan_cache(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    uo_root = repo / ".ascendc-pilot" / "uo"
    kernel = repo / "op_kernel" / "flash_attention_score_grad.cpp"
    kernel.parent.mkdir(parents=True, exist_ok=True)
    kernel.write_text(
        r'''
#define INVOKE_FAG_IMPL() \
    do { FlashAttentionScoreGradKernel<Cube, Vec> op; op.Process(); } while (0)

template <uint8_t axis>
inline __aicore__ void RegbaseFAG(__gm__ uint8_t *q)
{
    INVOKE_FAG_IMPL();
}

template <uint8_t axis>
__global__ __aicore__ void flash_attention_score_grad(__gm__ uint8_t *q)
{
    RegbaseFAG<axis>(q);
}
''',
        encoding="utf-8",
    )
    _write_yaml(
        uo_root / "runs" / "RUN_TEST" / "scope" / "scope_confirmed.yaml",
        {"confirmed_source_files": ["op_kernel/flash_attention_score_grad.cpp"]},
    )
    base_graph = {"version": 2, "nodes": [], "edges": []}
    _write_yaml(uo_root / "ir" / "entrypoint_graph.yaml", base_graph)

    first = materialize_macro_semantics(
        repo,
        "flash_attention_score_grad",
        architecture="arch35",
        uo_root=uo_root,
    )
    assert first["macro_materialization"]["cache_hit"] is False
    assert first["macro_materialization"]["source_read_count"] == 1
    assert first["entrypoint_graph"]["closure"]["kernel_main_chain"] == "closed"

    # Simulate entrypoint layer regeneration: cached source facts must be reapplied.
    _write_yaml(uo_root / "ir" / "entrypoint_graph.yaml", base_graph)
    second = materialize_macro_semantics(
        repo,
        "flash_attention_score_grad",
        architecture="arch35",
        uo_root=uo_root,
    )
    assert second["macro_materialization"]["cache_hit"] is True
    assert second["macro_materialization"]["source_read_count"] == 0
    assert second["entrypoint_graph"]["closure"]["kernel_main_chain"] == "closed"
