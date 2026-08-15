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


def test_alias_register_and_tiling_data_header_seed_nested_types(tmp_path: Path) -> None:
    """Entry may REGISTER an alias; *tiling_data* header still inventories ABI."""
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
        "template <bool Flag>\n"
        "class PackTilingData { public:\n"
        "  InnerParams base;\n"
        "  typename std::conditional<Flag, InnerParams, std::nullptr_t>::type opt;\n"
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
    outer_fields = {
        e.name: e.attrs.get("cpp_type")
        for e in cm.by_kind(EntityKind.TILING_FIELD)
        if e.attrs.get("owner") == "PackTilingData"
    }
    assert "base" in outer_fields
    assert "opt" in outer_fields
    assert "blockStarts" in outer_fields
    assert any(
        e.name == "scale" and e.attrs.get("owner") == "InnerParams"
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
    assert any(
        r.src in {e.id for e in keys}
        and r.dst == kernel.id
        and r.kind_name() == "SELECTS"
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
    assert any(e.name == "tilingKey" for e in keys)
    kernel = cm.by_name("toy", kind=EntityKind.KERNEL)[0]
    assert any(
        r.src in {e.id for e in keys}
        and r.dst == kernel.id
        and r.kind_name() == "SELECTS"
        for r in cm.relations.values()
    )
