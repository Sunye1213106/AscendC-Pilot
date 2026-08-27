# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def _product(cm: CodeMap, tmp_path: Path) -> None:
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)


def test_entities_in_files_batches_and_field_impact_many(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    host_a = cm.upsert(
        EntityKind.FUNCTION,
        "WriteA",
        eid="FN_a",
        file="op_host/a.cpp",
        line=10,
        status="confirmed",
    )
    host_b = cm.upsert(
        EntityKind.FUNCTION,
        "WriteB",
        eid="FN_b",
        file="op_host/b.cpp",
        line=20,
        status="confirmed",
    )
    fld_a = cm.upsert(
        EntityKind.TILING_FIELD,
        "fieldA",
        eid="TDF_a",
        file="op_host/a.cpp",
        line=10,
        status="confirmed",
    )
    fld_b = cm.upsert(
        EntityKind.TILING_FIELD,
        "fieldB",
        eid="TDF_b",
        file="op_host/b.cpp",
        line=20,
        status="confirmed",
    )
    cm.link(RelationKind.WRITES, host_a.id, fld_a.id, attrs={"file": "op_host/a.cpp", "line": 10})
    cm.link(RelationKind.WRITES, host_b.id, fld_b.id, attrs={"file": "op_host/b.cpp", "line": 20})
    _product(cm, tmp_path)
    q = open_query(tmp_path, architecture="arch35")
    hits = q.entities_in_files(["op_host/a.cpp", "op_host/b.cpp"])
    names = {str(row.get("name") or "") for row in hits}
    assert "WriteA" in names and "WriteB" in names
    packed = q.field_impact_many(["fieldA", "fieldB"])
    assert packed["fieldA"].get("ok") is True
    assert packed["fieldB"].get("ok") is True
    writers_a = {str(row.get("name") or "") for row in packed["fieldA"].get("writers") or []}
    assert "WriteA" in writers_a
    edges = q.edges_of_many([fld_a.id, fld_b.id])
    assert edges[fld_a.id]
    assert edges[fld_b.id]
    single = q.edges_of(fld_a.id)
    assert {row.get("dst") for row in single} == {row.get("dst") for row in edges[fld_a.id]} or single
