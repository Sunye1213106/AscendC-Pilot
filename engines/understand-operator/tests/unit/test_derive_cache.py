# -*- coding: utf-8 -*-
from __future__ import annotations

from uo_init import derive_cache


def test_derive_field_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("UO_DERIVE_CACHE", "1")
    monkeypatch.setenv("UO_CACHE_ROOT", str(tmp_path / "cache"))
    derive_cache.reset_stats()
    fp = derive_cache.bundle_fingerprint(
        {
            "host_ir": type("H", (), {"writes": [], "local_writes": [], "controls": []})(),
            "binding": type(
                "B",
                (),
                {
                    "site": type("S", (), {"to_dict": lambda self: {"line": 1}})(),
                    "bindings": [],
                },
            )(),
            "spec": type("Sp", (), {"op_name": "op", "arch_dir": "arch35"})(),
        }
    )
    key = derive_cache.field_cache_key("SplitAxis", fp, max_helper_guards=4)
    row = {"name": "SplitAxis", "status": "derived", "value_expr": {"op": "const", "value": 1}}
    assert derive_cache.store_field_row(key, row, op_dir=str(tmp_path), arch="arch35")
    loaded = derive_cache.load_field_row(key, op_dir=str(tmp_path), arch="arch35")
    assert loaded == row
    assert derive_cache.stats()["hit"] == 1
