# -*- coding: utf-8 -*-
"""def_sites must surface callee return / out-param assignments."""

from __future__ import annotations

from types import SimpleNamespace

from uo_init.derive_key_fields import KeyFieldDeriver


class _W:
    def __init__(self, path, line, rhs, function, file="t.cpp", via=""):
        self.path = path
        self.line = line
        self.rhs = rhs
        self.function = function
        self.file = file
        self.via = via
        self.column = 0
        self.kind = "assign"
        self.path_conditions = ()
        self.template_precondition = ""

    def guards(self):
        return []


class _IR:
    class_fields = ()
    local_writes = []
    writes = []
    summaries = {}
    field_decls = {}

    def __init__(self):
        # Caller assigns via call; real value is return inside callee.
        self.local_writes = [
            _W("__return__", 790, "deterSparseType", "GetDeterSparseTilingKey"),
            _W("__return__", 1534, "isSparse", "SetSparseParams"),
            _W("isSparse", 100, "SetSparseParams(ctx)", "Caller"),
            _W("deterSparseType", 110, "GetDeterSparseTilingKey(ctx)", "Caller"),
        ]
        self.writes = [
            _W("fBaseParams.isSparse", 100, "SetSparseParams(ctx)", "Caller"),
            _W(
                "fBaseParams.deterSparseType",
                110,
                "GetDeterSparseTilingKey(ctx)",
                "Caller",
            ),
        ]
        self.summaries = {
            "Caller": SimpleNamespace(calls=[], params=[], out_params=()),
            "SetSparseParams": SimpleNamespace(
                calls=[], params=["ctx"], out_params=()
            ),
            "GetDeterSparseTilingKey": SimpleNamespace(
                calls=[], params=["ctx"], out_params=()
            ),
        }

    def local_writes_in(self, fn):
        out = {}
        for w in self.local_writes:
            if w.function == fn:
                out.setdefault(w.path, []).append(w)
        return out

    def defs_by_function(self):
        return {}

    def writes_by_tail(self):
        out = {}
        for w in self.writes:
            out.setdefault(w.path.rsplit(".", 1)[-1], []).append(w)
        return out

    def expand_callee_writers(self):
        from uo_init.host_ir import HostIR

        # Reuse the real expansion logic via a thin HostIR-shaped object.
        hi = HostIR.__new__(HostIR)
        hi.writes = self.writes
        hi.local_writes = self.local_writes
        hi.call_sites = []
        return HostIR.expand_callee_writers(hi)

    def param_bound_member(self, *_a, **_k):
        return None


def test_all_defs_for_unions_callee_returns():
    eng = KeyFieldDeriver.__new__(KeyFieldDeriver)
    eng.ir = _IR()
    sites = eng._all_defs_for("isSparse", "Caller")
    lines = {(d.function, d.line) for d in sites}
    assert ("Caller", 100) in lines
    assert ("SetSparseParams", 1534) in lines


def test_field_defs_include_expanded_callee_writers():
    eng = KeyFieldDeriver.__new__(KeyFieldDeriver)
    eng.ir = _IR()
    sites = eng._field_defs("fBaseParams.deterSparseType")
    lines = {(d.function, d.line) for d in sites}
    # Call site + promoted return inside GetDeterSparseTilingKey.
    assert ("Caller", 110) in lines
    assert ("GetDeterSparseTilingKey", 790) in lines
