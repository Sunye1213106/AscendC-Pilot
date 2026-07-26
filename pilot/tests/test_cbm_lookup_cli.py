"""acp cbm lookup wraps CbmClient + windowed snippet."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.cbm_lookup import lookup_symbol


def test_lookup_reports_unavailable_without_cbm(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    (op / ".ascendc-pilot" / "uo" / "cbm").mkdir(parents=True)
    out = lookup_symbol(op, name="SaveToTilingData")
    assert out["status"] == "unavailable"
    assert out["ok"] is False
    assert "fallback" in out


def test_lookup_miss_when_db_empty_project(tmp_path: Path, monkeypatch) -> None:
    op = tmp_path / "DemoOp"
    uo = op / ".ascendc-pilot" / "uo"
    (uo / "cbm").mkdir(parents=True)
    (uo / "cbm" / "index_meta.json").write_text(
        '{"cbm_project":"demo","cbm_db_path":"%s"}'
        % (uo / "cbm" / "missing.db").as_posix().replace("\\", "/"),
        encoding="utf-8",
    )
    out = lookup_symbol(op, name="NoSuchSymbol")
    assert out["cbm_available"] is False or out["status"] in {"unavailable", "miss"}
