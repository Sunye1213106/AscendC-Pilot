# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from testcase_agent.product_uo import identity, product, view
from uo_init.ir.codemap import CodeMap
from uo_init.store.writer import write_codemap


def test_tg_product_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="missing finalized .uo"):
        product(tmp_path, op_name="toy", architecture="arch35")


def test_tg_view_uses_checked_and_rejects_stale(tmp_path: Path) -> None:
    import json
    import sqlite3

    cm = CodeMap(op_name="toy", architecture="arch35")
    path = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    write_codemap(cm, path)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
        ("custom/view.json", "custom/v1", json.dumps({"secret": 1})),
    )
    conn.commit()
    conn.close()
    ident = identity(tmp_path, op_name="toy", architecture="arch35")
    assert ident["architecture"] == "arch35"
    graph = view(tmp_path, "ir/operator_graph.yaml", op_name="toy", architecture="arch35")
    assert isinstance(graph, dict)
    with pytest.raises(RuntimeError, match="custom/view.json"):
        view(tmp_path, "custom/view.json", op_name="toy", architecture="arch35")


def test_identity_falls_back_to_cm_graph_fingerprint(tmp_path: Path) -> None:
    from uo_init.store.reader import read_meta

    cm = CodeMap(op_name="toy", architecture="arch35")
    path = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    write_codemap(cm, path)
    ident = identity(tmp_path, op_name="toy", architecture="arch35")
    meta = read_meta(path)
    expected = str(meta.get("cm_graph_fingerprint") or meta.get("graph_fingerprint") or "")
    assert ident["graph_fingerprint"]
    if expected:
        assert ident["graph_fingerprint"] == expected
