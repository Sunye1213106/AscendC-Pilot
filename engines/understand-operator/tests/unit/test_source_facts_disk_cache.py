# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.source_index.builder import get_or_build, reset_index_cache
from uo_init.source_index.model import SourceFacts


def test_source_facts_disk_cache_survives_process_clear(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UO_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("UO_ARCHITECTURE", "arch35")
    monkeypatch.setenv("UO_NATIVE_SCANNER", "0")
    src = tmp_path / "op_host"
    src.mkdir()
    path = src / "a.cpp"
    path.write_text('#include "shared.h"\nint f() { return 1; }\n', encoding="utf-8")
    first = get_or_build([path], root=str(tmp_path), architecture="arch35")
    facts = first.facts_for(path)
    assert isinstance(facts, SourceFacts)
    assert "shared.h" in facts.includes
    reset_index_cache()
    second = get_or_build([path], root=str(tmp_path), architecture="arch35")
    again = second.facts_for(path)
    assert again is not None
    assert "shared.h" in again.includes
