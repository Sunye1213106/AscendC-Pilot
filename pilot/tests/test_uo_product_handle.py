# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ascendc_pilot.uo_product_handle import build_uo_product_handle, format_handle_for_task
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.store.writer import write_codemap


def test_build_uo_product_handle(tmp_path: Path) -> None:
    cm = CodeMap(op_name="Demo", architecture="arch35")
    cm.add_entity(Entity(id="E1", kind=EntityKind.VARIABLE, name="x", attrs={}))
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "Demo.arch35.uo"
    product.parent.mkdir(parents=True)
    write_codemap(cm, product)
    handle = build_uo_product_handle(tmp_path, op_name="Demo", architecture="arch35")
    assert handle["ok"] is True
    assert handle["path"].endswith("Demo.arch35.uo")
    text = format_handle_for_task(handle)
    assert "UO_PRODUCT_HANDLE:" in text
    assert "do not search for another .uo" in text


def test_missing_uo_product_handle_asks_source_fallback(tmp_path: Path) -> None:
    (tmp_path / "op_host").mkdir()
    handle = build_uo_product_handle(tmp_path, op_name="Demo", architecture="arch35")
    assert handle["ok"] is False
    assert handle["error"] == "UO_PRODUCT_REQUIRED"
    values = [o.get("value") for o in (handle.get("ask_question") or {}).get("options") or []]
    assert values == ["uo-init", "source"]
    assert "arch35" in str(handle.get("expected_path") or "")
