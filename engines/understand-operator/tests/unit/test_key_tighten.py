# -*- coding: utf-8 -*-
"""strcmp layout rewrite + key reachability invariants."""
from __future__ import annotations

from types import SimpleNamespace

from uo_init.cpp_expr import parse_expr
from uo_init.expr_ir import Bin, Const
from uo_init.key_reachability import R_UNDERIVABLE, KeyReachability
from uo_init.materialize_tiling import classify_key_reachability
from uo_init.predicate import rewrite_strcmp_cmp
from uo_init.tpl_dsl import parse_args_decl, parse_args_sel


def test_rewrite_strcmp_layout_eq():
    tree = parse_expr('strcmp(GetAttrPointer(GetAttrs(context_), LAYOUT_ATTR_IDX), "TND") == 0')
    out = rewrite_strcmp_cmp(tree)
    assert isinstance(out, Bin)
    assert out.op == "=="
    assert isinstance(out.right, Const)
    assert out.right.value in ("TND", '"TND"') or str(out.right.value).strip("'\"") == "TND"


_TPL = """
ASCENDC_TPL_ARGS_DECL(FlashAttentionScoreGrad,
    ASCENDC_TPL_UINT_DECL(IsRegbase, ASCENDC_TPL_1_BW, ASCENDC_TPL_UI_LIST, 0, 1),
    ASCENDC_TPL_UINT_DECL(OutDType, ASCENDC_TPL_3_BW, ASCENDC_TPL_UI_LIST, 0, 1, 2, 3),
);
ASCENDC_TPL_SEL(
    ASCENDC_TPL_ARGS_SEL(
        ASCENDC_TPL_UINT_SEL(IsRegbase, ASCENDC_TPL_UI_LIST, 0, 1),
        ASCENDC_TPL_UINT_SEL(OutDType, ASCENDC_TPL_UI_LIST, 0, 1, 2, 3),
    ),
);
"""


def _schema():
    schema = parse_args_decl(_TPL)
    schema.selections = parse_args_sel(_TPL)
    return schema


def test_a_key_is_not_reachable_just_because_nothing_objected():
    """The old gate returned `reachable` whenever three rules stayed quiet.

    Two of those rules were operator facts written by hand (`IsRegbase` is
    always 1, `OutDType` equals `InputDType`). Correct or not, a verdict must
    come from the derivation, so with no derivation to consult every key is
    `underivable` — including the ones the old rules liked.
    """
    schema = _schema()
    verdict = classify_key_reachability(
        dims={"IsRegbase": "1", "OutDType": "2"},
        schema=schema,
        binding=None,
        blocker_ids=[],
        reachability=KeyReachability.unavailable("no derivation"),
    )
    assert verdict.status == R_UNDERIVABLE


def test_a_value_the_template_cannot_spell_is_rejected_before_the_solver():
    schema = _schema()
    bound = SimpleNamespace(
        bindings=[
            SimpleNamespace(decl=SimpleNamespace(name=d.name)) for d in schema.dims
        ]
    )
    verdict = classify_key_reachability(
        dims={"IsRegbase": "1", "OutDType": "9"},
        schema=schema,
        binding=bound,
        blocker_ids=[],
        reachability=KeyReachability.unavailable("no derivation"),
    )
    assert verdict.status == R_UNDERIVABLE
    assert "not in domain" in verdict.reason
