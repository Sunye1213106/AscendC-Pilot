# -*- coding: utf-8 -*-
from __future__ import annotations

from uo_init import fold_cache
from uo_init.clang_walk import CtrlNode


def test_fold_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("UO_FOLD_CACHE", "1")
    monkeypatch.setenv("UO_CACHE_ROOT", str(tmp_path / "cache"))
    fold_cache.reset_stats()
    key = fold_cache.instance_signature(
        harness_source=b"template void k<1>();\n",
        entry="k",
        kernel_args=["-std=c++17"],
        logical_file="kernel.cpp",
        clang_exe="clang++",
    )
    controls = [
        CtrlNode(
            id="kernel.cpp:10:0:if:0",
            kind="if",
            file="kernel.cpp",
            line=10,
            condition="N > 0",
            function="k",
        )
    ]
    path = fold_cache.store_fold_controls(key, controls, op_dir=str(tmp_path), arch="arch35")
    assert path and path.is_file()
    loaded = fold_cache.load_fold_controls(key, op_dir=str(tmp_path), arch="arch35")
    assert loaded is not None
    assert loaded[0].condition == "N > 0"
    assert fold_cache.stats()["hit"] == 1
