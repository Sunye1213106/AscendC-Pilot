# -*- coding: utf-8 -*-
from uo_init.tpl_dsl import (
    TplDim,
    TplSchema,
    bit_comment_ranges,
    parse_args_decl,
    parse_args_sel,
    parse_file,
)


MINI = """
ASCENDC_TPL_ARGS_DECL(OpX,
    ASCENDC_TPL_BOOL_DECL(IsEmpty, 0, 1),
    ASCENDC_TPL_UINT_DECL(Split, ASCENDC_TPL_3_BW, ASCENDC_TPL_UI_LIST, 0, 1, 5),
    ASCENDC_TPL_UINT_DECL(S1, ASCENDC_TPL_8_BW, ASCENDC_TPL_UI_LIST, 0, 64, 128),
)
"""


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
