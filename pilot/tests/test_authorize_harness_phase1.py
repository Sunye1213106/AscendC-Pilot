"""Phase1 harness: Agent ∩ Lease ∩ forbidden ∩ TOOL_UNKNOWN fail-closed."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.authorize import authorize
from ascendc_pilot.authorize.lease import issue_action_lease, lease_path
from ascendc_pilot.paths import agent_root, ensure_agent_layout
from ascendc_pilot.state import start_workflow


def test_readonly_agent_cannot_write_state(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "uo-query", phase="answer", force_phase=True)
    target = agent_root(op) / "state" / "workflow.yaml"
    verdict = authorize(
        op,
        tool="write",
        path=str(target),
        agent="uo-query",
        action="",
    )
    assert verdict.get("decision") == "deny"
    assert verdict.get("reason_code") == "FORBIDDEN_MODIFY_PILOT_STATE"


def test_uo_query_cannot_write_uo_product(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "uo-query", phase="answer", force_phase=True)
    target = agent_root(op) / "uo" / "summary" / "overview.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    verdict = authorize(
        op,
        tool="write",
        path=str(target),
        agent="uo-query",
        action="",
    )
    assert verdict.get("decision") == "deny"
    assert verdict.get("reason_code") in {
        "FORBIDDEN_MODIFY_UO_PRODUCT",
        "AGENT_WRITE_SCOPE",
    }


def test_producer_write_outside_lease_denied(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "tg-solve", phase="lemma", force_phase=True)
    issue_action_lease(
        op,
        action_id="lemma_mine",
        actor_id="tg-lemma-producer",
        allowed_write_paths=["runs/{run_id}/actions/lemma_mine/parts/**"],
    )
    outside = agent_root(op) / "tg" / "closure" / "lemmas" / "active_rules.yaml"
    outside.parent.mkdir(parents=True, exist_ok=True)
    verdict = authorize(
        op,
        tool="write",
        path=str(outside),
        agent="tg-lemma-producer",
        action="lemma_mine",
    )
    assert verdict.get("decision") == "deny"
    assert verdict.get("reason_code") in {
        "ACTION_WRITE_SCOPE_DENIED",
        "AGENT_WRITE_SCOPE",
        "FORBIDDEN_MODIFY_UO_PRODUCT",
    }


def test_producer_write_inside_lease_allowed(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "tg-solve", phase="lemma", force_phase=True)
    rel = "runs/x/actions/lemma_mine/parts/part_001.yaml"
    issue_action_lease(
        op,
        action_id="lemma_mine",
        actor_id="tg-lemma-producer",
        allowed_write_paths=[rel],
    )
    target = agent_root(op) / Path(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Ensure agent YAML is discoverable from the repo under test.
    agents_src = Path(__file__).resolve().parents[2] / "agents" / "tg-lemma-producer.yaml"
    if agents_src.is_file():
        dest = op / "agents"
        dest.mkdir(exist_ok=True)
        (dest / "tg-lemma-producer.yaml").write_text(
            agents_src.read_text(encoding="utf-8"), encoding="utf-8"
        )
    verdict = authorize(
        op,
        tool="write",
        path=str(target),
        agent="tg-lemma-producer",
        action="lemma_mine",
    )
    assert verdict.get("decision") == "allow", verdict


def test_referee_cannot_write_producer_path(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "tg-solve", phase="audit", force_phase=True)
    target = agent_root(op) / "runs" / "x" / "actions" / "lemma_mine" / "parts" / "part_001.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    verdict = authorize(
        op,
        tool="write",
        path=str(target),
        agent="tg-closure-referee",
        action="closure_audit",
    )
    assert verdict.get("decision") == "deny"
    assert verdict.get("reason_code") in {
        "AGENT_WRITE_SCOPE",
        "REFEREE_WRITE_SCOPE",
        "ACTION_WRITE_SCOPE_DENIED",
    }


def test_unknown_tool_denied_for_pilot_agent(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "uo-query", phase="answer", force_phase=True)
    verdict = authorize(
        op,
        tool="filesystem_write_v2",
        path=str(agent_root(op) / "runs" / "scratch" / "x.txt"),
        agent="uo-query",
    )
    assert verdict.get("decision") == "deny"
    assert verdict.get("reason_code") == "TOOL_UNKNOWN"


def test_stale_lease_run_mismatch_denied(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "tg-solve", phase="lemma", force_phase=True)
    issue_action_lease(
        op,
        action_id="lemma_mine",
        actor_id="tg-lemma-producer",
        allowed_write_paths=["runs/**/actions/lemma_mine/**"],
    )
    lp = lease_path(op)
    lease = yaml.safe_load(lp.read_text(encoding="utf-8"))
    lease["run_id"] = "STALE_RUN"
    lp.write_text(yaml.safe_dump(lease, allow_unicode=True), encoding="utf-8")
    target = (
        agent_root(op) / "runs" / "x" / "actions" / "lemma_mine" / "parts" / "part_001.yaml"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    verdict = authorize(
        op,
        tool="write",
        path=str(target),
        agent="tg-lemma-producer",
        action="lemma_mine",
    )
    assert verdict.get("decision") == "deny"
    assert verdict.get("reason_code") == "ACTION_RUN_MISMATCH"


def test_declare_workflow_passed_bash_forbidden(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op)
    start_workflow(op, "uo-query", phase="answer", force_phase=True)
    verdict = authorize(
        op,
        tool="bash",
        command="acp complete --passed",
        agent="uo-query",
    )
    assert verdict.get("decision") == "deny"
