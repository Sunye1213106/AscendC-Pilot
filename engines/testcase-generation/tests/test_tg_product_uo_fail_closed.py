# -*- coding: utf-8 -*-
"""TG product_uo fails closed on missing product and stale views."""
from __future__ import annotations

from pathlib import Path

import pytest

from testcase_agent.product_uo import identity, product, view
from uo_init.ir.codemap import CodeMap
from uo_init.store.writer import write_codemap


def test_missing_product_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="missing finalized .uo"):
        product(tmp_path, op_name="toy", architecture="arch35")
    with pytest.raises(FileNotFoundError, match="missing finalized .uo"):
        identity(tmp_path, architecture="arch35")


def test_view_does_not_return_stale_blob(tmp_path: Path) -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    path = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    write_codemap(cm, path)
    import json
    import sqlite3

    conn = sqlite3.connect(str(path))
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
