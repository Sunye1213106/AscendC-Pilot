# -*- coding: utf-8 -*-
from uo_init.accessor import bind_expression, count_getdim, layout_axis_scenes
from uo_init.expr_ir import Ref, Unknown, pretty


def test_attr_index_to_name():
    e = bind_expression(
        'context_->GetAttrs()->GetAttrPointer<char>(static_cast<size_t>(AttrIndex::TND_SOFTMAX_IN))'
    )
    assert isinstance(e, Ref)
    assert "tnd_softmax_in" in e.symbol


def test_getdim_to_input_shape():
    e = bind_expression("shape->GetStorageShape().GetDim(0)")
    assert "InputShape" in pretty(e) or pretty(e).startswith("InputShape")


def test_unknown_is_first_class():
    e = bind_expression("fooBarBaz(1,2,3)")
    assert isinstance(e, Unknown)
    assert e.reason


def test_layout_axis_two_scenes():
    code = 'if (strcmp(inputLayout, "TND") == 0) { q = t1*n*d; } else { q = b*s1*d; }'
    scenes = layout_axis_scenes(code)
    assert len(scenes) == 2
    axes = {frozenset(s["axes"]) for s in scenes}
    assert frozenset(["t1", "t2", "n1", "d"]) in axes
    assert frozenset(["b", "s1", "s2", "n1", "d"]) in axes


def test_accessor_coverage_floor(fag_dir):
    p = (
        fag_dir
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_common_regbase.cpp"
    )
    text = p.read_text(encoding="utf-8", errors="replace")
    n = count_getdim(text)
    assert n >= 30  # soft floor on common_regbase alone; full arch35 is higher
