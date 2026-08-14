# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.query.evidence import project_entity
from uo_init.query.legal_key_cache import expand_legal_key_rows
from uo_init.semantics.ascendc_storage import tposition_from_type_text
from uo_init.store.reader import load_view_blob, read_codemap
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def _product(cm: CodeMap, tmp_path: Path) -> Path:
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / f"{cm.op_name}.{cm.architecture}.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    return product


def test_project_entity_drops_branch_without_span() -> None:
    spanned = Entity(
        id="KBR_ok",
        kind=EntityKind.BRANCH,
        name="IS_DETERMINISTIC",
        file="kernel.cpp",
        line_start=42,
        line_end=42,
    )
    missing = Entity(id="KBR_empty", kind=EntityKind.BRANCH, name="no-span")
    assert project_entity(spanned) is not None
    assert project_entity(missing) is None
    assert project_entity(missing, require_span_for_branch=False) is not None


def test_writer_attrs_only_no_attribute_table(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="BUF",
            kind=EntityKind.BUFFER,
            name="local_q",
            attrs={
                "memory_space": "UB",
                "wrapper": "LocalTensor",
                "type_text": "LocalTensor<half>",
                "type_name": "LocalTensor",
            },
            file="ghost.cpp",
            line_start=10,
            line_end=10,
        )
    )
    product = _product(cm, tmp_path)
    loaded = read_codemap(product)
    buf = loaded.entities["BUF"]
    assert "type_text" not in buf.attrs
    assert buf.attrs.get("type_name") == "LocalTensor"
    assert buf.attrs.get("memory_space") == "UB"

    conn = sqlite3.connect(str(product))
    try:
        data = json.loads(
            conn.execute("SELECT data FROM entity WHERE id = ?", ("BUF",)).fetchone()[0]
        )
        assert "kind" not in data
        assert "file" not in data
        assert "type_text" not in data
        assert conn.execute("SELECT COUNT(*) FROM attribute").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM source_span").fetchone()[0] == 0
    finally:
        conn.close()


def test_legal_key_compact_on_disk_expanded_on_read(tmp_path: Path) -> None:
    from uo_init.ids import named_id

    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TK_SplitAxis",
            kind=EntityKind.TILING_KEY,
            name="SplitAxis",
            attrs={
                "source_declared": True,
                "decl_order": 0,
                "bit_width": 2,
                "bit_lo": 0,
                "bit_hi": 1,
                "value_domain": ["0", "1"],
                "allowed_values": ["0", "1"],
                "decl_kind": "UINT",
                "kind_tpl": "UINT",
                "provenance": "source_tpl_args_decl",
            },
            file="op_kernel/template_tiling_key.h",
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="TPL_0",
            kind=EntityKind.TEMPLATE,
            name="ARGS_SEL_0",
            attrs={
                "tpl_role": "args_sel_group",
                "sel_group_index": 0,
                "fixed_fields": {"SplitAxis": "1"},
                "field_domains": {},
                "provenance": "source_tpl_args_sel",
            },
            file="op_kernel/template_tiling_key.h",
            status="confirmed",
        )
    )
    product = _product(cm, tmp_path)
    conn = sqlite3.connect(str(product))
    try:
        raw = json.loads(
            conn.execute(
                "SELECT data FROM view_blob WHERE name = ?",
                ("tiling/legal_key_index.jsonl",),
            ).fetchone()[0]
        )
    finally:
        conn.close()
    assert isinstance(raw, dict)
    assert raw.get("dim_order") == ["SplitAxis"]
    assert raw["rows"] and isinstance(raw["rows"][0], list)

    blob = load_view_blob(product, "tiling/legal_key_index.jsonl")
    assert isinstance(blob, dict)
    assert blob["rows"][0]["dims"]["SplitAxis"] == "1"
    assert blob["rows"][0]["sel_group_id"] == named_id("TemplateBinding", "sel0")

    legacy = {
        "rows": [
            {
                "tiling_key": 1,
                "dims": {"SplitAxis": "1"},
                "sel_group_id": "legacy",
                "status": "template_admissible",
            }
        ]
    }
    expanded = expand_legal_key_rows(legacy)
    assert expanded[0]["dims"]["SplitAxis"] == "1"
    assert expanded[0]["sel_group_id"] == "legacy"


def test_impact_buckets_and_query_modes(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    key = cm.upsert(
        EntityKind.TILING_KEY,
        "SplitAxis",
        eid="TK",
        attrs={"source_declared": True, "packing_value_sites": [{"file": "host.cpp", "line": 10}]},
        file="host.cpp",
        line=10,
    )
    field = cm.upsert(
        EntityKind.TILING_FIELD,
        "s1",
        eid="TDF",
        attrs={
            "owner": "Toy",
            "host_writer_sites": [
                {"file": "host.cpp", "line": 11, "expression": "s1Inner * 2"}
            ],
            "value_defining_sites": [
                {"file": "host.cpp", "line": 8, "lhs": "s1Inner", "rhs": "shape.s1 / 8"}
            ],
        },
        file="host.cpp",
        line=11,
    )
    buf = cm.upsert(
        EntityKind.BUFFER,
        "local_q",
        eid="BUF",
        attrs={
            "memory_space": "UB",
            "tposition": "VECIN",
            "wrapper": "LocalTensor",
        },
        file="kernel.cpp",
        line=20,
    )
    op = cm.upsert(
        EntityKind.OPERATION,
        "DataCopy",
        eid="OP_copy",
        attrs={"callee": "DataCopy", "function": "Process"},
        file="kernel.cpp",
        line=30,
    )
    cm.link(RelationKind.SELECTS, key.id, buf.id)
    cm.link(RelationKind.WRITES, key.id, field.id)
    cm.link(RelationKind.READS, op.id, field.id)
    product = _product(cm, tmp_path)
    q = open_query(tmp_path)

    impact = q.impact_of("host.cpp", (10, 10))
    assert isinstance(impact, dict)
    assert "buckets" in impact
    assert impact["count"] >= 1
    assert "dispatch" in impact["buckets"] or "layout" in impact["buckets"]
    assert all("neighbors" not in hit for hit in impact["hits"])

    field_hit = q.field_impact("s1")
    assert field_hit["ok"] is True
    assert "neighbors" not in field_hit
    assert field_hit["readers"]
    projected = project_entity(field)
    assert projected is not None
    assert projected["facts"]["rhs"] == "shape.s1 / 8"

    buf_hit = project_entity(buf)
    assert buf_hit is not None
    assert buf_hit["facts"]["tposition"] == "VECIN"
    assert tposition_from_type_text("TQue<TPosition::VECOUT, 1>") == "VECOUT"
    assert tposition_from_type_text("LocalTensor<half>") is None

    locate = q.aggregate_locate("SplitAxis")
    assert locate["count"] >= 1
    assert locate["locations"][0]["file"]
    assert locate["locations"][0]["line_start"] == 10

    api = q.aggregate_kernel_api("DataCopy")
    assert api["count"] >= 1
    assert api["calls"][0]["facts"]["callee"] == "DataCopy"


def test_kernel_api_tque_queue_vs_flag_sync(tmp_path: Path) -> None:
    cm = CodeMap(op_name="sync", architecture="arch35")
    queue = cm.upsert(
        EntityKind.QUEUE,
        "inQue",
        eid="Q_in",
        attrs={"tposition": "VECIN", "memory_space": "UB"},
        file="kernel.cpp",
        line=10,
    )
    enque = cm.upsert(
        EntityKind.OPERATION,
        "EnQue",
        eid="OP_enque",
        attrs={"callee": "EnQue", "function": "Process", "mechanism": "tque"},
        file="kernel.cpp",
        line=20,
    )
    event = cm.upsert(
        EntityKind.EVENT,
        "EVENT_ID0",
        eid="EV0",
        attrs={"identity": "EVENT_ID0", "mechanism": "hard_event", "paired": True},
        file="kernel.cpp",
        line=30,
    )
    setf = cm.upsert(
        EntityKind.OPERATION,
        "SetFlag",
        eid="OP_set",
        attrs={
            "callee": "SetFlag",
            "function": "Process",
            "mechanism": "hard_event",
            "flag_paired": True,
        },
        file="kernel.cpp",
        line=30,
    )
    cm.link(RelationKind.REFERENCES, enque.id, queue.id)
    cm.link(RelationKind.SIGNALS, setf.id, event.id)
    _product(cm, tmp_path)
    q = open_query(tmp_path)

    tque = q.aggregate_kernel_api("EnQue")
    assert tque["count"] == 1
    facts = tque["calls"][0]["facts"]
    assert "sync" not in facts
    assert facts["mechanism"] == "tque"
    assert facts["queue"][0]["name"] == "inQue"
    assert facts["queue"][0]["tposition"] == "VECIN"

    flag = q.aggregate_kernel_api("SetFlag")
    assert flag["count"] == 1
    ff = flag["calls"][0]["facts"]
    assert ff["sync"][0]["kind"] == "SIGNALS"
    assert ff["flag_paired"] is True
    assert "queue" not in ff


def test_writer_keeps_long_packing_rhs(tmp_path: Path) -> None:
    long_rhs = "alpha && " + "beta && " * 80 + "omega"
    assert len(long_rhs) > 400
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TK",
            kind=EntityKind.TILING_KEY,
            name="IsFoo",
            attrs={
                "packing_value_sites": [
                    {"lhs": "foo", "rhs": long_rhs, "file": "op_host/x.cpp", "line": 10}
                ]
            },
            file="op_kernel/key.h",
            line_start=1,
            status="confirmed",
        )
    )
    product = _product(cm, tmp_path)
    loaded = read_codemap(product)
    sites = loaded.entities["TK"].attrs["packing_value_sites"]
    assert sites[0]["rhs"] == long_rhs


def test_writer_skips_branch_source_span(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="KBR",
            kind=EntityKind.BRANCH,
            name="IS_FOO",
            attrs={"snippet": "if constexpr (IS_FOO) {", "function": "SetConstInfo"},
            file="op_kernel/k.h",
            line_start=20,
            line_end=20,
            status="confirmed",
        )
    )
    product = _product(cm, tmp_path)
    conn = sqlite3.connect(str(product))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM source_span WHERE entity_id = ?", ("KBR",)
        ).fetchone()[0]
        assert n == 0
    finally:
        conn.close()

