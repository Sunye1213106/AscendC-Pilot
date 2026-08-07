from __future__ import annotations

from testcase_agent.closure.ledger import baseline_fingerprint


def test_baseline_fingerprint_is_content_sensitive_and_role_scoped(tmp_path) -> None:
    source = tmp_path / "op_host" / "x.cpp"
    source.parent.mkdir(parents=True)
    source.write_text("int x = 1;\n", encoding="utf-8")
    first = baseline_fingerprint(tmp_path)
    source.write_text("int x = 2;\n", encoding="utf-8")
    second = baseline_fingerprint(tmp_path)
    assert first["source_fingerprint"] != second["source_fingerprint"]
    assert second["roles"]["op_host"][0]["path"] == "op_host/x.cpp"
    assert second["protocol_version"] == "tg-oracle-probe/v2"
