# -*- coding: utf-8 -*-
"""ensure_tg_views is read-only: missing views fail closed and never write .uo."""
from __future__ import annotations

from pathlib import Path

import pytest

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.store.writer import write_codemap
from uo_init.tg_projection import ensure_tg_views, load_tg_view


def _write_incomplete(tmp_path: Path, *, op="toy", arch="arch35") -> Path:
    cm = CodeMap(op_name=op, architecture=arch)
    product = tmp_path / ".ascendc-pilot" / arch / "uo" / f"{op}.{arch}.uo"
    write_codemap(cm, product)
    return product


def _write_complete(tmp_path: Path, *, op="toy", arch="arch35") -> Path:
    cm = CodeMap(op_name=op, architecture=arch)
    cm.add_entity(
        Entity(
            id="TK_DType",
            kind=EntityKind.TILING_KEY,
            name="DType",
            attrs={
                "source_declared": True,
                "decl_order": 0,
                "bit_width": 1,
                "bit_lo": 0,
                "bit_hi": 0,
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
                "fixed_fields": {"DType": "0"},
                "field_domains": {},
            },
            file="op_kernel/template_tiling_key.h",
            status="confirmed",
        )
    )
    product = tmp_path / ".ascendc-pilot" / arch / "uo" / f"{op}.{arch}.uo"
    write_codemap(cm, product)
    return product


def test_ensure_tg_views_complete_is_readonly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    product = _write_complete(tmp_path)
    before = product.read_bytes()

    def _forbid_write(*_args, **_kwargs):
        raise AssertionError("ensure_tg_views must not write_codemap")

    monkeypatch.setattr("uo_init.tg_projection.write_codemap", _forbid_write)
    monkeypatch.setattr("uo_init.tg_projection.backfill_from_source", _forbid_write)
    out = ensure_tg_views(tmp_path, op_name="toy", architecture="arch35")
    assert out.get("ok") is True, out
    assert out.get("backfilled") is False
    assert int(out.get("legal_key_count") or 0) > 0
    assert product.read_bytes() == before


def test_ensure_tg_views_missing_fails_without_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    product = _write_incomplete(tmp_path)
    before = product.read_bytes()

    def _forbid_write(*_args, **_kwargs):
        raise AssertionError("ensure_tg_views must not write_codemap")

    monkeypatch.setattr("uo_init.tg_projection.write_codemap", _forbid_write)
    monkeypatch.setattr("uo_init.tg_projection.backfill_from_source", _forbid_write)
    out = ensure_tg_views(tmp_path, op_name="toy", architecture="arch35")
    assert out.get("ok") is False, out
    assert out.get("backfilled") is False
    error = str(out.get("error") or "")
    assert "/uo-init" in error
    assert product.read_bytes() == before


def test_ensure_tg_views_requires_architecture(tmp_path: Path) -> None:
    _write_complete(tmp_path)
    out = ensure_tg_views(tmp_path, op_name="toy", architecture="")
    assert out.get("ok") is False
    assert "ARCHITECTURE_MISSING" in str(out.get("error") or "")


def test_load_tg_view_does_not_return_stale_blob(tmp_path: Path) -> None:
    product = _write_complete(tmp_path)
    import json
    import sqlite3

    stale = {"schema": "uo-operator-graph/v1", "fingerprint": "stale", "edge_count": 99}
    conn = sqlite3.connect(str(product))
    conn.execute(
        "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
        ("ir/operator_graph.yaml", "uo-operator-graph/v1", json.dumps(stale)),
    )
    conn.commit()
    conn.close()
    view = load_tg_view(product, "ir/operator_graph.yaml")
    if view is None:
        return
    assert view.get("edge_count") != 99
    assert view.get("stale_blob") is None
