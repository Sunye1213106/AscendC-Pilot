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
    tensor_inputs = [e for e in cm.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "tensor"]
    assert len(tensor_inputs) == 2
    assert tensor_inputs[0].attrs.get("dtype") == ["DT_FLOAT16"]
    assert len([e for e in cm.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "attribute"]) == 1
    outputs = list(cm.by_kind(EntityKind.OUTPUT))
    assert len(outputs) == 1
    assert outputs[0].attrs.get("dtype") == ["DT_FLOAT16"]

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


def test_registered_type_without_tiling_data_filename_has_fields(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n"
        "  .INPUT(query, TensorType({DT_FLOAT16}))\n"
        "  .OUTPUT(out, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch35" / "layout_types.h").write_text(
        "class PackedLayout { public:\n  uint32_t blockDim;\n  int64_t s1;\n};\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/layout_types.h"\n'
        "template <bool Flag>\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *query, __gm__ uint8_t *out, "
        "__gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {\n"
        '  REGISTER_TILING_FOR_TILINGKEY("(TILING_KEY_VAR & 0x1)", PackedLayout);\n'
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    from uo_init.passes.tiling_field_complete import complete_tiling_fields
    from uo_init.passes.tiling_registration import enrich_tiling_registrations

    complete_tiling_fields(cm, op, architecture="arch35")
    enrich_tiling_registrations(cm, op, architecture="arch35")

    assert cm.by_name("PackedLayout", kind=EntityKind.TILING_DATA)
    fields = {e.name for e in cm.by_kind(EntityKind.TILING_FIELD) if e.attrs.get("owner") == "PackedLayout"}
    assert {"blockDim", "s1"} <= fields
    td = cm.by_name("PackedLayout", kind=EntityKind.TILING_DATA)[0]
    kernels = cm.by_kind(EntityKind.KERNEL)
    assert kernels
    assert any(
        r.src == td.id and r.dst == kernels[0].id and r.kind_name() == "FLOWS_TO"
        for r in cm.relations.values()
    )

    from uo_init.passes.kernel_tiling_closure import finalize_kernel_tiling_closure
    from uo_init.passes.kernel_tiling_metrics import finalize_kernel_tiling_metrics

    finalize_kernel_tiling_closure(cm, op, architecture="arch35")
    finalize_kernel_tiling_metrics(cm)
    assert any(
        r.src == td.id
        and r.dst in {k.id for k in cm.by_kind(EntityKind.KERNEL)}
        and r.kind_name() == "FLOWS_TO"
        for r in cm.relations.values()
    )
