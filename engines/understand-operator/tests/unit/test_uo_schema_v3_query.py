# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.query.legal_key_cache import query_legal_keys
from uo_init.query.sql import UoSqlQuery
from uo_init.store.schema import SCHEMA_VERSION
from uo_init.store.writer import write_codemap


def _product(tmp_path: Path) -> Path:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="FN1",
            kind=EntityKind.FUNCTION,
            name="Process",
            file="op_kernel\\arch35\\process.h",
            line_start=10,
            line_end=12,
            attrs={"layer": "kernel", "snippet": "void Process();"},
        )
    )
    product = tmp_path / "toy.arch35.uo"
    write_codemap(cm, product)
    conn = sqlite3.connect(str(product))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO legal_key(id, packed, hex, sel_group, status) VALUES (?,?,?,?,?)",
            (0, "1", "0x1", "g0", "template_admissible"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO legal_key(id, packed, hex, sel_group, status) VALUES (?,?,?,?,?)",
            (1, "2", "0x2", "g0", "template_admissible"),
        )
        conn.executemany(
            "INSERT OR REPLACE INTO legal_key_dim(key_id, dim, value) VALUES (?,?,?)",
            [
                (0, "IsTnd", "1"),
                (0, "DType", "2"),
                (1, "IsTnd", "0"),
                (1, "DType", "2"),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return product


def test_schema_v3_indexes_and_legal_key_tables(tmp_path: Path) -> None:
    product = _product(tmp_path)
    conn = sqlite3.connect(str(product))
    try:
        schema = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]
        assert schema == SCHEMA_VERSION
        indexes = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "idx_span_entity" in indexes
        assert "idx_entity_file_line" in indexes
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "legal_key" in tables
        assert "attribute" not in tables
        file_path = conn.execute("SELECT file FROM entity WHERE id='FN1'").fetchone()[0]
        assert "\\" not in str(file_path)
        for sql, params in (
            ("SELECT s.id FROM source_span s WHERE s.entity_id = ?", ("FN1",)),
            (
                "SELECT e.id FROM entity e LEFT JOIN source_span s ON s.entity_id = e.id "
                "WHERE e.id = ?",
                ("FN1",),
            ),
            (
                "SELECT e.id FROM entity e WHERE e.kind = ? AND e.name = ? COLLATE NOCASE",
                ("FUNCTION", "Process"),
            ),
            (
                "SELECT e.id FROM entity e WHERE e.file = ? AND e.line_start <= ? AND e.line_end >= ?",
                (file_path, 12, 10),
            ),
        ):
            plan = " ".join(
                " ".join(str(x) for x in r)
                for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params)
            ).lower()
            assert "scan source_span" not in plan, plan
            assert "use temp b-tree" not in plan, plan
    finally:
        conn.close()


def test_legal_key_sql_intersection(tmp_path: Path) -> None:
    product = _product(tmp_path)
    out = query_legal_keys(product, pattern="IsTnd=1,DType=2", limit=8)
    assert out.get("backend") == "sql"
    assert out.get("total_matched") == 1
    assert out["rows"][0]["dims"]["IsTnd"] == "1"


def test_fag_product_hot_query_plans_if_present() -> None:
    import os

    import pytest

    root = Path(
        os.environ.get("UO_OP_DIR")
        or r"d:\TEST\ops-transformer\attention\flash_attention_score_grad"
    )
    product = root / ".ascendc-pilot" / "arch35" / "uo" / f"{root.name}.arch35.uo"
    if not product.is_file():
        pytest.skip("FAG .uo product not present")
    conn = sqlite3.connect(f"file:{product.as_posix()}?mode=ro", uri=True)
    try:
        schema = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if schema is None or str(schema[0]) != SCHEMA_VERSION:
            pytest.skip("FAG product is not v3")
        for sql, params in (
            (
                "SELECT e.id FROM entity e LEFT JOIN source_span s ON s.entity_id = e.id "
                "WHERE e.name = ? COLLATE NOCASE LIMIT 32",
                ("LocalTensor",),
            ),
            (
                "SELECT key_id FROM legal_key_dim WHERE dim = ? AND value = ?",
                ("IsTnd", "1"),
            ),
        ):
            plan = " ".join(
                " ".join(str(x) for x in r)
                for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params)
            ).lower()
            assert "scan source_span" not in plan, plan
            assert "use temp b-tree" not in plan, plan
    finally:
        conn.close()


def test_summary_and_context_manager_do_not_hydrate(tmp_path: Path) -> None:
    product = _product(tmp_path)
    with UoSqlQuery(product) as q:
        summary = q.summary()
        assert summary.get("op_name") == "toy"
        assert q._engine is None
    from uo_init.store.reader import _SHARED_CONN

    assert str(product.resolve()) not in _SHARED_CONN
