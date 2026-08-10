from __future__ import annotations

from testcase_agent.closure import closure_state
from testcase_agent.closure import workspace as W


def test_unknown_relation_never_removes_a_declared_key(monkeypatch, tmp_path) -> None:
    ws = W.Workspace(root=tmp_path, artifacts=tmp_path / "artifacts", state=tmp_path / "state").ensure()
    monkeypatch.setattr("testcase_agent.closure.ledger.declared", lambda: {1, 2})
    monkeypatch.setattr("testcase_agent.closure.ledger.load_R", lambda _ws: {1})
    monkeypatch.setattr("testcase_agent.closure.ledger.load_E", lambda _ws: set())
    monkeypatch.setattr(W, "decode", lambda key: {"mode": "x" if key == 1 else None})
    doc = closure_state.build(ws, relations=[{"op": "eq", "field": "mode", "value": "x"}])
    assert doc["D"] == [1, 2]
    assert doc["U"] == [2]
    assert doc["invariants"]["unknown_never_removed"] is True
