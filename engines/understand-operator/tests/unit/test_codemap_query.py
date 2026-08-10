# -*- coding: utf-8 -*-
"""CodemapQuery contract: fields, callers, completeness."""
from __future__ import annotations

from pathlib import Path

from uo_init.host_codemap import (
    CodemapQuery,
    QueryResult,
    default_codemap_completeness,
)
from uo_init.ids import named_id
from uo_init.kb_export import export_kb
from uo_init.kb_index import upsert_host_view_tables
from uo_init.kb_model import Edge, Evidence, KnowledgeBase, Node


def _kb_with_calls() -> KnowledgeBase:
    kb = KnowledgeBase("SampleOp", "arch35")
    ev = Evidence.at("op_host/sample.cpp", 10, snippet="Run")
    for name, line in (("Run", 10), ("Hook", 20)):
        kb.add_node(
            Node(
                id=named_id("Function", name),
                kind="Function",
                name=name,
                layer="host",
                data={"file": "op_host/sample.cpp", "line": line},
                evidence=[Evidence.at("op_host/sample.cpp", line, snippet=name)],
            )
        )
    kb.add_edge(
        Edge.make(
            "calls",
            named_id("Function", "Run"),
            named_id("Function", "Hook"),
            data={
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
    )
    kb.add_node(
        Node(
            id=named_id("TilingKeyDim", "mode"),
            kind="TilingKeyDim",
            name="mode",
            layer="tiling",
            evidence=[ev],
        )
    )
    return kb


def test_default_completeness_marks_fast_as_partial():
    c = default_codemap_completeness(init_profile="fast", closure_mode="keypath")
    assert c["host"]["functions"]["call_closure"] == "partial"
    assert c["lemma_certificate"]["call_closure_complete"] is False
    assert c["api"]["completeness"] == "skipped"


def test_callers_of_and_fields(tmp_path: Path):
    root = tmp_path / "uo"
    kb = _kb_with_calls()
    receipt = export_kb(kb, root)
    assert receipt.get("hash_encoding") == "canonical_json"

    upsert_host_view_tables(
        root,
        {
            "schema": "tg-host-view/v1",
            "source": {"graph_fingerprint": receipt["graph_fingerprint"]},
            "fields": [
                {
                    "name": "mode",
                    "kind": "key_dim",
                    "exactness": "exact",
                    "grade": "ok",
                    "writers": [
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
                    "reads": [{"var": "x", "root": "ATTRIBUTE"}],
                }
            ],
            "predicates": [],
        },
    )

    q = CodemapQuery(root)
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
    assert wrapped.fingerprint
