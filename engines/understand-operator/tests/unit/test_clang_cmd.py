# -*- coding: utf-8 -*-
from __future__ import annotations

from uo_init.clang_cmd import find_clang


def test_find_clang_returns_path_or_none() -> None:
    exe = find_clang()
    assert exe is None or isinstance(exe, str)
