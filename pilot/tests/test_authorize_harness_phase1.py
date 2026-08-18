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
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-query", phase="answer", force_phase=True, architecture="arch35")
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
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-query", phase="answer", force_phase=True, architecture="arch35")
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
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "tg-solve", phase="construct", force_phase=True, architecture="arch35")
    issue_action_lease(
        op,
        action_id="construct_cases",
        actor_id="tg-analyst",
        allowed_write_paths=["runs/{run_id}/actions/construct_cases/parts/**"],
    )
    outside = agent_root(op) / "tg" / "init.yaml"
    outside.parent.mkdir(parents=True, exist_ok=True)
    verdict = authorize(
        op,
        tool="write",
        path=str(outside),
        agent="tg-analyst",
        action="construct_cases",
    )
    assert verdict.get("decision") == "deny"
    assert verdict.get("reason_code") in {
        "ACTION_WRITE_SCOPE_DENIED",
        "AGENT_WRITE_SCOPE",
        "FORBIDDEN_MODIFY_UO_PRODUCT",
        "FORBIDDEN_WRITE_UO_FORMAL_PRODUCTS",
    }


def test_producer_write_inside_lease_allowed(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "tg-solve", phase="construct", force_phase=True, architecture="arch35")
    rel = "runs/x/actions/construct_cases/parts/part_001.yaml"
    issue_action_lease(
        op,
        action_id="construct_cases",
        actor_id="tg-analyst",
        allowed_write_paths=[rel],
    )
    target = agent_root(op) / Path(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Ensure agent YAML is discoverable from the repo under test.
    agents_src = Path(__file__).resolve().parents[2] / "agents" / "tg-analyst.yaml"
    if agents_src.is_file():
        dest = op / "agents"
        dest.mkdir(exist_ok=True)
        (dest / "tg-analyst.yaml").write_text(
            agents_src.read_text(encoding="utf-8"), encoding="utf-8"
        )
    verdict = authorize(
        op,
        tool="write",
        path=str(target),
        agent="tg-analyst",
        action="construct_cases",
    )
    assert verdict.get("decision") == "allow", verdict


def test_referee_cannot_write_producer_path(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "tg-solve", phase="analyze", force_phase=True, architecture="arch35")
    target = agent_root(op) / "runs" / "x" / "actions" / "construct_cases" / "parts" / "part_001.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    verdict = authorize(
        op,
        tool="write",
        path=str(target),
        agent="ce-reviewer",
        action="code_review",
    )
    assert verdict.get("decision") == "deny"
    assert verdict.get("reason_code") in {
        "AGENT_WRITE_SCOPE",
        "REFEREE_WRITE_SCOPE",
        "ACTION_WRITE_SCOPE_DENIED",
        "ACTION_NOT_ALLOWED",
    }


def test_unknown_tool_denied_for_pilot_agent(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-query", phase="answer", force_phase=True, architecture="arch35")
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
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "tg-solve", phase="construct", force_phase=True, architecture="arch35")
    issue_action_lease(
        op,
        action_id="construct_cases",
        actor_id="tg-analyst",
        allowed_write_paths=["runs/**/actions/construct_cases/**"],
    )
    lp = lease_path(op)
    lease = yaml.safe_load(lp.read_text(encoding="utf-8"))
    lease["run_id"] = "STALE_RUN"
    lp.write_text(yaml.safe_dump(lease, allow_unicode=True), encoding="utf-8")
    target = (
        agent_root(op) / "runs" / "x" / "actions" / "construct_cases" / "parts" / "part_001.yaml"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    verdict = authorize(
        op,
        tool="write",
        path=str(target),
        agent="tg-analyst",
        action="construct_cases",
    )
    assert verdict.get("decision") == "deny"
    assert verdict.get("reason_code") == "ACTION_RUN_MISMATCH"


def test_declare_workflow_passed_bash_forbidden(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-query", phase="answer", force_phase=True, architecture="arch35")
    verdict = authorize(
        op,
        tool="bash",
        command="acp complete --passed",
        agent="uo-query",
    )
    assert verdict.get("decision") == "deny"


def test_uo_query_denies_repo_grep_escape(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-query", phase="answer", force_phase=True, architecture="arch35")
    for cmd in (
        'findstr /S "ARGS_SEL" *.h',
        'grep -r "fusedOuter" .',
        'rg "DTemplateNum" op_kernel',
    ):
        verdict = authorize(op, tool="bash", command=cmd, agent="uo-query", action="kb_lookup")
        assert verdict.get("decision") == "deny", (cmd, verdict)
        assert verdict.get("reason_code") == "REPO_GREP_ESCAPE", (cmd, verdict)
    grep_tool = authorize(op, tool="grep", command="", agent="uo-query", action="kb_lookup")
    assert grep_tool.get("decision") == "deny"
    assert grep_tool.get("reason_code") == "REPO_GREP_ESCAPE"
    listing = authorize(
        op, tool="bash", command="pwd", agent="uo-query", action="kb_lookup"
    )
    assert listing.get("decision") == "allow"


def test_skill_allowed_for_primary_denied_for_uo_query(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-query", phase="answer", force_phase=True, architecture="arch35")
    primary = authorize(op, tool="skill", command="uo-init", agent="ascendc-pilot")
    assert primary.get("decision") == "allow", primary
    assert primary.get("reason_code") == "SKILL_PRIMARY"
    child = authorize(op, tool="skill", command="operator-analysis", agent="uo-query", action="kb_lookup")
    assert child.get("decision") == "deny", child
    assert child.get("reason_code") == "SKILL_SUBAGENT_ESCAPE"


def test_acp_stdout_pipe_denied_findstr_pipe_allowed_for_primary(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    piped = authorize(
        op,
        tool="bash",
        command="acp uo-query --mode locate --pattern foo | Select-Object -Last 20",
        agent="ascendc-pilot",
    )
    assert piped.get("decision") == "deny", piped
    assert piped.get("reason_code") == "ACP_PIPE_BUFFER"
    locate = authorize(
        op,
        tool="bash",
        command='findstr /I /N "IS_FP32_INPUT" op_kernel\\x.h | Select-Object -First 15',
        agent="ascendc-pilot",
    )
    assert locate.get("decision") == "allow", locate
    assert locate.get("reason_code") == "BASH_READONLY_INSPECT"
    chained = authorize(
        op,
        tool="bash",
        command="cd D:\\op && acp status --project D:\\op",
        agent="ascendc-pilot",
    )
    assert chained.get("decision") == "allow", chained
    assert chained.get("reason_code") in {"HARNESS_CLI", "HARNESS_START"}
