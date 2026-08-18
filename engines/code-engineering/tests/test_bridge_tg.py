from __future__ import annotations

import csv
from pathlib import Path

from code_engineering.bridge_tg import bridge_tg


def _write_cases(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_empty_affected_keys_do_not_select_entire_corpus(tmp_path: Path) -> None:
    _write_cases(
        tmp_path / ".ascendc-pilot" / "arch35" / "tg" / "cases.csv",
        [
            {"tiling_key": "1", "dim_DType": "fp16"},
            {"tiling_key": "2", "dim_DType": "bf16"},
            {"tiling_key": "3", "dim_DType": ""},
        ],
    )
    result = bridge_tg(tmp_path, {"affected_keys": [], "fields": []}, architecture="arch35")
    assert result["case_count"] == 0
    assert result["filter"] == "none"


def test_field_filter_selects_without_keys(tmp_path: Path) -> None:
    _write_cases(
        tmp_path / ".ascendc-pilot" / "arch35" / "tg" / "cases.csv",
        [
            {"tiling_key": "1", "dim_DType": "fp16"},
            {"tiling_key": "2", "dim_DType": "bf16"},
        ],
    )
    result = bridge_tg(
        tmp_path,
        {"affected_keys": [], "key_dims": ["DType"]},
        architecture="arch35",
    )
    assert result["case_count"] == 2
    assert result["filter"] == "fields"


def test_key_filter_does_not_or_in_unrelated_rows(tmp_path: Path) -> None:
    _write_cases(
        tmp_path / ".ascendc-pilot" / "arch35" / "tg" / "cases.csv",
        [
            {"tiling_key": "10", "dim_DType": "fp16"},
            {"tiling_key": "20", "dim_DType": "bf16"},
        ],
    )
    result = bridge_tg(tmp_path, {"affected_keys": [10], "fields": []}, architecture="arch35")
    assert result["impacted_keys"] == [10]
    assert result["case_count"] == 1
