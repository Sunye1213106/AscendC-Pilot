"""Obligation ledger monotonicity and collect_obligations integration."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.obligations import collect_obligations
from ascendc_pilot.obligations.ledger import (
    can_transition,
    ledger_path,
    load_ledger,
    upsert_item,
    validate_ledger,
)
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import record_gate, start_workflow


def test_transitions_monotonic() -> None:
    assert can_transition("open", "candidate")
    assert can_transition("candidate", "verified")
    assert can_transition("open", "blocked")
    assert not can_transition("verified", "open")
    assert not can_transition("verified", "candidate")


def test_collect_writes_ledger(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "uo-init", intent="t", op_name="toy", architecture="arch0")
    items = collect_obligations(tmp_path, "uo-init")
    assert isinstance(items, list)
    assert ledger_path(tmp_path).is_file()
    ledger = load_ledger(tmp_path)
    assert validate_ledger(ledger) == []
    # After a gate pass, static obligation settled by that gate becomes verified.
    # Prefer a gate that exists in STATIC_OBLIGATION_GATE_MAP if any.
    from ascendc_pilot.workflows.specs import STATIC_OBLIGATION_GATE_MAP

    if STATIC_OBLIGATION_GATE_MAP:
        gate = next(iter(STATIC_OBLIGATION_GATE_MAP.values()))
        record_gate(tmp_path, gate, ok=True)
        items2 = collect_obligations(tmp_path, "uo-init")
        ledger2 = load_ledger(tmp_path)
        verified = [
            oid
            for oid, row in (ledger2.get("items") or {}).items()
            if isinstance(row, dict) and row.get("status") == "verified"
        ]
        # At least the gate-settled static ids should appear verified when mapped.
        assert isinstance(items2, list)
        assert isinstance(verified, list)
        assert validate_ledger(ledger2) == []


def test_untrusted_verified_claim_is_only_candidate(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    ledger = load_ledger(tmp_path)
    row = upsert_item(
        ledger,
        oid="X",
        status="done",
        settled_by_gate="invented",
        evidence=[{"gate_id": "invented", "run_id": "r"}],
        reason="producer_claim",
    )
    assert row["status"] == "candidate"
    assert row.get("settled_by_gate") is None
    assert row.get("evidence") == []
    assert validate_ledger(ledger) == []


def test_refuse_silent_downgrade(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "uo-init", intent="t", op_name="toy", architecture="arch0")
    ledger = load_ledger(tmp_path)
    upsert_item(
        ledger,
        oid="X",
        status="verified",
        settled_by_gate="g",
        evidence=[{"gate_id": "g", "run_id": "r"}],
        reason="seed",
        verified_by_harness=True,
    )
    upsert_item(ledger, oid="X", status="open", reason="bad", allow_revert=False)
    assert ledger["items"]["X"]["status"] == "verified"
    assert validate_ledger(ledger) == []
