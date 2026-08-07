# -*- coding: utf-8 -*-
from uo_init.clang_walk import _loop_header


class _Kind:
    def __init__(self, name: str):
        self.name = name


class _Cursor:
    def __init__(self, kind: str, spelling: str = "", children=()):
        self.kind = _Kind(kind)
        self.spelling = spelling
        self._children = list(children)

    def get_children(self):
        return list(self._children)


def test_range_for_direct_var_decl_is_induction_var():
    var = _Cursor("VAR_DECL", "needSyncRound")
    body = _Cursor("COMPOUND_STMT")
    _cond, induction, _init, _step = _loop_header([var, body], "cxx_for_range")
    assert induction == ("needSyncRound",)
