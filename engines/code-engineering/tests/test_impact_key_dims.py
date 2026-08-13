# -*- coding: utf-8 -*-
"""CE impact: arch-scoped .uo, no host_codemap.yaml, dim names are not packed keys."""
from __future__ import annotations

from pathlib import Path

from code_engineering.impact import impact_from_diff


DIFF = (
    "diff --git a/op_host/tiling.cpp b/op_host/tiling.cpp\n"
    "--- a/op_host/tiling.cpp\n"
    "+++ b/op_host/tiling.cpp\n"
    "@@ -12,1 +12,2 @@\n"
    " keep\n"
    "+added\n"
)


def test_dim_names_stay_in_key_dims_not_affected_keys(monkeypatch) -> None:
    fake = {
        "fields": [
            {
                "name": "DType",
                "kind": "key_dim_host",
                "tiling_key": "DType",
                "writers": [{"file": "op_host/tiling.cpp", "line": 12, "function": "DoTiling"}],
            }
        ],
        "keys": [],
    }
    monkeypatch.setattr(
        "code_engineering.impact._load_host_view",
        lambda *_args, **_kwargs: (fake, "mock"),
    )
    report = impact_from_diff(DIFF, project_root=Path("."), architecture="arch35")
    assert "DType" in report.key_dims
    assert report.affected_keys == []


def test_numeric_looking_dim_name_is_not_a_packed_key(monkeypatch) -> None:
    fake = {
        "fields": [
            {
                "name": "16",
                "kind": "key_dim",
                "tiling_key": "16",
                "writers": [{"file": "op_host/tiling.cpp", "line": 12}],
            }
        ],
        "keys": [],
    }
    monkeypatch.setattr(
        "code_engineering.impact._load_host_view",
        lambda *_args, **_kwargs: (fake, "mock"),
    )
    report = impact_from_diff(DIFF, project_root=Path("."), architecture="arch35")
    assert "16" in report.key_dims
    assert 16 not in report.affected_keys


def test_packed_int_keys_are_collected(monkeypatch) -> None:
    fake = {
        "fields": [
            {
                "name": "DType",
                "kind": "key_dim_host",
                "tiling_key": "DType",
                "packed_key": 0x10,
                "writers": [{"file": "op_host/tiling.cpp", "line": 12}],
            }
        ],
        "keys": [7],
    }
    monkeypatch.setattr(
        "code_engineering.impact._load_host_view",
        lambda *_args, **_kwargs: (fake, "mock"),
    )
    report = impact_from_diff(DIFF, project_root=Path("."), architecture="arch35")
    assert "DType" in report.key_dims
    assert report.affected_keys == [7, 16]


def test_no_host_codemap_yaml_fallback(tmp_path: Path) -> None:
    yaml_only = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "ir" / "host_codemap.yaml"
    yaml_only.parent.mkdir(parents=True, exist_ok=True)
    yaml_only.write_text(
        "fields: [{name: DType, writers: [{file: op_host/tiling.cpp, line: 12}]}]\n",
        encoding="utf-8",
    )
    report = impact_from_diff(DIFF, project_root=tmp_path, architecture="arch35")
    assert report.hit_writers == []
    assert "host_codemap" not in report.note
    assert "missing" in report.note
