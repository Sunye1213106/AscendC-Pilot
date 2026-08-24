# -*- coding: utf-8 -*-
"""Intake must stay self-consistent: one primary table, a runnable entry, and a
reader that dispatches on file content rather than on the file extension.

Every fixture here is synthetic. The failures they pin were found on a real FAG test
repo but none of the assertions mention an operator or a column name from it.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from testcase_agent import bind_parts as BP
from testcase_agent import test_repo as TR


def _wrapper_repo(root: Path) -> Path:
    """A repo whose argparse lives in a package module behind a thin runnable wrapper."""
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "main.py").write_text(
        "import argparse\n"
        "from .util import helper\n"
        "def main():\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--case', default='data/cases.csv')\n"
        "    p.add_argument('--mode', default='profiler', choices=['only_grad', 'profiler'])\n"
        "    return p.parse_args()\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    (pkg / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "run_op.py").write_text(
        "from pkg.main import main\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    return root


def _write_xlsx(path: Path, header: list[str], rows: list[list[str]]) -> None:
    """Minimal OOXML workbook written by hand so the test needs no writer library."""

    def cell(value: str) -> str:
        return f'<c t="inlineStr"><is><t>{value}</t></is></c>'

    body = "".join(
        "<row>" + "".join(cell(v) for v in line) + "</row>" for line in [header, *rows]
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{body}</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="s1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        zf.writestr("xl/worksheets/sheet1.xml", sheet)


def test_entry_prefers_runnable_wrapper_over_relative_import_module(tmp_path: Path) -> None:
    root = _wrapper_repo(tmp_path / "repo")
    (root / "data").mkdir()
    (root / "data" / "cases.csv").write_text("Testcase_Name,D\na,64\n", encoding="utf-8")

    doc = TR.contract_from_inventory(TR.scan(root))
    # pkg/main.py owns the argparse but `python pkg/main.py` raises ImportError.
    assert doc["entry"] == "run_op.py"
    assert doc["flag_owner"] == "pkg/main.py"
    # Following the wrapper must not lose the flags it delegates to.
    assert doc["case_arg"] == "--case"
    assert "only_grad" in doc["modes"]["precision"]
    assert "profiler" in doc["modes"]["perf"]
    assert any(f["code"] == "entry_delegates_flags" for f in doc["findings"])


def test_entry_ignores_report_tool_that_has_its_own_argparse(tmp_path: Path) -> None:
    root = _wrapper_repo(tmp_path / "repo")
    (root / "data").mkdir()
    (root / "data" / "cases.csv").write_text("Testcase_Name,D\na,64\n", encoding="utf-8")
    (root / "pkg" / "show_prof.py").write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--wait')\n"
        "if __name__ == '__main__':\n"
        "    p.parse_args()\n",
        encoding="utf-8",
    )
    doc = TR.contract_from_inventory(TR.scan(root))
    # A display tool has argparse too, but no case selection, so it is not the driver.
    assert doc["entry"] == "run_op.py"
    assert "--wait" not in " ".join(doc["modes"]["perf"] + doc["modes"]["precision"])


def test_ooxml_named_xls_is_still_read(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "run_op.py").write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--case')\n"
        "if __name__ == '__main__':\n"
        "    p.parse_args()\n",
        encoding="utf-8",
    )
    # OOXML content behind a legacy `.xls` name: xlrd refuses it, openpyxl refuses the
    # suffix, so a suffix-driven reader drops the table entirely.
    _write_xlsx(
        root / "data" / "legacy_name.xls",
        ["Testcase_Name", "Layout", "D"],
        [["a", "TND", "64"], ["b", "BNSD", "128"]],
    )
    inv = TR.scan(root)
    table = next(t for t in inv["tables"] if t["path"].endswith("legacy_name.xls"))
    assert not table.get("error")
    assert table["kind"] == "xlsx"
    assert table["columns"] == ["Testcase_Name", "Layout", "D"]
    assert table["profile"]["n_rows"] == 2
    assert not any(f["code"] == "unreadable_table" for f in TR.contract_from_inventory(inv)["findings"])


def test_profile_and_header_come_from_the_same_table(tmp_path: Path) -> None:
    """The classic provenance split: two tables, different headers, same repo."""
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "run_op.py").write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--case')\n"
        "if __name__ == '__main__':\n"
        "    p.parse_args()\n",
        encoding="utf-8",
    )
    # Sorts first by name and is readable, so a "first table with a profile" rule picks
    # it — but it has fewer columns, so it is NOT the primary table.
    _write_xlsx(
        root / "data" / "aaa_other.xls",
        ["Testcase_Name", "Layout", "D"],
        [["x", "TND", "1"], ["y", "TND", "2"], ["z", "TND", "3"]],
    )
    (root / "data" / "zzz_primary.csv").write_text(
        "Testcase_Name,Input_Layout,D,Extra\n"
        "a,BNSD,64,7\n"
        "b,BSND,128,8\n",
        encoding="utf-8",
    )

    inv = TR.scan(root)
    contract = TR.contract_from_inventory(inv)
    assert contract["primary_table"].endswith("zzz_primary.csv")
    assert contract["table_kind"] == "csv"
    assert contract["column_profile"]["n_rows"] == 2

    scan = {"kind": "script_repo", "inventory": inv, "contract": contract}
    columns = BP._column_names(scan)
    profiles = BP._profiles(scan)
    assert "Extra" in columns and "Input_Layout" in columns
    # Every declared column is profiled, and nothing leaks in from the other table.
    assert set(profiles) == set(columns)
    assert all(profiles[c] for c in columns)
    assert "Layout" not in profiles
    # table_kind describes the primary table, not "any xls in the repo".
    assert BP._table_kind(scan) == "csv"


def test_profile_recovers_primary_when_receipt_predates_primary_table(tmp_path: Path) -> None:
    """Old receipts carry no primary_table; header matching must still bind the profile."""
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "run_op.py").write_text(
        "import argparse\np = argparse.ArgumentParser()\np.add_argument('--case')\n"
        "if __name__ == '__main__':\n    p.parse_args()\n",
        encoding="utf-8",
    )
    _write_xlsx(root / "data" / "aaa_other.xls", ["Testcase_Name", "Layout"], [["x", "TND"]])
    (root / "data" / "zzz_primary.csv").write_text(
        "Testcase_Name,Input_Layout,D\na,BNSD,64\n", encoding="utf-8"
    )
    inv = TR.scan(root)
    contract = TR.contract_from_inventory(inv)
    contract.pop("primary_table")
    contract.pop("column_profile")
    contract.pop("table_kind")
    scan = {"kind": "script_repo", "inventory": inv, "contract": contract}
    profiles = BP._profiles(scan)
    assert set(profiles) == {"Testcase_Name", "Input_Layout", "D"}


@pytest.mark.parametrize(
    "magic,want",
    [(b"PK\x03\x04ab", "xlsx"), (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "xls")],
)
def test_workbook_format_follows_content(tmp_path: Path, magic: bytes, want: str) -> None:
    path = tmp_path / "table.xls"
    path.write_bytes(magic + b"\x00" * 32)
    assert TR._workbook_format(path) == want
