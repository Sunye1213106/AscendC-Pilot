# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.kernel_root_trace import _tpipe_decl_lines
from uo_init.query.legal_key_cache import (
    _MAX_CACHED_PRODUCTS,
    _store_cache,
    clear_legal_key_cache,
)
from uo_init.query.sql import UoSqlQuery, _IDENT_NAME_RE
from uo_init.store.writer import write_codemap
from uo_init.tpl_dsl import bool_value_aliases
from uo_init.uo_query import open_query


def _product(cm: CodeMap, tmp_path: Path) -> Path:
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    return product


def test_sql_connect_closes(tmp_path: Path) -> None:
    from uo_init.store.reader import close_uo_connections, shared_uo

    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="K_Flag",
            kind=EntityKind.TILING_KEY,
            name="Flag",
            attrs={"source_declared": True, "value_domain": ["0", "1"]},
            file="op_kernel/key.h",
            line_start=1,
            status="confirmed",
        )
    )
    product = _product(cm, tmp_path)
    q = UoSqlQuery(product)
    with q._connect() as conn:
        conn.execute("select 1").fetchone()
        again = shared_uo(product)
        assert again is conn
    close_uo_connections(product)
    try:
        conn.execute("select 1")
        raise AssertionError("sqlite connection stayed open")
    except sqlite3.ProgrammingError:
        pass


def test_index_hint_uses_declared_dim_not_istnd(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="K_TRANS_B",
            kind=EntityKind.TILING_KEY,
            name="TRANS_B",
            attrs={"source_declared": True, "value_domain": ["0", "1"]},
            file="op_kernel/key.h",
            line_start=2,
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="K_junk",
            kind=EntityKind.TILING_KEY,
            name="0",
            attrs={"source_declared": False},
            file="op_kernel/toy.cpp",
            line_start=8,
            status="extracted",
        )
    )
    _product(cm, tmp_path)
    out = open_query(tmp_path).agent_query()
    assert out["shape"] == "index"
    assert "0" not in out.get("dim_names", [])
    assert "TRANS_B" in out.get("dim_names", [])
    hint = str(out.get("hint") or "")
    assert "IsTnd=1" not in hint
    assert "TRANS_B" in hint
    assert "Name=Value" in hint


def test_field_extras_backfill_reads(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    field = Entity(
        id="F_groupNum",
        kind=EntityKind.TILING_FIELD,
        name="groupNum",
        file="op_host/tiling.h",
        line_start=10,
        status="confirmed",
    )
    reader = Entity(
        id="FN_kernel",
        kind=EntityKind.FUNCTION,
        name="Process",
        file="op_kernel/toy.cpp",
        line_start=40,
        status="extracted",
    )
    cm.add_entity(field)
    cm.add_entity(reader)
    cm.link(RelationKind.READS, reader.id, field.id)
    _product(cm, tmp_path)
    out = open_query(tmp_path).agent_query(pattern="groupNum")
    card = next(row for row in out.get("cards") or [] if row.get("kind") == "TILING_FIELD")
    extras = card.get("extras") or {}
    readers = extras.get("readers") or []
    edges = card.get("edges") or {}
    assert readers or (edges.get("READS") or {}).get("neighbors")


def test_bool_aliases_only_for_boolish_tokens() -> None:
    assert "true" in bool_value_aliases("1")
    assert "0" in bool_value_aliases("false")
    assert bool_value_aliases("GMM_TRANS") == ("GMM_TRANS",)


def test_numeric_catalog_is_not_listed_as_tpl_dim() -> None:
    assert _IDENT_NAME_RE.fullmatch("0") is None
    assert _IDENT_NAME_RE.fullmatch("TRANS_B")


def test_tpipe_decl_inside_define() -> None:
    text = "#define FOO() \\\n  TPipe pipeBase; \\\n  op.Init(&pipeBase)\n"
    lines = _tpipe_decl_lines(text)
    assert lines.get("pipeBase") == 2


def test_tpipe_decl_skips_pointer_and_keeps_instance() -> None:
    text = "AscendC::TPipe *pipe;\nAscendC::TPipe pipe;\n"
    lines = _tpipe_decl_lines(text)
    assert lines.get("pipe") == 2


def test_legal_key_cache_lru() -> None:
    clear_legal_key_cache()
    for i in range(_MAX_CACHED_PRODUCTS + 2):
        _store_cache(f"/tmp/p{i}.uo", {"ok": True, "i": i})
    from uo_init.query import legal_key_cache as mod

    assert len(mod._CACHE) == _MAX_CACHED_PRODUCTS
    clear_legal_key_cache()


def test_type_prefix_name_card_and_wraps_skips_buffer(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    owner = Entity(
        id="SRCTYPE::mutex.h::MutexBuffer",
        kind=EntityKind.TYPE,
        name="MutexBuffer",
        file="op_kernel/arch35/mutex_buffer.h",
        line_start=52,
        status="confirmed",
    )
    policy = Entity(
        id="SRCTYPE::policy.h::MutexBuffersPolicyDB",
        kind=EntityKind.TYPE,
        name="MutexBuffersPolicyDB",
        file="op_kernel/arch35/mutex_buffers_policy.h",
        line_start=10,
        status="confirmed",
    )
    buf = Entity(
        id="BUF_a",
        kind=EntityKind.BUFFER,
        name="a_",
        file="op_kernel/arch35/mutex_buffers_policy.h",
        line_start=40,
        status="extracted",
    )
    field = Entity(
        id="SRCFIELD::mutex.h::MutexBuffer::tensor_",
        kind=EntityKind.FIELD,
        name="tensor_",
        file="op_kernel/arch35/mutex_buffer.h",
        line_start=146,
        status="confirmed",
    )
    cm.add_entity(owner)
    cm.add_entity(policy)
    cm.add_entity(buf)
    cm.add_entity(field)
    cm.link(RelationKind.WRAPS, policy.id, owner.id, status="confirmed")
    cm.link(RelationKind.WRAPS, buf.id, owner.id, attrs={"via": "member_type"}, status="confirmed")
    cm.link(RelationKind.CONTAINS, owner.id, field.id, attrs={"via": "class_member"}, status="confirmed")
    cm.link(RelationKind.CONTAINS, policy.id, owner.id, attrs={"via": "class_member"}, status="confirmed")
    _product(cm, tmp_path)
    q = open_query(tmp_path)
    out = q.agent_query(pattern="MutexBuffersPolicy")
    names = {str(c.get("name") or "") for c in out.get("cards") or []}
    assert "MutexBuffersPolicyDB" in names
    card = q.agent_query(pattern="MutexBuffer")
    type_card = next(c for c in card["cards"] if c.get("kind") == EntityKind.TYPE.value)
    wraps = (type_card.get("edges") or {}).get("WRAPS") or {}
    wrap_names = [n.get("name") for n in wraps.get("neighbors") or []]
    assert "a_" not in wrap_names
    contains = (type_card.get("edges") or {}).get("CONTAINS") or {}
    contain_kinds = {n.get("kind") for n in contains.get("neighbors") or []}
    assert EntityKind.TYPE.value not in contain_kinds
