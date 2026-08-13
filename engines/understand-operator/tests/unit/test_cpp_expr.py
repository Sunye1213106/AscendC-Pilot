# -*- coding: utf-8 -*-
import pytest

from uo_init.cpp_expr import EvalUnknown, evaluate, free_symbols, parse_expr, tokenize
from uo_init.expr_ir import Bin, Call, Const, Ite, Ref, pretty


def test_scoped_identifier_is_one_token():
    assert [t.text for t in tokenize("NpuArch::DAV_3510")] == ["NpuArch::DAV_3510"]


def test_precedence_and_associativity():
    e = parse_expr("a == 1 && b != 2 || c")
    assert pretty(e) == "(((a@0 == 1) && (b@0 != 2)) || c@0)"


def test_arrow_chain_becomes_nested_calls():
    e = parse_expr("ctx->GetAttrs()->GetAttrNum()")
    assert pretty(e) == "GetAttrNum(GetAttrs(ctx@0))"


def test_static_cast_is_transparent():
    e = parse_expr("static_cast<size_t>(AttrIndex::X)")
    assert e == Ref("AttrIndex::X")


def test_named_and_functional_integer_casts_are_transparent():
    assert parse_expr("reinterpret_cast<uint8_t>(Mode::ON)") == Ref("Mode::ON")
    assert parse_expr("const_cast<int>(kFlag)") == Ref("kFlag")
    assert parse_expr("uint8_t(Mode::ON)") == Ref("Mode::ON")


def test_template_call_arguments_are_parsed():
    e = parse_expr("p->GetAttrPointer<char>(idx)")
    assert isinstance(e, Call)
    assert e.func == "GetAttrPointer"
    assert e.args[1] == Ref("idx")


def test_member_access_is_marked_as_field():
    e = parse_expr("params.sparseMode")
    assert isinstance(e, Call) and e.func == "field:sparseMode"


def test_ternary_parses():
    e = parse_expr('n > 2 ? p : ""')
    assert isinstance(e, Ite)
    assert e.else_ == Const("", string_literal=True)


def test_a_quoted_value_is_marked_and_a_bare_name_is_not():
    # The quotes are dropped here, so whether they were there is recorded: with
    # them the value is a string, without them it is a reference to a name.
    quoted = parse_expr('layout == "TND"')
    assert quoted.right == Const("TND", string_literal=True)
    assert parse_expr("layout == TND").right == Ref("TND")


def test_short_circuit_avoids_unbound_symbol():
    e = parse_expr("a && b")
    assert evaluate(e, {"a": False}) is False
    with pytest.raises(EvalUnknown):
        evaluate(e, {"a": True})


def test_symbol_hook_used_for_unbound_names():
    e = parse_expr("x + 1")
    assert evaluate(e, {}, symbol_hook=lambda s, env: 41) == 42


def test_call_hook_receives_the_call_node():
    e = parse_expr("strcmp(a, b)")
    seen = {}

    def hook(call, env):
        seen["func"] = call.func
        return 0

    assert evaluate(e, {"a": "", "b": ""}, call_hook=hook) == 0
    assert seen["func"] == "strcmp"


def test_free_symbols():
    assert free_symbols(parse_expr("a == b && f(c)")) == {"a", "b", "c"}
