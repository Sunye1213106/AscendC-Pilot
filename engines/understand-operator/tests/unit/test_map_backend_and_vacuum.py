# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

from uo_init.parallel import _default_map_backend, _map_backend
from uo_init.store.writer import vacuum_uo_enabled


def test_default_backend_is_thread_on_windows(monkeypatch):
    monkeypatch.delenv("UO_MAP_BACKEND", raising=False)
    if sys.platform.startswith("linux"):
        assert _default_map_backend() == "process"
        assert _map_backend() == "process"
    else:
        assert _default_map_backend() == "thread"
        assert _map_backend() == "thread"
    monkeypatch.setenv("UO_MAP_BACKEND", "process")
    assert _map_backend() == "process"
    monkeypatch.setenv("UO_MAP_BACKEND", "thread")
    assert _map_backend() == "thread"


def test_vacuum_off_when_product_exists(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UO_VACUUM_UO", raising=False)
    dest = tmp_path / "op.arch35.uo"
    assert vacuum_uo_enabled(dest) is True
    dest.write_text("x", encoding="utf-8")
    assert vacuum_uo_enabled(dest) is False
    monkeypatch.setenv("UO_VACUUM_UO", "1")
    assert vacuum_uo_enabled(dest) is True
    monkeypatch.setenv("UO_VACUUM_UO", "0")
    assert vacuum_uo_enabled(dest) is False
