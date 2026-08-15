# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from testcase_agent import test_repo as TR

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "tests" / "fixtures" / "_generic_test_repo"


def test_scan_empty_is_default_input():
    inv = TR.scan("")
    assert inv["kind"] == "default_input"
    doc = TR.contract_from_inventory(inv, knob_defaults={"n": 4, "dtype": "fp16"})
    assert doc["kind"] == "default_input"
    row = TR.fill_row(doc, name="default_input")
    assert row["n"] == "4"
    assert row["dtype"] == "fp16"


def test_scan_generic_repo_finds_entry_and_csv():
    inv = TR.scan(FIXTURE)
    assert inv["kind"] == "script_repo"
    assert any(str(e.get("path") or "").endswith("run_op.py") for e in inv["entries"])
    assert any(str(t.get("path") or "").endswith("cases.csv") for t in inv["tables"])
    doc = TR.contract_from_inventory(
        inv,
        host_fields=["dtype"],
        key_dims=["n"],
    )
    assert doc["kind"] == "script_repo"
    assert doc["entry"].endswith("run_op.py")
    assert doc["case_arg"] == "--case"
    assert "--mode" in doc["modes"]["precision"]
    assert "dtype" in doc["columns"]
    row = TR.fill_row(doc, {"dtype": "bf16"}, name="generated")
    assert row["dtype"] == "bf16"
    assert row["Testcase_Name"] == "generated"


def test_cross_check_flags_unmapped_columns():
    inv = TR.scan(FIXTURE)
    doc = TR.contract_from_inventory(inv, host_fields=[], key_dims=[])
    codes = {f["code"] for f in doc["findings"]}
    assert "unmapped_column" in codes


def test_cross_check_flags_missing_key_dim_column():
    inv = TR.scan(FIXTURE)
    doc = TR.contract_from_inventory(inv, host_fields=["dtype"], key_dims=["SplitAxis"])
    codes = {f["code"] for f in doc["findings"]}
    assert "missing_column" in codes
    row = TR.fill_row(doc, {"dtype": "fp16", "SplitAxis": "1"}, name="generated")
    assert row["dtype"] == "fp16"
    assert "SplitAxis" not in row
