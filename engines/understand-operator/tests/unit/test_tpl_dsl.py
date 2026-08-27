# -*- coding: utf-8 -*-
from uo_init.tpl_dsl import (
    TplDim,
    TplSchema,
    bit_comment_ranges,
    expand_tpl_source,
    parse_args_decl,
    parse_args_sel,
    parse_file,
    parse_tpl_corpus,
    strip_cpp_comments,
)


MINI = """
ASCENDC_TPL_ARGS_DECL(OpX,
    ASCENDC_TPL_BOOL_DECL(IsEmpty, 0, 1),
    ASCENDC_TPL_UINT_DECL(Split, ASCENDC_TPL_3_BW, ASCENDC_TPL_UI_LIST, 0, 1, 5),
    ASCENDC_TPL_UINT_DECL(S1, ASCENDC_TPL_8_BW, ASCENDC_TPL_UI_LIST, 0, 64, 128),
)
"""


def test_parse_kernel_type_decl_is_a_packing_dim():
    src = (
        "ASCENDC_TPL_ARGS_DECL(OpX,\n"
        "    ASCENDC_TPL_UINT_DECL(MODE, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1),\n"
        "    ASCENDC_TPL_KERNEL_TYPE_DECL(CV_MODE, ASCENDC_TPL_MIX_AIC_1_1, ASCENDC_TPL_MIX_AIC_1_2));\n"
    )
    sch = parse_args_decl(src)
    assert [d.name for d in sch.dims] == ["MODE", "CV_MODE"]
    assert sch.dims[1].kind == "KERNEL_TYPE"
    assert sch.dims[1].bw == 6


def test_parse_minimal_decl_fixture():
    sch = parse_args_decl(MINI)
    assert len(sch.dims) == 3
    assert sch.total_bits == 1 + 3 + 8
    assert sch.dims[0].bit_lo == 0 and sch.dims[0].bit_hi == 0
    assert sch.dims[1].bit_lo == 1 and sch.dims[1].bit_hi == 3
    assert sch.dims[2].bit_lo == 4 and sch.dims[2].bit_hi == 11


def test_uint_index_encoding():
    """The UI_LIST marker introduces the values; it is not one of them, so
    indices count from the first real value."""
    dim = TplDim(
        name="S1",
        kind="UINT",
        bw=8,
        vals=["ASCENDC_TPL_UI_LIST", "0", "64", "128"],
    )
    sch = TplSchema(op_tag="X", dims=[dim])
    assert dim.value_domain == ["0", "64", "128"]
    assert sch.encode_uint(dim, "0") == 0
    assert sch.encode_uint(dim, "64") == 1
    assert sch.encode_uint(dim, 128) == 2


def test_bool_direct_encoding():
    sch = TplSchema(op_tag="X", dims=[])
    assert sch.encode_bool(1) == 1
    assert sch.encode_bool(0) == 0
    assert sch.encode_bool("true") == 1
    assert sch.encode_bool("false") == 0


def test_bool_sel_canonicalizes_true_false():
    groups = parse_args_sel(
        "ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_BOOL_SEL(HasAttenMask, false, true));"
    )
    assert groups[0][0]["vals"] == ["0", "1"]


def test_uint_literal_and_named_macro_width():
    sch = parse_args_decl(
        "ASCENDC_TPL_ARGS_DECL(Op,"
        "ASCENDC_TPL_UINT_DECL(Dx, ROPE_GRAD_BIT_WIDTH, ASCENDC_TPL_UI_RANGE, 1, 201, 206),"
        "ASCENDC_TPL_UINT_DECL(Flag, 1, ASCENDC_TPL_UI_LIST, 0, 1),"
        ")"
    )
    assert sch.dims[0].name == "Dx"
    assert sch.dims[0].bw == 8
    assert sch.dims[1].name == "Flag"
    assert sch.dims[1].bw == 1
    assert sch.dims[1].vals[0] == "ASCENDC_TPL_UI_LIST"
    sch = parse_args_decl(
        "ASCENDC_TPL_ARGS_DECL(Op,"
        "ASCENDC_TPL_UINT_DECL(A, ASCENDC_TPL_10_BW, ASCENDC_TPL_UI_LIST, 0),"
        "ASCENDC_TPL_UINT_DECL(B, ASCENDC_TPL_12_BW, ASCENDC_TPL_UI_LIST, 0),"
        ")"
    )
    assert sch.dims[0].bw == 10
    assert sch.dims[1].bw == 12


def test_fag_arch35_contract(fag_dir):
    p = fag_dir / "op_kernel" / "arch35" / "flash_attention_score_grad_template_tiling_key.h"
    sch = parse_file(p)
    assert len(sch.dims) == 19
    assert sch.total_bits == 55
    assert len(sch.selections) == 65
    text = p.read_text(encoding="utf-8", errors="replace")
    comments = bit_comment_ranges(text)
    # if comments present, they must match computed ranges
    for d in sch.dims:
        if d.name in comments:
            assert comments[d.name] == (d.bit_lo, d.bit_hi)


def test_fag_arch22_smoke(fag_dir):
    p = fag_dir / "op_kernel" / "arch22" / "flash_attention_score_grad_template_tiling_key.h"
    sch = parse_file(p)
    assert len(sch.dims) == 20
    assert len(sch.selections) == 58


def test_load_quoted_include_texts_resolves_repo_relative(tmp_path):
    from uo_init.tpl_dsl import load_quoted_include_texts

    ops = tmp_path / "ops"
    header = ops / "mc2" / "foo" / "op_kernel" / "arch35" / "foo_apt_tiling_key.h"
    header.parent.mkdir(parents=True)
    header.write_text("#define SET_NOT_USE_X 0UL, 0UL, 0\n", encoding="utf-8")
    src = ops / "mc2" / "foo" / "op_host" / "op_tiling" / "arch35" / "foo.cpp"
    src.parent.mkdir(parents=True)
    src.write_text(
        '#include "mc2/foo/op_kernel/arch35/foo_apt_tiling_key.h"\n'
        "uint64_t k = GET_TPL_TILING_KEY(1, SET_NOT_USE_X);\n",
        encoding="utf-8",
    )
    texts = load_quoted_include_texts(src, extra_roots=[ops])
    assert any("SET_NOT_USE_X" in body for body in texts)


def test_expand_tpl_source_inlines_gen_reduce_tiling_key():
    header = (
        "#define GEN_REDUCE_TILING_KEY(result, reduceTilingKey, ...) "
        "result = GET_TPL_TILING_KEY(reduceTilingKey.isContiguous, "
        "reduceTilingKey.patternID, __VA_ARGS__)\n"
    )
    src = "void T::Pack() { GEN_REDUCE_TILING_KEY(tilingKey_, key_, dxTilingKey, dCosFlag_); }\n"
    expanded = expand_tpl_source(src, [header])
    assert "GET_TPL_TILING_KEY" in expanded
    assert "key_.isContiguous" in expanded or "key.isContiguous" in expanded
    assert "dxTilingKey" in expanded
    assert "GEN_REDUCE_TILING_KEY" not in expanded


def test_decl_comment_after_open_paren_does_not_pollute_name():
    src = (
        "ASCENDC_TPL_ARGS_DECL(Op,\n"
        "    ASCENDC_TPL_UINT_DECL( // shard axis\n"
        "        Y_SHARD, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1),\n"
        "    ASCENDC_TPL_BOOL_DECL( // flag\n"
        "        IS_BIAS, 0, 1));\n"
    )
    sch = parse_args_decl(src)
    assert [d.name for d in sch.dims] == ["Y_SHARD", "IS_BIAS"]
    assert sch.dims[0].value_domain == ["0", "1"]


def test_parse_file_merges_included_decl_into_sel(tmp_path):
    decl = tmp_path / "toy_tiling_key_decl.h"
    decl.write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy,\n"
        "  ASCENDC_TPL_UINT_DECL(MODE, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1, 2),\n"
        "  ASCENDC_TPL_BOOL_DECL(SCALE, 0, 1));\n",
        encoding="utf-8",
    )
    sel = tmp_path / "arch35" / "toy_apt_tiling_key.h"
    sel.parent.mkdir()
    sel.write_text(
        '#include "../toy_tiling_key_decl.h"\n'
        "ASCENDC_TPL_SEL(\n"
        "  ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_UINT_SEL(MODE, ASCENDC_TPL_UI_LIST, 0),\n"
        "                       ASCENDC_TPL_BOOL_SEL(SCALE, 0)),\n"
        "  ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_UINT_SEL(MODE, ASCENDC_TPL_UI_LIST, 2),\n"
        "                       ASCENDC_TPL_BOOL_SEL(SCALE, 0, 1)));\n",
        encoding="utf-8",
    )
    sch = parse_file(sel)
    assert [d.name for d in sch.dims] == ["MODE", "SCALE"]
    assert len(sch.selections) == 2
    both = parse_tpl_corpus([decl, sel])
    assert [d.name for d in both.dims] == ["MODE", "SCALE"]
    assert len(both.selections) == 2


def test_strip_cpp_comments_keeps_code():
    assert "NAME" in strip_cpp_comments("ASCENDC_TPL_UINT_DECL( // x\n        NAME, 1)")


def test_strip_cpp_comments_skips_comment_marker_inside_string():
    src = 'const char *s = "http://example"; /* gone */ int x;'
    out = strip_cpp_comments(src)
    assert "http://example" in out
    assert "gone" not in out
    assert "int x" in out


def test_strip_cpp_comments_leaves_comment_free_text_unchanged():
    src = "ASCENDC_TPL_BOOL_DECL(IsFoo, 0, 1)"
    assert strip_cpp_comments(src) is src or strip_cpp_comments(src) == src


def test_expand_tpl_source_inlines_get_tpl_placeholder_macros():
    header = (
        "#define SET_NOT_USE_QUANT_MM_TILING 0UL, 0UL, 0\n"
        "#define SET_NOT_USE_WEIGHT_QUANT_MM_TILING 0UL, 0UL, 0UL, 0, 0\n"
    )
    src = (
        "uint64_t k = GET_TPL_TILING_KEY(MMTYPE_FP_MM, false, false, isA2ARSAG, "
        "commMode, matmulWithAdd, SET_NOT_USE_QUANT_MM_TILING, "
        "SET_NOT_USE_WEIGHT_QUANT_MM_TILING);\n"
    )
    expanded = expand_tpl_source(src, [header])
    inner = expanded[expanded.find("(") + 1 : expanded.rfind(")")]
    args = [a.strip() for a in inner.split(",") if a.strip()]
    assert len(args) == 14
    assert "SET_NOT_USE_QUANT_MM_TILING" not in expanded


def test_expand_args_sel_helper_macros_beyond_old_cap():
    """ARGS_SEL(helper(...)) must expand every call, including token-paste.

    A 24-step one-at-a-time expander left later groups empty, so TplSchemaPass
    stamped TPL views that canonical TEMPLATE facts could not rebuild.
    """
    n = 40
    header = (
        "#define SET_HELPER(kind, tag) "
        "ASCENDC_TPL_BOOL_SEL(FLAG, 0), "
        "ASCENDC_TPL_UINT_SEL(MODE, ASCENDC_TPL_UI_LIST, MODE_##tag)\n"
    )
    decl = (
        "ASCENDC_TPL_ARGS_DECL(OpX,\n"
        "    ASCENDC_TPL_BOOL_DECL(FLAG, 0, 1),\n"
        "    ASCENDC_TPL_UINT_DECL(MODE, ASCENDC_TPL_4_BW, ASCENDC_TPL_UI_LIST, MODE_A, MODE_B),\n"
        ")\n"
    )
    sels = "\n".join(
        f"    ASCENDC_TPL_ARGS_SEL(SET_HELPER(ASCENDC_TPL_KERNEL, {'A' if i % 2 == 0 else 'B'})),"
        for i in range(n)
    )
    src = decl + "\n" + sels + "\n"
    sch = parse_args_decl(expand_tpl_source(src, [header]))
    sch.selections = parse_args_sel(expand_tpl_source(src, [header]))
    assert len(sch.selections) == n
    assert all(len(g) == 2 for g in sch.selections)
    assert sch.selections[0][1]["vals"][-1] == "MODE_A"
    assert "SET_HELPER" not in expand_tpl_source(src, [header])


def test_parse_args_sel_skips_empty_helper_groups():
    src = (
        "ASCENDC_TPL_ARGS_SEL(SET_NOT_EXPANDED(FOO)),\n"
        "ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_BOOL_SEL(FLAG, 0)),\n"
    )
    groups = parse_args_sel(src)
    assert len(groups) == 1
    assert groups[0][0]["name"] == "FLAG"
