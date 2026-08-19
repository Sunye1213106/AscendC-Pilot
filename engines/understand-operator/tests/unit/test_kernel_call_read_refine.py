from __future__ import annotations

from pathlib import Path

from uo_init.cpp_lex import method_identity
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.kernel_call_boundaries import classify_kernel_call_boundaries
from uo_init.passes.kernel_call_read_refine import refine_kernel_calls_and_tiling_reads


def test_method_identity_strips_decl_noise() -> None:
    short, owner, signature = method_identity(
        "template<> __aicore__ inline int64_t "
        "FlashAttentionScoreGradKernelDeter<T>::CalBandDeterIndex"
    )
    assert short == "CalBandDeterIndex"
    assert owner == "FlashAttentionScoreGradKernelDeter"
    assert "template<>" in signature
    assert "CalBandDeterIndex" in signature


def test_refine_binds_this_call_to_short_method_definition(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    src = root / "op_kernel" / "arch35" / "k.cpp"
    src.parent.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    src.write_text(
        """
class FlashAttentionScoreGradKernelDeter {
public:
  void Process() {
    this->CalBandDeterIndex();
  }
};

template<>
__aicore__ inline int64_t FlashAttentionScoreGradKernelDeter<float>::CalBandDeterIndex() {
  int64_t acc = 0;
  acc += 1;
  acc += 2;
  return acc;
}
""",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.meta["kernel_tiling_closure"] = {
        "selected_kernel_files": ["op_kernel/arch35/k.cpp"],
    }
    refine_kernel_calls_and_tiling_reads(cm, root, architecture="arch35")
    classify_kernel_call_boundaries(cm)
    methods = cm.by_name("CalBandDeterIndex", kind=EntityKind.METHOD)
    assert methods, [e.name for e in cm.entities.values()]
    deter = methods[0]
    assert deter.name == "CalBandDeterIndex"
    assert deter.attrs.get("owner") == "FlashAttentionScoreGradKernelDeter"
    assert deter.attrs.get("provenance") == "source_kernel_definition_v2"
    assert int(deter.line_end or 0) > int(deter.line_start or 0)
    bound = [
        rel
        for rel in cm.relations.values()
        if rel.kind_name() == RelationKind.CALLS.value
        and rel.dst == deter.id
    ]
    assert bound, list(cm.relations.values())
    assert all(
        str(rel.attrs.get("provenance") or "") == "source_kernel_call_bound_v2" for rel in bound
    )
    assert not any(
        str(rel.attrs.get("provenance") or "") == "source_kernel_call_boundary" for rel in bound
    )


def test_refine_skips_foreign_arch_method_bodies(tmp_path: Path) -> None:
    root = tmp_path / "toy"
    current = root / "op_kernel" / "arch35" / "k.cpp"
    foreign = root / "op_kernel" / "arch22" / "old.h"
    current.parent.mkdir(parents=True)
    foreign.parent.mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    current.write_text(
        "class Cur { public: void Process() { Helper(); } };\n"
        "inline void Helper() {}\n",
        encoding="utf-8",
    )
    foreign.write_text(
        "class OldArch { public: void OldOnly() {} };\n"
        "inline void OldOnly() {}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.meta["kernel_tiling_closure"] = {
        "selected_kernel_files": [
            "op_kernel/arch35/k.cpp",
            "op_kernel/arch22/old.h",
        ],
    }
    refine_kernel_calls_and_tiling_reads(cm, root, architecture="arch35")
    names = {e.name for e in cm.entities.values()}
    assert "Helper" in names
    assert "OldOnly" not in names
