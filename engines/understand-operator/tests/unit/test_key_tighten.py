# -*- coding: utf-8 -*-
"""strcmp layout rewrite + key reachability invariants."""
from __future__ import annotations

from uo_init.cpp_expr import parse_expr
from uo_init.expr_ir import Bin, Const
from uo_init.materialize_tiling import z3_check_key_dims
from uo_init.predicate import rewrite_strcmp_cmp


def test_rewrite_strcmp_layout_eq():
    tree = parse_expr('strcmp(GetAttrPointer(GetAttrs(context_), LAYOUT_ATTR_IDX), "TND") == 0')
    out = rewrite_strcmp_cmp(tree)
    assert isinstance(out, Bin)
    assert out.op == "=="
    assert isinstance(out.right, Const)
    assert out.right.value in ("TND", '"TND"') or str(out.right.value).strip("'\"") == "TND"


def test_z3_invariants_reject_out_dtype_mismatch():
    status, reason, _ = z3_check_key_dims(
        {"IsRegbase": "1", "OutDType": "1", "InputDType": "2", "IsEmptyTensor": "0"}
    )
    assert status == "unreachable"
    assert reason == "Z3_UNSAT"


def test_z3_invariants_accept_matching():
    status, reason, _ = z3_check_key_dims(
        {"IsRegbase": "1", "OutDType": "2", "InputDType": "2", "IsEmptyTensor": "0"}
    )
    assert status == "reachable"
    assert reason == "OK"
