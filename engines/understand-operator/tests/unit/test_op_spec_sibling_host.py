from __future__ import annotations

from pathlib import Path

from uo_init.op_spec import _sibling_operator_dirs, discover


def test_sibling_operator_dirs_follows_relative_kernel_include(tmp_path: Path) -> None:
    family = tmp_path / "attention"
    wrap = family / "scatter_pa_cache"
    sib = family / "scatter_pa_kv_cache"
    (wrap / "op_kernel").mkdir(parents=True)
    (sib / "op_host").mkdir(parents=True)
    (sib / "op_kernel" / "arch35").mkdir(parents=True)
    kernel = wrap / "op_kernel" / "scatter_pa_cache.cpp"
    kernel.write_text(
        '#include "../../scatter_pa_kv_cache/op_kernel/arch35/foo.h"\n'
        "__global__ void scatter_pa_cache() {}\n",
        encoding="utf-8",
    )
    found = _sibling_operator_dirs(kernel, wrap)
    assert [p.name for p in found] == ["scatter_pa_kv_cache"]


def test_discover_uses_sibling_host_tiling(tmp_path: Path) -> None:
    family = tmp_path / "attention"
    wrap = family / "scatter_pa_cache"
    sib = family / "scatter_pa_kv_cache"
    (wrap / "op_graph").mkdir(parents=True)
    (wrap / "op_host").mkdir(parents=True)
    (wrap / "op_kernel").mkdir(parents=True)
    (sib / "op_host").mkdir(parents=True)
    (sib / "op_kernel" / "arch35").mkdir(parents=True)
    (wrap / "op_graph" / "scatter_pa_cache_proto.h").write_text(
        "REG_OP(ScatterPaCache)\n  .INPUT(key, TensorType({DT_FLOAT16}))\n"
        "  .OUTPUT(key_cache_out, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(ScatterPaCache)\n",
        encoding="utf-8",
    )
    (wrap / "op_host" / "scatter_pa_cache_def.cpp").write_text(
        "class ScatterPaCache : public OpDef {};\n",
        encoding="utf-8",
    )
    (sib / "op_host" / "scatter_pa_kv_cache_tiling.cpp").write_text(
        "void DoTiling() {}\n",
        encoding="utf-8",
    )
    (wrap / "op_kernel" / "scatter_pa_cache.cpp").write_text(
        '#include "../../scatter_pa_kv_cache/op_kernel/arch35/foo.h"\n'
        "__global__ __aicore__ void scatter_pa_cache() {}\n",
        encoding="utf-8",
    )
    spec = discover(wrap, arch_dir="arch35")
    names = [p.name for p in spec.host_targets]
    assert "scatter_pa_kv_cache_tiling.cpp" in names
    assert any("host_targets_from_sibling_kernel_include" in a for a in spec.ambiguities)


def test_discover_unions_sibling_host_when_local_register_exists(tmp_path: Path) -> None:
    family = tmp_path / "attention"
    wrap = family / "mla_prolog_v3"
    sib = family / "mla_prolog"
    (wrap / "op_graph").mkdir(parents=True)
    (wrap / "op_host").mkdir(parents=True)
    (wrap / "op_kernel").mkdir(parents=True)
    (sib / "op_host").mkdir(parents=True)
    (sib / "op_kernel" / "arch35").mkdir(parents=True)
    (wrap / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(MlaPrologV3)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n"
        "  .OUTPUT(y, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(MlaPrologV3)\n",
        encoding="utf-8",
    )
    (wrap / "op_host" / "mla_prolog_v3_tiling_register.cpp").write_text(
        "IMPL_OP_OPTILING(MlaPrologV3).Tiling(TilingMlaProlog);\n",
        encoding="utf-8",
    )
    (sib / "op_host" / "mla_prolog_tiling.cpp").write_text(
        "uint64_t GetTilingKey() { return 1; }\n",
        encoding="utf-8",
    )
    (wrap / "op_kernel" / "mla_prolog_v3.cpp").write_text(
        '#include "../../mla_prolog/op_kernel/arch35/kernel.h"\n'
        "__global__ __aicore__ void mla_prolog_v3() {}\n",
        encoding="utf-8",
    )
    spec = discover(wrap, arch_dir="arch35")
    names = [p.name for p in spec.host_targets]
    assert "mla_prolog_v3_tiling_register.cpp" in names
    assert "mla_prolog_tiling.cpp" in names


def test_discover_skips_sibling_when_local_host_already_packs(tmp_path: Path) -> None:
    family = tmp_path / "attention"
    wrap = family / "fused_infer_attention_score"
    sib = family / "prompt_flash_attention"
    (wrap / "op_graph").mkdir(parents=True)
    (wrap / "op_host").mkdir(parents=True)
    (wrap / "op_kernel").mkdir(parents=True)
    (sib / "op_host").mkdir(parents=True)
    (sib / "op_kernel" / "arch35").mkdir(parents=True)
    (wrap / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(FusedInferAttentionScore)\n  .INPUT(query, TensorType({DT_FLOAT16}))\n"
        "  .OUTPUT(attention_out, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(FusedInferAttentionScore)\n",
        encoding="utf-8",
    )
    (wrap / "op_host" / "fused_infer_attention_score_tiling.cpp").write_text(
        "uint64_t DoTiling() { return GET_TPL_TILING_KEY(0, 1, 2); }\n",
        encoding="utf-8",
    )
    (sib / "op_host" / "prompt_flash_attention_tiling.cpp").write_text(
        "uint64_t GetTilingKey() { return 1; }\n",
        encoding="utf-8",
    )
    (wrap / "op_kernel" / "fused_infer_attention_score_apt.cpp").write_text(
        '#include "../../prompt_flash_attention/op_kernel/arch35/entry.h"\n'
        "__global__ __aicore__ void fused_infer_attention_score() {}\n",
        encoding="utf-8",
    )
    spec = discover(wrap, arch_dir="arch35")
    names = [p.name for p in spec.host_targets]
    assert "fused_infer_attention_score_tiling.cpp" in names
    assert "prompt_flash_attention_tiling.cpp" not in names


def test_discover_defaults_to_newest_hyphenated_arch(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_host" / "arch35").mkdir(parents=True)
    (op / "op_host" / "arch-920r1").mkdir(parents=True)
    (op / "op_kernel" / "arch-920r1").mkdir(parents=True)
    (op / "op_host" / "toy_def.cpp").write_text(
        "class Toy : public OpDef {};\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch-920r1" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy() {}\n",
        encoding="utf-8",
    )
    spec = discover(op)
    assert spec.arch_dir == "arch-920r1"
    assert spec.available_archs[-1] == "arch-920r1"
    spec_pin = discover(op, arch_dir="arch-920r1")
    assert spec_pin.arch_dir == "arch-920r1"
