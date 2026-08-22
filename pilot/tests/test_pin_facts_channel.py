"""Pin facts belong on this-run state and host_step, not a Host-folder glob."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.actions.dispatch import attach_host_step
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import complete_workflow, load_state, save_state, start_workflow


def _operator(root: Path) -> Path:
    op = root / "worktree" / "attention" / "demo_op"
    (op / "op_host" / "arch0").mkdir(parents=True)
    (op / "op_kernel" / "arch0").mkdir(parents=True)
    return op


def test_attach_host_step_done_surfaces_pin_facts(tmp_path: Path) -> None:
    host = tmp_path / "host"
    host.mkdir()
    op = _operator(tmp_path)
    changed = ["attention/demo_op/op_kernel/arch0/kernel.cpp"]
    pin_zh = (
        f"已获取 PR 代码。changed-files 已唯一确定算子 `{op.name}`、"
        f"architecture `arch0`。后续 `pilot_run` 使用该 `--project` 与 `--architecture`。"
    )
    out = attach_host_step(
        host,
        {
            "ok": True,
            "stop_reason": "workflow_complete",
            "status": "passed",
            "complete": {
                "message_zh": pin_zh,
                "user_goal_next_project": str(op),
                "user_goal_next_architecture": "arch0",
                "selected_by": "pr_changed_files",
                "changed_files": changed,
                "project": str(op),
                "architecture": "arch0",
                "state": {"workflow_id": "goal-intake", "architecture": "goal"},
            },
        },
    )
    step = out.get("host_step") or {}
    assert step.get("kind") == "done"
    assert step.get("project") == str(op)
    assert step.get("architecture") == "arch0"
    assert step.get("selected_by") == "pr_changed_files"
    preview = step.get("changed_files_preview") or step.get("changed_files")
    assert changed[0] in list(preview or [])
    assert op.name in str(step.get("message_zh") or "")
    assert "arch0" in str(step.get("message_zh") or "")
    assert "工作流已完成" in str(step.get("message_zh") or "") or pin_zh in str(
        step.get("message_zh") or ""
    )


def test_complete_workflow_reads_pin_from_run_state_not_clone_receipts(tmp_path: Path) -> None:
    host = tmp_path / "host"
    host.mkdir()
    op = _operator(tmp_path)
    ensure_agent_layout(host, arch="goal")
    start_workflow(host, "auto", intent="生成 case", architecture="goal")
    st = load_state(host)
    st["next_project"] = str(op)
    st["next_architecture"] = "arch0"
    st["selected_by"] = "pr_changed_files"
    st["changed_files"] = ["attention/demo_op/op_kernel/arch0/kernel.cpp"]
    st["pin_message_zh"] = (
        f"已获取 PR 代码。changed-files 已唯一确定算子 `{op.name}`、"
        "architecture `arch0`。"
    )
    save_state(host, st)

    payload = complete_workflow(host)
    assert payload.get("ok") is True
    assert payload.get("status") == "passed"
    assert str(payload.get("user_goal_next_project") or payload.get("project") or "") == str(op)
    assert str(payload.get("user_goal_next_architecture") or payload.get("architecture") or "") == "arch0"
    assert payload.get("selected_by") == "pr_changed_files"
    assert "demo_op" in str(payload.get("message_zh") or "")
    assert "arch0" in str(payload.get("message_zh") or "")
    done = "工作流已完成"
    msg = str(payload.get("message_zh") or "")
    if done in msg:
        assert msg.index("demo_op") < msg.index(done)


def test_complete_workflow_already_complete_keeps_pin(tmp_path: Path) -> None:
    host = tmp_path / "host"
    host.mkdir()
    op = _operator(tmp_path)
    ensure_agent_layout(host, arch="goal")
    start_workflow(host, "auto", intent="生成 case", architecture="goal")
    st = load_state(host)
    st["status"] = "passed"
    st["next_project"] = str(op)
    st["next_architecture"] = "arch0"
    st["selected_by"] = "pr_changed_files"
    st["changed_files"] = ["attention/demo_op/op_kernel/arch0/kernel.cpp"]
    st["pin_message_zh"] = (
        f"已获取 PR 代码。changed-files 已唯一确定算子 `{op.name}`、"
        "architecture `arch0`。"
    )
    save_state(host, st)
    payload = complete_workflow(host)
    assert payload.get("already_complete") is True
    assert "demo_op" in str(payload.get("message_zh") or "")
    assert payload.get("selected_by") == "pr_changed_files"


def test_clone_only_unique_pin_writes_host_run_state(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions import goal_engines
    from ascendc_pilot.actions.goal_engines import run_intent_promote

    host = tmp_path / "host"
    host.mkdir()
    op = _operator(tmp_path)

    class FakeWorkspace:
        @staticmethod
        def acquire_pull_request(*_a, **_k) -> dict:
            return {
                "ok": True,
                "operator_roots": [str(op)],
                "operator_targets": [
                    {
                        "operator_root": str(op),
                        "operator_name": op.name,
                        "architecture": "arch0",
                    }
                ],
                "changed_files": ["attention/demo_op/op_kernel/arch0/kernel.cpp"],
                "worktree_head": str(op),
                "changeset": {
                    "changed_files": ["attention/demo_op/op_kernel/arch0/kernel.cpp"]
                },
            }

        @staticmethod
        def resolve_targets_or_ask(acquire: dict, **kwargs: object) -> dict:
            del kwargs
            return {
                "ok": True,
                "project": str(op),
                "architecture": "arch0",
                "operator_roots": acquire.get("operator_roots") or [],
                "operator_targets": acquire.get("operator_targets") or [],
                "changed_files": acquire.get("changed_files") or [],
                "worktree_head": str(op),
            }

    monkeypatch.setattr(goal_engines, "_git_workspace", lambda: FakeWorkspace)
    state = start_workflow(host, "auto", intent="生成 case", architecture="goal")
    rid = str(state.get("run_id") or "")
    staging = (
        Path(host)
        / ".ascendc-pilot"
        / "goal"
        / "runs"
        / rid
        / "actions"
        / "intent_promote"
        / "staging.yaml"
    )
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_text(
        yaml.safe_dump(
            {
                "intent_text": "为这个 PR 生成针对性测试用例",
                "objective_zh": "为这个 PR 生成针对性测试用例",
                "source": {
                    "kind": "pull_request",
                    "url": "https://example.test/org/repo/pull/1",
                },
                "needed_capabilities": ["knowledge", "change_analysis", "test_generation"],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    out = run_intent_promote(host, {"run_id": rid, "architecture": "goal", "intent": "生成 case"})
    assert out.get("ok") is True
    assert out.get("selected_by") == "pr_changed_files"
    st = load_state(host)
    assert str(st.get("next_project") or "") == str(op)
    assert st.get("next_architecture") == "arch0"
    assert st.get("selected_by") == "pr_changed_files"
    assert "kernel.cpp" in str(st.get("changed_files") or [])
