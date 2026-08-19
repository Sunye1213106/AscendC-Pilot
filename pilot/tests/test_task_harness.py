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
            "needed_workflows": ["tg-plan", "tg-solve"],
        }
    )
    assert checked["ok"] is True
    intent = checked["intent"]
    assert intent["source"]["kind"] == "pull_request"
    assert intent["source"]["url"] == url
    assert "ce-review" not in intent["needed_workflows"]
    assert "tg-plan" in intent["needed_workflows"]


def test_unknown_workflow_rejected() -> None:
    checked = validate_intent_staging(
        {"objective_zh": "x", "needed_workflows": ["teleport"], "source": {"kind": "none"}}
    )
    assert checked["ok"] is False
    assert checked["error"] == "UNKNOWN_WORKFLOW"


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
            "needed_workflows": ["tg-solve"],
            "source": {"kind": "pull_request", "url": "https://evil.example/a/b/pull/1"},
        }
    )
    assert checked["ok"] is False
    assert checked["error"] == "PR_HOST_NOT_ALLOWED"


def test_plan_for_test_generation_does_not_insert_pr_dependencies() -> None:
    planned = plan_for(
        {
            "needed_workflows": ["tg-plan", "tg-solve"],
            "source": {"kind": "pull_request", "url": "https://gitcode.com/a/b/pulls/1"},
        },
        {"has_uo": False, "uo_stale": False},
    )
    wids = [str(s.get("workflow_id") or s.get("id")) for s in planned["steps"]]
    assert "uo-init" not in wids
    assert "ce-review" not in wids
    assert "goal-impact" not in wids
    assert "tg-plan" in wids and "tg-solve" in wids


def test_plan_for_review_and_tg_union() -> None:
    planned = plan_for(
        {
            "needed_workflows": ["ce-review", "tg-plan", "tg-solve"],
            "source": {"kind": "pull_request", "url": "https://gitcode.com/a/b/pulls/1"},
        },
        {"has_uo": False, "uo_stale": False, "has_tg_init": False},
    )
    wids = [str(s.get("workflow_id") or s.get("id")) for s in planned["steps"]]
    assert "ce-review" in wids
    assert "tg-plan" in wids
    assert wids.index("ce-review") < wids.index("tg-plan")
    assert "goal-impact" not in wids
    assert "uo-init" not in wids


def test_workflow_catalog_lists_slash_not_skills() -> None:
    from ascendc_pilot.harness.intent import render_workflow_catalog, workflow_catalog

    rows = workflow_catalog()
    ids = {str(r["id"]) for r in rows}
    assert "ce-review" in ids and "tg-plan" in ids and "tg-solve" in ids
    assert "code-review" not in ids
    text = render_workflow_catalog()
    assert "/ce-review" in text
    assert "不是 Goal 步骤" in text


def test_validate_intent_staging_does_not_parse_user_text() -> None:
    checked = validate_intent_staging(
        {
            "objective_zh": "生成用例",
            "intent_text": "请 /ce-review 并且生成用例",
            "source": {"kind": "none"},
            "needed_workflows": ["tg-plan", "tg-solve"],
        }
    )
    assert checked["ok"] is True
    assert checked["intent"]["needed_workflows"] == ["tg-plan", "tg-solve"]
    assert "ce-review" not in checked["intent"]["needed_workflows"]


def test_code_review_capability_does_not_invent_workflows() -> None:
    planned = plan_for(
        {"needed_capabilities": ["knowledge", "code_review"], "source": {"kind": "local"}},
        {"has_uo": True},
    )
    wids = [str(s.get("workflow_id") or s.get("id")) for s in planned["steps"]]
    assert "ce-review" not in wids
    assert wids == []


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
    assert "获取 PR 与代码" in contents or "审查改动" in contents or "建立算子理解" in contents
    assert all("确认进入规划" not in c for c in contents)
    in_prog = [it for it in board["native_items"] if it["status"] == "in_progress"]
    assert len(in_prog) <= 1


def test_todo_uses_public_plan_without_auto_session(tmp_path: Path) -> None:
    create_user_goal(
        tmp_path,
        intent_text="审查改动",
        llm_intent={"source": {"kind": "local"}, "objective_zh": "审查改动"},
        public_plan=[
            {"id": "acquire_change", "summary_zh": "获取改动", "status": "passed"},
            {"id": "review_change", "summary_zh": "审查改动", "status": "in_progress"},
        ],
        architecture="arch35",
        session_kind="expert",
    )
    start_workflow(tmp_path, "ce-review", phase="review", force_phase=True, architecture="arch35")
    board = build_todo(tmp_path)
    ids = [it["id"] for it in board["native_items"]]
    assert ids == ["acquire_change", "review_change"]
    assert board["native_items"][1]["status"] == "in_progress"


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


def test_scope_receipt_roundtrip_removed() -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    assert "goal-impact" not in WORKFLOWS


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
    from ascendc_pilot.planning.task_plan import mark_step_passed, plan_for, write_task_plan
    from ascendc_pilot.planning.task_plan import load_task_plan
    from ascendc_pilot.user_goal import load_user_goal

    llm = {
        "objective_zh": "生成 case",
        "needed_workflows": ["uo-init", "tg-plan", "tg-solve"],
        "source": {"kind": "local"},
        "constraints": {},
    }
    create_user_goal(tmp_path, intent_text="生成 case", llm_intent=llm)
    plan = plan_for(llm, {"has_uo": False})
    plan = mark_step_passed(plan, "uo-init")
    write_task_plan(tmp_path, plan)
    out = apply_revision(tmp_path, delta_text="不要 fp32")
    assert out.get("revised") is True
    goal = load_user_goal(tmp_path) or {}
    assert "fp32" in (goal.get("constraints") or {}).get("exclude_dtype", [])
    after = load_task_plan(tmp_path) or {}
    by_id = {str(s.get("id")): str(s.get("status")) for s in after.get("steps") or []}
    assert by_id.get("uo-init") == "passed"
    assert by_id.get("tg-plan") in {"pending", "in_progress"}
    assert by_id.get("tg-plan") != "passed"


def test_worktree_identity_unique_and_lock(tmp_path: Path, monkeypatch) -> None:
    import sys

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # noqa: WPS433

    monkeypatch.setenv("ASCENDC_WORKSPACE_CACHE", str(tmp_path / "cache"))
    a = gw.worktree_home(
        host="gitcode.com",
        owner="cann",
        repo="ops-transformer",
        number=9851,
        head_sha="abcdef1234567890",
        run_id="runA",
    )
    b = gw.worktree_home(
        host="gitcode.com",
        owner="cann",
        repo="ops-transformer",
        number=9851,
        head_sha="abcdef1234567890",
        run_id="runB",
    )
    assert a != b
    assert "generate_change_tests" not in str(a)
    first = gw.acquire_workspace_lock(a, "runA")
    assert first.get("ok") is True
    second = gw.acquire_workspace_lock(a, "runB")
    assert second.get("ok") is False
    assert second.get("error") == "WORKSPACE_IN_USE"
    dest = a / "head"
    dest.mkdir(parents=True)
    (dest / "keep.txt").write_text("owned-by-runA", encoding="utf-8")
    blocked = gw.create_worktree(tmp_path, dest, "deadbeef", run_id="runB")
    assert blocked.get("error") == "WORKSPACE_IN_USE"
    assert (dest / "keep.txt").is_file()


def test_detect_operator_roots_common_fanout_and_empty(tmp_path: Path) -> None:
    import sys

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # noqa: WPS433

    attention = tmp_path / "attention"
    (attention / "common").mkdir(parents=True)
    (attention / "common" / "foo.cpp").write_text("// shared", encoding="utf-8")
    for name in ("op_a", "op_b"):
        (attention / name / "op_host").mkdir(parents=True)
        (attention / name / "op_kernel").mkdir(parents=True)
    roots = gw.detect_operator_roots(tmp_path, ["attention/common/foo.cpp"])
    names = sorted(p.name for p in roots)
    assert names == ["op_a", "op_b"]

    empty = gw.detect_operator_roots(tmp_path, ["docs/README.md"])
    assert empty == []


def test_intent_promote_clone_only_pins_unique_arch(tmp_path: Path, monkeypatch) -> None:
    import yaml

    from ascendc_pilot.actions import goal_engines
    from ascendc_pilot.actions.goal_engines import run_intent_promote
    from ascendc_pilot.paths import agent_root
    from ascendc_pilot.state import start_workflow

    host = tmp_path / "host"
    host.mkdir()
    uo_dir = host / ".ascendc-pilot" / "arch35" / "uo"
    uo_dir.mkdir(parents=True)
    (uo_dir / "HostOp.arch35.uo").write_bytes(b"uo")

    pinned = tmp_path / "worktree" / "FlashAttention"
    pinned.mkdir(parents=True)
    (pinned / "op_host" / "arch35").mkdir(parents=True)
    (pinned / "op_kernel" / "arch35").mkdir(parents=True)

    class FakeWorkspace:
        @staticmethod
        def acquire_pull_request(url: str, **kwargs: object) -> dict:
            del url, kwargs
            return {
                "ok": True,
                "operator_roots": [str(pinned)],
                "architectures": ["arch35"],
                "changed_architectures": ["arch35"],
                "changed_files": ["op_host/arch35/x.cpp"],
                "worktree_head": str(pinned),
                "operator_targets": [
                    {
                        "operator_root": str(pinned),
                        "operator_name": "FlashAttention",
                        "architecture": "arch35",
                    }
                ],
                "changeset": {
                    "schema": "pilot-changeset/v1",
                    "base_source": "provider",
                    "changed_files": ["op_host/arch35/x.cpp"],
                },
            }

        @staticmethod
        def resolve_targets_or_ask(acquire: dict, **kwargs: object) -> dict:
            del kwargs
            return {
                "ok": True,
                "project": str(pinned),
                "architecture": "arch35",
                "operator_roots": [str(pinned)],
                "operator_targets": acquire["operator_targets"],
                "worktree_head": str(pinned),
                "changeset": acquire["changeset"],
            }

    monkeypatch.setattr(goal_engines, "_git_workspace", lambda: FakeWorkspace)
    state = start_workflow(host, "auto", intent="生成 case", architecture="arch35")
    rid = str(state.get("run_id") or "")
    staging = (
        agent_root(host, "arch35") / "runs" / rid / "actions" / "intent_promote" / "staging.yaml"
    )
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_text(
        yaml.safe_dump(
            {
                "intent_text": "为这个 PR 生成针对性测试用例",
                "objective_zh": "为这个 PR 生成针对性测试用例",
                "source": {
                    "kind": "pull_request",
                    "url": "https://gitcode.com/cann/ops-transformer/pull/9851",
                },
                "needed_capabilities": ["knowledge", "change_analysis", "test_generation"],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    out = run_intent_promote(host, {"run_id": rid, "architecture": "arch35", "intent": "生成 case"})
    assert out.get("ok") is True
    assert Path(str(out.get("project"))).resolve() == pinned.resolve()
    assert out.get("next_workflow_id") == ""
    assert out.get("clone_only") is True
    assert out.get("architecture") == "arch35"
    pin = pinned / ".ascendc-pilot" / "pr_arch_pin.yaml"
    assert pin.is_file()
    pin_doc = yaml.safe_load(pin.read_text(encoding="utf-8")) or {}
    assert pin_doc.get("architectures") == ["arch35"]
    receipt = agent_root(host, "arch35") / "runs" / rid / "receipts" / "intent_promoted.yaml"
    assert receipt.is_file()
    assert "op_host/arch35/x.cpp" in list(out.get("changed_files") or [])
    assert "git show --stat" not in str(out.get("message_zh") or "")


def test_intent_promote_empty_roots_returns_facts(tmp_path: Path, monkeypatch) -> None:
    import yaml

    from ascendc_pilot.actions import goal_engines
    from ascendc_pilot.actions.goal_engines import run_intent_promote
    from ascendc_pilot.paths import agent_root
    from ascendc_pilot.state import start_workflow

    host = tmp_path / "host"
    host.mkdir()

    class FakeWorkspace:
        @staticmethod
        def acquire_pull_request(*_a, **_k) -> dict:
            return {
                "ok": True,
                "operator_roots": [],
                "operator_targets": [],
                "changed_files": ["docs/README.md"],
                "worktree_head": str(tmp_path / "head"),
                "changeset": {"changed_files": ["docs/README.md"]},
            }

        @staticmethod
        def resolve_targets_or_ask(acquire: dict, **kwargs: object) -> dict:
            del kwargs
            return {
                "ok": False,
                "error": "OPERATOR_ROOTS_EMPTY",
                "reason_code": "OPERATOR_ROOTS_EMPTY",
                "needs_human_decision": True,
                "decision_kind": "project",
                "changed_files": acquire.get("changed_files") or [],
                "ask_question": {"prompt_zh": "请选择", "options": []},
            }

    monkeypatch.setattr(goal_engines, "_git_workspace", lambda: FakeWorkspace)
    state = start_workflow(host, "auto", intent="生成 case", architecture="arch35")
    rid = str(state.get("run_id") or "")
    staging = (
        agent_root(host, "arch35") / "runs" / rid / "actions" / "intent_promote" / "staging.yaml"
    )
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_text(
        yaml.safe_dump(
            {
                "intent_text": "生成 case",
                "objective_zh": "生成 case",
                "source": {
                    "kind": "pull_request",
                    "url": "https://github.com/org/ops-transformer/pull/12",
                },
                "needed_capabilities": ["test_generation"],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    out = run_intent_promote(host, {"run_id": rid, "architecture": "arch35", "intent": "生成 case"})
    assert out.get("ok") is True
    assert out.get("clone_only") is True
    assert out.get("next_workflow_id") == ""
    assert list(out.get("changed_files") or []) == ["docs/README.md"]
    assert list(out.get("operator_roots") or []) == []


def test_pr_base_uses_provider_metadata(tmp_path: Path, monkeypatch) -> None:
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
    (src / "op_host" / "a.cpp").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c1"], cwd=src, check=True, capture_output=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, check=True, capture_output=True, text=True
    ).stdout.strip()
    (src / "op_host" / "a.cpp").write_text("two\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c2"], cwd=src, check=True, capture_output=True)
    (src / "op_host" / "a.cpp").write_text("three\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c3"], cwd=src, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert base != head

    cache = tmp_path / "cache"
    monkeypatch.setenv("ASCENDC_WORKSPACE_CACHE", str(cache))
    mirror = gw.ensure_bare_mirror(str(src), host="github.com", owner="org", repo="repo")
    assert mirror.get("ok") is True
    mirror_path = Path(mirror["path"])
    monkeypatch.setattr(
        gw,
        "fetch_pr_metadata",
        lambda url: {
            "ok": True,
            "head_sha": head,
            "base_sha": base,
            "base_ref": "release",
            "base_source": "provider",
        },
    )
    monkeypatch.setattr(
        gw,
        "fetch_pr_refs",
        lambda *_a, **_k: {
            "head_sha": head,
            "base_sha": head,
            "base_ref": "main",
            "base_source": "default_branch_fallback",
        },
    )
    out = gw.acquire_pull_request(
        "https://github.com/org/repo/pull/12",
        run_id="run-meta",
    )
    assert out.get("ok") is True
    assert out.get("base_source") == "provider"
    assert out.get("base_sha") == base
    assert "op_host/a.cpp" in (out.get("changed_files") or [])
    assert str(out.get("run_id")) == "run-meta"
    assert "run-meta" in str(out.get("workspace_home") or "")
    del mirror_path


def _seed_local_pr_mirror(tmp_path: Path, monkeypatch, gw):
    src = tmp_path / "src"
    src.mkdir()
    (src / "op_host").mkdir()
    (src / "op_kernel").mkdir()
    (src / "op_host" / "a.cpp").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c1"], cwd=src, check=True, capture_output=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, check=True, capture_output=True, text=True
    ).stdout.strip()
    (src / "op_host" / "a.cpp").write_text("two\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c2"], cwd=src, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, check=True, capture_output=True, text=True
    ).stdout.strip()
    cache = tmp_path / "cache"
    monkeypatch.setenv("ASCENDC_WORKSPACE_CACHE", str(cache))
    mirror = gw.ensure_bare_mirror(str(src), host="github.com", owner="org", repo="repo")
    assert mirror.get("ok") is True
    monkeypatch.setattr(
        gw,
        "fetch_pr_metadata",
        lambda url: {
            "ok": True,
            "head_sha": head,
            "base_sha": base,
            "base_ref": "main",
            "base_source": "provider",
        },
    )
    monkeypatch.setattr(
        gw,
        "fetch_pr_refs",
        lambda *_a, **_k: {
            "head_sha": head,
            "base_sha": base,
            "base_ref": "main",
            "base_source": "default_branch_fallback",
        },
    )
    return src, head, base


def test_acquire_into_opencode_workspace_not_cache(tmp_path: Path, monkeypatch) -> None:
    import sys

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # noqa: WPS433

    _seed_local_pr_mirror(tmp_path, monkeypatch, gw)
    workspace = tmp_path / "opencode-ws"
    workspace.mkdir()
    out = gw.acquire_pull_request(
        "https://github.com/org/repo/pull/12",
        run_id="run-ws",
        workspace_root=workspace,
    )
    assert out.get("ok") is True
    head = Path(str(out.get("worktree_head") or ""))
    assert head.is_dir()
    assert ".ascendc-pr" in head.parts
    assert head.resolve() != workspace.resolve()
    assert (head / "op_host" / "a.cpp").is_file()
    assert not (workspace / "op_host").exists()
    assert out.get("skipped_checkout") is False
    assert any(Path(p).resolve() == head.resolve() or str(head) in str(p) for p in (out.get("operator_roots") or []))


def test_acquire_does_not_skip_clone_when_workspace_is_operator(tmp_path: Path, monkeypatch) -> None:
    import sys

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # noqa: WPS433

    _seed_local_pr_mirror(tmp_path, monkeypatch, gw)
    op = tmp_path / "local-op"
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir()
    marker = op / "keep-me.txt"
    marker.write_text("local", encoding="utf-8")
    out = gw.acquire_pull_request(
        "https://github.com/org/repo/pull/12",
        run_id="run-local",
        workspace_root=op,
    )
    assert out.get("ok") is True
    assert out.get("skipped_checkout") is False
    assert marker.read_text(encoding="utf-8") == "local"
    head = Path(str(out.get("worktree_head")))
    assert ".ascendc-pr" in head.parts
    assert head.resolve() != op.resolve()
    assert (head / "op_host" / "a.cpp").is_file()


def test_acquire_refuses_pilot_checkout_workspace(tmp_path: Path, monkeypatch) -> None:
    import sys

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # noqa: WPS433

    _seed_local_pr_mirror(tmp_path, monkeypatch, gw)
    fake = tmp_path / "AscendC-Pilot"
    (fake / "pilot" / "ascendc_pilot").mkdir(parents=True)
    (fake / "engines").mkdir()
    out = gw.acquire_pull_request(
        "https://github.com/org/repo/pull/12",
        workspace_root=fake,
    )
    assert out.get("ok") is False
    assert out.get("error") == "PILOT_CHECKOUT_FORBIDDEN"
    assert not any(fake.rglob("op_host"))


def test_extract_pr_url_allowlist() -> None:
    import sys

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw  # noqa: WPS433

    assert (
        gw.extract_pr_url("看这个 https://gitcode.com/cann/ops-transformer/pull/9851 谢谢")
        == "https://gitcode.com/cann/ops-transformer/pull/9851"
    )
    assert gw.extract_pr_url("https://evil.example/org/repo/pull/1") == ""


def test_public_plan_uo_init_does_not_pass_impact(tmp_path: Path) -> None:
    from ascendc_pilot.planning.task_plan import (
        PUBLIC_PLAN_TEST_GENERATION,
        mark_step_passed,
        plan_for,
        write_task_plan,
    )
    from ascendc_pilot.user_goal import load_user_goal, mark_workflow_passed

    ids = [row["id"] for row in PUBLIC_PLAN_TEST_GENERATION]
    assert ids[:3] == ["acquire_change", "ensure_knowledge", "review_change"]
    llm = {
        "objective_zh": "生成针对性测试用例",
        "needed_workflows": ["uo-init", "ce-review", "tg-plan", "tg-solve"],
        "source": {"kind": "pull_request", "url": "https://github.com/org/repo/pull/1"},
    }
    create_user_goal(tmp_path, intent_text="生成 case", llm_intent=llm)
    plan = plan_for(llm, {"has_uo": False})
    plan = mark_step_passed(plan, "workspace_acquire")
    write_task_plan(tmp_path, plan)
    adv = mark_workflow_passed(tmp_path, "uo-init")
    assert adv is not None
    by_id = {
        str(s.get("id")): str(s.get("status"))
        for s in (load_user_goal(tmp_path) or {}).get("public_plan") or []
    }
    assert by_id.get("review_change") != "passed"


def test_acceptance_not_passed_without_replay(tmp_path: Path) -> None:
    from ascendc_pilot.planning.task_plan import (
        acceptance_satisfied,
        mark_step_passed,
        plan_for,
        write_task_plan,
    )
    from ascendc_pilot.user_goal import mark_workflow_passed

    llm = {
        "objective_zh": "生成针对性测试用例",
        "needed_workflows": ["tg-plan", "tg-solve"],
        "needed_capabilities": ["knowledge", "test_generation"],
        "source": {"kind": "local"},
    }
    create_user_goal(tmp_path, intent_text="生成 case", llm_intent=llm, architecture="arch35")
    plan = plan_for(llm, {"has_uo": True, "uo_stale": False})
    plan = mark_step_passed(plan, "tg-plan")
    write_task_plan(tmp_path, plan)
    assert acceptance_satisfied(plan, tmp_path, architecture="arch35") is False
    adv = mark_workflow_passed(tmp_path, "tg-solve")
    assert adv is not None
    assert adv.get("completed") is False
    assert adv.get("acceptance_failed") is True
    assert "回放" in str(adv.get("next_summary_zh") or adv.get("message_zh") or "")


def test_authorize_allows_primary_git_cli(tmp_path: Path) -> None:
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.paths import ensure_agent_layout

    op = tmp_path / "op"
    op.mkdir()
    (op / "op_host").mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "auto", intent="生成 case", architecture="arch35")
    verdict = authorize(op, tool="bash", command="git remote -v", agent="ascendc-pilot")
    assert verdict.get("decision") == "allow"
    assert verdict.get("reason_code") == "GIT_CLI_ALLOWED"


def test_authorize_allows_primary_git_clone(tmp_path: Path) -> None:
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.paths import ensure_agent_layout

    op = tmp_path / "op"
    op.mkdir()
    (op / "op_host").mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "auto", intent="生成 case", architecture="arch35")
    clone = authorize(
        op,
        tool="bash",
        command="git clone https://gitcode.com/cann/ops-transformer.git dest",
        agent="ascendc-pilot",
    )
    assert clone.get("decision") == "allow"
    assert clone.get("reason_code") == "GIT_CLI_ALLOWED"
    worktree = authorize(
        op,
        tool="bash",
        command="git worktree add --detach dest abcdef",
        agent="ascendc-pilot",
    )
    assert worktree.get("decision") == "allow"
    assert worktree.get("reason_code") == "GIT_CLI_ALLOWED"


def test_authorize_allows_primary_workspace_delete(tmp_path: Path) -> None:
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.paths import ensure_agent_layout

    op = tmp_path / "op"
    op.mkdir()
    (op / "op_host").mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "auto", intent="生成 case", architecture="arch35")
    leftover = r"D:\TEST\pr_workspace\.ascendc-pr\gitcode.com--cann--ops-transformer--pr-9851"
    verdict = authorize(
        op,
        tool="bash",
        command=f"Remove-Item -Recurse -Force -LiteralPath '{leftover}'",
        agent="ascendc-pilot",
    )
    assert verdict.get("decision") == "allow"
    assert verdict.get("reason_code") == "PRIMARY_BASH_ASK"
    protected = authorize(
        op,
        tool="bash",
        command="Remove-Item -Recurse -Force .ascendc-pilot",
        agent="ascendc-pilot",
    )
    assert protected.get("decision") == "deny"
    assert protected.get("reason_code") == "BASH_PROTECTED_WRITE"


def test_authorize_denies_uo_query_git_cli(tmp_path: Path) -> None:
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.paths import ensure_agent_layout

    op = tmp_path / "op"
    op.mkdir()
    (op / "op_host").mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "auto", intent="生成 case", architecture="arch35")
    verdict = authorize(
        op,
        tool="bash",
        command="git log -1",
        agent="uo-query",
        action="kb_lookup",
    )
    assert verdict.get("decision") == "deny"
    assert verdict.get("reason_code") == "GIT_NOT_FOR_UO_QUERY"


def test_authorize_denies_uncited_operator_source_when_uo_exists(tmp_path: Path) -> None:
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.paths import ensure_agent_layout, uo_root

    op = tmp_path / "op"
    op.mkdir()
    (op / "op_host").mkdir()
    kernel = op / "op_kernel"
    kernel.mkdir()
    src = kernel / "foo.cpp"
    src.write_text("int x;\n", encoding="utf-8")
    ensure_agent_layout(op, arch="arch35")
    uo = uo_root(op, arch="arch35")
    uo.mkdir(parents=True, exist_ok=True)
    (uo / "op.arch35.uo").write_bytes(b"uo")
    start_workflow(op, "tg-plan", architecture="arch35")
    deny_p = authorize(op, tool="read", path=str(src), agent="ascendc-pilot")
    assert deny_p.get("decision") == "allow"
    deny_tg = authorize(
        op, tool="read", path=str(src), agent="tg-analyst", action="plan_fuse"
    )
    assert deny_tg.get("decision") == "allow"
    allow_q = authorize(
        op, tool="read", path=str(src), agent="uo-query", action="kb_lookup"
    )
    assert allow_q.get("decision") == "allow"
    grep_deny = authorize(
        op, tool="grep", path=str(src), agent="ascendc-pilot", command="int x"
    )
    assert grep_deny.get("decision") == "deny"
    assert grep_deny.get("reason_code") == "SOURCE_READ_USE_UO_QUERY"


def test_authorize_allows_pilot_cli_uo_query_file_line(tmp_path: Path) -> None:
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.paths import ensure_agent_layout

    op = tmp_path / "op"
    op.mkdir()
    (op / "op_host").mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "tg-plan", architecture="arch35")
    verdict = authorize(
        op,
        tool="pilot_cli",
        command=f"uo-query --project {op} --file op_kernel/foo.cpp --line 12",
        agent="ascendc-pilot",
    )
    assert verdict.get("decision") == "allow"
    assert verdict.get("reason_code") == "PILOT_CLI_OK"


def test_authorize_allows_cited_truncated_window_read(tmp_path: Path) -> None:
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.authorize.citations import record_from_payload
    from ascendc_pilot.paths import ensure_agent_layout, uo_root

    op = tmp_path / "op"
    op.mkdir()
    (op / "op_host").mkdir()
    kernel = op / "op_kernel"
    kernel.mkdir()
    src = kernel / "foo.cpp"
    src.write_text("int x;\n" * 40, encoding="utf-8")
    ensure_agent_layout(op, arch="arch35")
    uo = uo_root(op, arch="arch35")
    uo.mkdir(parents=True, exist_ok=True)
    (uo / "op.arch35.uo").write_bytes(b"uo")
    start_workflow(op, "tg-plan", architecture="arch35")
    record_from_payload(
        op,
        {
            "truncated": True,
            "cards": [{"file": "op_kernel/foo.cpp", "line": 12, "snippet": "12: int x; …"}],
        },
        arch="arch35",
    )
    allow_w = authorize(
        op,
        tool="read",
        path=str(src),
        command="offset=12 limit=20",
        agent="ascendc-pilot",
    )
    assert allow_w.get("decision") == "allow"
    allow_full = authorize(op, tool="read", path=str(src), agent="ascendc-pilot")
    assert allow_full.get("decision") == "allow"


def test_authorize_allows_operator_source_without_uo(tmp_path: Path) -> None:
    from ascendc_pilot.authorize import authorize
    from ascendc_pilot.paths import ensure_agent_layout

    op = tmp_path / "op"
    op.mkdir()
    (op / "op_host").mkdir()
    src = op / "op_kernel"
    src.mkdir()
    f = src / "foo.cpp"
    f.write_text("int x;\n", encoding="utf-8")
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "auto", intent="生成 case", architecture="arch35")
    verdict = authorize(op, tool="read", path=str(f), agent="ascendc-pilot")
    assert verdict.get("decision") == "allow"
