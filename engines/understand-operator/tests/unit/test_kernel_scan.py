# -*- coding: utf-8 -*-
from types import SimpleNamespace
from pathlib import Path

from uo_init.passes import kernel_scan as kscan


def test_collect_call_sites_allows_walk_methods(monkeypatch, tmp_path: Path):
    """Packed-key kernels put EnQue in class methods, not the KERNEL entry."""
    site = SimpleNamespace(caller="InitAllZeroOutput", callee="EnQue", file="x.h")
    wr = SimpleNamespace(
        path=str(tmp_path / "op_kernel" / "entry.cpp"),
        call_sites=[site],
        functions={"InitAllZeroOutput": object(), "incre_flash_attention": object()},
        local_decls=[],
        controls=[],
    )
    monkeypatch.setattr(
        "uo_init.tu_cache.iter_cached_walks", lambda *a, **k: [wr]
    )
    import time

    calls, *_ = kscan.collect_call_sites_from_walks(
        tmp_path,
        architecture="arch22",
        reachable={"incre_flash_attention"},
        filter_strict=True,
        deadline=time.time() + 30,
    )
    assert [s.callee for s in calls] == ["EnQue"]
