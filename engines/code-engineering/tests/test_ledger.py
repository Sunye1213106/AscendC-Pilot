from pathlib import Path

from code_engineering.ledger import Ledger, load_ledger, save_ledger


def test_ledger_open_computation_and_roundtrip(tmp_path: Path) -> None:
    ledger = Ledger(O={"a", "b", "c"}, V={"a"}, X={"c"})
    assert ledger.Open == {"b"}

    path = save_ledger(ledger, tmp_path, architecture="arch20")
    loaded = load_ledger(tmp_path, architecture="arch20")

    assert path == tmp_path / ".ascendc-pilot" / "arch20" / "ce" / "impact" / "ledger.yaml"
    assert loaded.Open == {"b"}
