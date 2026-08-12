# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.query.legal_key_cache import clear_legal_key_cache, query_legal_keys
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def test_legal_key_cache_reuses_parse(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(Entity(id="TK", kind=EntityKind.TILING_KEY, name="SplitAxis", attrs={"source_declared": True}))
    product = tmp_path / "toy.arch35.uo"
    rows = [
        {"key_id": "k0", "dims": {"SplitAxis": 0}},
        {"key_id": "k1", "dims": {"SplitAxis": 1}},
        {"key_id": "k2", "dims": {"Layout": "TND"}},
    ]
    write_codemap(
        cm,
        product,
        views={"tiling/legal_key_index.jsonl": {"rows": rows}},
    )
    clear_legal_key_cache()
    first = query_legal_keys(product, dim="SplitAxis", value="1", limit=10)
    assert first["total_matched"] == 1
    assert first["rows"][0]["key_id"] == "k1"
    second = query_legal_keys(product, pattern="TND", limit=10)
    assert second["cached"] is True
    assert second["total_matched"] == 1


def test_aggregate_modes(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="TK",
            kind=EntityKind.TILING_KEY,
            name="SplitAxis",
            attrs={"source_declared": True, "decl_order": 0},
        )
    )
    cm.add_entity(
        Entity(id="BUF", kind=EntityKind.BUFFER, name="local_q", attrs={"scope": "main"})
    )
    cm.add_entity(
        Entity(id="U1", kind=EntityKind.OTHER, name="gap", attrs={}, status="unresolved")
    )
    product = tmp_path / ".ascendc-pilot" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path)
    assert q.aggregate_tiling_key("SplitAxis")["count"] >= 1
    assert q.aggregate_buffer("local")["count"] >= 1
    assert q.aggregate_gaps()["total"] >= 1
