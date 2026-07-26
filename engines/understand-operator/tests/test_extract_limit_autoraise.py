"""ses_0662: extract candidate budget auto-raise + pilot_params persistence."""

from __future__ import annotations

from pathlib import Path

from uo.scripts.propose_extract_plan import (
    _auto_raise_extract_limits,
    apply_extract_limits_to_environ,
    load_extract_limit_overrides,
    persist_extract_limits,
    resolve_extract_limits,
)


def test_auto_raise_fits_raw_within_hard_max() -> None:
    limits = {
        "writers": 200,
        "receivers": 200,
        "aliases": 300,
        "non_sink_roots": 512,
        "extra_entries": 100,
    }
    raw = {
        "writers": 136,
        "receivers": 18,
        "aliases": 118,
        "non_sink_roots": 648,
        "extra_entries": 1,
    }
    new_limits, raised, still_over = _auto_raise_extract_limits(raw, limits)
    assert still_over == {}
    assert raised == {"non_sink_roots": 648}
    assert new_limits["non_sink_roots"] == 648
    assert new_limits["writers"] == 200


def test_persist_and_resolve_extract_limits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("UO_EXTRACT_MAX_NON_SINK", raising=False)
    path = persist_extract_limits(tmp_path, {"non_sink_roots": 1024})
    assert path is not None and path.is_file()
    overrides = load_extract_limit_overrides(tmp_path)
    assert overrides["non_sink_roots"] == 1024
    resolved = resolve_extract_limits(tmp_path)
    assert resolved["non_sink_roots"] == 1024
    # env wins over pilot_params
    monkeypatch.setenv("UO_EXTRACT_MAX_NON_SINK", "2048")
    assert resolve_extract_limits(tmp_path)["non_sink_roots"] == 2048
    apply_extract_limits_to_environ({"non_sink_roots": 900})
    assert resolve_extract_limits(tmp_path)["non_sink_roots"] == 900
