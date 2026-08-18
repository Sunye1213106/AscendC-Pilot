"""Task Harness: LLM intake, Task Plan, Todo projection, scope, workspace."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ascendc_pilot.harness.intent import validate_intent_staging
from ascendc_pilot.human_confirm import hosted_confirm_should_ask
from ascendc_pilot.planning.task_plan import plan_for, write_task_plan
from ascendc_pilot.state import start_workflow
from ascendc_pilot.todo import build_todo
from ascendc_pilot.user_goal import create_user_goal
from ascendc_pilot.workflows import list_user_workflows, resolve_workflow_id


def test_intent_source_is_not_capability() -> None:
    url = "https://github.com/org/ops-transformer/pull/12"
    checked = validate_intent_staging(
        {
            "objective_zh": "为这个 PR 生成针对性测试用例",
            "source": {"kind": "pull_request", "url": url},
            "needed_capabilities": ["knowledge", "change_analysis", "test_generation"],
        }
    )
    assert checked["ok"] is True
    intent = checked["intent"]
    assert intent["source"]["kind"] == "pull_request"
    assert intent["source"]["url"] == url
    assert "code_review" not in intent["needed_capabilities"]
    assert "test_generation" in intent["needed_capabilities"]


def test_unknown_capability_rejected() -> None:
    checked = validate_intent_staging(
        {"objective_zh": "x", "needed_capabilities": ["teleport"], "source": {"kind": "none"}}
    )
    assert checked["ok"] is False
    assert checked["error"] == "UNKNOWN_CAPABILITY"


def test_disallowed_pr_host_rejected() -> None:
    checked = validate_intent_staging(
        {
            "objective_zh": "生成 case",
            "needed_capabilities": ["test_generation"],
            "source": {"kind": "pull_request", "url": "https://evil.example/a/b/pull/1"},
        }
    )
    assert checked["ok"] is False
    assert checked["error"] == "PR_HOST_NOT_ALLOWED"


def test_plan_for_test_generation_not_ce_review() -> None:
    planned = plan_for(
        {
            "needed_capabilities": ["knowledge", "change_analysis", "test_generation"],
            "source": {"kind": "pull_request", "url": "https://gitcode.com/a/b/pulls/1"},
        },
        {"has_uo": False, "uo_stale": False},
    )
    wids = [str(s.get("workflow_id") or s.get("id")) for s in planned["steps"]]
    assert "ce-review" not in wids
    assert "uo-init" in wids
    assert "goal-impact" in wids
    assert "tg-init" in wids and "tg-plan" in wids and "tg-solve" in wids


def test_code_review_capability_still_expands_ce_review() -> None:
    planned = plan_for(
        {"needed_capabilities": ["knowledge", "code_review"], "source": {"kind": "local"}},
        {"has_uo": True},
    )
    wids = [str(s.get("workflow_id") or s.get("id")) for s in planned["steps"]]
    assert "ce-review" in wids


def test_auto_alias_and_slash_preserved() -> None:
    assert resolve_workflow_id("auto") == "goal-intake"
    users = list_user_workflows()
    for wid in ("uo-init", "tg-init", "tg-plan", "tg-solve", "ce-review", "ce-plan", "ce-apply"):
        assert wid in users
    assert "goal-intake" not in users
    assert "auto" not in users


def test_todo_uses_public_plan(tmp_path: Path) -> None:
    llm = {
        "objective_zh": "生成针对性测试用例",
        "needed_capabilities": ["knowledge", "change_analysis", "test_generation"],
        "source": {"kind": "local"},
    }
    create_user_goal(tmp_path, intent_text="帮我生成对应 case", llm_intent=llm, architecture="goal")
    write_task_plan(tmp_path, plan_for(llm, {"has_uo": False}))
    start_workflow(tmp_path, "auto", intent="帮我生成对应 case")
    board = build_todo(tmp_path)
    contents = [it["content"] for it in board["native_items"]]
    assert "获取 PR 与代码" in contents or "分析改动影响" in contents or "建立算子理解" in contents
    assert all("确认进入规划" not in c for c in contents)
    in_prog = [it for it in board["native_items"] if it["status"] == "in_progress"]
    assert len(in_prog) <= 1


def test_tg_confirms_do_not_ask(tmp_path: Path) -> None:
    start_workflow(
        tmp_path,
        "tg-init",
        phase="confirm",
        force_phase=True,
        architecture="arch35",
        intent="只绑定测试脚本",
    )
    from ascendc_pilot.state import load_state

    state = load_state(tmp_path) or {}
    assert hosted_confirm_should_ask(tmp_path, state, action_id="human_confirm") is False
    state["workflow_id"] = "tg-plan"
    assert hosted_confirm_should_ask(tmp_path, state, action_id="plan_approve") is False


def test_scope_receipt_roundtrip(tmp_path: Path) -> None:
    from ascendc_pilot.human_confirm import _identity, _materialize_test_scope
    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.user_goal import load_user_goal

    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "goal-impact", architecture="arch35", intent="scope")
    create_user_goal(
        tmp_path,
        intent_text="生成 case",
        llm_intent={
            "objective_zh": "生成 case",
            "needed_capabilities": ["test_generation"],
            "source": {"kind": "local"},
        },
        architecture="arch35",
    )
    from ascendc_pilot.state import load_state

    state = load_state(tmp_path) or {}
    identity = _identity(
        {
            "run_id": state.get("run_id"),
            "workflow_id": "goal-impact",
            "action_id": "test_scope",
            "human_decision_value": "pr_targeted",
        }
    )
    identity["human_decision_value"] = "pr_targeted"
    out = _materialize_test_scope(tmp_path, state, identity, "2026-01-01T00:00:00Z")
    assert out.get("ok") is True
    goal = load_user_goal(tmp_path) or {}
    receipt = (goal.get("artifacts") or {}).get("scope_decision") or {}
    assert receipt.get("value") == "pr_targeted"
    assert receipt.get("digest")


def test_git_workspace_local_mirror(tmp_path: Path, monkeypatch) -> None:
    import sys

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # noqa: WPS433

    src = tmp_path / "src"
    src.mkdir()
    (src / "op_host").mkdir()
    (src / "op_kernel").mkdir()
    (src / "README.md").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=src, check=True, capture_output=True)
    (src / "README.md").write_text("two\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "change"], cwd=src, check=True, capture_output=True)

    cache = tmp_path / "cache"
    monkeypatch.setenv("ASCENDC_WORKSPACE_CACHE", str(cache))
    mirror = gw.ensure_bare_mirror(str(src), host="local", owner="t", repo="op")
    assert mirror.get("ok") is True
    files = gw.changed_files(Path(mirror["path"]), "HEAD~1", "HEAD")
    roots = gw.detect_operator_roots(src, ["README.md", "op_host/x.cpp"])
    assert src in roots or any(p == src for p in roots)


def test_reconcile_drops_dtype(tmp_path: Path) -> None:
    from ascendc_pilot.planning.reconcile import apply_revision
    from ascendc_pilot.planning.task_plan import plan_for, write_task_plan
    from ascendc_pilot.user_goal import load_user_goal

    llm = {
        "objective_zh": "生成 case",
        "needed_capabilities": ["test_generation"],
        "source": {"kind": "local"},
        "constraints": {},
    }
    create_user_goal(tmp_path, intent_text="生成 case", llm_intent=llm)
    write_task_plan(tmp_path, plan_for(llm, {"has_uo": True}))
    out = apply_revision(tmp_path, delta_text="不要 fp32")
    assert out.get("revised") is True
    goal = load_user_goal(tmp_path) or {}
    assert "fp32" in (goal.get("constraints") or {}).get("exclude_dtype", [])
