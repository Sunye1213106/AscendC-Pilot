# -*- coding: utf-8 -*-
from __future__ import annotations

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.kernel_root_trace import _link, _reset_link_site_seen


def test_link_sites_dedupe_without_losing_distinct_rows():
    _reset_link_site_seen()
    cm = CodeMap(op_name="op", architecture="arch35")
    src = cm.upsert(EntityKind.METHOD, "Caller", eid="m_caller")
    dst = cm.upsert(EntityKind.OPERATION, "DataCopy", eid="op_copy")
    _link(
        cm,
        RelationKind.CALLS,
        src.id,
        dst.id,
        attrs={"file": "k.h", "line": 10, "column": 1, "receiver": "x"},
    )
    _link(
        cm,
        RelationKind.CALLS,
        src.id,
        dst.id,
        attrs={"file": "k.h", "line": 10, "column": 1, "receiver": "x"},
    )
    _link(
        cm,
        RelationKind.CALLS,
        src.id,
        dst.id,
        attrs={"file": "k.h", "line": 20, "column": 1, "receiver": "x"},
    )
    rels = [r for r in cm.relations.values() if r.kind_name() == RelationKind.CALLS.value]
    assert len(rels) == 1
    sites = rels[0].attrs.get("sites") or []
    assert len(sites) == 2
    lines = sorted(int(s["line"]) for s in sites)
    assert lines == [10, 20]
