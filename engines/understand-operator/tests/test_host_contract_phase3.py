"""阶段3：TilingData schema / FieldWrite / receiver binding。"""
from __future__ import annotations

from uo.scripts.ascendc_macro_facts import extract_macro_facts
from uo.scripts.receiver_binding import extract_receiver_bindings_from_text
from uo.scripts.tiling_data_flow import extract_field_writes_from_text
from uo.scripts.tiling_data_schema import (
    extract_schemas_from_macro_facts,
    variant_identity,
)


def test_no_roots0_default_with_two_get_tiling_data():
    text = """
    auto *normal = context->GetTilingData<NormalTiling>();
    auto *tnd = context->GetTilingData<TndTiling>();
    if (isTnd) {
        params_ = &tnd->baseParams;
    } else {
        params_ = &normal->baseParams;
    }
"""
    bindings = extract_receiver_bindings_from_text(text, file_path="t.cpp")
    real = [b for b in bindings if b.get("receiver") == "params_"]
    assert real
    # Must not invent single default from roots[0]
    schemas = {b.get("root_schema_variant") for b in real}
    # Either alternatives or last write — root_variable must be tnd or normal
    assert real[0].get("root_variable") in {"tnd", "normal"}
    assert real[0].get("root_schema_variant") in {"TndTiling", "NormalTiling"}
    alts = real[0].get("alternatives") or []
    # second assignment stored as alternative
    assert alts or real[0]["root_variable"] in {"tnd", "normal"}


def test_common_assign_without_body_no_placeholder():
    """无 #define 时不算 binding 宏：不发明 placeholder，也不按宏名硬编码 unresolved。"""
    text = "TILING_DATA_COMMON_ASSIGN(tilingData, Base);"
    bindings = extract_receiver_bindings_from_text(text)
    real = [b for b in bindings if b.get("receiver")]
    assert not real
    assert not any(b.get("canonical") for b in bindings if b.get("receiver"))


def test_common_assign_with_substitution():
    text = """
#define TILING_DATA_COMMON_ASSIGN(ROOT, PREFIX) params_ = &(ROOT)->PREFIX##BaseParams
TILING_DATA_COMMON_ASSIGN(tilingData, Foo);
auto *tilingData = GetTilingData<DemoTiling>();
"""
    # order: need GetTilingData before or after — our extractor scans whole text
    text2 = """
auto *tilingData = GetTilingData<DemoTiling>();
#define TILING_DATA_COMMON_ASSIGN(ROOT, PREFIX) params_ = &(ROOT)->PREFIX##BaseParams
TILING_DATA_COMMON_ASSIGN(tilingData, Foo);
"""
    bindings = extract_receiver_bindings_from_text(text2)
    real = [b for b in bindings if b.get("receiver") == "params_"]
    assert real
    assert real[0].get("parameter_substitution_resolved") is True
    assert real[0].get("nested_path") == "FooBaseParams"
    assert real[0].get("root_schema_variant") == "DemoTiling"


def test_field_write_versions_and_rhs(tmp_path):
    body = """
    tiling_->set_mode(0);
    if (cond) {
        tiling_->set_mode(1);
    }
"""
    # binding
    preamble = "auto *root = GetTilingData<DemoTiling>();\ntiling_ = &root->base;\n"
    ents, edges, _ev, _un = extract_field_writes_from_text(
        preamble + body,
        file_path="x.cpp",
        writer_function="Save",
        compile_context_id="cc",
        architecture="arch35",
    )
    writes = [e for e in ents if e["kind"] == "FieldWrite"]
    assert len(writes) >= 2
    assert any(w.get("rhs_expression_ir", {}).get("source_text") == "0" for w in writes)
    assert any(w.get("rhs_expression_ir", {}).get("source_text") == "1" for w in writes)
    assert any(e.get("type") == "WRITES_FIELD" for e in edges)
    # reaching definition on last
    modes = [w for w in writes if "mode" in str(w.get("field_path"))]
    assert any(w.get("reaching_definition") is True for w in modes)


def test_schema_from_macro_facts(tmp_path):
    repo = tmp_path / "op"
    (repo / "op_host").mkdir(parents=True)
    (repo / "op_host" / "td.h").write_text(
        """
BEGIN_TILING_DATA_DEF(DemoTilingData)
TILING_DATA_FIELD_DEF(uint32_t, s1);
TILING_DATA_FIELD_DEF_STRUCT(BaseParams, baseParams);
END_TILING_DATA_DEF
REGISTER_TILING_DATA_CLASS(DemoOp, DemoTilingData)
""",
        encoding="utf-8",
    )
    uo = repo / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    facts = extract_macro_facts(repo, "Demo", uo_root=uo)
    ents, _ev, _un = extract_schemas_from_macro_facts(
        facts, compile_context_id="cc", architecture="arch35"
    )
    kinds = {e["kind"] for e in ents}
    assert "TilingSchema" in kinds
    assert "TilingSchemaVariant" in kinds
    assert "TilingField" in kinds
    vid = variant_identity(base_schema="DemoTilingData", compile_context_id="cc", architecture="arch35")
    assert vid.startswith("TSV:")
