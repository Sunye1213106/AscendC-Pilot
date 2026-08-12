"""Init-audit schema must teach tilingkey checklist, not removed CSV ids."""

from __future__ import annotations

from pathlib import Path

_TILINGKEY_IDS = (
    "tilingkey_contract",
    "declared_set_nonempty",
    "binding_inventory",
    "host_view_aligned",
    "graph_fingerprint",
    "integrity_gate",
)


def test_init_audit_schema_matches_tilingkey_ids() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = (root / "agents" / "references" / "init-audit-schema.md").read_text(encoding="utf-8")
    assert "TILINGKEY_AUDIT_CHECKLIST_IDS" in schema
    assert "chain_to_csv" not in schema
    assert "full_csv_closure" not in schema
    assert "verify-csv-closure" not in schema
    for cid in _TILINGKEY_IDS:
        assert cid in schema, cid
    assert "conditional_pass" in schema or "空的 `reads`" in schema or "reads" in schema
    method = (
        root
        / "skills"
        / "testcase-generation"
        / "capabilities"
        / "tg-init-audit"
        / "METHOD.md"
    ).read_text(encoding="utf-8")
    assert "status: pass" in method or "pass` 或 `fail" in method
    assert "不是 blocker" in method
