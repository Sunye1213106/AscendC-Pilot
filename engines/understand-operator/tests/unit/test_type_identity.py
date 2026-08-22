# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from uo_init.ir.type_identity import iter_field_decl_rows, iter_unique_field_decls


def test_iter_field_decl_rows_keeps_divergent_types_on_same_member() -> None:
    ir = SimpleNamespace(
        field_decls={
            ("Process", "gatedBuf"): {
                "owner": "Process",
                "name": "gatedBuf",
                "type_text": "WrapA",
                "file": "op_kernel/arch35/process.h",
                "line": 10,
            },
            ("Process", "gatedBuf", 2): {
                "owner": "Process",
                "name": "gatedBuf",
                "type_text": "WrapB",
                "file": "op_kernel/arch35/process.h",
                "line": 12,
            },
        }
    )
    rows = list(iter_field_decl_rows(ir))
    assert len(rows) == 1
    owner, member, type_text, _file, _line = rows[0]
    assert owner == "Process"
    assert member == "gatedBuf"
    assert "WrapA" in type_text
    assert "WrapB" in type_text


def test_iter_unique_field_decls_merges_divergent_types() -> None:
    ir = SimpleNamespace(
        field_decls=[
            {
                "owner": "Process",
                "name": "buf",
                "type_text": "WrapA",
                "file": "a.h",
                "line": 1,
            },
            {
                "owner": "Process",
                "name": "buf",
                "type_text": "WrapB",
                "file": "b.h",
                "line": 2,
            },
        ]
    )
    rows = list(iter_unique_field_decls(ir))
    assert len(rows) == 1
    assert "WrapA" in rows[0][2]
    assert "WrapB" in rows[0][2]
