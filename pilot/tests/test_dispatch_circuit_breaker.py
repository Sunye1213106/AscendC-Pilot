# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions import dispatch


def test_second_identical_dispatch_failure_is_blocked(monkeypatch, tmp_path: Path):
    state = {
        "ticket_id": "ticket-1",
        "status": "processing",
        "workflow_id": "tg-plan",
        "action_id": "plan_fuse",
    }

    def load(_root, _ticket_id):
        return dict(state)

    def write(_root, doc):
        state.clear()
        state.update(doc)
        return tmp_path / "ticket.yaml"

    monkeypatch.setattr(dispatch._legacy, "load_dispatch_ticket", load)
    monkeypatch.setattr(dispatch._legacy, "_write_ticket", write)

    first = dispatch.release_dispatch_ticket(tmp_path, "ticket-1", error="OUTPUT_CONTRACT_FAILED")
    assert first["retryable"] is True
    assert state["status"] == "open"
    assert state["same_failure_count"] == 1

    state["status"] = "processing"
    second = dispatch.release_dispatch_ticket(tmp_path, "ticket-1", error="OUTPUT_CONTRACT_FAILED")
    assert second["retryable"] is False
    assert second["reason_code"] == "REPEATED_DETERMINISTIC_FAILURE"
    assert state["status"] == "blocked_repeat_failure"
    assert state["same_failure_count"] == 2
