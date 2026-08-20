# -*- coding: utf-8 -*-
"""Fan-out dispatch tickets wait for every slice before finalize."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ascendc_pilot.actions.dispatch import (
    ack_fanout_slice,
    dispatch_result,
    infer_slice_id,
    issue_dispatch_ticket,
    load_dispatch_ticket,
)
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import start_workflow


def _issue_pair(tmp_path: Path) -> dict[str, Any]:
    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "ce-review", phase="review", force_phase=True, architecture="arch0")
    spec_stub = "AXIS=spec\nSLICE_ID=spec\nread method_spec.md"
    std_stub = "AXIS=standards\nSLICE_ID=standards\nread method_standards.md"
    return issue_dispatch_ticket(
        tmp_path,
        run_id="run_fanout",
        action_id="code_review",
        actor_id="ce-reviewer",
        lease_id="lease1",
        session_dir=str(tmp_path / "session"),
        task_prompt_stub="parent stub",
        expected_slices=["spec", "standards"],
        dispatch_tasks=[
            {
                "slice_id": "spec",
                "focus": "Spec",
                "first_mode": "spec",
                "actor_id": "ce-reviewer",
                "action_id": "code_review",
                "task_prompt_stub": spec_stub,
            },
            {
                "slice_id": "standards",
                "focus": "Standards",
                "first_mode": "standards",
                "actor_id": "ce-reviewer",
                "action_id": "code_review",
                "task_prompt_stub": std_stub,
            },
        ],
    )


def test_infer_slice_id_prefers_axis_and_explicit() -> None:
    expected = ["spec", "standards"]
    assert infer_slice_id("hello", expected, {}, explicit="standards") == "standards"
    assert infer_slice_id("AXIS=spec\nbody", expected, {}) == "spec"
    assert infer_slice_id("no axis", expected, {"spec": {"text": "x"}}) == "standards"
    assert infer_slice_id("no axis", expected, {}) == ""
    assert infer_slice_id("完成。已编写 parts/harness.yaml。", ["harness", "bind"], {}) == "harness"
    assert infer_slice_id("wrote bind.yaml", ["harness", "bind"], {"harness": {"text": "x"}}) == "bind"
    assert infer_slice_id("see harness.yaml and bind.yaml", ["harness", "bind"], {}) == ""


def test_first_slice_ack_does_not_consume(tmp_path: Path) -> None:
    ticket = _issue_pair(tmp_path)
    tid = str(ticket["ticket_id"])
    first = ack_fanout_slice(
        tmp_path, tid, result_text="spec findings", slice_id="spec"
    )
    assert first.get("ok") is True
    assert first.get("waiting_slices") is True
    assert first.get("remaining_slices") == ["standards"]
    assert first.get("host_step", {}).get("kind") == "dispatch_subagent"
    assert first.get("remaining_slices") == ["standards"]
    tasks = first.get("host_step", {}).get("tasks") or first.get("host_step", {}).get(
        "dispatch_tasks"
    ) or []
    if tasks:
        assert {t.get("slice_id") for t in tasks} <= {"standards"}
    stub = str(first["host_step"].get("task_prompt_stub") or "")
    assert "AXIS=standards" in stub
    assert "AXIS=spec" not in stub
    loaded = load_dispatch_ticket(tmp_path, tid)
    assert loaded.get("status") == "collecting"
    assert "spec" in (loaded.get("slice_results") or {})
    assert "standards" not in (loaded.get("slice_results") or {})


def test_second_slice_ack_is_ready(tmp_path: Path) -> None:
    ticket = _issue_pair(tmp_path)
    tid = str(ticket["ticket_id"])
    ack_fanout_slice(tmp_path, tid, result_text="spec body", slice_id="spec")
    second = ack_fanout_slice(
        tmp_path, tid, result_text="standards body", slice_id="standards"
    )
    assert second.get("ok") is True
    assert second.get("ready") is True
    assert second.get("waiting_slices") is not True
    combined = str(second.get("combined_text") or "")
    assert "## AXIS=spec" in combined
    assert "spec body" in combined
    assert "## AXIS=standards" in combined
    assert "standards body" in combined


def test_dispatch_result_waits_then_finalizes(tmp_path: Path, monkeypatch) -> None:
    ticket = _issue_pair(tmp_path)
    tid = str(ticket["ticket_id"])
    first = dispatch_result(tmp_path, ticket_id=tid, result_text="spec only", slice_id="spec")
    assert first.get("waiting_slices") is True
    assert load_dispatch_ticket(tmp_path, tid).get("status") == "collecting"

    calls: dict[str, Any] = {}

    def fake_run_action(*_a, **kwargs):
        calls["action_result"] = kwargs.get("action_result")
        return {"ok": True}

    def fake_drive(_root, **_k):
        return {"ok": True, "stop_reason": "workflow_complete", "status": "passed", "complete": {}}

    import ascendc_pilot.actions as actions_mod
    import ascendc_pilot.actions.drive as drive_mod
    import ascendc_pilot.actions.runtime as runtime_mod

    monkeypatch.setattr(actions_mod, "run_action", fake_run_action)
    monkeypatch.setattr(drive_mod, "drive_until_interaction", fake_drive)
    monkeypatch.setattr(runtime_mod, "prepare_action", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(
        "ascendc_pilot.actions.dispatch_legacy.attach_host_step",
        lambda _root, driven: driven,
    )

    second = dispatch_result(
        tmp_path, ticket_id=tid, result_text="std only", slice_id="standards"
    )
    assert second.get("waiting_slices") is not True
    assert load_dispatch_ticket(tmp_path, tid).get("status") == "consumed"
    payload = calls.get("action_result") or {}
    assert payload.get("fanout") is True
    assert "spec only" in str(payload.get("result_text") or "")
    assert "std only" in str(payload.get("result_text") or "")


def test_single_task_ticket_skips_fanout_ack(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "uo-query", phase="answer", force_phase=True, architecture="arch0")
    ticket = issue_dispatch_ticket(
        tmp_path,
        run_id="run_single",
        action_id="kb_lookup",
        actor_id="uo-query",
    )
    acked = ack_fanout_slice(
        tmp_path, str(ticket["ticket_id"]), result_text="one answer"
    )
    assert acked.get("fanout") is False
    assert acked.get("waiting_slices") is not True
    assert load_dispatch_ticket(tmp_path, str(ticket["ticket_id"])).get("status") == "open"


def _issue_pair_with_state_run(tmp_path: Path) -> tuple[dict[str, Any], str]:
    from ascendc_pilot.state import load_state

    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "ce-review", phase="review", force_phase=True, architecture="arch0")
    run_id = str((load_state(tmp_path) or {}).get("run_id") or "").strip()
    spec_stub = "AXIS=spec\nSLICE_ID=spec\nread method_spec.md"
    std_stub = "AXIS=standards\nSLICE_ID=standards\nread method_standards.md"
    ticket = issue_dispatch_ticket(
        tmp_path,
        run_id=run_id,
        action_id="code_review",
        actor_id="ce-reviewer",
        lease_id="lease1",
        session_dir=str(tmp_path / "session"),
        task_prompt_stub="parent stub",
        expected_slices=["spec", "standards"],
        dispatch_tasks=[
            {
                "slice_id": "spec",
                "focus": "Spec",
                "first_mode": "spec",
                "actor_id": "ce-reviewer",
                "action_id": "code_review",
                "task_prompt_stub": spec_stub,
            },
            {
                "slice_id": "standards",
                "focus": "Standards",
                "first_mode": "standards",
                "actor_id": "ce-reviewer",
                "action_id": "code_review",
                "task_prompt_stub": std_stub,
            },
        ],
    )
    return ticket, run_id


def test_ack_ready_without_new_slice_id(tmp_path: Path) -> None:
    ticket = _issue_pair(tmp_path)
    tid = str(ticket["ticket_id"])
    ack_fanout_slice(tmp_path, tid, result_text="spec body", slice_id="spec")
    ack_fanout_slice(tmp_path, tid, result_text="std body", slice_id="standards")
    ready = ack_fanout_slice(tmp_path, tid, result_text="harvest", slice_id="")
    assert ready.get("ready") is True
    assert ready.get("ok") is True
    assert ready.get("error") != "SLICE_ID_REQUIRED"


def test_harvest_partial_parts_reuses_ticket(tmp_path: Path) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step
    from ascendc_pilot.paths import agent_root

    ticket, run_id = _issue_pair_with_state_run(tmp_path)
    tid = str(ticket["ticket_id"])
    parts = agent_root(tmp_path) / "runs" / run_id / "actions" / "code_review" / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    (parts / "spec.md").write_text("spec harvested", encoding="utf-8")
    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "interaction_required",
            "status": "running",
            "next": {
                "action_id": "code_review",
                "execution_kind": "subagent",
                "actor_id": "ce-reviewer",
            },
        },
    )
    assert out.get("dispatch_ticket") == tid
    assert out.get("prepare", {}).get("reused_ticket") is True
    remaining = (out.get("host_step") or {}).get("remaining_slices") or out.get("remaining_slices")
    step = out.get("host_step") or {}
    assert step.get("kind") == "dispatch_subagent"
    assert "standards" in str(step.get("remaining_slices") or remaining or step)
    tickets = list(
        (tmp_path / ".ascendc-pilot").rglob("dxt_*.yaml")
    )
    ids = {p.stem for p in tickets}
    assert tid in ids
    assert len(ids) == 1


def test_harvest_complete_parts_does_not_issue_new_ticket(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions import dispatch_legacy
    from ascendc_pilot.actions.dispatch import attach_host_step
    from ascendc_pilot.paths import agent_root

    ticket, run_id = _issue_pair_with_state_run(tmp_path)
    tid = str(ticket["ticket_id"])
    parts = agent_root(tmp_path) / "runs" / run_id / "actions" / "code_review" / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    (parts / "spec.md").write_text("spec harvested", encoding="utf-8")
    (parts / "standards.md").write_text("standards harvested", encoding="utf-8")

    seen: dict[str, Any] = {}

    def fake_dispatch_result(project_root, **kwargs):
        seen["ticket_id"] = kwargs.get("ticket_id")
        return {"ok": True, "harvested": True, "ticket_id": kwargs.get("ticket_id")}

    monkeypatch.setattr(dispatch_legacy, "dispatch_result", fake_dispatch_result)
    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "interaction_required",
            "status": "running",
            "next": {
                "action_id": "code_review",
                "execution_kind": "subagent",
                "actor_id": "ce-reviewer",
            },
        },
    )
    assert seen.get("ticket_id") == tid
    assert (parts / "merged.md").is_file()
    assert out.get("ticket_id") == tid or seen.get("ticket_id") == tid
    ids = {p.stem for p in (tmp_path / ".ascendc-pilot").rglob("dxt_*.yaml")}
    assert ids == {tid}


def test_ce_review_serial_ack_without_parts(tmp_path: Path) -> None:
    """Count-complete ACK: order does not matter; no parts files required."""
    ticket = _issue_pair(tmp_path)
    tid = str(ticket["ticket_id"])
    missing = ack_fanout_slice(tmp_path, tid, result_text="no axis in the summary")
    assert missing.get("ok") is False
    assert missing.get("error") == "SLICE_ID_REQUIRED"
    first = ack_fanout_slice(tmp_path, tid, result_text="spec findings", slice_id="spec")
    assert first.get("waiting_slices") is True
    assert first.get("remaining_slices") == ["standards"]
    second = ack_fanout_slice(
        tmp_path, tid, result_text="standards findings", slice_id="standards"
    )
    assert second.get("ok") is True
    assert second.get("ready") is True
    loaded = load_dispatch_ticket(tmp_path, tid)
    assert set((loaded.get("slice_results") or {}).keys()) == {"spec", "standards"}


def _issue_bind_pair_with_state_run(tmp_path: Path) -> tuple[dict[str, Any], str, Path]:
    from ascendc_pilot.state import load_state

    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "tg-init", phase="bind", force_phase=True, architecture="arch0")
    run_id = str((load_state(tmp_path) or {}).get("run_id") or "").strip()
    sdir = tmp_path / "bind_session"
    sdir.mkdir()
    harness_stub = "AXIS=harness\nSLICE_ID=harness\nwrite parts/harness.yaml"
    bind_stub = "AXIS=bind\nSLICE_ID=bind\nwrite parts/bind.yaml"
    ticket = issue_dispatch_ticket(
        tmp_path,
        run_id=run_id,
        action_id="bind_init",
        actor_id="tg-analyst",
        lease_id="lease1",
        session_dir=str(sdir),
        task_prompt_stub="parent stub",
        expected_slices=["harness", "bind"],
        dispatch_tasks=[
            {
                "slice_id": "harness",
                "focus": "Harness",
                "first_mode": "harness",
                "actor_id": "tg-analyst",
                "action_id": "bind_init",
                "task_prompt_stub": harness_stub,
            },
            {
                "slice_id": "bind",
                "focus": "Bind",
                "first_mode": "bind",
                "actor_id": "tg-analyst",
                "action_id": "bind_init",
                "task_prompt_stub": bind_stub,
            },
        ],
    )
    return ticket, run_id, sdir


def test_harvest_bind_yaml_from_session_dir_finalizes(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions import dispatch_legacy
    from ascendc_pilot.actions.dispatch import attach_host_step

    ticket, _run_id, sdir = _issue_bind_pair_with_state_run(tmp_path)
    tid = str(ticket["ticket_id"])
    parts = sdir / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    (parts / "harness.yaml").write_text("golden: {status: match}\n", encoding="utf-8")
    (parts / "bind.yaml").write_text("columns: [{name: B}]\n", encoding="utf-8")

    seen: dict[str, Any] = {}

    def fake_dispatch_result(project_root, **kwargs):
        seen["ticket_id"] = kwargs.get("ticket_id")
        return {"ok": True, "harvested": True, "ticket_id": kwargs.get("ticket_id")}

    monkeypatch.setattr(dispatch_legacy, "dispatch_result", fake_dispatch_result)
    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "interaction_required",
            "status": "running",
            "next": {
                "action_id": "bind_init",
                "execution_kind": "subagent",
                "actor_id": "tg-analyst",
            },
        },
    )
    assert seen.get("ticket_id") == tid
    assert out.get("ticket_id") == tid or seen.get("ticket_id") == tid
    assert not (parts / "merged.md").is_file()
    ids = {p.stem for p in (tmp_path / ".ascendc-pilot").rglob("dxt_*.yaml")}
    assert ids == {tid}


def test_harvest_bind_yaml_partial_then_complete(tmp_path: Path, monkeypatch) -> None:
    """One slice already on disk (rework-like); writing the other reaches count-complete."""
    from ascendc_pilot.actions import dispatch_legacy
    from ascendc_pilot.actions.dispatch import attach_host_step

    ticket, _run_id, sdir = _issue_bind_pair_with_state_run(tmp_path)
    tid = str(ticket["ticket_id"])
    parts = sdir / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    (parts / "bind.yaml").write_text("columns: [{name: B}]\n", encoding="utf-8")
    first = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "interaction_required",
            "status": "running",
            "next": {
                "action_id": "bind_init",
                "execution_kind": "subagent",
                "actor_id": "tg-analyst",
            },
        },
    )
    assert first.get("dispatch_ticket") == tid
    remaining = (first.get("host_step") or {}).get("remaining_slices") or first.get(
        "remaining_slices"
    )
    assert remaining == ["harness"] or "harness" in str(remaining)
    (parts / "harness.yaml").write_text("golden: {status: match}\n", encoding="utf-8")

    seen: dict[str, Any] = {}

    def fake_dispatch_result(project_root, **kwargs):
        seen["ticket_id"] = kwargs.get("ticket_id")
        return {"ok": True, "harvested": True, "ticket_id": kwargs.get("ticket_id")}

    monkeypatch.setattr(dispatch_legacy, "dispatch_result", fake_dispatch_result)
    second = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "interaction_required",
            "status": "running",
            "next": {
                "action_id": "bind_init",
                "execution_kind": "subagent",
                "actor_id": "tg-analyst",
            },
        },
    )
    assert seen.get("ticket_id") == tid
    ids = {p.stem for p in (tmp_path / ".ascendc-pilot").rglob("dxt_*.yaml")}
    assert ids == {tid}
    assert second.get("host_step", {}).get("kind") != "failed"
