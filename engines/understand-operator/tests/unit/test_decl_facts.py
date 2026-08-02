# -*- coding: utf-8 -*-
"""Reading the declared interface, including the part that is easy to lose.

The dtype lists in an operator definition are columns of a table: entry `i` of
every parameter belongs to one supported combination. Read as independent sets
they permit combinations the operator never claimed -- a FLOAT8 query beside a
FLOAT16 key -- and the analysis then reports keys for inputs that are refused
before any tiling happens.
"""
from __future__ import annotations

from pathlib import Path

from uo_init.decl_facts import extract_decl_facts, parse_proto

OPDEF = """\
class Widget : public OpDef {
public:
    explicit Widget(const char *name) : OpDef(name)
    {
        this->Input("query")
            .ParamType(REQUIRED)
            .DataType({ge::DT_FLOAT16, ge::DT_BF16, ge::DT_FLOAT8_E5M2});
        this->Input("key")
            .ParamType(REQUIRED)
            .DataType({ge::DT_FLOAT16, ge::DT_BF16, ge::DT_FLOAT8_E5M2});
        this->Input("mask")
            .ParamType(OPTIONAL)
            .DataType({ge::DT_UINT8});
        this->Output("out")
            .ParamType(REQUIRED)
            .DataType({ge::DT_FLOAT16, ge::DT_BF16, ge::DT_FLOAT16});
        this->Attr("head_num").AttrType(REQUIRED).Int();
        this->Attr("sparse_mode").AttrType(OPTIONAL).Int(0);
        this->Attr("keep_prob").AttrType(OPTIONAL).Float(1.0);
    }
};
OP_ADD(Widget);
"""

PROTO = """\
REG_OP(Widget)
    .INPUT(query, TensorType({DT_FLOAT16, DT_BF16, DT_FLOAT8_E5M2}))
    .INPUT(key, TensorType({DT_FLOAT16, DT_BF16, DT_FLOAT8_E5M2}))
    .OPTIONAL_INPUT(mask, TensorType({DT_UINT8}))
    .OUTPUT(out, TensorType({DT_FLOAT16, DT_BF16}))
    .REQUIRED_ATTR(head_num, Int)
    .ATTR(sparse_mode, Int, 0)
    .ATTR(keep_prob, Float, 1.0)
    .OP_END_FACTORY_REG(Widget)
"""


def _facts(tmp_path: Path, opdef: str = OPDEF, proto: str = PROTO):
    d = tmp_path / "widget_def.cpp"
    d.write_text(opdef, encoding="utf-8")
    p = tmp_path / "widget_proto.h"
    p.write_text(proto, encoding="utf-8")
    return extract_decl_facts(d, p)


def test_parameters_carry_the_position_host_code_reads_them_by(tmp_path: Path) -> None:
    facts = _facts(tmp_path)
    assert facts.index_of("query") == 0
    assert facts.index_of("mask") == 2
    assert facts.index_of("out", kind="output") == 0
    assert facts.by_name("sparse_mode").index == 1


def test_dtype_lists_are_read_as_combinations_not_as_sets(tmp_path: Path) -> None:
    facts = _facts(tmp_path)
    assert len(facts.combinations) == 3
    pairs = {(c.by_param["query"], c.by_param["key"]) for c in facts.combinations}
    assert pairs == {
        ("DT_FLOAT16", "DT_FLOAT16"),
        ("DT_BF16", "DT_BF16"),
        ("DT_FLOAT8_E5M2", "DT_FLOAT8_E5M2"),
    }
    # The pairing is the point: nothing here permits a BF16 query with a
    # FLOAT16 key, though both appear in both lists.
    assert ("DT_BF16", "DT_FLOAT16") not in pairs


def test_a_single_entry_holds_for_every_combination(tmp_path: Path) -> None:
    """`mask` lists one dtype against three combinations, meaning it every
    time -- not that two combinations leave it unspecified."""
    facts = _facts(tmp_path)
    assert [c.by_param["mask"] for c in facts.combinations] == ["DT_UINT8"] * 3


def test_a_repeated_dtype_is_still_its_own_combination(tmp_path: Path) -> None:
    """`out` names FLOAT16 twice. Deduplicating would shorten the column and
    misalign every parameter after it."""
    facts = _facts(tmp_path)
    assert [c.by_param["out"] for c in facts.combinations] == [
        "DT_FLOAT16",
        "DT_BF16",
        "DT_FLOAT16",
    ]


def test_columns_that_cannot_line_up_are_refused_not_guessed(tmp_path: Path) -> None:
    ragged = OPDEF.replace(
        '.DataType({ge::DT_FLOAT16, ge::DT_BF16, ge::DT_FLOAT8_E5M2});\n'
        '        this->Input("mask")',
        '.DataType({ge::DT_FLOAT16, ge::DT_BF16});\n        this->Input("mask")',
        1,
    )
    facts = _facts(tmp_path, opdef=ragged)
    assert facts.combinations == []
    assert any("ragged" in n for n in facts.disagreements)


def test_attribute_defaults_come_through(tmp_path: Path) -> None:
    facts = _facts(tmp_path)
    assert facts.attr_defaults() == {"sparse_mode": "0", "keep_prob": "1.0"}


def test_optional_inputs_are_named(tmp_path: Path) -> None:
    assert _facts(tmp_path).optional_inputs() == ["mask"]


def test_the_two_declarations_are_compared_rather_than_merged(tmp_path: Path) -> None:
    """They are maintained by hand and drift. Which one is right is not
    something this can decide, so it says so instead of picking."""
    drifted = PROTO.replace(".ATTR(sparse_mode, Int, 0)", ".ATTR(sparse_mode, Int, 3)")
    facts = _facts(tmp_path, proto=drifted)
    assert any(
        "sparse_mode" in n and "default" in n for n in facts.disagreements
    ), facts.disagreements


def test_a_parameter_missing_from_one_side_is_reported(tmp_path: Path) -> None:
    short = PROTO.replace(
        "    .OPTIONAL_INPUT(mask, TensorType({DT_UINT8}))\n", ""
    )
    facts = _facts(tmp_path, proto=short)
    assert any("input_names_differ" in n for n in facts.disagreements)


def test_agreeing_declarations_report_nothing(tmp_path: Path) -> None:
    assert _facts(tmp_path).disagreements == []


def test_the_prototype_reads_on_its_own(tmp_path: Path) -> None:
    p = tmp_path / "widget_proto.h"
    p.write_text(PROTO, encoding="utf-8")
    name, params = parse_proto(p)
    assert name == "Widget"
    assert [x.name for x in params if x.kind == "input"] == ["query", "key", "mask"]
    assert next(x for x in params if x.name == "mask").optional
    assert not next(x for x in params if x.name == "query").optional
    assert next(x for x in params if x.name == "head_num").value_type == "Int"
