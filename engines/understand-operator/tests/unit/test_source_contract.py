from __future__ import annotations

from pathlib import Path

from uo_init.diagnostics.audit import audit_codemap
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
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
    query_rope = cm.by_name("query_rope", kind=EntityKind.INPUT)[0]
    kernel = [e for e in cm.by_kind(EntityKind.KERNEL) if e.name == "toy"][0]
    assert any(
        r.src == query_rope.id and r.dst == kernel.id and r.kind_name() == "FLOWS_TO"
        for r in cm.relations.values()
    )


def test_alias_register_and_nested_member_types_are_inventoried(tmp_path: Path) -> None:
    """REGISTER an alias; nested member types are queued from the class body, not the filename."""
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
    (op / "op_kernel" / "arch35" / "toy_tiling_data.h").write_text(
        "class InnerParams { public:\n  int64_t scale;\n};\n"
        "class TndParams { public:\n  uint64_t tndStartBIdx;\n};\n"
        "template <bool Flag>\n"
        "class PackTilingData { public:\n"
        "  InnerParams base;\n"
        "  typename std::conditional<Flag, InnerParams, std::nullptr_t>::type opt;\n"
        "  typename std::conditional<!Flag, TndParams, std::nullptr_t>::type tnd;\n"
        "  int64_t blockStarts[4];\n"
        "};\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch35" / "entry.h").write_text(
        '#include "toy_tiling_data.h"\n'
        "using PackAlias = PackTilingData<true>;\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/entry.h"\n'
        "template <bool Flag>\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *query, __gm__ uint8_t *out, "
        "__gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {\n"
        "  REGISTER_TILING_DEFAULT(PackAlias);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    from uo_init.passes.tiling_field_complete import complete_tiling_fields

    complete_tiling_fields(cm, op, architecture="arch35")

    assert cm.by_name("PackTilingData", kind=EntityKind.TILING_DATA)
    assert cm.by_name("InnerParams", kind=EntityKind.TILING_DATA)
    assert cm.by_name("TndParams", kind=EntityKind.TILING_DATA)
    outer_fields = {
        e.name: e.attrs.get("cpp_type")
        for e in cm.by_kind(EntityKind.TILING_FIELD)
        if e.attrs.get("owner") == "PackTilingData"
    }
    assert "base" in outer_fields
    assert "opt" in outer_fields
    assert "tnd" in outer_fields
    assert "blockStarts" in outer_fields
    assert any(
        e.name == "scale" and e.attrs.get("owner") == "InnerParams"
        for e in cm.by_kind(EntityKind.TILING_FIELD)
    )
    assert any(
        e.name == "tndStartBIdx" and e.attrs.get("owner") == "TndParams"
        for e in cm.by_kind(EntityKind.TILING_FIELD)
    )


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


def test_multiline_reg_op_and_def_cpp_inputs(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n"
        "  .INPUT(x,\n"
        "         TensorType({DT_FLOAT16, DT_BF16}))\n"
        "  .DYNAMIC_INPUT(y, TensorType({DT_FLOAT}))\n"
        "  .OUTPUT(z, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "__aicore__ __global__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *z, "
        "__gm__ uint8_t *workspace, __gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA(td, tiling);\n"
        "  (void)td.blockDim;\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch35" / "toy_tiling_data.h").write_text(
        "class ToyTiling { public:\n  uint32_t blockDim;\n};\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        '#include "arch35/toy_tiling_data.h"\n'
        "REGISTER_TILING_DEFAULT(ToyTiling);\n"
        "__aicore__ __global__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *z, "
        "__gm__ uint8_t *workspace, __gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA(td, tiling);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    names = {e.name for e in cm.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "tensor"}
    assert names == {"x", "y"}
    assert cm.by_name("z", kind=EntityKind.OUTPUT)
    kernels = cm.by_kind(EntityKind.KERNEL)
    assert any(k.name == "toy" for k in kernels)
    td = cm.by_name("ToyTiling", kind=EntityKind.TILING_DATA)
    assert td
    assert any(
        r.src == td[0].id and r.kind_name() == "FLOWS_TO"
        for r in cm.relations.values()
    )


def test_macro_tiling_data_fields_survive_get_tiling_data_identity(tmp_path: Path) -> None:
    """GET_TILING_DATA_WITH_STRUCT names a type that only exists as BEGIN_TILING_DATA_DEF."""
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n"
        "  .INPUT(query, TensorType({DT_FLOAT16}))\n"
        "  .OUTPUT(out, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "toy_tiling.h").write_text(
        "BEGIN_TILING_DATA_DEF(QLIV2TilingData)\n"
        "TILING_DATA_FIELD_DEF(uint32_t, bSize)\n"
        "TILING_DATA_FIELD_DEF(uint32_t, n2Size)\n"
        "END_TILING_DATA_DEF\n"
        "REGISTER_TILING_DATA_CLASS(Toy, QLIV2TilingData)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy(__gm__ uint8_t *query, __gm__ uint8_t *out, "
        "__gm__ uint8_t *workspace, __gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA_WITH_STRUCT(QLIV2TilingData, tiling_data_in, tiling);\n"
        "  (void)tiling_data_in.bSize;\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    assert cm.by_name("QLIV2TilingData", kind=EntityKind.TILING_DATA)
    fields = {
        e.name
        for e in cm.by_kind(EntityKind.TILING_FIELD)
        if e.attrs.get("owner") == "QLIV2TilingData"
    }
    assert {"bSize", "n2Size"} <= fields



def test_def_cpp_used_when_op_graph_missing(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_host" / "toy_def.cpp").write_text(
        'void ToyInferShape() {\n'
        '  this->Input("tokens").ParamType(REQUIRED);\n'
        '  this->Output("y").ParamType(REQUIRED);\n'
        '  this->Attr("axis");\n'
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    inputs = {e.name for e in cm.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "tensor"}
    attrs = {e.name for e in cm.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "attribute"}
    assert inputs == {"tokens"}
    assert attrs == {"axis"}
    assert cm.by_name("y", kind=EntityKind.OUTPUT)


def test_tpl_keys_come_from_entry_reachable_header_only(tmp_path: Path) -> None:
    """Sibling apt/non-apt TPL headers must not merge into one schema."""
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel" / "arch22").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy_tiling_key.h").write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy,\n"
        "  ASCENDC_TPL_BOOL_DECL(TPL_ISBIAS, 0, 1),\n"
        "  ASCENDC_TPL_UINT_DECL(BIAS_DTYPE, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1, 2));\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy_apt_tiling_key.h").write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy,\n"
        "  ASCENDC_TPL_BOOL_DECL(TPL_ISPERBLOCK, 0, 1),\n"
        "  ASCENDC_TPL_UINT_DECL(TPL_INPUT, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1),\n"
        "  ASCENDC_TPL_UINT_DECL(TPL_OUTPUT, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1),\n"
        "  ASCENDC_TPL_UINT_DECL(TPL_COMM, ASCENDC_TPL_1_BW, ASCENDC_TPL_UI_LIST, 0, 1));\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch22" / "toy.cpp").write_text(
        '#include "../toy_tiling_key.h"\n'
        '__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *tiling) {}\n',
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch22")
    enrich_codemap_from_operator_source(cm, op, architecture="arch22")
    keys = [e.name for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")]
    assert keys == ["TPL_ISBIAS", "BIAS_DTYPE"]
    bias = cm.by_name("BIAS_DTYPE", kind=EntityKind.TILING_KEY)[0]
    assert bias.attrs.get("bit_width") == 2
    assert bias.attrs.get("provenance") == "source_tpl_args_decl"


def test_dtype_decl_is_a_source_declared_tiling_key(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch35" / "toy_template_tiling_key.h").write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy,\n"
        "  ASCENDC_TPL_DTYPE_DECL(DimA, DT_FLOAT, DT_FLOAT16),\n"
        "  ASCENDC_TPL_BOOL_DECL(Flag, 0, 1));\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/toy_template_tiling_key.h"\n'
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *tiling) {}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    keys = [e.name for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")]
    assert keys == ["DimA", "Flag"]
    assert cm.meta["source_declared_tiling_key_count"] == 2
    dim = cm.by_name("DimA", kind=EntityKind.TILING_KEY)[0]
    assert dim.attrs.get("decl_kind") == "dtype"


def test_tpl_schema_glob_does_not_merge_unselected_schema(tmp_path: Path) -> None:
    """Layout glob may see a second ARGS_DECL; only the entry-reachable schema is declared."""
    from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions
    from uo_init.passes.tpl_schema import run as run_tpl_schema

    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host" / "arch35").mkdir(parents=True)
    variant = op / "op_kernel" / "arch35" / "variant"
    variant.mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (variant / "variant_tiling_key.h").write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy,\n"
        "  ASCENDC_TPL_UINT_DECL(K0, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1),\n"
        "  ASCENDC_TPL_UINT_DECL(K1, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1),\n"
        "  ASCENDC_TPL_UINT_DECL(K2, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1));\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy_tiling_key.h").write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy,\n"
        "  ASCENDC_TPL_DTYPE_DECL(DimA, DT_FLOAT, DT_FLOAT16),\n"
        "  ASCENDC_TPL_DTYPE_DECL(DimB, DT_FLOAT, DT_FLOAT16),\n"
        "  ASCENDC_TPL_BOOL_DECL(Flag, 0, 1));\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/variant/variant_tiling_key.h"\n'
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *tiling) {}\n",
        encoding="utf-8",
    )
    (op / "op_host" / "arch35" / "tiling.cpp").write_text(
        "uint64_t BuildKey() { return GET_TPL_TILING_KEY(0, 1, 0); }\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    run_tpl_schema(cm, context={"op_root": str(op), "architecture": "arch35", "tg_views": {}})
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    bind_host_tiling_key_expressions(cm, op, architecture="arch35")
    keys = [e.name for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")]
    assert keys == ["K0", "K1", "K2"]
    assert cm.meta["source_declared_tiling_key_count"] == 3
    packing = cm.meta["host_tiling_key_packing"]
    assert packing["fields_bound"] == 3
    assert packing["declared"] == 3
    report = audit_codemap(cm)
    assert report["counts"]["source_declared_tiling_keys"] == 3
    assert "TILING_KEY_CARDINALITY_MISMATCH" not in {
        f.get("code") for f in report.get("blocking") or []
    }


def test_reconcile_source_declared_demotes_catalog_and_foreign_tpl() -> None:
    from uo_init.passes.source_contract import reconcile_source_declared_tiling_keys

    cm = CodeMap(op_name="toy", architecture="arch22")
    cm.meta["source_declared_tiling_keys"] = ["attenEnable", "ropeDim"]
    cm.meta["source_declared_tiling_key_count"] = 2
    for name in ("attenEnable", "ropeDim", "100000", "InputDType"):
        cm.upsert(
            EntityKind.TILING_KEY,
            name,
            attrs={"source_declared": True, "decl_order": 0},
        )
    reconcile_source_declared_tiling_keys(cm)
    declared = {
        e.name for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")
    }
    assert declared == {"attenEnable", "ropeDim"}
    assert cm.by_name("100000", kind=EntityKind.TILING_KEY)[0].attrs.get("source_declared") is False
    assert cm.by_name("InputDType", kind=EntityKind.TILING_KEY)[0].attrs.get("source_declared") is False


def test_late_tpl_schema_does_not_expand_decimal_packing_schema(tmp_path: Path) -> None:
    """Host ``tilingKey *= 10`` is the arch22 schema; sibling-arch TPL is not extra declared keys."""
    from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions
    from uo_init.passes.kernel_tiling_closure import finalize_kernel_tiling_closure
    from uo_init.passes.tpl_schema import run as run_tpl_schema

    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host" / "arch22").mkdir(parents=True)
    (op / "op_kernel" / "arch22").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OUTPUT(y, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "arch22" / "tiling.cpp").write_text(
        "uint64_t GetTilingKey() const {\n"
        "  uint64_t tilingKey = 10;\n"
        "  if (tmpData.attenEnable) { tilingKey += 1; }\n"
        "  tilingKey *= 10;\n"
        "  if (tmpData.ropeDim != 0) { tilingKey += 1; }\n"
        "  tilingKey *= 10;\n"
        "  if (tmpData.layout == 1) { tilingKey += 1; }\n"
        "  tilingKey *= 10;\n"
        "  if (tmpData.deterministic) { tilingKey += 1; }\n"
        "  tilingKey *= 10;\n"
        "  if (tmpData.kvMerge) { tilingKey += 1; }\n"
        "  return tilingKey;\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch22" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  if (TILING_KEY_IS(100000)) { return; }\n"
        "  if (TILING_KEY_IS(110000)) { return; }\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch35" / "toy_template_tiling_key.h").write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy,\n"
        "  ASCENDC_TPL_UINT_DECL(InputDType, ASCENDC_TPL_3_BW, ASCENDC_TPL_UI_LIST, 0, 1),\n"
        "  ASCENDC_TPL_BOOL_DECL(IsTnd, 0, 1),\n"
        "  ASCENDC_TPL_BOOL_DECL(IsRope, 0, 1));\n"
        "ASCENDC_TPL_SEL(ASCENDC_TPL_ARGS_SEL(\n"
        "  ASCENDC_TPL_UINT_SEL(InputDType, ASCENDC_TPL_UI_LIST, 0, 1),\n"
        "  ASCENDC_TPL_BOOL_SEL(IsTnd, 0, 1),\n"
        "  ASCENDC_TPL_BOOL_SEL(IsRope, 0, 1)));\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch22")
    enrich_codemap_from_operator_source(cm, op, architecture="arch22")
    bind_host_tiling_key_expressions(cm, op, architecture="arch22")
    finalize_kernel_tiling_closure(cm, op, architecture="arch22")
    run_tpl_schema(cm, context={"op_root": str(op), "architecture": "arch22", "tg_views": {}})
    declared = [
        e.name for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")
    ]
    assert declared == ["attenEnable", "ropeDim", "layout", "deterministic", "kvMerge"]
    assert cm.meta["source_declared_tiling_key_count"] == 5
    packing = cm.meta.get("host_tiling_key_packing") or {}
    assert packing.get("fields_bound") == 5
    report = audit_codemap(cm)
    codes = {f.get("code") for f in report.get("blocking") or []}
    assert "TILING_KEY_CARDINALITY_MISMATCH" not in codes
    assert "INCOMPLETE_HOST_TILINGKEY_PACKING" not in codes


def test_op_def_datatype_chain_fills_input_dtype(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_host" / "toy_def.cpp").write_text(
        "class Toy : public OpDef {\n"
        "  explicit Toy(const char *name) : OpDef(name) {\n"
        '    this->Input("x")\n'
        "        .ParamType(DYNAMIC)\n"
        "        .DataType({ge::DT_FLOAT16, ge::DT_BF16, ge::DT_INT8})\n"
        "        .Format({ge::FORMAT_ND});\n"
        '    this->Output("y").DataType({ge::DT_FLOAT16});\n'
        "  }\n"
        "};\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    inp = cm.by_name("x", kind=EntityKind.INPUT)[0]
    assert inp.attrs.get("dtype") == ["DT_FLOAT16", "DT_BF16", "DT_INT8"]
    assert (inp.attrs.get("facts") or {}).get("dtype") == ["DT_FLOAT16", "DT_BF16", "DT_INT8"]
    out = cm.by_name("y", kind=EntityKind.OUTPUT)[0]
    assert out.attrs.get("dtype") == ["DT_FLOAT16"]
    assert (out.attrs.get("facts") or {}).get("dtype") == ["DT_FLOAT16"]


def test_reg_op_datatype_alias_fills_quoted_type_param(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n"
        '  .INPUT(key, "T")\n'
        "  .INPUT(slot, TensorType({DT_INT32, DT_INT64}))\n"
        '  .OUTPUT(key_cache, "T")\n'
        "  .DATATYPE(T, TensorType({DT_FLOAT16, DT_BF16, DT_INT8}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    key = cm.by_name("key", kind=EntityKind.INPUT)[0]
    assert key.attrs.get("dtype") == ["DT_FLOAT16", "DT_BF16", "DT_INT8"]
    assert (key.attrs.get("facts") or {}).get("dtype") == ["DT_FLOAT16", "DT_BF16", "DT_INT8"]
    out = cm.by_name("key_cache", kind=EntityKind.OUTPUT)[0]
    assert out.attrs.get("dtype") == ["DT_FLOAT16", "DT_BF16", "DT_INT8"]


def test_op_def_named_datatype_vector_fills_input_dtype(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        'REG_OP(Toy)\n  .INPUT(x, "T")\n  .OUTPUT(y, "T")\n  .OP_END_FACTORY_REG(Toy)\n',
        encoding="utf-8",
    )
    (op / "op_host" / "toy_def.cpp").write_text(
        "static const std::vector<ge::DataType> keyDataType = {\n"
        "    ge::DT_INT8, ge::DT_FLOAT16, ge::DT_INT8, ge::DT_BF16,\n"
        "};\n"
        "class Toy : public OpDef {\n"
        "  explicit Toy(const char *name) : OpDef(name) {\n"
        '    this->Input("x").ParamType(REQUIRED).DataType(keyDataType);\n'
        '    this->Output("y").DataType(keyDataType);\n'
        "  }\n"
        "};\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    inp = cm.by_name("x", kind=EntityKind.INPUT)[0]
    assert inp.attrs.get("dtype") == ["DT_INT8", "DT_FLOAT16", "DT_BF16"]
    assert (inp.attrs.get("facts") or {}).get("dtype") == ["DT_INT8", "DT_FLOAT16", "DT_BF16"]
    out = cm.by_name("y", kind=EntityKind.OUTPUT)[0]
    assert out.attrs.get("dtype") == ["DT_INT8", "DT_FLOAT16", "DT_BF16"]


def test_op_def_datatypelist_fills_input_dtype(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_host" / "toy_def.cpp").write_text(
        "class Toy : public OpDef {\n"
        "  explicit Toy(const char *name) : OpDef(name) {\n"
        '    this->Input("indices").ParamType(REQUIRED).DataTypeList({ge::DT_INT32});\n'
        '    this->Output("fetched").DataTypeList({ge::DT_BF16, ge::DT_FLOAT16, ge::DT_FLOAT});\n'
        "  }\n"
        "};\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    inp = cm.by_name("indices", kind=EntityKind.INPUT)[0]
    assert inp.attrs.get("dtype") == ["DT_INT32"]
    assert (inp.attrs.get("facts") or {}).get("dtype") == ["DT_INT32"]
    out = cm.by_name("fetched", kind=EntityKind.OUTPUT)[0]
    assert out.attrs.get("dtype") == ["DT_BF16", "DT_FLOAT16", "DT_FLOAT"]


def test_reg_op_input_gets_dtype_from_def_cpp(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({}))\n  .OUTPUT(y, TensorType({}))\n  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "toy_def.cpp").write_text(
        "class Toy : public OpDef {\n"
        "  explicit Toy(const char *name) : OpDef(name) {\n"
        '    this->Input("x").DataType({ge::DT_FLOAT16, ge::DT_BF16});\n'
        '    this->Output("y").DataType({ge::DT_FLOAT16});\n'
        "  }\n"
        "};\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    inp = cm.by_name("x", kind=EntityKind.INPUT)[0]
    assert inp.attrs.get("dtype") == ["DT_FLOAT16", "DT_BF16"]
    assert (inp.attrs.get("facts") or {}).get("dtype") == ["DT_FLOAT16", "DT_BF16"]


def test_kernel_including_tpl_header_selects_declared_keys(tmp_path: Path) -> None:
    """Preprocessor may sit between template<> and __global__; include still selects."""
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OUTPUT(y, TensorType({DT_FLOAT16}))\n  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch35" / "toy_template_tiling_key.h").write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy,\n"
        "  ASCENDC_TPL_UINT_DECL(K0, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1),\n"
        "  ASCENDC_TPL_UINT_DECL(K1, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1));\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy_apt.cpp").write_text(
        '#include "arch35/toy_template_tiling_key.h"\n'
        "#if defined(VARIANT_A)\n"
        "template <int8_t K0, int8_t K1>\n"
        "#endif\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {}\n",
        encoding="utf-8",
    )
    (op / "op_host" / "arch35" / "tiling.cpp").write_text(
        "uint64_t BuildKey() { return GET_TPL_TILING_KEY(0, 1); }\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    keys = [e for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")]
    assert [e.name for e in keys] == ["K0", "K1"]
    kernel = cm.by_name("toy", kind=EntityKind.KERNEL)[0]
    selected = {
        cm.entities[r.src].name
        for r in cm.relations.values()
        if r.kind_name() == "SELECTS" and r.dst == kernel.id
    }
    assert selected >= {"K0", "K1"}


def test_include_guard_is_not_a_tiling_key(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT}))\n  .OUTPUT(y, TensorType({DT_FLOAT}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "#ifndef __OP_HOST_MATMUL_V3_TILING_KEY_H__\n"
        "#define __OP_HOST_MATMUL_V3_TILING_KEY_H__\n"
        "void DoTiling() { SetTilingKey(tiling); }\n"
        "#endif\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "class ToyTilingData { public: uint32_t worldSize; };\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA_WITH_STRUCT(ToyTilingData, td, tiling);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    names = {e.name for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")}
    assert "__OP_HOST_MATMUL_V3_TILING_KEY_H__" not in names
    assert "tiling" not in names
    kernel = cm.by_name("toy", kind=EntityKind.KERNEL)[0]
    td = cm.by_name("ToyTilingData", kind=EntityKind.TILING_DATA)[0]
    assert any(
        r.src == td.id and r.dst == kernel.id and r.kind_name() == "FLOWS_TO"
        for r in cm.relations.values()
    )


def test_single_kernel_selects_declared_keys_without_tiling_key_is(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT}))\n  .OUTPUT(y, TensorType({DT_FLOAT}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "constexpr uint64_t TILING_KEY_INIT = 10000UL;\n"
        "void DoTiling() { (void)TILING_KEY_INIT; }\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "class ToyTilingData { public: uint32_t worldSize; };\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA_WITH_STRUCT(ToyTilingData, td, tiling);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    keys = [e for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")]
    assert any(e.name == "TILING_KEY_INIT" for e in keys)
    kernel = cm.by_name("toy", kind=EntityKind.KERNEL)[0]
    assert not any(
        r.src in {e.id for e in keys}
        and r.dst == kernel.id
        and r.kind_name() == "SELECTS"
        for r in cm.relations.values()
    )
    assert not any(
        str(r.attrs.get("provenance") or "") == "source_single_kernel_selects"
        for r in cm.relations.values()
    )


def test_class_tiling_data_reads_brace_initializers(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT}))\n  .OUTPUT(y, TensorType({DT_FLOAT}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch35" / "toy_tiling_data.h").write_text(
        "class ToyTilingData {\n"
        "public:\n"
        "    int64_t totalLength{0};\n"
        "    int64_t needCoreNum{0};\n"
        "};\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy_apt.cpp").write_text(
        "REGISTER_TILING_DEFAULT(ToyTilingData);\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA(td, tiling);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    assert cm.by_name("ToyTilingData", kind=EntityKind.TILING_DATA)
    fields = {
        e.name
        for e in cm.by_kind(EntityKind.TILING_FIELD)
        if e.attrs.get("owner") == "ToyTilingData"
    }
    assert fields == {"totalLength", "needCoreNum"}


def test_reinterpret_cast_tiling_data_flows_to_kernel(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OUTPUT(y, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "toy_tiling.h").write_text(
        "BEGIN_TILING_DATA_DEF(ToyTilingData)\n"
        "TILING_DATA_FIELD_DEF(uint64_t, tilingKey);\n"
        "END_TILING_DATA_DEF\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "REGISTER_TILING_DEFAULT(ToyTilingData);\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  __gm__ ToyTilingData *td = "
        "reinterpret_cast<__gm__ ToyTilingData *>(tiling);\n"
        "  uint64_t k = td->tilingKey;\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    td = cm.by_name("ToyTilingData", kind=EntityKind.TILING_DATA)
    assert td
    kernel = cm.by_name("toy", kind=EntityKind.KERNEL)[0]
    assert any(
        r.src == td[0].id and r.dst == kernel.id and r.kind_name() == "FLOWS_TO"
        for r in cm.relations.values()
    )


def test_packed_tiling_key_is_selects_host_produced_key(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OUTPUT(y, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "void DoTiling(auto *ctx) {\n"
        "  uint64_t tilingKey = 1;\n"
        "  ctx->SetTilingKey(tilingKey);\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  TILING_KEY_IS(QF16_NOCACHE_BSA_TILING);\n"
        "  TILING_KEY_IS(QBF16_NOCACHE_BSA_TILING);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    keys = [e for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")]
    names = {e.name for e in keys}
    assert "QF16_NOCACHE_BSA_TILING" in names
    assert "QBF16_NOCACHE_BSA_TILING" in names
    kernel = cm.by_name("toy", kind=EntityKind.KERNEL)[0]
    assert any(
        r.src in {e.id for e in keys}
        and r.dst == kernel.id
        and r.kind_name() == "SELECTS"
        for r in cm.relations.values()
    )


def test_bare_get_tilingkey_is_a_packing_helper() -> None:
    from uo_init.passes.source_contract import iter_packing_helper_calls

    text = "uint64_t GetTilingKey() const { return GET_TILINGKEY(layout, sparse, mask, topk); }\n"
    calls = list(iter_packing_helper_calls(text))
    assert len(calls) == 1
    _start, _end, args, name = calls[0]
    assert name == "GET_TILINGKEY"
    assert args == ["layout", "sparse", "mask", "topk"]


def test_single_arg_get_tpl_tiling_key_is_a_packing_helper() -> None:
    from uo_init.passes.source_contract import iter_packing_helper_calls

    text = "GET_TPL_TILING_KEY(isDeterministic);\n"
    calls = list(iter_packing_helper_calls(text))
    assert len(calls) == 1
    _start, _end, args, name = calls[0]
    assert name == "GET_TPL_TILING_KEY"
    assert args == ["isDeterministic"]


def test_single_arg_get_tilingkey_is_not_a_dimension_pack() -> None:
    from uo_init.passes.source_contract import iter_packing_helper_calls

    text = "return GET_TILINGKEY(packed);\n"
    assert list(iter_packing_helper_calls(text)) == []



def test_tiling_key_is_integer_suffix_is_a_catalog(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OUTPUT(y, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "void DoTiling(auto *ctx) { ctx->SetTilingKey(1); }\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  if (TILING_KEY_IS(10000000000000000024UL)) { return; }\n"
        "  if (TILING_KEY_IS(10000000000000001024UL)) { return; }\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    names = {e.name for e in cm.by_kind(EntityKind.TILING_KEY)}
    assert "10000000000000000024" in names
    assert "10000000000000001024" in names


def test_get_tilingkey_helper_mints_packing_dimensions(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OUTPUT(y, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "uint64_t GetTilingKey() const {\n"
        "  return GET_TILINGKEY(tilingKeyLayout, hasAttenMask, hasTopkMask);\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  if (TILING_KEY_IS(10000000000000000024UL)) { return; }\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    names = {e.name for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")}
    assert "tilingKeyLayout" in names
    assert "hasAttenMask" in names
    assert "hasTopkMask" in names


def test_tiling_key_is_plain_macro_ident_is_a_catalog(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OUTPUT(y, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "void GenTilingKey() {\n"
        "  tilingKey_ = static_cast<uint64_t>(templateType_) * 100 + isFullyLoad_;\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "#define NORMAL_INT32_FULLY_LOAD 141\n"
        "#define NORMAL_INT32_NOT_FULLY_LOAD 140\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  if TILING_KEY_IS(NORMAL_INT32_FULLY_LOAD) { return; }\n"
        "  else if TILING_KEY_IS(NORMAL_INT32_NOT_FULLY_LOAD) { return; }\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    by_name = {
        e.name: e
        for e in cm.by_kind(EntityKind.TILING_KEY)
        if e.attrs.get("source_declared")
    }
    assert "NORMAL_INT32_FULLY_LOAD" in by_name
    assert "NORMAL_INT32_NOT_FULLY_LOAD" in by_name
    assert by_name["NORMAL_INT32_FULLY_LOAD"].attrs.get("value") == 141
    assert by_name["NORMAL_INT32_NOT_FULLY_LOAD"].attrs.get("value") == 140
    from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions

    bind_host_tiling_key_expressions(cm, op, architecture="arch35")
    meta = cm.meta["host_tiling_key_packing"]
    assert meta["fields_bound"] == 2
    for name in ("NORMAL_INT32_FULLY_LOAD", "NORMAL_INT32_NOT_FULLY_LOAD"):
        assert by_name[name].attrs.get("host_packing_expressions")


def test_tiling_key_is_wrapper_macro_mints_invocation_args(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OUTPUT(y, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "void GenTilingKey() {\n"
        "  tilingKey_ = item.tilingKey;\n"
        "}\n"
        "uint64_t GetTilingKey() const { return tilingKey_; }\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "#define TILING_KEY_1111 1111\n"
        "#define TILING_KEY_1110 1110\n"
        "#define TILING_KEY_BRANCH(tilingKey, flag) { \\\n"
        "    if (TILING_KEY_IS(tilingKey)) { (void)flag; } \\\n"
        "}\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  TILING_KEY_BRANCH(TILING_KEY_1111, true)\n"
        "  TILING_KEY_BRANCH(TILING_KEY_1110, false)\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    by_name = {
        e.name: e
        for e in cm.by_kind(EntityKind.TILING_KEY)
        if e.attrs.get("source_declared")
    }
    assert "tilingKey" not in by_name
    assert "TILING_KEY_1111" in by_name
    assert "TILING_KEY_1110" in by_name
    assert by_name["TILING_KEY_1111"].attrs.get("value") == 1111
    from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions

    bind_host_tiling_key_expressions(cm, op, architecture="arch35")
    meta = cm.meta["host_tiling_key_packing"]
    assert meta["fields_bound"] == 2


def _bare_op(root: Path) -> None:
    (root / "op_graph").mkdir(parents=True)
    (root / "op_host").mkdir(parents=True)
    (root / "op_kernel").mkdir(parents=True)
    (root / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT16}))\n  .OUTPUT(y, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )


def test_iter_bitpack_dims_shift_chain_names_fields_not_integers() -> None:
    from uo_init.passes.source_contract import iter_bitpack_dims

    text = (
        "void SetTilingKey(const ge::DataType inDtype, bool doRmsQuant, auto *context) {\n"
        "  uint64_t tilingKey = static_cast<uint64_t>(inDtype == ge::DT_BF16);\n"
        "  tilingKey = (tilingKey << 2) + static_cast<uint64_t>(param.cacheMode);\n"
        "  tilingKey = (tilingKey << 1) + static_cast<uint64_t>(formatWeight1 == ge::FORMAT_FRACTAL_NZ);\n"
        "  tilingKey = (tilingKey << 1) + static_cast<uint64_t>(formatWeight2 == ge::FORMAT_FRACTAL_NZ);\n"
        "  tilingKey = (tilingKey << 1) + static_cast<uint64_t>(formatWeight3 == ge::FORMAT_FRACTAL_NZ);\n"
        "  tilingKey = (tilingKey << 2) + static_cast<uint64_t>(param.quantMode);\n"
        "  if (!doRmsQuant){\n"
        "    tilingKey += 1000;\n"
        "  }\n"
        "  context->SetTilingKey(tilingKey);\n"
        "}\n"
    )
    dims = iter_bitpack_dims(text)
    names = [d["name"] for d in dims]
    assert names == [
        "inDtype",
        "cacheMode",
        "formatWeight1",
        "formatWeight2",
        "formatWeight3",
        "quantMode",
        "doRmsQuant",
    ]
    assert "0" not in names
    assert "4" not in names
    assert "8" not in names


def test_iter_bitpack_dims_weighted_add_is_four_axes() -> None:
    from uo_init.passes.source_contract import iter_bitpack_dims

    text = (
        "void ComputeTilingKey() {\n"
        "  tilingKey_ += normType * NORM_TYPE_TILING_KEY;\n"
        "  tilingKey_ += normAddedType * NORM_ADDED_TYPE_TILING_KEY;\n"
        "  tilingKey_ += ropeType * ROPE_TYPE_TILING_KEY;\n"
        "  tilingKey_ += concatOrder * CONCAT_ORDER_TILING_KEY;\n"
        "}\n"
    )
    dims = iter_bitpack_dims(text)
    assert [d["name"] for d in dims] == [
        "normType",
        "normAddedType",
        "ropeType",
        "concatOrder",
    ]


def test_iter_bitpack_dims_ignores_named_key_plus_one() -> None:
    from uo_init.passes.source_contract import iter_bitpack_dims

    text = (
        "void GenTilingKey() {\n"
        "  tilingKey_ = TILING_KEY_DIVIDE_BS_FP16;\n"
        "  if (tokenDtype_ == 1) tilingKey_ += 1;\n"
        "}\n"
    )
    assert iter_bitpack_dims(text) == []


def test_iter_bitpack_dims_ignores_same_place_plus_one_flags() -> None:
    from uo_init.passes.source_contract import iter_bitpack_dims

    text = (
        "void GenTilingKey() {\n"
        "  uint64_t tilingKey = 0;\n"
        "  if (hasDrop) tilingKey += 1;\n"
        "  if (hasPse) tilingKey += 1;\n"
        "  if (hasMask) tilingKey += 1;\n"
        "  if (hasRope) tilingKey += 1;\n"
        "}\n"
    )
    assert iter_bitpack_dims(text) == []


def test_iter_bitpack_dims_times_ten_shifts_plus_one_flags() -> None:
    from uo_init.passes.source_contract import iter_bitpack_dims

    text = (
        "uint64_t GetTilingKey() const {\n"
        "  uint64_t tilingKey = 10;\n"
        "  if (tmpData.attenEnable) {\n"
        "    tilingKey += 1;\n"
        "  }\n"
        "  tilingKey *= 10;\n"
        "  if (tmpData.ropeDim != 0) {\n"
        "    tilingKey += 1;\n"
        "  }\n"
        "  tilingKey *= 10;\n"
        "  if (tmpData.layout == 1) {\n"
        "    tilingKey += 1;\n"
        "  }\n"
        "  tilingKey *= 10;\n"
        "  if (tmpData.deterministic) {\n"
        "    tilingKey += 1;\n"
        "  }\n"
        "  tilingKey *= 10;\n"
        "  if (tmpData.kvMerge) {\n"
        "    tilingKey += 1;\n"
        "  }\n"
        "  return tilingKey;\n"
        "}\n"
    )
    dims = iter_bitpack_dims(text)
    assert [d["name"] for d in dims] == [
        "attenEnable",
        "ropeDim",
        "layout",
        "deterministic",
        "kvMerge",
    ]


def test_iter_bitpack_dims_if_literal_pack_is_independent_axes() -> None:
    from uo_init.passes.source_contract import iter_bitpack_dims

    text = (
        "uint64_t GenerateTilingKey(gert::TilingContext *ctx) {\n"
        "  uint64_t tilingKey = 9000000000000000ULL;\n"
        "  if (socVer_ == SOC_VER_950_CODE) {\n"
        "    tilingKey = 9050000000000000ULL;\n"
        "  }\n"
        "  if (dataType_ == ge::DT_FLOAT16) {\n"
        "    tilingKey += 0;\n"
        "  } else if (dataType_ == ge::DT_BF16) {\n"
        "    tilingKey += 22220ULL;\n"
        "  } else if (dataType_ == ge::DT_FLOAT8_E4M3FN) {\n"
        "    if (attentionOutDataType_ == ge::DT_FLOAT16) {\n"
        "      tilingKey += 10;\n"
        "    } else if (attentionOutDataType_ == ge::DT_BF16) {\n"
        "      tilingKey += 20;\n"
        "    }\n"
        "  }\n"
        "  if (kvCacheLayout_ == BSAKvCacheLayout::TND_KV) {\n"
        "    tilingKey += 30000000ULL;\n"
        "  } else if (kvCacheLayout_ == BSAKvCacheLayout::BNSD_KV) {\n"
        "    tilingKey += 50000000ULL;\n"
        "  }\n"
        "  bool hasPagedCache = (ctx->GetOptionalInputTensor(BLOCK_TABLE_INDEX) != nullptr);\n"
        "  if (hasPagedCache) {\n"
        "    tilingKey += 1000000ULL;\n"
        "  }\n"
        "  if (innerPrecise_ == 1) {\n"
        "    tilingKey += 100000ULL;\n"
        "  } else if (innerPrecise_ == 4) {\n"
        "    tilingKey += 400000ULL;\n"
        "  }\n"
        "  if (maskType_ == 3) {\n"
        "    tilingKey += 3000ULL;\n"
        "  }\n"
        "  if (qInputLayout_ == BSAQInputLayout::TND_Q) {\n"
        "    tilingKey += 2;\n"
        "  } else if (qInputLayout_ == BSAQInputLayout::BNSD_Q) {\n"
        "    tilingKey += 3;\n"
        "  }\n"
        "  if (softmaxLseFlag_) {\n"
        "    tilingKey += 100000000ULL;\n"
        "  }\n"
        "  return tilingKey;\n"
        "}\n"
    )
    dims = iter_bitpack_dims(text)
    names = [d["name"] for d in dims]
    assert names == [
        "socVer_",
        "dataType_",
        "attentionOutDataType_",
        "kvCacheLayout_",
        "hasPagedCache",
        "innerPrecise_",
        "maskType_",
        "qInputLayout_",
        "softmaxLseFlag_",
    ]
    assert "QF16_KVF16_TND_TND_NOCACHE_FLOATSM_NOMASK_BSA_TILING" not in names


def test_if_literal_pack_mints_axes_not_named_catalog(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _bare_op(op)
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "uint64_t GenerateTilingKey() {\n"
        "  uint64_t tilingKey = 9000000000000000ULL;\n"
        "  if (socVer_ == 950) tilingKey = 9050000000000000ULL;\n"
        "  if (dataType_ == 1) tilingKey += 22220ULL;\n"
        "  if (kvCacheLayout_ == 1) tilingKey += 30000000ULL;\n"
        "  if (hasPagedCache) tilingKey += 1000000ULL;\n"
        "  if (innerPrecise_ == 1) tilingKey += 100000ULL;\n"
        "  if (maskType_ == 3) tilingKey += 3000ULL;\n"
        "  if (qInputLayout_ == 2) tilingKey += 2;\n"
        "  if (softmaxLseFlag_) tilingKey += 100000000ULL;\n"
        "  return tilingKey;\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  TILING_KEY_IS(QF16_KVF16_TND_TND_NOCACHE_FLOATSM_NOMASK_BSA_TILING);\n"
        "  TILING_KEY_IS(QBF16_KVBF16_BNSD_BNSD_NOCACHE_HALFSM_NOMASK_BSA_TILING);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    by_name = {
        e.name: e
        for e in cm.by_kind(EntityKind.TILING_KEY)
        if e.attrs.get("source_declared")
    }
    assert "QF16_KVF16_TND_TND_NOCACHE_FLOATSM_NOMASK_BSA_TILING" not in by_name
    assert set(by_name) >= {
        "socVer_",
        "dataType_",
        "kvCacheLayout_",
        "hasPagedCache",
        "innerPrecise_",
        "maskType_",
        "qInputLayout_",
        "softmaxLseFlag_",
    }
    assert by_name["dataType_"].attrs.get("provenance") == "source_bitpack_dim"
    legal = cm.meta.get("source_packed_legal_keys") or []
    assert "QF16_KVF16_TND_TND_NOCACHE_FLOATSM_NOMASK_BSA_TILING" in legal
    from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions

    bind_host_tiling_key_expressions(cm, op, architecture="arch35")
    meta = cm.meta["host_tiling_key_packing"]
    assert meta["fields_bound"] == meta["declared"]
    assert meta["declared"] >= 8
    assert any("dataType_" in e for e in (by_name["dataType_"].attrs.get("host_packing_expressions") or []))


def test_shift_pack_mints_dimensions_not_tiling_key_is_catalog(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _bare_op(op)
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "void SetTilingKey(const ge::DataType inDtype, bool doRmsQuant, auto *context) {\n"
        "  uint64_t tilingKey = static_cast<uint64_t>(inDtype == ge::DT_BF16);\n"
        "  tilingKey = (tilingKey << 2) + static_cast<uint64_t>(param.cacheMode);\n"
        "  tilingKey = (tilingKey << 1) + static_cast<uint64_t>(formatWeight1 == ge::FORMAT_FRACTAL_NZ);\n"
        "  tilingKey = (tilingKey << 1) + static_cast<uint64_t>(formatWeight2 == ge::FORMAT_FRACTAL_NZ);\n"
        "  tilingKey = (tilingKey << 1) + static_cast<uint64_t>(formatWeight3 == ge::FORMAT_FRACTAL_NZ);\n"
        "  tilingKey = (tilingKey << 2) + static_cast<uint64_t>(param.quantMode);\n"
        "  if (!doRmsQuant){\n"
        "    tilingKey += 1000;\n"
        "  }\n"
        "  context->SetTilingKey(tilingKey);\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  if (TILING_KEY_IS(0)) { return; }\n"
        "  if (TILING_KEY_IS(4)) { return; }\n"
        "  if (TILING_KEY_IS(8)) { return; }\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    by_name = {
        e.name: e
        for e in cm.by_kind(EntityKind.TILING_KEY)
        if e.attrs.get("source_declared")
    }
    assert set(by_name) == {
        "inDtype",
        "cacheMode",
        "formatWeight1",
        "formatWeight2",
        "formatWeight3",
        "quantMode",
        "doRmsQuant",
    }
    assert by_name["cacheMode"].attrs.get("provenance") == "source_bitpack_dim"
    assert by_name["cacheMode"].attrs.get("bit_width") == 2
    assert "0" not in by_name
    assert "4" not in by_name
    assert "8" not in by_name
    legal = cm.meta.get("source_packed_legal_keys") or []
    assert "0" in legal
    assert "4" in legal
    assert "8" in legal
    from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions

    bind_host_tiling_key_expressions(cm, op, architecture="arch35")
    meta = cm.meta["host_tiling_key_packing"]
    assert meta["fields_bound"] == 7
    assert meta["declared"] == 7
    for name, needle in (
        ("inDtype", "inDtype"),
        ("cacheMode", "cacheMode"),
        ("formatWeight1", "formatWeight1"),
        ("quantMode", "quantMode"),
        ("doRmsQuant", "1000"),
    ):
        exprs = " ".join(by_name[name].attrs.get("host_packing_expressions") or [])
        assert needle in exprs
    kernel = cm.by_name("toy", kind=EntityKind.KERNEL)[0]
    assert any(
        r.src == by_name["cacheMode"].id
        and r.dst == kernel.id
        and r.kind_name() == "SELECTS"
        for r in cm.relations.values()
    )


def test_get_tilingkey_helper_wins_over_bitpack_shift(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _bare_op(op)
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "uint64_t GetTilingKey() const {\n"
        "  return GET_TILINGKEY(layout, sparse, mask);\n"
        "}\n"
        "void PackBits() {\n"
        "  uint64_t tilingKey = static_cast<uint64_t>(inDtype == ge::DT_BF16);\n"
        "  tilingKey = (tilingKey << 2) + static_cast<uint64_t>(param.cacheMode);\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  if (TILING_KEY_IS(24UL)) { return; }\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    names = {e.name for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")}
    assert names == {"layout", "sparse", "mask"}
    assert "cacheMode" not in names
    assert "24" not in names


def test_tiling_key_is_integer_catalog_without_bitpack(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _bare_op(op)
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "void DoTiling(auto *ctx) { ctx->SetTilingKey(24UL); }\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  if (TILING_KEY_IS(24UL)) { return; }\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    names = {e.name for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")}
    assert names == {"24"}


def test_named_key_plus_one_stays_macro_catalog(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _bare_op(op)
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "#define TILING_KEY_DIVIDE_BS_FP16 100\n"
        "#define TILING_KEY_DIVIDE_BS_BF16 101\n"
        "void GenTilingKey() {\n"
        "  tilingKey_ = TILING_KEY_DIVIDE_BS_FP16;\n"
        "  if (tokenDtype_ == 1) tilingKey_ += 1;\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "#define TILING_KEY_DIVIDE_BS_FP16 100\n"
        "#define TILING_KEY_DIVIDE_BS_BF16 101\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  if (TILING_KEY_IS(TILING_KEY_DIVIDE_BS_FP16)) { return; }\n"
        "  if (TILING_KEY_IS(TILING_KEY_DIVIDE_BS_BF16)) { return; }\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    names = {e.name for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")}
    assert names == {"TILING_KEY_DIVIDE_BS_FP16", "TILING_KEY_DIVIDE_BS_BF16"}
    assert "tokenDtype_" not in names
    from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions

    bind_host_tiling_key_expressions(cm, op, architecture="arch35")
    meta = cm.meta["host_tiling_key_packing"]
    assert meta["fields_bound"] == 2


def test_weighted_add_mints_axes_not_impl_integers(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    _bare_op(op)
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "void ComputeTilingKey() {\n"
        "  tilingKey_ += normType * NORM_TYPE_TILING_KEY;\n"
        "  tilingKey_ += normAddedType * NORM_ADDED_TYPE_TILING_KEY;\n"
        "  tilingKey_ += ropeType * ROPE_TYPE_TILING_KEY;\n"
        "  tilingKey_ += concatOrder * CONCAT_ORDER_TILING_KEY;\n"
        "}\n"
        "void PostTiling() { context_->SetTilingKey(tilingKey_); }\n",
        encoding="utf-8",
    )
    impls = "\n".join(
        f"  if (TILING_KEY_IS({v})) {{ return; }}"
        for v in (0, 10, 100, 110, 200, 100000, 100010, 200000)
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        f"__gm__ uint8_t *tiling) {{\n{impls}\n}}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    by_name = {
        e.name: e
        for e in cm.by_kind(EntityKind.TILING_KEY)
        if e.attrs.get("source_declared")
    }
    assert set(by_name) == {"normType", "normAddedType", "ropeType", "concatOrder"}
    assert "0" not in by_name
    assert "100000" not in by_name
    legal = cm.meta.get("source_packed_legal_keys") or []
    assert "0" in legal
    assert "100000" in legal
    from uo_init.passes.host_tiling_key import bind_host_tiling_key_expressions

    bind_host_tiling_key_expressions(cm, op, architecture="arch35")
    meta = cm.meta["host_tiling_key_packing"]
    assert meta["fields_bound"] == 4
    assert meta["declared"] == 4
    assert "normType" in " ".join(by_name["normType"].attrs.get("host_packing_expressions") or [])


def test_local_tiling_key_is_not_replaced_by_foreign_get_tpl(tmp_path: Path) -> None:
    import yaml

    family = tmp_path / "mc2"
    op = family / "teardown"
    foreign = family / "matmul"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (foreign / "op_host").mkdir(parents=True)
    (op / "op_host" / "tiling.cpp").write_text(
        "void Pack() {\n"
        "  uint64_t tilingKey = 10000;\n"
        "  tilingKey += static_cast<uint64_t>(quantMode);\n"
        "  context_->SetTilingKey(tilingKey);\n"
        "}\n",
        encoding="utf-8",
    )
    (foreign / "op_host" / "tiling.cpp").write_text(
        "uint64_t Build() {\n"
        "  return GET_TPL_TILING_KEY(a, b, c, d, e, f, g, h, i, j, k, l, m, n, o, p);\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "teardown.cpp").write_text(
        "__global__ __aicore__ void teardown() {\n"
        "  if (TILING_KEY_IS(10000)) { return; }\n"
        "  if (TILING_KEY_IS(11000)) { return; }\n"
        "}\n",
        encoding="utf-8",
    )
    scope = op / ".ascendc-pilot" / "arch35" / "uo" / "summary"
    scope.mkdir(parents=True)
    (scope / "scope_set.yaml").write_text(
        yaml.safe_dump(
            {
                "confirmed_source_files": [
                    "op_host/tiling.cpp",
                    "op_kernel/teardown.cpp",
                    "matmul/op_host/tiling.cpp",
                ]
            }
        ),
        encoding="utf-8",
    )
    cm = CodeMap(op_name="teardown", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    by_name = {
        e.name: e
        for e in cm.by_kind(EntityKind.TILING_KEY)
        if e.attrs.get("source_declared")
    }
    assert set(by_name) == {"10000", "11000"}
    assert not any(name.startswith("pack_arg_") for name in by_name)


def test_wrapper_uses_sibling_get_tpl_when_local_host_has_no_packing(tmp_path: Path) -> None:
    import yaml

    family = tmp_path / "attention"
    wrap = family / "mla_v3"
    sib = family / "mla"
    (wrap / "op_graph").mkdir(parents=True)
    (wrap / "op_host").mkdir(parents=True)
    (wrap / "op_kernel").mkdir(parents=True)
    (sib / "op_host").mkdir(parents=True)
    (wrap / "op_host" / "register.cpp").write_text(
        "IMPL_OP_OPTILING(MlaV3).Tiling(TilingMla);\n",
        encoding="utf-8",
    )
    (sib / "op_host" / "tiling.cpp").write_text(
        "uint64_t Build() { return GET_TPL_TILING_KEY(0, 0, cvMode); }\n",
        encoding="utf-8",
    )
    (wrap / "op_kernel" / "mla_v3.cpp").write_text(
        '#include "../../mla/op_kernel/kernel.h"\n'
        "__global__ __aicore__ void mla_v3() {}\n",
        encoding="utf-8",
    )
    scope = wrap / ".ascendc-pilot" / "arch35" / "uo" / "summary"
    scope.mkdir(parents=True)
    (scope / "scope_set.yaml").write_text(
        yaml.safe_dump(
            {
                "confirmed_source_files": [
                    "op_host/register.cpp",
                    "op_kernel/mla_v3.cpp",
                    "mla/op_host/tiling.cpp",
                ]
            }
        ),
        encoding="utf-8",
    )
    cm = CodeMap(op_name="mla_v3", architecture="arch35")
    enrich_codemap_from_operator_source(cm, wrap, architecture="arch35")
    by_name = {
        e.name: e
        for e in cm.by_kind(EntityKind.TILING_KEY)
        if e.attrs.get("source_declared")
    }
    assert "cvMode" in by_name
    assert by_name["cvMode"].attrs.get("provenance") == "source_packing_helper_arg"


def test_set_tiling_key_catalog_macro_is_a_key_without_tiling_key_spelling(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT}))\n  .OUTPUT(y, TensorType({DT_FLOAT}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_host" / "toy_tiling.cpp").write_text(
        "void DoTiling(auto *ctx) { ctx->SetTilingKey(NORMAL_INT32_FULLY_LOAD); }\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "class ToyTilingData { public: uint32_t worldSize; };\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA_WITH_STRUCT(ToyTilingData, td, tiling);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    names = {e.name for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")}
    assert "NORMAL_INT32_FULLY_LOAD" in names
    assert "tiling" not in names
    key = cm.by_name("NORMAL_INT32_FULLY_LOAD", kind=EntityKind.TILING_KEY)[0]
    assert int(key.attrs.get("candidate_score") or 0) == 1


def test_tiling_data_bindings_are_per_kernel_not_cartesian(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT}))\n  .OUTPUT(y, TensorType({DT_FLOAT}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch35" / "types.h").write_text(
        "class AData { public: uint32_t a; };\n"
        "class BData { public: uint32_t b; };\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "ka.cpp").write_text(
        '#include "arch35/types.h"\n'
        "__global__ __aicore__ void kernel_a(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA_WITH_STRUCT(AData, td, tiling);\n"
        "}\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "kb.cpp").write_text(
        '#include "arch35/types.h"\n'
        "__global__ __aicore__ void kernel_b(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA_WITH_STRUCT(BData, td, tiling);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    a = cm.by_name("AData", kind=EntityKind.TILING_DATA)[0]
    b = cm.by_name("BData", kind=EntityKind.TILING_DATA)[0]
    ka = cm.by_name("kernel_a", kind=EntityKind.KERNEL)[0]
    kb = cm.by_name("kernel_b", kind=EntityKind.KERNEL)[0]
    flows = [
        (r.src, r.dst)
        for r in cm.relations.values()
        if r.kind_name() == "FLOWS_TO" and r.attrs.get("binding_role") == "consumer"
    ]
    assert (a.id, ka.id) in flows
    assert (b.id, kb.id) in flows
    assert (a.id, kb.id) not in flows
    assert (b.id, ka.id) not in flows
    bindings = cm.meta.get("tiling_data_bindings") or []
    pairs = {(row["kernel_entry"], row["type"]) for row in bindings}
    assert ("kernel_a", "AData") in pairs
    assert ("kernel_b", "BData") in pairs


def test_raw_tiling_cast_binds_type_without_tilingdata_suffix(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT}))\n  .OUTPUT(y, TensorType({DT_FLOAT}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch35" / "toy_tiling_data.h").write_text(
        "class WireAbi { public: uint32_t blockDim; };\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        '#include "arch35/toy_tiling_data.h"\n'
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  auto *td = reinterpret_cast<WireAbi*>(tiling);\n"
        "  (void)td->blockDim;\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    td = cm.by_name("WireAbi", kind=EntityKind.TILING_DATA)
    assert td
    kernel = cm.by_name("toy", kind=EntityKind.KERNEL)[0]
    assert any(
        r.src == td[0].id
        and r.dst == kernel.id
        and r.kind_name() == "FLOWS_TO"
        and r.attrs.get("binding_role") == "consumer"
        for r in cm.relations.values()
    )


def test_bare_get_tiling_data_does_not_bind_every_type_in_file(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT}))\n  .OUTPUT(y, TensorType({DT_FLOAT}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "class ATiling { public: int a; };\n"
        "class BTiling { public: int b; };\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA(td, tiling);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(EntityKind.TILING_DATA, "ATiling")
    cm.upsert(EntityKind.TILING_DATA, "BTiling")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    kernel = cm.by_name("toy", kind=EntityKind.KERNEL)[0]
    a_id = cm.by_name("ATiling", kind=EntityKind.TILING_DATA)[0].id
    b_id = cm.by_name("BTiling", kind=EntityKind.TILING_DATA)[0].id
    flows = [
        r
        for r in cm.relations.values()
        if r.kind_name() == RelationKind.FLOWS_TO.value
        and r.dst == kernel.id
        and r.src in {a_id, b_id}
    ]
    assert flows == []


def test_unregistered_class_in_tiling_data_header_is_not_seeded(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT}))\n  .OUTPUT(y, TensorType({DT_FLOAT}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch35" / "toy_tiling_data.h").write_text(
        "class ExtraTiling { public: int stray; };\n"
        "class ToyTiling { public: int n; };\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        '#include "arch35/toy_tiling_data.h"\n'
        "REGISTER_TILING_DEFAULT(ToyTiling);\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA(td, tiling);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    assert cm.by_name("ToyTiling", kind=EntityKind.TILING_DATA)
    assert not cm.by_name("ExtraTiling", kind=EntityKind.TILING_DATA)


def test_register_helper_suffix_type_is_kept(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n  .INPUT(x, TensorType({DT_FLOAT}))\n  .OUTPUT(y, TensorType({DT_FLOAT}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "class FooHelper { public: uint32_t n; };\n"
        "REGISTER_TILING_DEFAULT(FooHelper);\n"
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, "
        "__gm__ uint8_t *tiling) {\n"
        "  GET_TILING_DATA(td, tiling);\n"
        "}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    assert cm.by_name("FooHelper", kind=EntityKind.TILING_DATA)
    assert any(
        e.name == "n" and e.attrs.get("owner") == "FooHelper"
        for e in cm.by_kind(EntityKind.TILING_FIELD)
    )


def test_kernel_param_camelcase_binds_snake_reg_op_and_deq_scale(tmp_path: Path) -> None:
    op = tmp_path / "toy"
    (op / "op_graph").mkdir(parents=True)
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_graph" / "toy_proto.h").write_text(
        "REG_OP(Toy)\n"
        "  .INPUT(query, TensorType({DT_FLOAT16}))\n"
        "  .OPTIONAL_INPUT(query_rope, TensorType({DT_FLOAT16}))\n"
        "  .OPTIONAL_INPUT(d_scale_q, TensorType({DT_FLOAT}))\n"
        "  .OUTPUT(dq, TensorType({DT_FLOAT16}))\n"
        "  .OUTPUT(dq_rope, TensorType({DT_FLOAT16}))\n"
        "  .OP_END_FACTORY_REG(Toy)\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "toy.cpp").write_text(
        "__global__ __aicore__ void toy(\n"
        "    __gm__ uint8_t *query, __gm__ uint8_t *queryRope,\n"
        "    __gm__ uint8_t *deqScaleQ, __gm__ uint8_t *dq, __gm__ uint8_t *dqRope,\n"
        "    __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    enrich_codemap_from_operator_source(cm, op, architecture="arch35")
    kernel = cm.by_name("toy", kind=EntityKind.KERNEL)[0]
    flows = {
        (cm.entities[r.src].name, cm.entities[r.dst].name)
        for r in cm.relations.values()
        if r.kind_name() == "FLOWS_TO"
        and r.attrs.get("provenance") in {
            "clang_kernel_abi",
            "source_kernel_abi_position",
            "source_kernel_abi_position_verified",
        }
    }
    assert ("query", "toy") in flows
    assert ("query_rope", "toy") in flows
    assert ("d_scale_q", "toy") in flows
    assert ("toy", "dq") in flows
    assert ("toy", "dq_rope") in flows
