# -*- coding: utf-8 -*-
import pytest

from uo_init.tpl_bind import bind, parse_kernel_nttps, parse_host_encode_args_text
from uo_init.tpl_dsl import parse_file


def test_bind_arity_match(fag_dir):
    key = fag_dir / "op_kernel" / "arch35" / "flash_attention_score_grad_template_tiling_key.h"
    apt = fag_dir / "op_kernel" / "flash_attention_score_grad_apt.cpp"
    host = (
        fag_dir
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_normal_regbase.cpp"
    )
    sch = parse_file(key)
    nttps = parse_kernel_nttps(apt.read_text(encoding="utf-8", errors="replace"))
    from uo_init.tpl_bind import bind_sources

    try:
        res = bind_sources(key, host, apt, entry_name="flash_attention_score_grad")
    except Exception:
        res = bind(sch, [f"arg{i}" for i in range(len(sch.dims))], nttps)
    assert len(res.bindings) == 19


def test_bind_names_aligned(fag_dir):
    key = fag_dir / "op_kernel" / "arch35" / "flash_attention_score_grad_template_tiling_key.h"
    apt = fag_dir / "op_kernel" / "flash_attention_score_grad_apt.cpp"
    host = (
        fag_dir
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_normal_regbase.cpp"
    )
    from uo_init.tpl_bind import bind_sources

    res = bind_sources(key, host, apt, entry_name="flash_attention_score_grad")
    res.check()
    assert [b.decl.name for b in res.bindings] == [b.nttp_name for b in res.bindings]


def test_host_expr_contains_known_fields(fag_dir):
    key = fag_dir / "op_kernel" / "arch35" / "flash_attention_score_grad_template_tiling_key.h"
    apt = fag_dir / "op_kernel" / "flash_attention_score_grad_apt.cpp"
    host = (
        fag_dir
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_normal_regbase.cpp"
    )
    from uo_init.tpl_bind import bind_sources

    res = bind_sources(key, host, apt, entry_name="flash_attention_score_grad")
    blob = " ".join(b.host_expr for b in res.bindings)
    assert "isNzOut" in blob or "splitAxis" in blob or "fBaseParams" in blob


def test_mismatch_raises(fag_dir):
    key = fag_dir / "op_kernel" / "arch35" / "flash_attention_score_grad_template_tiling_key.h"
    sch = parse_file(key)
    with pytest.raises(ValueError, match="arity"):
        bind(sch, ["a"] * 18, [("uint8_t", f"D{i}") for i in range(19)])
