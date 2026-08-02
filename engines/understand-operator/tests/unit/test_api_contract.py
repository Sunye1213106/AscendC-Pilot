# -*- coding: utf-8 -*-
"""Reading the API layer's refusals, and getting them onto declared names.

The checks are written in the API layer's own vocabulary -- `queryRope`,
`qDtype`, `fagShape.dDim` -- while everything downstream speaks in the names
the operator declares. A condition that lands on the wrong name, or on half of
the right ones, is not a weaker premise than the truth: it is a different one,
and it will exclude inputs the operator accepts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from uo_init.api_contract import _Grounding
from uo_init.decl_facts import DeclFacts
from uo_init.variable_model import ParamDecl


@dataclass
class _Summary:
    name: str = ""
    locals: dict = field(default_factory=dict)
    params: list = field(default_factory=list)
    calls: list = field(default_factory=list)


@dataclass
class _Write:
    path: str
    rhs: str
    function: str = ""


DECLARED = DeclFacts(
    params=[
        ParamDecl(kind="input", name="query", index=0),
        ParamDecl(kind="input", name="key", index=1),
        ParamDecl(kind="input", name="atten_mask", index=2, param_type="OPTIONAL"),
        ParamDecl(kind="input", name="query_rope", index=3, param_type="OPTIONAL"),
        ParamDecl(kind="input", name="actual_seq_qlen", index=4, param_type="OPTIONAL"),
        ParamDecl(kind="input", name="sink", index=5, param_type="OPTIONAL"),
        ParamDecl(kind="attr", name="input_layout", index=0),
        ParamDecl(kind="attr", name="head_num", index=1),
    ]
)


def _ground(summaries=None, writes=()):
    return _Grounding(DECLARED, summaries or {}, writes=writes)


def test_a_camel_case_name_reaches_its_declared_form() -> None:
    found, missing = _ground().resolve("queryRope != nullptr", "check")
    assert found == ["query_rope"]
    assert missing == []


def test_the_suffixes_the_api_adds_are_stripped() -> None:
    """`attenMaskOptional` is `atten_mask`; the suffix marks how the API takes
    it, not a different input."""
    found, _ = _ground().resolve("attenMaskOptional == nullptr", "check")
    assert found == ["atten_mask"]


def test_suffixes_are_stripped_as_many_as_there_are() -> None:
    found, _ = _ground().resolve("sinkInOptional != nullptr", "check")
    assert found == ["sink"]


def test_the_two_sides_may_break_words_differently() -> None:
    """`actualSeqQLen` reads as `actual_seq_q_len`; the operator declares
    `actual_seq_qlen`. Same input, different idea of where the words end."""
    found, missing = _ground().resolve("actualSeqQLenOptional != nullptr", "check")
    assert found == ["actual_seq_qlen"]
    assert missing == []


def test_calls_and_qualifiers_are_syntax_not_inputs() -> None:
    found, missing = _ground().resolve(
        "query->GetDataType() == op::DataType::DT_BF16", "check"
    )
    assert found == ["query"]
    assert missing == []


def test_a_cast_names_a_type_not_a_value() -> None:
    found, missing = _ground().resolve(
        "static_cast<int64_t>(headNum) > 0", "check"
    )
    assert found == ["head_num"]
    assert missing == []


def test_words_inside_a_string_are_a_value_not_names() -> None:
    found, missing = _ground().resolve(
        'strcmp(inputLayout, "same_as_input") != 0', "check"
    )
    assert found == ["input_layout"]
    assert missing == []


def test_a_local_is_followed_back_to_what_it_was_read_from() -> None:
    summaries = {"check": _Summary(locals={"qDtype": "query->GetDataType()"})}
    found, missing = _ground(summaries).resolve("qDtype == DT_BF16", "check")
    assert found == ["query"]
    assert missing == []


def test_a_formal_is_followed_back_through_its_callers() -> None:
    """The checker takes `layout` and knows nothing about where it came from.
    The caller does."""
    summaries = {
        "check": _Summary(params=["layout"]),
        "driver": _Summary(calls=[("check", ("inputLayout",))]),
    }
    found, missing = _ground(summaries).resolve('layout == "TND"', "check")
    assert found == ["input_layout"]
    assert missing == []


def test_every_caller_is_followed_not_the_first() -> None:
    """Each call happens, so each argument is equally constrained by the check.
    Taking one would drop a real requirement on the other."""
    summaries = {
        "check": _Summary(params=["tensor"]),
        "a": _Summary(calls=[("check", ("query",))]),
        "b": _Summary(calls=[("check", ("key",))]),
    }
    found, _ = _ground(summaries).resolve("tensor == nullptr", "check")
    assert sorted(found) == ["key", "query"]


def test_a_field_of_a_scratch_struct_reaches_the_input_that_filled_it() -> None:
    writes = [_Write("fagShape.dDim", "queryShape.GetDim(2)", "fill")]
    summaries = {"fill": _Summary(locals={"queryShape": "query->GetViewShape()"})}
    found, missing = _ground(summaries, writes).resolve(
        "fagShape.dDim == 192", "fill"
    )
    assert found == ["query"]
    assert missing == []


def test_a_field_written_in_one_function_is_found_from_another() -> None:
    writes = [_Write("fagShape.dDim", "query->GetViewShape().GetDim(2)", "fill")]
    found, missing = _ground({}, writes).resolve("fagShape.dDim == 192", "test")
    assert found == ["query"]
    assert missing == []


def test_the_struct_holding_a_field_is_not_itself_a_missing_input() -> None:
    """`fagShape` carries no value of its own, so it is not what is missing.
    A field of it with nothing written to it is."""
    writes = [_Write("fagShape.dDim", "query->GetViewShape().GetDim(2)", "fill")]
    found, missing = _ground({}, writes).resolve(
        "fagShape.dDim == 192 && fagShape.needTranspose", "fill"
    )
    assert found == ["query"]
    assert missing == ["needTranspose"]


def test_an_identifier_reaching_nothing_is_reported() -> None:
    """Not silently dropped: a condition grounded in part is a different
    condition, and downstream has to be able to tell."""
    found, missing = _ground().resolve("mysteryValue > 3", "check")
    assert found == []
    assert missing == ["mysteryValue"]


def test_the_chase_stops_rather_than_looping() -> None:
    """Two locals defined from each other terminate, and reach no input --
    which leaves the condition ungrounded rather than quietly grounded."""
    summaries = {"check": _Summary(locals={"a": "b + 1", "b": "a - 1"})}
    found, _ = _ground(summaries).resolve("a > 0", "check")
    assert found == []


# -- the refusal test itself, which needs clang -------------------------------

cindex = pytest.importorskip("clang.cindex", reason="libclang bindings not installed")

from uo_init.clang_walk import _guard_clause_negations  # noqa: E402

SOURCE = """\
enum Status { OK = 0, FAILED = 1 };

bool Check(int layout, int dtype)
{
    if (layout == 4 && dtype != 2) {
        OP_LOGE("rope needs bf16");
        return false;
    }
    if (dtype == 9) {
        return false;
    }
    return true;
}
"""


@pytest.fixture(scope="module")
def guards(tmp_path_factory):
    root = tmp_path_factory.mktemp("api")
    source = root / "check.cpp"
    source.write_text(SOURCE, encoding="utf-8")
    try:
        tu = cindex.Index.create().parse(str(source), args=["-std=c++17"])
    except cindex.LibclangError as exc:  # pragma: no cover - environment
        pytest.skip(f"libclang unavailable: {exc}")

    def ifs(node):
        for child in node.get_children():
            if child.kind.name == "IF_STMT":
                yield child
            yield from ifs(child)

    return list(ifs(tu.cursor))


def test_logging_an_error_on_the_way_out_is_a_refusal(guards) -> None:
    got = _guard_clause_negations(guards[0], True)
    assert [c.kind for c in got] == ["bailout"]


def test_tiling_does_not_read_a_bare_return_that_way(guards) -> None:
    """`return false` is ordinary control flow in tiling. Reading it as a
    refusal would turn every early return into a claim about the input."""
    got = _guard_clause_negations(guards[0], False)
    assert [c.kind for c in got] != ["bailout"]


def test_leaving_without_saying_why_is_not_a_refusal_either(guards) -> None:
    """The second branch returns false with no error logged, so nothing marks
    it as rejecting the input rather than handling a case."""
    got = _guard_clause_negations(guards[1], True)
    assert [c.kind for c in got] != ["bailout"]
