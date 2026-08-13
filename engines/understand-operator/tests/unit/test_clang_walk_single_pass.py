# -*- coding: utf-8 -*-
from uo_init.clang_walk import _use_single_ast_pass


def test_kernel_uses_single_ast_pass():
    assert _use_single_ast_pass("kernel") is True
    assert _use_single_ast_pass("KERNEL") is True


def test_host_keeps_index_then_walk():
    assert _use_single_ast_pass("host") is False
    assert _use_single_ast_pass("HOST") is False
