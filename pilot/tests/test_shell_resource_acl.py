"""Shell reads must obey the same Action lease ACL the Read tool obeys.

A tool-level fence is a fence a window walks around with `Get-Content` the
moment `Read` is denied, without ever intending to evade.
"""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.authorize.lease import (
    issue_action_lease,
    lease_authorizes_actor,
)
from ascendc_pilot.authorize.shell_read import extract_read_paths, shell_read_denial
from ascendc_pilot.state import start_workflow


def _lease(op: Path, *, forbid: list[str], allow: list[str]) -> dict:
    return issue_action_lease(
        op,
        action_id="bind_init",
        actor_id="tg-analyst",
        allowed_read_paths=allow,
        forbidden_read_paths=forbid,
    )


def test_extract_read_paths_covers_content_emitters() -> None:
    assert extract_read_paths(
        "Get-Content D:/op/.ascendc-pilot/runs/R/actions/a/parts/bind.yaml"
    ) == ["D:/op/.ascendc-pilot/runs/R/actions/a/parts/bind.yaml"]
    assert extract_read_paths("cat runs/R/receipts/plan_scope_packet.yaml") == [
        "runs/R/receipts/plan_scope_packet.yaml"
    ]
    assert extract_read_paths("git show HEAD:tiling/deter.h") == ["tiling/deter.h"]
    # Directory listing leaks no artifact body.
    assert extract_read_paths("Get-ChildItem D:/op/.ascendc-pilot/runs") == []
    # Pipe stages are inspected too, not just the head.
    assert "runs/R/actions/a/parts/bind.yaml" in extract_read_paths(
        "cd D:/op ; Select-String -Path runs/R/actions/a/parts/bind.yaml -Pattern foo"
    )


def test_forbidden_sibling_part_is_denied_through_shell(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    start_workflow(op, "tg-init", phase="bind", force_phase=True, architecture="arch35")
    forbid = ["runs/RUN_T/actions/bind_init/parts/bind.yaml"]
    lease = _lease(op, forbid=forbid, allow=["runs/RUN_T/actions/bind_init/**"])

    denied = shell_read_denial(
        "Get-Content "
        + (op / ".ascendc-pilot/runs/RUN_T/actions/bind_init/parts/bind.yaml").as_posix(),
        lease=lease,
        project_root=op,
        agent="tg-analyst",
    )
    assert denied is not None
    assert denied["error"] == "ACTION_FORBIDDEN_READ_PATH"

    allowed = shell_read_denial(
        "Get-Content "
        + (op / ".ascendc-pilot/runs/RUN_T/actions/bind_init/prompt.md").as_posix(),
        lease=lease,
        project_root=op,
        agent="tg-analyst",
    )
    assert allowed is None


def test_operator_source_reads_stay_out_of_the_artifact_fence(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    start_workflow(op, "tg-init", phase="bind", force_phase=True, architecture="arch35")
    lease = _lease(op, forbid=["runs/RUN_T/actions/bind_init/parts/bind.yaml"], allow=[])
    assert (
        shell_read_denial(
            "Get-Content op_host/deter.h",
            lease=lease,
            project_root=op,
            agent="tg-analyst",
        )
        is None
    )


def test_primary_review_delegate_reads_under_controller_lease(tmp_path: Path) -> None:
    """plan_ingest holds an ascendc-pilot lease but tg-analyst does the reading."""
    op = tmp_path / "DemoOp"
    op.mkdir()
    start_workflow(op, "tg-plan", phase="model", force_phase=True, architecture="arch35")
    lease = issue_action_lease(
        op,
        action_id="plan_ingest",
        actor_id="ascendc-pilot",
        allowed_read_paths=["runs/RUN_T/actions/plan_ingest/**"],
        delegate_actor_ids=["tg-analyst"],
    )
    assert lease_authorizes_actor(lease, "tg-analyst")
    assert lease_authorizes_actor(lease, "ascendc-pilot")
    assert lease_authorizes_actor(lease, "uo-semantic-resolve") is False


def test_plan_ingest_spec_declares_its_owner_window() -> None:
    """The delegate must come from the Spec, not from a runtime guess."""
    from ascendc_pilot.actions.runtime import _delegate_actors
    from ascendc_pilot.workflows import action_by_id

    action = action_by_id("tg-plan", "plan_ingest")
    assert action.get("delegate_actor_ids") == ["tg-analyst"]
    assert _delegate_actors(action, "primary_review", workflow_id="tg-plan") == [
        "tg-analyst"
    ]
    # Subagent actions keep their own lease; nothing is delegated.
    assert _delegate_actors(action, "subagent", workflow_id="tg-plan") == []


def test_lease_without_delegates_keeps_owner_only(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    start_workflow(op, "tg-init", phase="bind", force_phase=True, architecture="arch35")
    lease = issue_action_lease(op, action_id="bind_init", actor_id="tg-analyst")
    assert lease_authorizes_actor(lease, "tg-analyst")
    assert lease_authorizes_actor(lease, "ascendc-pilot") is False
