# -*- coding: utf-8 -*-
"""InputSemantics: the engine asks, the operator answers."""

from __future__ import annotations

from replay import inputs as I
from replay.semantics import InputSemantics


def test_the_active_semantics_satisfies_the_protocol():
    assert isinstance(I.SEMANTICS, InputSemantics)


def test_the_shim_carries_no_layout_rules():
    """shapes/layout/pse live in the operator package; the shim only loads."""
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "replay" / "inputs.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                body.pop(0)
    code = ast.unparse(tree)
    # Re-exports of constants are fine; defining the shape maps is not.
    for name in ("mask_shapes", "pse_shapes", 'layout == "TND"',
                 'layout == "SBH"', "PSE_ALIBI_S = 1024", "ROPE_D = 64"):
        assert name not in code, f"shim still carries {name!r}"


def test_shapes_still_fail_fast_on_unknown_mask():
    import pytest
    with pytest.raises(ValueError, match="not a mask shape"):
        I.shapes(I.Case(atten_mask="bss"))


def test_a_tnd_case_still_derives_prefix_sum_extents():
    c = I.Case(layout="TND", seq_q=[128, 256], seq_kv=[128, 256]).normalised()
    ins, _ = I.shapes(c)
    assert ins["query"] == [256, 1, 128]
    assert ins["actual_seq_qlen"] == [2]
