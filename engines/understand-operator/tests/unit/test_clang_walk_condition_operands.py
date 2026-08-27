# -*- coding: utf-8 -*-
from uo_init.clang_walk import (
    _Walker,
    collect_condition_operands,
    collect_condition_reads,
)


class _Kind:
    def __init__(self, name: str):
        self.name = name


class _Cursor:
    def __init__(self, kind: str, spelling: str = "", children=(), referenced=None):
        self.kind = _Kind(kind)
        self.spelling = spelling
        self._children = list(children)
        self.referenced = referenced
        self.defn_calls = 0

    def get_children(self):
        return list(self._children)

    def get_definition(self):
        self.defn_calls += 1
        raise AssertionError("get_definition must not run when referenced is set")


def test_operands_use_referenced_not_definition():
    var = _Cursor("VAR_DECL", "s1Inner")
    ref = _Cursor("DECL_REF_EXPR", "s1Inner", referenced=var)
    paths, ops = collect_condition_reads(ref)
    assert paths == []
    assert ops == ["s1Inner"]
    assert collect_condition_operands(ref) == ["s1Inner"]
    assert ref.defn_calls == 0


def test_operands_skip_callees():
    fn = _Cursor("FUNCTION_DECL", "CheckShapeValid")
    ref = _Cursor("DECL_REF_EXPR", "CheckShapeValid", referenced=fn)
    _paths, ops = collect_condition_reads(ref)
    assert ops == []


def test_fill_frames_only_prunes_operator_toplevel_not_bodies():
    w = _Walker(needle="op", op_root="/op", side="host")
    w._fill_frames_only = True
    w._scope_memo["/op/a.cpp"] = True
    cur = object()
    assert w._should_prune(cur, "FUNCTION_DECL", "/op/a.cpp", "") is True
    assert w._should_prune(cur, "FUNCTION_DECL", "/op/a.cpp", "DoOpTiling") is False


def test_kernel_walker_skips_condition_operand_walk(monkeypatch):
    calls = {"n": 0}

    def _boom(cursor, limit=256):
        calls["n"] += 1
        raise AssertionError("kernel must not walk condition operands")

    monkeypatch.setattr("uo_init.clang_walk.collect_condition_reads", _boom)
    w = _Walker(needle="flash_attention_score_grad", op_root="/op", side="kernel")
    w._scope_memo["/op/k.cpp"] = True

    class _File:
        name = "/op/k.cpp"

    class _Loc:
        file = _File()
        line = 10
        column = 2

    class _If:
        kind = _Kind("IF_STMT")
        location = _Loc()

        def get_children(self):
            return []

    w._record_control(_If(), "if_stmt", "flag", [], "Process", cond_cursor=_Cursor("DECL_REF_EXPR", "flag"))
    assert calls["n"] == 0
    assert w.controls[0].reads == ()
