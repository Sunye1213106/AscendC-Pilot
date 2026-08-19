from __future__ import annotations

import json
from pathlib import Path

import pytest

from ascendc_pilot.planning.task_plan import current_workflow_id, load_task_plan
from ascendc_pilot.user_goal import load_user_goal


def _operator(root: Path) -> Path:
    op = root / "repo" / "attention" / "demo_op"
    (op / "op_host" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    return op


def test_pr_goal_promote_persists_plan_and_marks_workspace_acquired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ascendc_pilot.actions import goal_engines

    host = tmp_path / "host"
    host.mkdir()
    op = _operator(tmp_path)

    class FakeWorkspace:
        @staticmethod
        def acquire_pull_request(url: str, **_: object) -> dict[str, object]:
            del url
            return {
                "ok": True,
                "workspace_mode": "isolated_pr",
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
                "diff_digest": "deadbeef",
                "changed_files": ["attention/demo_op/op_kernel/arch35/kernel.cpp"],
                "operator_roots": [str(op)],
                "architectures": ["arch35"],
                "changed_architectures": ["arch35"],
                "operator_targets": [
                    {
                        "operator_root": str(op),
                        "operator_name": "demo_op",
                        "architecture": "arch35",
                    }
                ],
                "worktree_head": str(op),
                "changeset": {
                    "schema": "pilot-changeset/v1",
                    "base_sha": "a" * 40,
                    "head_sha": "b" * 40,
                    "diff_digest": "deadbeef",
                    "changed_files": ["attention/demo_op/op_kernel/arch35/kernel.cpp"],
                },
            }

        @staticmethod
        def resolve_targets_or_ask(acquire: dict, **_: object) -> dict:
            return {
                "ok": True,
                "project": str(op),
                "architecture": "arch35",
                "operator_roots": [str(op)],
                "operator_targets": acquire.get("operator_targets") or [],
                "worktree_head": str(op),
                "changeset": acquire.get("changeset") or {},
            }

    monkeypatch.setattr(goal_engines, "_git_workspace", lambda: FakeWorkspace)
    contract = {
        "schema": "pilot-goal-contract/v1",
        "user_text": "分析 PR 并生成对应测试用例",
        "objective_zh": "按 PR 影响范围生成可执行测试用例",
        "source": {"kind": "pull_request", "url": "https://github.com/acme/ops/pull/7"},
        "needed_workflows": ["tg-solve"],
        "constraints": {"test_script_root": str(tmp_path / "tests_repo")},
    }
    ctx = {
        "run_id": "RUN_goal",
        "architecture": "goal",
        "intent": json.dumps(contract, ensure_ascii=False),
    }
    out = goal_engines.run_intent_promote(host, ctx)
    assert out["ok"] is True
    assert out["next_workflow_id"] == "uo-init"
    assert Path(str(out["project"])).resolve() == op.resolve()

    plan = load_task_plan(op)
    assert plan is not None
    steps = plan["steps"]
    assert [s["id"] for s in steps] == [
        "workspace_acquire",
        "uo-init",
        "ce-review",
        "tg-init",
        "tg-plan",
        "tg-solve",
    ]
    assert steps[0]["status"] == "passed"
    assert current_workflow_id(plan) == "uo-init"

    goal = load_user_goal(op)
    assert goal is not None
    assert goal["project"] == op.as_posix()
    assert goal["architecture"] == "arch35"
    assert goal["source"]["head_sha"] == "b" * 40
    assert goal["constraints"]["test_script_root"] == str(tmp_path / "tests_repo")

    # Empty Host cwd is only a clone anchor; control plane stays on the operator.
    assert load_task_plan(host) is None
    assert load_user_goal(host) is None
    assert not (host / ".ascendc-pilot").exists()


def test_review_completion_writes_planning_context(tmp_path: Path) -> None:
    from ascendc_pilot import user_goal

    op = _operator(tmp_path)
    review = (
        op
        / ".ascendc-pilot"
        / "arch35"
        / "runs"
        / "RUN_review"
        / "actions"
        / "code_review"
        / "parts"
    )
    review.mkdir(parents=True)
    (review / "spec.md").write_text("changed_scope: host branch\naffected_scope: tiling key\n", encoding="utf-8")
    (review / "standards.md").write_text("risks: boundary regression\nvalidation_targets: replay branch\n", encoding="utf-8")

    goal = {
        "schema": "pilot-user-goal/v2",
        "status": "active",
        "architecture": "arch35",
        "artifacts": {},
    }
    state = {"architecture": "arch35", "run_id": "RUN_review"}
    got = user_goal._capture_review_planning_context(op, goal, state)
    path = Path(got["artifacts"]["review_planning_context"])
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "changed_scope: host branch" in text
    assert "validation_targets: replay branch" in text
    assert got["artifacts"]["review_report"]["status"] == "delivered"
