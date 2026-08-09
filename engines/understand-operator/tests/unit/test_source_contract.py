from __future__ import annotations

from pathlib import Path

from uo_init.diagnostics.audit import audit_codemap
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.source_contract import enrich_codemap_from_operator_source


KEYS = [
    "IsEmptyTensor", "SplitAxis", "InputDType", "IsTnd", "IsDrop", "IsPse",
    "IsAttenMask", "S1TemplateNum", "S2TemplateNum", "DTemplateNum", "DeterType",
    "IsNEqual", "IsBn2MultiBlk", "IsDNoEqual", "IsRope", "OutDType", "IsNzOut",
    "IsTndSwizzle", "IsRegbase",
]


def _seed_operator(root: Path) -> None:
    (root / "op_graph").mkdir(parents=True)
    (root / "op_host" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n"
        "  .INPUT(query, TensorType({DT_FLOAT16}))\n"
        "  .OPTIONAL_INPUT(query_rope, TensorType({DT_FLOAT16}))\n"
        "  .OUTPUT(dq, TensorType({DT_FLOAT16}))\n"
        "  .REQUIRED_ATTR(input_layout, String)\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (root / "op_host" / "arch35" / "common.h").write_text(
        "enum class InputIndex : unsigned { QUERY = 0, QUERY_ROPE };\n"
        "enum class AttrIndex : unsigned { INPUT_LAYOUT = 0 };\n",
        encoding="utf-8",
    )
    (root / "op_host" / "arch35" / "tiling.cpp").write_text(
        "auto queryShape = context_->GetInputShape(static_cast<size_t>(InputIndex::QUERY));\n"
        "int64_t s1 = queryShape->GetStorageShape().GetDim(0);\n"
        "data.set_s1(s1);\n",
        encoding="utf-8",
    )
    decls = []
    for name in KEYS:
        if name in {"SplitAxis", "InputDType", "S1TemplateNum", "S2TemplateNum", "DTemplateNum", "DeterType", "OutDType"}:
            decls.append(f"ASCENDC_TPL_UINT_DECL({name}, BW, ASCENDC_TPL_UI_LIST, 0, 1)")
        else:
            decls.append(f"ASCENDC_TPL_BOOL_DECL({name}, 0, 1)")
    (root / "op_kernel" / "arch35" / "toy_template_tiling_key.h").write_text(
        "#define BW 4\nASCENDC_TPL_ARGS_DECL(Toy,\n" + ",\n".join(decls) + "\n);\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "toy_tiling_data.h").write_text(
        "class BaseParams { public:\n  int64_t s1;\n  uint32_t d;\n"
        "  int64_t get_s1() const { return s1; }\n};\n"
        "class ToyTilingData { public:\n  BaseParams base;\n  uint32_t blockOuter;\n};\n",
        encoding="utf-8",
    )
    tpl = ", ".join(
        ("bool " if name.startswith("Is") else "uint8_t ") + name for name in KEYS
    )
    (root / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/toy_template_tiling_key.h"\n'
        f"template <{tpl}>\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *query, __gm__ uint8_t *queryRope, "
        "__gm__ uint8_t *dq, __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {\n"
        "  GET_TILING_DATA_WITH_STRUCT(ToyTilingData, td, tiling_data);\n"
        "}\n",
        encoding="utf-8",
    )


def test_source_contract_recovers_19_keys_api_tilingdata_and_kernel_flow(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _seed_operator(op)
    cm = CodeMap(op_name="toy", architecture="arch35")
    var = cm.upsert(
        EntityKind.VARIABLE,
        "s1",
        attrs={
            "identity": {"normalized": {"source_name": "s1"}},
            "sources": [{"file": "toy/op_host/arch35/tiling.cpp", "span": {"start_line": 2, "end_line": 2}}],
        },
    )
    assert var

    enrich_codemap_from_operator_source(cm, op, architecture="arch35")

    assert len(cm.by_kind(EntityKind.TILING_KEY)) == 19
    assert cm.by_name("IsEmptyTensor", kind=EntityKind.TILING_KEY)
    assert len(cm.by_kind(EntityKind.TILING_DATA)) == 2
    assert len(cm.by_kind(EntityKind.TILING_FIELD)) == 4
    assert len([e for e in cm.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "tensor"]) == 2
    assert len([e for e in cm.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "attribute"]) == 1
    assert len(cm.by_kind(EntityKind.OUTPUT)) == 1

    bound = {
        cm.entities[r.src].name
        for r in cm.relations.values()
        if r.kind_name() == "BINDS" and cm.entities.get(r.src)
        and cm.entities[r.src].kind_name() == EntityKind.TILING_KEY.value
    }
    assert bound == set(KEYS)
    report = audit_codemap(cm)
    assert report["counts"]["source_declared_tiling_keys"] == 19
    assert report["evidence_backed_tilingdata_kernel_path"] is True
    assert report["evidence_backed_input_output_path"] is True
