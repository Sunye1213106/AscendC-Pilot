# -*- coding: utf-8 -*-
"""CE product_uo fails closed when the CodeMap product is missing or stale."""
from __future__ import annotations

from pathlib import Path

import pytest

from code_engineering.product_uo import identity, product, view
from uo_init.ir.codemap import CodeMap
from uo_init.store.writer import write_codemap


def test_missing_product_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="missing finalized .uo"):
        product(tmp_path, architecture="arch35")
    with pytest.raises(FileNotFoundError, match="missing finalized .uo"):
        identity(tmp_path, architecture="arch35")


def test_view_uses_checked_and_hides_stale_blob(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    product_path = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    write_codemap(cm, product_path)
    import json
    import sqlite3

    conn = sqlite3.connect(str(product_path))
    conn.execute(
        "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
        (
            "ir/operator_graph.yaml",
            "uo-operator-graph/v1",
            json.dumps({"schema": "uo-operator-graph/v1", "edge_count": 99}),
        ),
    )
    conn.commit()
    conn.close()
    graph = view(tmp_path, "ir/operator_graph.yaml", architecture="arch35")
    assert isinstance(graph, dict)
    assert graph.get("edge_count") != 99


def test_unknown_stale_view_raises(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    product_path = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    write_codemap(cm, product_path)
    import json
    import sqlite3

    conn = sqlite3.connect(str(product_path))
    conn.execute(
        "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
        ("custom/view.json", "custom/v1", json.dumps({"value": 2})),
    )
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="custom/view.json"):
        view(tmp_path, "custom/view.json", architecture="arch35")


def test_identity_uses_cm_graph_fingerprint(tmp_path: Path) -> None:
    from uo_init.store.reader import read_meta

    cm = CodeMap(op_name="toy", architecture="arch35")
    product_path = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    write_codemap(cm, product_path)
    ident = identity(tmp_path, op_name="toy", architecture="arch35")
    meta = read_meta(product_path)
    expected = str(meta.get("cm_graph_fingerprint") or meta.get("graph_fingerprint") or "")
    assert ident["graph_fingerprint"]
    if expected:
        assert ident["graph_fingerprint"] == expected
