# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ascendc_pilot.authorize.exploration_budget import (
    DUP_REASON,
    HARD_REASON,
    check_and_record,
    classify_tool,
    init_budget,
    load_budget,
)
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import start_workflow


def test_classify_tool_buckets() -> None:
    assert classify_tool("bash", "acp uo-query --mode tiling_key --pattern X") == "semantic"
    assert classify_tool("bash", "acp ro-search --pattern foo") == "repo"
    assert classify_tool("read", path="op_host/foo.cpp") == "source"
    assert classify_tool("read", path=".ascendc-pilot/uo/x.uo") is None


def test_budget_duplicate_and_exhaust(tmp_path: Path) -> None:
    op = tmp_path / "op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-query", architecture="arch35", intent="q")
    from ascendc_pilot.state import load_state

    state = load_state(op)
    run_id = str(state["run_id"])
    init_budget(op, run_id=run_id, action_id="kb_lookup")

    cmd = "acp uo-query --mode search --pattern SplitAxis --project /x"
    a = check_and_record(op, run_id=run_id, action_id="kb_lookup", tool="bash", command=cmd)
    assert a["ok"] is True
    b = check_and_record(op, run_id=run_id, action_id="kb_lookup", tool="bash", command=cmd)
    assert b["ok"] is False
    assert b["reason_code"] == DUP_REASON

    # Fill semantic budget with unique patterns
    for i in range(20):
        r = check_and_record(
            op,
            run_id=run_id,
            action_id="kb_lookup",
            tool="bash",
            command=f"acp uo-query --mode search --pattern Dim{i}",
        )
        if not r.get("ok") and r.get("reason_code") == HARD_REASON:
            break
    else:
        raise AssertionError("expected EXPLORATION_BUDGET_EXHAUSTED")
    body = load_budget(op, run_id=run_id, action_id="kb_lookup")
    assert body is not None
    assert int(body["counts"]["total"]) >= 6
