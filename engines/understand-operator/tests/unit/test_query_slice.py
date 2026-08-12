from __future__ import annotations

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.query.slice import slice_backward, slice_forward


def test_directed_slice_filters_depth_budget_and_evidence() -> None:
    cm = CodeMap(op_name="slice", architecture="arch35")
    source = cm.upsert(
        EntityKind.INPUT,
        "source",
        eid="source",
        attrs={"provenance": "clang_ast"},
    )
    middle = cm.upsert(EntityKind.FIELD, "middle", eid="middle")
    sink = cm.upsert(
        EntityKind.OPERATION,
        "sink",
        eid="sink",
        status="partial",
    )
    cm.link(RelationKind.FLOWS_TO, source.id, middle.id, attrs={"provenance": "clang_ast"})
    cm.link(RelationKind.CALLS, middle.id, sink.id)

    forward = slice_forward(cm, [source.id], edge_kinds=["FLOWS_TO"], depth=3)
    assert {row["id"] for row in forward["nodes"]} == {"source", "middle"}
    assert [row["kind"] for row in forward["edges"]] == ["FLOWS_TO"]
    assert forward["evidence_tier_hints"]["A"] >= 1
    assert forward["truncated"] is False

    backward = slice_backward(cm, [sink.id], depth=3, budget=2)
    assert {row["id"] for row in backward["nodes"]} == {"sink", "middle"}
    assert backward["truncated"] is True
    assert any(row["evidence_tier"] == "C" for row in backward["nodes"])
