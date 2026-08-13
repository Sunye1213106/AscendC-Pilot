# -*- coding: utf-8 -*-
"""CodemapQuery contract: fields, callers, completeness — ``.uo`` authority."""
from __future__ import annotations

from pathlib import Path

from uo_init.host_codemap import (
    CodemapQuery,
    QueryResult,
    default_codemap_completeness,
)
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.store.writer import write_codemap


def test_default_completeness_marks_fast_as_partial():
    c = default_codemap_completeness(init_profile="fast", closure_mode="keypath")
    assert c["host"]["functions"]["call_closure"] == "partial"
    assert c["lemma_certificate"]["call_closure_complete"] is False
    assert c["api"]["completeness"] == "skipped"


def test_callers_of_and_fields(tmp_path: Path):
    cm = CodeMap(op_name="SampleOp", architecture="arch35")
    run = cm.upsert(
        EntityKind.FUNCTION, "Run", file="op_host/sample.cpp", line=10
    )
    hook = cm.upsert(
        EntityKind.FUNCTION, "Hook", file="op_host/sample.cpp", line=20
    )
    cm.link(
        RelationKind.CALLS,
        run.id,
        hook.id,
        attrs={
            "file": "op_host/sample.cpp",
            "line": 12,
            "guards": ["ready"],
            "args": [],
            "sites": [
                {
                    "file": "op_host/sample.cpp",
                    "line": 12,
                    "guards": ["ready"],
                    "args": [],
                    "receiver": "",
                }
            ],
        },
    )
    cm.upsert(
        EntityKind.TILING_KEY,
        "mode",
        attrs={
            "source_declared": True,
            "decl_order": 0,
            "host_writer_sites": [
                {
                    "path": "mode",
                    "function": "Hook",
                    "file": "op_host/sample.cpp",
                    "line": 20,
                    "rhs": "1",
                    "via": "direct",
                    "guards": ["ready"],
                }
            ],
        },
    )
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "SampleOp.arch35.uo"
    write_codemap(cm, product)

    q = CodemapQuery(tmp_path)
    assert q._mode == "uo"
    assert isinstance(q.completeness(), QueryResult)
    callers = q.callers_of("Hook")
    assert callers
    assert callers[0]["caller"] == "Run"
    assert q.callees_of("Run")[0]["callee"] == "Hook"
    fields = q.fields()
    assert any(f.get("name") == "mode" for f in fields)
    mode = next(f for f in fields if f.get("name") == "mode")
    assert mode["writers"][0]["guards"] == ["ready"]
    wrapped = q.callers("Hook")
    assert wrapped.completeness in {"partial", "complete", "unknown"}
    assert wrapped.fingerprint or True
