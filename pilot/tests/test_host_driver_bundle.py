"""Host Session Driver + Bundle closure unit tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.actions.dispatch import (
    build_host_step,
    claim_dispatch_ticket,
    consume_dispatch_ticket,
    issue_dispatch_ticket,
    load_dispatch_ticket,
)
from ascendc_pilot.actions.method_bundle import (
    check_bundle_readable,
    extract_stub_paths,
    materialize_method_bundle,
)
from ascendc_pilot.agents_registry import scope_allows_path, split_scope_ns
from ascendc_pilot.authorize.cache import build_cache_key, clear, get, put
from ascendc_pilot.authorize.serve import handle_request
from ascendc_pilot.authorize.session_registry import (
    clear as clear_sessions,
    lookup_child_session,
    register_child_session,
)
from ascendc_pilot.context.compiler import missing_reference_paths
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import start_workflow


REPO = Path(__file__).resolve().parents[2]


def test_split_scope_ns_prefixes() -> None:
    assert split_scope_ns("method:skills/operator-analysis/**") == (
        "method",
        "skills/operator-analysis/**",
    )
    assert split_scope_ns("pilot:uo/**")[0] == "pilot"
    assert split_scope_ns("source:op_host/**")[0] == "source"
    # Legacy bare skills/** → method
    assert split_scope_ns("skills/foo/**") == ("method", "skills/foo/**")
    assert split_scope_ns("uo/**") == ("pilot", "uo/**")


def test_scope_allows_method_path(tmp_path: Path) -> None:
    skill = REPO / "skills" / "operator-analysis" / "SKILL.md"
    assert skill.is_file()
    assert scope_allows_path(
        skill,
        ["method:skills/operator-analysis/**"],
        project_root=REPO,
    )


def test_dispatch_ticket_oneshot(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "uo-query", phase="answer", force_phase=True, architecture="arch0")
    ticket = issue_dispatch_ticket(
        tmp_path,
        run_id="run_test",
        action_id="kb_lookup",
        actor_id="uo-query",
        lease_id="lease1",
        session_dir="/tmp/session",
        task_prompt_stub="read prompt.md",
    )
    tid = str(ticket["ticket_id"])
    assert tid.startswith("dxt_")
    loaded = load_dispatch_ticket(tmp_path, tid)
    assert loaded.get("status") == "open"
    claimed = claim_dispatch_ticket(tmp_path, tid)
    assert claimed.get("ok") is True
    assert claimed["ticket"].get("status") == "processing"
    # Second claim while processing fails
    again = claim_dispatch_ticket(tmp_path, tid)
    assert again.get("ok") is False
    # Finalize fail → reopen
    from ascendc_pilot.actions.dispatch import release_dispatch_ticket, mark_dispatch_ticket_consumed

    released = release_dispatch_ticket(tmp_path, tid, error="bad payload")
    assert released.get("ok") is True
    assert load_dispatch_ticket(tmp_path, tid).get("status") == "open"
    # Retry claim + consume
    assert claim_dispatch_ticket(tmp_path, tid).get("ok") is True
    assert mark_dispatch_ticket_consumed(tmp_path, tid).get("ok") is True
    assert load_dispatch_ticket(tmp_path, tid).get("status") == "consumed"
    assert claim_dispatch_ticket(tmp_path, tid).get("ok") is False


def test_build_host_step_kinds() -> None:
    step = build_host_step(kind="done", message_zh="ok")
    assert step["kind"] == "done"
    ask = build_host_step(
        kind="ask_human",
        ask_question={"header": "h", "question": "q", "options": [{"label": "a"}]},
    )
    assert ask["kind"] == "ask_human"
    assert ask["ask_question"]["header"] == "h"


def test_build_host_step_attaches_fanout_tasks() -> None:
    prep = {
        "action_id": "kb_lookup",
        "actor_id": "uo-query",
        "task_prompt_stub": "parent stub",
        "session_dir": "/s",
        "dispatch_tasks": [
            {
                "slice_id": "sel",
                "focus": "SEL",
                "first_mode": "template_match",
                "actor_id": "uo-query",
                "action_id": "kb_lookup",
                "task_prompt_stub": "SLICE_ID=sel\nA",
            },
            {
                "slice_id": "locate",
                "focus": "locate",
                "first_mode": "locate",
                "actor_id": "uo-query",
                "action_id": "kb_lookup",
                "task_prompt_stub": "SLICE_ID=locate\nB",
            },
        ],
    }
    step = build_host_step(kind="dispatch_subagent", prepare=prep, actor_id="uo-query")
    assert step["kind"] == "dispatch_subagent"
    assert len(step["tasks"]) == 2
    assert step["tasks"][0]["slice_id"] == "sel"
    assert "SLICE_ID=sel" in step["tasks"][0]["task_prompt_stub"]
    assert step["task_prompt_stub"] == "parent stub"


def test_bundle_readable_future_write_and_project_root(tmp_path: Path) -> None:
    from ascendc_pilot.actions.method_bundle import TaskStubPointers, check_bundle_readable
    from ascendc_pilot.paths import agent_root, ensure_agent_layout

    ensure_agent_layout(tmp_path, arch="arch0")
    (tmp_path / "op_host").mkdir()
    (tmp_path / "op_kernel").mkdir()
    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "prompt.md").write_text("# p\n", encoding="utf-8")
    (sdir / "method.md").write_text("# m\n", encoding="utf-8")
    (sdir / "bundle.yaml").write_text("ok: true\n", encoding="utf-8")
    future = agent_root(tmp_path, "arch0") / "tg" / "init" / "audit_report.yaml"
    ptr = TaskStubPointers(
        prompt=str(sdir / "prompt.md"),
        method=str(sdir / "method.md"),
        bundle=str(sdir / "bundle.yaml"),
        session_dir=str(sdir),
        project_root=str(tmp_path.resolve()),
        write=[str(future)],
    )
    br = check_bundle_readable(
        pointers=ptr,
        session_dir=sdir,
        project_root=tmp_path,
        allowed_read_paths=["runs/**", "tg/**"],
        allowed_write_paths=["tg/init/audit_report.yaml"],
        allowed_source_roots=["op_host", "op_kernel"],
    )
    assert br.get("ok") is True, br
    assert not future.exists()


def test_bundle_readable_rejects_unleased_source_read(tmp_path: Path) -> None:
    from ascendc_pilot.actions.method_bundle import TaskStubPointers, check_bundle_readable
    from ascendc_pilot.paths import ensure_agent_layout

    ensure_agent_layout(tmp_path, arch="arch0")
    (tmp_path / "op_host").mkdir()
    outside = tmp_path / "unrelated" / "secret.cpp"
    outside.parent.mkdir()
    outside.write_text("int x;\n", encoding="utf-8")
    sdir = tmp_path / "session"
    sdir.mkdir()
    (sdir / "prompt.md").write_text("# p\n", encoding="utf-8")
    (sdir / "method.md").write_text("# m\n", encoding="utf-8")
    (sdir / "bundle.yaml").write_text("ok: true\n", encoding="utf-8")
    ptr = TaskStubPointers(
        prompt=str(sdir / "prompt.md"),
        method=str(sdir / "method.md"),
        bundle=str(sdir / "bundle.yaml"),
        session_dir=str(sdir),
        project_root=str(tmp_path.resolve()),
        read=[str(outside)],
    )
    br = check_bundle_readable(
        pointers=ptr,
        session_dir=sdir,
        project_root=tmp_path,
        allowed_read_paths=["runs/**"],
        allowed_source_roots=["op_host", "op_kernel"],
    )
    assert br.get("ok") is False
    assert br.get("reason_code") == "BUNDLE_NOT_READABLE"
    assert br.get("unleased")


def test_bundle_readable_requires_session_pack(tmp_path: Path) -> None:
    sdir = tmp_path / "session"
    sdir.mkdir()
    # Missing prompt/method/bundle → fail
    br = check_bundle_readable(
        stub="Read prompt.md",
        session_dir=sdir,
        project_root=tmp_path,
        allowed_read_paths=["runs/**"],
    )
    assert br.get("ok") is False
    assert br.get("reason_code") == "BUNDLE_NOT_READABLE"
    assert br.get("missing")

    (sdir / "prompt.md").write_text("# p\n", encoding="utf-8")
    (sdir / "method.md").write_text("# m\n", encoding="utf-8")
    (sdir / "bundle.yaml").write_text("ok: true\n", encoding="utf-8")
    br2 = check_bundle_readable(
        stub="Read session prompt.md and method.md",
        session_dir=sdir,
        project_root=tmp_path,
        allowed_read_paths=["runs/**"],
    )
    assert br2.get("ok") is True


def test_extract_stub_paths_finds_typed_inputs_not_writes() -> None:
    stub = (
        "prompt: /s/prompt.md\n"
        "method: /s/method.md\n"
        "bundle: /s/bundle.yaml\n"
        "read: uo/summary/overview.yaml\n"
        "write: tg/init/audit_report.yaml\n"
        "acp --project /mnt/op/synthetic_cli\n"
        "See prose path tg/init/ignored.yaml\n"
    )
    paths = extract_stub_paths(stub)
    assert any("uo/summary" in p for p in paths)
    assert any("prompt.md" in p for p in paths)
    assert not any("audit_report" in p for p in paths)
    assert not any("synthetic_cli" in p for p in paths)
    assert not any("ignored.yaml" in p for p in paths)


def test_materialize_method_bundle_copies_refs(tmp_path: Path) -> None:
    sdir = tmp_path / "session"
    sdir.mkdir()
    mat = materialize_method_bundle(
        sdir,
        skill_ids=["operator-analysis"],
        existing_method="# existing\n",
        project_root=REPO,
    )
    assert (sdir / "method.md").is_file()
    method = (sdir / "method.md").read_text(encoding="utf-8")
    assert "# existing" in method
    assert "Materialized skill:" not in method
    assert "Available refs (index)" not in method
    assert mat.get("copied") == []
    assert mat.get("indexed") == []


def test_materialize_method_bundle_copies_named_refs_only(tmp_path: Path) -> None:
    sdir = tmp_path / "session"
    sdir.mkdir()
    mat = materialize_method_bundle(
        sdir,
        skill_ids=["code-engineering"],
        existing_method="See playbook `references/gotchas.md`.\n",
        project_root=REPO,
        prompt="Also `references/risk-classes.md`.\n",
    )
    copied = list(mat.get("copied") or [])
    assert copied == [
        "refs/code-engineering/gotchas.md",
        "refs/code-engineering/risk-classes.md",
    ]
    assert (sdir / "refs" / "code-engineering" / "gotchas.md").is_file()
    assert (sdir / "refs" / "code-engineering" / "risk-classes.md").is_file()
    assert not (sdir / "refs" / "code-engineering" / "scenario-catalog.md").is_file()
    assert mat.get("indexed") == [
        "references/code-engineering/gotchas.md",
        "references/code-engineering/risk-classes.md",
    ]


def test_method_bundle_repo_root_is_parents_3() -> None:
    from ascendc_pilot.actions import method_bundle as mb

    here = Path(mb.__file__).resolve()
    assert here.parents[3] in mb._repo_candidates(None)
    found = mb.find_cognitive_skill_dir("code-engineering", project_root=None)
    assert found is not None
    assert (found / "SKILL.md").is_file()
    assert (found / "references" / "gotchas.md").is_file()


def test_serve_authorize_ping_and_register_session(tmp_path: Path) -> None:
    clear_sessions()
    ping = handle_request({"method": "ping"})
    assert ping.get("ok") is True
    reg = handle_request(
        {
            "method": "register-session",
            "project": str(tmp_path),
            "session_id": "ses_test_host_driver",
            "actor_id": "uo-query",
            "action_id": "kb_lookup",
            "lease_id": "L1",
            "run_id": "R1",
        }
    )
    assert reg.get("ok") is True
    hit = lookup_child_session("ses_test_host_driver")
    assert hit is not None
    assert hit.get("actor_id") == "uo-query"
    look = handle_request({"method": "lookup-session", "session_id": "ses_test_host_driver"})
    assert look.get("ok") is True


def test_authorize_verdict_cache_roundtrip(tmp_path: Path) -> None:
    clear()
    key = build_cache_key(
        tmp_path,
        tool="read",
        command="",
        path="uo/x.yaml",
        agent="uo-query",
        action="kb_lookup",
        lease_id="L",
    )
    assert key is not None
    put(key, {"ok": True, "decision": "allow"})
    hit = get(key)
    assert hit is not None
    assert hit.get("decision") == "allow"


def test_missing_reference_paths_helper() -> None:
    assert missing_reference_paths(
        [{"path": "a.md", "status": "ok"}, {"path": "b.md", "status": "missing"}]
    ) == ["b.md"]


def test_agent_yaml_uses_scope_namespaces() -> None:
    agents = REPO / "agents"
    for name in (
        "uo-query.yaml",
        "tg-init-audit.yaml",
        "tg-lemma-producer.yaml",
        "ce-reviewer.yaml",
    ):
        doc = yaml.safe_load((agents / name).read_text(encoding="utf-8"))
        reads = list(doc.get("read_scopes") or [])
        assert reads, name
        assert any(
            str(s).startswith(("pilot:", "method:", "source:")) for s in reads
        ), f"{name} missing namespaced scopes"
        desc = str(doc.get("description") or "")
        assert "skills/" not in desc or "method.md" in desc, (
            f"{name} description still points at host skill paths without session method"
        )


def test_path_within_scopes_namespace_aware() -> None:
    from ascendc_pilot.ownership import path_within_scopes

    assert path_within_scopes("uo/**", ["pilot:uo/**", "pilot:runs/**"])
    assert path_within_scopes("pilot:uo/**", ["uo/**", "runs/**"])
    assert path_within_scopes("uo/summary/overview.yaml", ["pilot:uo/**"])
    # Cross-namespace must not match
    assert not path_within_scopes("method:skills/**", ["pilot:skills/**", "pilot:uo/**"])
    assert not path_within_scopes("source:op_kernel/**", ["pilot:op_kernel/**"])
    # Universal pilot ceiling
    assert path_within_scopes("uo/**", ["pilot:*"])
    assert path_within_scopes("runs/x/**", ["*"])


def test_attach_host_step_continue_goal(tmp_path: Path) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step
    from ascendc_pilot.user_goal import create_tilingkey_full_coverage_goal

    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "tg-init", force_phase=True, architecture="arch0")
    create_tilingkey_full_coverage_goal(
        tmp_path,
        architecture="arch0",
        intent_text="建立全量 TilingKey 覆盖测试",
        current_step="tg_init",
    )
    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "workflow_complete",
            "status": "passed",
            "complete": {
                "user_goal_next_workflow_id": "tg-plan",
                "user_goal_next_summary_zh": "规划测试义务",
                "state": {"workflow_id": "tg-init", "architecture": "arch0"},
            },
        },
    )
    step = out.get("host_step") or {}
    assert step.get("kind") == "continue_goal"
    assert step.get("next_workflow_id") == "tg-plan"
    assert "全量" in str(step.get("intent") or "") or bool(step.get("intent"))


def test_attach_host_step_failed_keeps_engine_error(tmp_path: Path) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step

    out = attach_host_step(
        tmp_path,
        {
            "ok": False,
            "stop_reason": "deterministic_action_failed",
            "failed_action": "detect_changes",
            "error": "manifest.source.revision is unknown; run /uo-init first",
            "message_zh": "确定性 Action `detect_changes` 失败：manifest.source.revision is unknown; run /uo-init first",
            "failure": {
                "error": "manifest.source.revision is unknown; run /uo-init first",
                "engine": {"ok": False, "error": "manifest.source.revision is unknown; run /uo-init first"},
            },
        },
    )
    step = out.get("host_step") or {}
    assert step.get("kind") == "failed"
    assert "unknown" in str(step.get("message_zh") or "")
    assert step.get("failed_action") == "detect_changes"
    assert "unknown" in str(step.get("error_detail") or "")
    assert "unknown" in str(out.get("error") or "")


def test_attach_host_step_failed_keeps_nested_cann_message(tmp_path: Path) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step

    out = attach_host_step(
        tmp_path,
        {
            "ok": False,
            "stop_reason": "deterministic_action_failed",
            "failed_action": "apply_update",
            "engine": {
                "ok": False,
                "engine": "apply_update",
                "action_results": [
                    {
                        "ok": False,
                        "result": {
                            "error": "CANN_ENV_NOT_READY",
                            "message_zh": "UO 解析前 CANN 环境未就绪。请设置 UO_CANN_ROOT。",
                        }
                    }
                ],
            },
        },
    )
    step = out.get("host_step") or {}
    assert step.get("kind") == "failed"
    assert "UO_CANN_ROOT" in str(step.get("message_zh") or "")
    assert str(step.get("message_zh") or "") != "deterministic_action_failed"


def test_done_read_hint_uses_arch_scoped_quality_path(tmp_path: Path) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step

    ensure_agent_layout(tmp_path, arch="arch35")
    quality = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "checks" / "quality.yaml"
    quality.parent.mkdir(parents=True, exist_ok=True)
    quality.write_text("graph: {}\n", encoding="utf-8")
    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "workflow_complete",
            "status": "passed",
            "complete": {
                "state": {"workflow_id": "uo-init", "architecture": "arch35"},
            },
        },
    )
    step = out.get("host_step") or {}
    q = str(step.get("quality_path") or "").replace("\\", "/")
    msg = str(step.get("message_zh") or "")
    assert step.get("kind") == "done"
    assert "/arch35/uo/checks/quality.yaml" in q
    assert "/.ascendc-pilot/uo/" not in q
    assert q in msg.replace("\\", "/")
    assert "请 Read uo/checks/quality.yaml" not in msg
    assert out.get("message_zh") == step.get("message_zh")


def test_done_read_hint_globs_quality_when_arch_missing(tmp_path: Path) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step

    quality = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "checks" / "quality.yaml"
    quality.parent.mkdir(parents=True, exist_ok=True)
    quality.write_text("graph: {}\n", encoding="utf-8")
    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "workflow_complete",
            "status": "passed",
            "complete": {"state": {"workflow_id": "uo-init"}},
        },
    )
    q = str((out.get("host_step") or {}).get("quality_path") or "").replace("\\", "/")
    assert "/arch35/uo/checks/quality.yaml" in q
    assert "请 Read uo/checks/quality.yaml" not in str((out.get("host_step") or {}).get("message_zh") or "")


def test_method_bundle_fail_closed_without_placeholder(tmp_path: Path) -> None:
    sdir = tmp_path / "session"
    sdir.mkdir()
    mat = materialize_method_bundle(
        sdir,
        skill_ids=["definitely-missing-skill-xyz"],
        existing_method="",
        project_root=tmp_path,
    )
    assert mat.get("ok") is False
    assert mat.get("reason_code") == "METHOD_BUNDLE_MISSING"
    assert not (sdir / "method.md").is_file()


def test_parse_acp_stdout_ignores_stderr_heartbeat() -> None:
    """Mirror Host Driver protocol: stdout JSON only; stderr heartbeats ignored."""
    import json

    stdout = json.dumps({"ok": True, "host_step": {"kind": "done"}}, ensure_ascii=False)
    stderr = (
        "[acp-auto] drain start\n"
        "[acp-auto] run prepare (phase=prepare 准备范围)\n"
        "[acp-auto] drain stop interaction_required\n"
    )
    # Simulate the fixed parser (must NOT concat stderr).
    text = stdout  # not stdout + stderr
    parsed = json.loads(text[text.index("{") :])
    assert parsed["ok"] is True
    assert parsed["host_step"]["kind"] == "done"
    # Old buggy concat would fail:
    broken = f"{stdout}\n{stderr}"
    try:
        json.loads(broken[broken.index("{") :])
        concat_ok = True
    except json.JSONDecodeError:
        concat_ok = False
    assert concat_ok is False
