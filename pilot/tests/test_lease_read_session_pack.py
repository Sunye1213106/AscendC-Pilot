"""ses_062d: producer must read session pack + IR parent dirs under lease."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.authorize.lease import (
    issue_action_lease,
    lease_allows_read_path,
)
from ascendc_pilot.actions.runtime import _build_task_prompt_stub
from ascendc_pilot.state import start_workflow


def test_lease_allows_session_pack_via_roots_and_pattern(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    start_workflow(op, "uo-init", phase="extract", force_phase=True)
    run_id = "RUN_T"
    sdir = op / ".ascendc-pilot" / "runs" / run_id / "actions" / "extract_plan"
    sdir.mkdir(parents=True)
    lease = issue_action_lease(
        op,
        action_id="extract_plan",
        actor_id="uo-semantic-resolve",
        allowed_read_paths=[
            f"runs/{run_id}/actions/extract_plan/**",
            "uo/ir/extract_plan_candidates.yaml",
            "uo/ir/entrypoint_graph.yaml",
        ],
        allowed_read_roots=[sdir.as_posix()],
    )
    assert lease_allows_read_path(lease, f"runs/{run_id}/actions/extract_plan/prompt.md")["ok"]
    assert lease_allows_read_path(lease, f"runs/{run_id}/actions/extract_plan/method.md")["ok"]
    assert lease_allows_read_path(lease, "uo/ir/extract_plan_candidates.yaml")["ok"]
    assert lease_allows_read_path(lease, "uo/ir")["ok"]  # parent dir list/glob
    assert lease_allows_read_path(lease, "uo/ir/llm_tasks.yaml")["ok"] is False


def test_lease_roots_alone_allow_session_files(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    start_workflow(op, "uo-init", phase="extract", force_phase=True)
    sdir = op / ".ascendc-pilot" / "runs" / "RUN_T" / "actions" / "extract_plan"
    sdir.mkdir(parents=True)
    lease = issue_action_lease(
        op,
        action_id="extract_plan",
        actor_id="uo-semantic-resolve",
        allowed_read_paths=["uo/ir/extract_plan_candidates.yaml"],
        allowed_read_roots=[sdir.as_posix()],
    )
    assert lease_allows_read_path(lease, "runs/RUN_T/actions/extract_plan/prompt.md")["ok"]
    assert lease_allows_read_path(lease, "uo/ir/extract_plan_candidates.yaml")["ok"]
    # Still not a free pass on unrelated IR.
    assert lease_allows_read_path(lease, "uo/ir/llm_tasks.yaml")["ok"] is False


def test_lease_write_paths_are_always_readable(tmp_path: Path) -> None:
    """Global invariant: producer can Read back what the Action leased for Write."""
    op = tmp_path / "DemoOp"
    op.mkdir()
    start_workflow(op, "uo-init", phase="extract", force_phase=True)
    lease = issue_action_lease(
        op,
        action_id="extract_plan",
        actor_id="uo-semantic-resolve",
        allowed_read_paths=["uo/ir/extract_plan_candidates.yaml"],
        allowed_write_paths=["uo/ir/extract_plan.yaml"],
    )
    assert "uo/ir/extract_plan.yaml" in (lease.get("allowed_read_paths") or [])
    assert lease_allows_read_path(lease, "uo/ir/extract_plan.yaml")["ok"]
    assert lease_allows_read_path(lease, "uo/ir/extract_plan_candidates.yaml")["ok"]
    # Still deny unrelated IR not on the allow-list.
    assert lease_allows_read_path(lease, "uo/ir/llm_tasks.yaml")["ok"] is False


def test_stub_uses_absolute_read_paths_under_agent_root() -> None:
    stub = _build_task_prompt_stub(
        actor_id="uo-semantic-resolve",
        action_id="extract_plan",
        run_id="RUN_T",
        session_dir="D:/op/.ascendc-pilot/runs/RUN_T/actions/extract_plan",
        prompt_path="D:/op/.ascendc-pilot/runs/RUN_T/actions/extract_plan/prompt.md",
        method_path="D:/op/.ascendc-pilot/runs/RUN_T/actions/extract_plan/method.md",
        bundle_path="D:/op/.ascendc-pilot/runs/RUN_T/actions/extract_plan/bundle.yaml",
        dispatch_targets={
            "read": ["uo/ir/extract_plan_candidates.yaml", "uo/ir/entrypoint_graph.yaml"],
            "write": ["uo/ir/extract_plan.yaml"],
        },
        agent_root_path="D:/op/.ascendc-pilot",
    )
    assert "D:/op/.ascendc-pilot/uo/ir/extract_plan_candidates.yaml" in stub
    assert "read: uo/ir/extract_plan_candidates.yaml" not in stub
