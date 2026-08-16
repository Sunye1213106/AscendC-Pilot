# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ascendc_pilot.authorize.exploration_budget import (
    DEFAULT_LIMITS,
    DUP_REASON,
    HARD_REASON,
    SOFT_REASON,
    check_and_record,
    classify_tool,
    init_budget,
    load_budget,
)
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import start_workflow


def _started_query(tmp_path: Path) -> tuple[Path, str]:
    op = tmp_path / "op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-query", architecture="arch35", intent="q")
    from ascendc_pilot.state import load_state

    state = load_state(op)
    run_id = str(state["run_id"])
    init_budget(op, run_id=run_id, action_id="kb_lookup")
    return op, run_id


def test_classify_tool_buckets() -> None:
    assert classify_tool("bash", "acp uo-query --mode tiling_key --pattern X") == "semantic"
    assert classify_tool("bash", "acp ro-search --pattern foo") == "repo"
    assert classify_tool("read", path="op_host/foo.cpp") == "source"
    assert classify_tool("read", path=".ascendc-pilot/uo/x.uo") is None


def test_semantic_duplicate_is_denied(tmp_path: Path) -> None:
    op, run_id = _started_query(tmp_path)
    cmd = "acp uo-query --mode search --pattern SplitAxis --project /x"
    a = check_and_record(op, run_id=run_id, action_id="kb_lookup", tool="bash", command=cmd)
    assert a["ok"] is True
    b = check_and_record(op, run_id=run_id, action_id="kb_lookup", tool="bash", command=cmd)
    assert b["ok"] is False
    assert b["reason_code"] == DUP_REASON


def test_source_duplicate_is_window_not_file(tmp_path: Path) -> None:
    op, run_id = _started_query(tmp_path)
    path = "op_host/foo.cpp"
    first = check_and_record(
        op,
        run_id=run_id,
        action_id="kb_lookup",
        tool="read",
        path=path,
        command="offset=100;limit=40",
    )
    second_window = check_and_record(
        op,
        run_id=run_id,
        action_id="kb_lookup",
        tool="read",
        path=path,
        command="offset=800;limit=40",
    )
    duplicate = check_and_record(
        op,
        run_id=run_id,
        action_id="kb_lookup",
        tool="read",
        path=path,
        command="offset=100;limit=40",
    )
    assert first["ok"] is True
    assert second_window["ok"] is True
    assert duplicate["ok"] is False
    assert duplicate["reason_code"] == DUP_REASON


def test_source_without_range_does_not_false_deduplicate_file(tmp_path: Path) -> None:
    op, run_id = _started_query(tmp_path)
    path = "op_host/foo.cpp"
    first = check_and_record(op, run_id=run_id, action_id="kb_lookup", tool="read", path=path)
    second = check_and_record(op, run_id=run_id, action_id="kb_lookup", tool="read", path=path)
    assert first["ok"] is True
    assert second["ok"] is True


def test_total_soft_and_hard_limits(tmp_path: Path) -> None:
    op, run_id = _started_query(tmp_path)
    results = []
    # Use non-duplicated repo searches to avoid semantic per-bucket meaning
    # dominating the total-budget regression.
    repo_soft = int(DEFAULT_LIMITS["repo"])
    total_soft = int(DEFAULT_LIMITS["total"])
    hard_total = int(DEFAULT_LIMITS["hard_total"])
    for i in range(hard_total):
        r = check_and_record(
            op,
            run_id=run_id,
            action_id="kb_lookup",
            tool="grep",
            command=f"pattern-{i}",
            path=f"file-{i}.txt",
        )
        results.append(r)
        assert r["ok"] is True, (i, r)
    assert results[repo_soft - 1].get("warning") == SOFT_REASON
    assert results[total_soft - 1].get("warning") == SOFT_REASON
    assert results[hard_total - 1].get("hard_limit_reached") is True

    denied = check_and_record(
        op,
        run_id=run_id,
        action_id="kb_lookup",
        tool="grep",
        command=f"pattern-{hard_total}",
        path=f"file-{hard_total}.txt",
    )
    assert denied["ok"] is False
    assert denied["reason_code"] == HARD_REASON
    body = load_budget(op, run_id=run_id, action_id="kb_lookup")
    assert body is not None
    assert int(body["counts"]["total"]) == hard_total
    assert int(body["limits"]["semantic"]) == int(DEFAULT_LIMITS["semantic"])
    assert int(body["limits"]["hard_total"]) == hard_total
