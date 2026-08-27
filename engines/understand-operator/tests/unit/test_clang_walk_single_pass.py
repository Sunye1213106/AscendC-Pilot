# -*- coding: utf-8 -*-
from uo_init.clang_walk import _use_single_ast_pass


def test_kernel_uses_single_ast_pass():
    assert _use_single_ast_pass("kernel") is True
    assert _use_single_ast_pass("KERNEL") is True


def test_host_also_uses_single_ast_pass():
    """Host used to always do index_walk + walk; both sides now share one pass."""
    assert _use_single_ast_pass("host") is True
    assert _use_single_ast_pass("HOST") is True
