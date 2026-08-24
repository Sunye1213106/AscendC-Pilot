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
from ascendc_pilot.actions.method_bundle import missing_reference_paths
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.state import start_workflow


REPO = Path(__file__).resolve().parents[2]


def test_split_scope_ns_prefixes() -> None:
    assert split_scope_ns("method:skills/uo-query/**") == (
        "method",
        "skills/uo-query/**",
    )
    assert split_scope_ns("pilot:uo/**")[0] == "pilot"
    assert split_scope_ns("source:op_host/**")[0] == "source"
    # Legacy bare skills/** → method
    assert split_scope_ns("skills/foo/**") == ("method", "skills/foo/**")
    assert split_scope_ns("uo/**") == ("pilot", "uo/**")


def test_scope_allows_method_path(tmp_path: Path) -> None:
    skill = REPO / "skills" / "uo-query" / "SKILL.md"
    assert skill.is_file()
    assert scope_allows_path(
        skill,
        ["method:skills/uo-query/**"],
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
    future = agent_root(tmp_path, "arch0") / "tg" / "init.yaml"
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
        allowed_write_paths=["tg/init.yaml"],
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
        "write: tg/init.yaml\n"
        "pilot_cli commands must pass --project /mnt/op/synthetic_cli\n"
        "See prose path tg/init/ignored.yaml\n"
    )
    paths = extract_stub_paths(stub)
    assert any("uo/summary" in p for p in paths)
    assert any("prompt.md" in p for p in paths)
    assert not any("ignored.yaml" in p for p in paths)
    assert not any("synthetic_cli" in p for p in paths)
    assert not any("ignored.yaml" in p for p in paths)


def test_materialize_method_bundle_copies_refs(tmp_path: Path) -> None:
    sdir = tmp_path / "session"
    sdir.mkdir()
    mat = materialize_method_bundle(
        sdir,
        skill_ids=["uo-query"],
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
    implicit = materialize_method_bundle(
        sdir / "implicit",
        skill_ids=["ce-plan-draft"],
        existing_method="See playbook `references/gotchas.md`.\n",
        project_root=REPO,
        current_skill_id="ce-plan-draft",
    )
    assert implicit.get("ok") is True, implicit
    assert implicit.get("copied") == []
    assert not (sdir / "implicit" / "refs" / "ce-plan-draft" / "gotchas.md").exists()
    mat = materialize_method_bundle(
        sdir / "explicit",
        skill_ids=["ce-plan-draft"],
        existing_method="See playbook `references/gotchas.md`.\n",
        project_root=REPO,
        current_skill_id="ce-plan-draft",
        explicit_refs=["gotchas.md"],
    )
    copied = list(mat.get("copied") or [])
    assert copied == ["refs/ce-plan-draft/gotchas.md"]
    assert (sdir / "explicit" / "refs" / "ce-plan-draft" / "gotchas.md").is_file()
    assert not (sdir / "explicit" / "refs" / "ce-plan-draft" / "scenario-catalog.md").is_file()
    assert mat.get("indexed") == ["references/ce-plan-draft/gotchas.md"]


def test_method_bundle_repo_root_is_parents_3() -> None:
    from ascendc_pilot.actions import method_bundle as mb

    here = Path(mb.__file__).resolve()
    assert here.parents[3] in mb._repo_candidates(None)
    found = mb.find_cognitive_skill_dir("ce-plan-draft", project_root=None)
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


def test_knowledge_refs_materialize_into_session(tmp_path: Path) -> None:
    from ascendc_pilot.actions.method_bundle import materialize_knowledge_refs
    from ascendc_pilot.workflows import WORKFLOWS

    sdir = tmp_path / "session"
    sdir.mkdir()
    out = materialize_knowledge_refs(
        sdir,
        ["ascendc/precision.md", "ascendc/performance.md"],
        project_root=REPO,
    )
    assert out.get("ok") is True, out
    assert (sdir / "knowledge" / "ascendc" / "precision.md").is_file()
    body = (sdir / "knowledge" / "ascendc" / "precision.md").read_text(encoding="utf-8")
    assert "P-CAST" not in body
    assert "/tg-plan" not in body
    fuse = next(a for a in WORKFLOWS["tg-plan"]["actions"] if a["id"] == "plan_fuse")
    assert "evidence.md" in (fuse.get("refs") or [])
    assert "ascendc/precision.md" in (fuse.get("knowledge_refs") or [])
    draft = next(a for a in WORKFLOWS["ce-plan"]["actions"] if a["id"] == "plan_draft")
    assert "ascendc/cross-layer-contracts.md" in (draft.get("knowledge_refs") or [])
    assert not any(str(r).startswith("P-") for r in (draft.get("refs") or []))
    revise = next(a for a in WORKFLOWS["ce-apply"]["actions"] if a["id"] == "plan_revise")
    assert revise.get("knowledge_refs") == draft.get("knowledge_refs")


def test_knowledge_refs_namespace_and_missing(tmp_path: Path) -> None:
    from ascendc_pilot.actions.method_bundle import materialize_knowledge_refs

    sdir = tmp_path / "session"
    sdir.mkdir()
    isolated = materialize_knowledge_refs(
        sdir,
        ["ascendc/precision.md"],
        project_root=REPO,
        knowledge_ns="standards",
    )
    assert isolated.get("ok") is True, isolated
    assert (sdir / "knowledge" / "standards" / "ascendc" / "precision.md").is_file()
    assert not (sdir / "knowledge" / "ascendc" / "precision.md").exists()
    missing = materialize_knowledge_refs(
        sdir,
        ["ascendc/does-not-exist.md"],
        project_root=REPO,
    )
    assert missing.get("ok") is False
    assert missing.get("reason_code") == "KNOWLEDGE_MISSING"
    assert "ascendc/does-not-exist.md" in (missing.get("missing") or [])


def test_append_action_ref_pointers_skips_only_present() -> None:
    from ascendc_pilot.actions.runtime import _append_action_ref_pointers

    text = "# draft\n\n读 `knowledge/ascendc/precision.md`。\n"
    action = {
        "knowledge_refs": [
            "ascendc/precision.md",
            "ascendc/performance.md",
        ]
    }
    out = _append_action_ref_pointers(text, action)
    assert "`knowledge/ascendc/precision.md`" in out
    assert "`knowledge/ascendc/performance.md`" in out
    assert out.count("`knowledge/ascendc/precision.md`") == 1


def test_agent_yaml_uses_scope_namespaces() -> None:
    agents = REPO / "agents"
    for name in (
        "uo-query.yaml",
        "tg-analyst.yaml",
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
    from ascendc_pilot.planning.task_plan import plan_for, write_task_plan
    from ascendc_pilot.user_goal import create_user_goal

    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "tg-init", force_phase=True, architecture="arch0")
    llm_intent = {
        "objective_zh": "生成针对性测试用例",
        "needed_capabilities": ["knowledge", "test_generation"],
        "needed_workflows": ["tg-init", "tg-plan", "tg-solve"],
        "source": {"kind": "local"},
        "intent_text": "帮我生成对应 case",
    }
    create_user_goal(
        tmp_path,
        intent_text="帮我生成对应 case",
        llm_intent=llm_intent,
        architecture="arch0",
    )
    write_task_plan(tmp_path, plan_for(llm_intent, {"has_uo": True}))
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


def test_done_read_hint_uses_status_query_not_quality_read(tmp_path: Path) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step

    ensure_agent_layout(tmp_path, arch="arch35")
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
    msg = str(step.get("message_zh") or "")
    assert step.get("kind") == "done"
    assert "uo-query --status-only" in msg
    assert "Read" not in msg or "quality.yaml" not in msg
    assert out.get("message_zh") == step.get("message_zh")


def test_done_read_hint_embeds_quality_counts(tmp_path: Path) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step
    from ascendc_pilot.paths import uo_root

    ensure_agent_layout(tmp_path, arch="arch35")
    checks = uo_root(tmp_path, arch="arch35") / "checks"
    checks.mkdir(parents=True, exist_ok=True)
    (checks / "quality.yaml").write_text(
        "grade: ready\n"
        "integrity: pass\n"
        "locate_ready: true\n"
        "graph:\n"
        "  entity_count: 19606\n"
        "  relation_count: 37694\n"
        "unresolved:\n"
        "  locate_blocking: 0\n"
        "  total: 11\n",
        encoding="utf-8",
    )
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
    msg = str((out.get("host_step") or {}).get("message_zh") or "")
    assert "uo-query --status-only" in msg
    assert "grade=ready" in msg
    assert "19606" in msg
    assert "37694" in msg
    assert "locate_blocking=0" in msg
    assert "请 Read uo/checks/quality.yaml" not in msg


def test_done_read_hint_without_arch_still_status_query(tmp_path: Path) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step

    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "workflow_complete",
            "status": "passed",
            "complete": {"state": {"workflow_id": "uo-init"}},
        },
    )
    msg = str((out.get("host_step") or {}).get("message_zh") or "")
    assert "uo-query --status-only" in msg
    assert "请 Read uo/checks/quality.yaml" not in msg


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
    assert mat.get("reason_code") == "SKILL_BUNDLE_MISSING"
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


def test_attach_host_step_projects_existing_ask_without_reentering_drive(
    tmp_path: Path, monkeypatch
) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step

    def boom(*_args, **_kwargs):
        raise AssertionError("must not reenter drive or re-prepare")

    monkeypatch.setattr("ascendc_pilot.actions.drive.drive_until_interaction", boom)
    monkeypatch.setattr("ascendc_pilot.actions.runtime.prepare_action", boom)
    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "interaction_required",
            "next": {
                "execution_kind": "primary_interactive",
                "action_id": "plan_approve",
                "actor_id": "ascendc-pilot",
            },
            "ask_question": {
                "header": "批准规划？",
                "options": [{"label": "批准", "value": "approve"}],
            },
            "needs_human_decision": True,
        },
        reenter_drive=False,
    )
    step = out.get("host_step") or {}
    assert step.get("kind") == "ask_human"


def test_attach_host_step_reuses_primary_review_prepare_without_reentering_drive(
    tmp_path: Path, monkeypatch
) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step

    def boom(*_args, **_kwargs):
        raise AssertionError("must not reenter drive or re-prepare")

    monkeypatch.setattr("ascendc_pilot.actions.drive.drive_until_interaction", boom)
    monkeypatch.setattr("ascendc_pilot.actions.runtime.prepare_action", boom)
    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "interaction_required",
            "next": {
                "execution_kind": "primary_review",
                "action_id": "bind_review",
                "actor_id": "ascendc-pilot",
            },
            "prepare": {
                "ok": True,
                "host_step_kind": "primary_review",
                "harness_path": "h.yaml",
                "bind_path": "b.yaml",
                "message_zh": "请通读 harness.yaml 与 bind.yaml。下一发 PASS。",
            },
        },
        reenter_drive=False,
    )
    step = out.get("host_step") or {}
    assert step.get("kind") == "primary_review"
    assert "PASS" in str(step.get("message_zh") or "")


def test_attach_host_step_bind_review_pass_drains_even_without_reenter(
    tmp_path: Path, monkeypatch
) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step

    drained = {"n": 0}

    def fake_drive(_root, prepare=None, **_kwargs):
        drained["n"] += 1
        return {
            "ok": True,
            "stop_reason": "workflow_complete",
            "status": "passed",
            "host_step": {"kind": "done", "message_zh": "init.yaml 已写出"},
        }

    def fake_prep(_root, action_id: str):
        assert action_id == "bind_review"
        return {
            "ok": True,
            "auto_finalize": True,
            "action_id": "bind_review",
            "harness_path": "h.yaml",
            "bind_path": "b.yaml",
            "message_zh": "主控裁判已放行，本轮继续 bind_promote。",
        }

    monkeypatch.setattr("ascendc_pilot.actions.drive.drive_until_interaction", fake_drive)
    monkeypatch.setattr("ascendc_pilot.actions.runtime.prepare_action", fake_prep)
    monkeypatch.setattr(
        "ascendc_pilot.state.load_state",
        lambda *_args, **_kwargs: {"run_id": "R", "workflow_id": "tg-init"},
    )
    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "interaction_required",
            "next": {
                "execution_kind": "primary_review",
                "action_id": "bind_review",
                "actor_id": "ascendc-pilot",
            },
        },
        reenter_drive=False,
    )
    assert drained["n"] == 1
    assert (out.get("host_step") or {}).get("kind") == "done"


def test_attach_host_step_existing_pass_prep_drains_without_reprepare(
    tmp_path: Path, monkeypatch
) -> None:
    from ascendc_pilot.actions.dispatch import attach_host_step

    drained = {"n": 0}

    def fake_drive(_root, prepare=None, **_kwargs):
        drained["n"] += 1
        return {
            "ok": True,
            "stop_reason": "workflow_complete",
            "status": "passed",
            "host_step": {"kind": "done", "message_zh": "init.yaml 已写出"},
        }

    def boom(*_args, **_kwargs):
        raise AssertionError("must not re-prepare bind_review after PASS")

    monkeypatch.setattr("ascendc_pilot.actions.drive.drive_until_interaction", fake_drive)
    monkeypatch.setattr("ascendc_pilot.actions.runtime.prepare_action", boom)
    out = attach_host_step(
        tmp_path,
        {
            "ok": True,
            "stop_reason": "interaction_required",
            "next": {
                "execution_kind": "primary_review",
                "action_id": "bind_review",
                "actor_id": "ascendc-pilot",
            },
            "prepare": {
                "ok": True,
                "auto_finalize": True,
                "message_zh": "主控裁判已放行，本轮继续 bind_promote。",
            },
        },
        reenter_drive=False,
    )
    assert drained["n"] == 1
    assert (out.get("host_step") or {}).get("kind") == "done"
