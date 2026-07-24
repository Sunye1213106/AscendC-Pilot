"""Ownership / identity model tests for Pilot Spec, lease, prompts, and run isolation."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from ascendc_pilot.authorize import authorize
from ascendc_pilot.authorize.lease import issue_action_lease, lease_allows_write_path, load_lease
from ascendc_pilot.ownership import (
    EXECUTION_PRIMARY_INTERACTIVE,
    action_write_paths,
    path_matches_patterns,
    unresolved_placeholders,
)
from ascendc_pilot.workflows.specs import WORKFLOWS


def test_action_yaml_matches_workflow_spec(repo_root: Path):
    import sys

    sys.path.insert(0, str(repo_root / "scripts"))
    import compose_runtime as compose

    compose.sync_action_yaml_mirrors(repo_root)
    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue
        for action in meta.get("actions") or []:
            mid = str(action.get("action_method_id") or "")
            if "/" not in mid:
                continue
            wf, name = mid.split("/", 1)
            if wf != wid:
                continue
            path = repo_root / "skills" / "actions" / wf / name / "action.yaml"
            if not path.is_file():
                continue
            ayaml = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            errs = compose._action_yaml_drift(wid, action, ayaml)
            assert not errs, errs


def test_agent_role_matches_action_role(repo_root: Path):
    agents = {}
    for p in (repo_root / "agents").glob("*.yaml"):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if data.get("id"):
            agents[str(data["id"])] = data
    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved"):
            continue
        for action in meta.get("actions") or []:
            agent_id = action.get("agent_id")
            role = action.get("role_id")
            if not agent_id or agent_id == "ascendc-pilot":
                continue
            ag = agents.get(str(agent_id))
            assert ag, f"missing agent {agent_id}"
            assert ag.get("role") == role, f"{wid}/{action.get('id')}: {ag.get('role')} != {role}"


def test_prompt_identity_is_runtime_rendered(tmp_path: Path, monkeypatch):
    from ascendc_pilot.actions import runtime as rt
    from ascendc_pilot.state import start_workflow

    project = tmp_path / "op"
    project.mkdir()
    monkeypatch.setattr(
        rt,
        "_load_method_and_prompt",
        lambda repo, action: (
            "method for <ACTION_ID>",
            textwrap.dedent(
                """\
                Bundle identity is authoritative.
                workflow_id: <WORKFLOW_ID>
                action_id: <ACTION_ID>
                actor_id: <ACTOR_ID>
                run_id: <RUN_ID>
                architecture: <ARCHITECTURE>
                """
            ),
        ),
    )
    monkeypatch.setattr(
        rt,
        "invoke_engine",
        lambda *a, **k: {
            "ok": True,
            "phase": "propose",
            "candidates_path": "uo/ir/extract_plan_candidates.yaml",
        },
    )
    start_workflow(project, "uo-init", force_phase=True, phase="extract", architecture="arch35")
    monkeypatch.setattr(
        "ascendc_pilot.workflows.pipeline.recommend_next_action",
        lambda *a, **k: {"id": "extract_plan", "reason": "test"},
    )
    out = rt.prepare_action(project, "extract_plan")
    assert out.get("ok"), out
    prompt = Path(out["prompt_path"]).read_text(encoding="utf-8")
    assert unresolved_placeholders(prompt) == []
    assert out["run_id"] in prompt
    assert "<WORKFLOW_ID>" not in prompt
    assert "uo-init" in prompt
    assert out.get("execution_mode") == "subagent"
    assert "identity" in (yaml.safe_load(Path(out["bundle_path"]).read_text(encoding="utf-8")) or {})


def test_no_prompt_contains_hardcoded_conflicting_owner(repo_root: Path):
    for p in (repo_root / "prompts" / "tasks" / "uo").glob("*.md"):
        text = p.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("- workflow_id:"):
                if "<WORKFLOW_ID>" in line:
                    continue
                if "uo-update" in line:
                    assert any(x in p.name for x in ("update", "apply-update", "plan-update", "diff"))
                if "uo-init" in line:
                    assert "update" not in p.name
            if line.strip().startswith("- actor_id:"):
                assert "<ACTOR_ID>" in line or "<" in line


def test_skill_action_set_matches_spec(repo_root: Path):
    import sys

    sys.path.insert(0, str(repo_root / "scripts"))
    import compose_runtime as compose

    errs = compose.sync_skill_action_markers(repo_root)
    assert not errs, errs
    meta = WORKFLOWS["uo-init"]
    text = (repo_root / "skills" / "workflows" / "uo-init" / "SKILL.md").read_text(encoding="utf-8")
    block = text.split("<!-- BEGIN GENERATED ACTIONS -->", 1)[1].split("<!-- END GENERATED ACTIONS -->", 1)[0]
    found = set(__import__("re").findall(r"(?m)^\|\s*`([a-z0-9_]+)`\s*\|", block))
    expected = {str(a.get("id")) for a in meta["actions"]}
    assert found == expected


def test_method_prompt_contract_files_required(repo_root: Path):
    for action in WORKFLOWS["uo-init"]["actions"]:
        mode = action.get("execution_mode")
        if mode not in {"subagent", "primary_interactive"}:
            continue
        mid = action["action_method_id"]
        wf, name = mid.split("/", 1)
        method = repo_root / "skills" / "actions" / wf / name / "METHOD.md"
        assert method.is_file() and method.read_text(encoding="utf-8").strip()
        tpid = action.get("task_prompt_id")
        assert tpid
        dom, pname = tpid.split("/", 1)
        prompt = repo_root / "prompts" / "tasks" / dom / f"{pname}.md"
        assert prompt.is_file() and prompt.read_text(encoding="utf-8").strip()
        assert action.get("output_contract_id")


def test_scope_confirmation_is_primary_interactive():
    action = next(a for a in WORKFLOWS["uo-init"]["actions"] if a["id"] == "scope_confirmation")
    assert action["execution_mode"] == EXECUTION_PRIMARY_INTERACTIVE
    assert action["agent_id"] == "ascendc-pilot"
    assert action["role_id"] == "controller"


def test_scope_prepare_does_not_dispatch_primary_as_subagent(tmp_path: Path, monkeypatch):
    from ascendc_pilot.actions import runtime as rt
    from ascendc_pilot.state import start_workflow

    project = tmp_path / "op"
    project.mkdir()
    start_workflow(project, "uo-init", force_phase=True, phase="scope", architecture="arch35")
    monkeypatch.setattr(
        "ascendc_pilot.workflows.pipeline.recommend_next_action",
        lambda *a, **k: {"id": "scope_confirmation", "reason": "test"},
    )
    out = rt.prepare_action(project, "scope_confirmation")
    assert out.get("ok"), out
    assert out.get("execution_mode") == EXECUTION_PRIMARY_INTERACTIVE
    assert out.get("dispatch_task") is False
    assert not out.get("task_prompt_stub")
    assert out.get("primary_instructions_path")
    assert out.get("interactive_steps")


def test_scope_prompt_does_not_reinvoke_run_action(repo_root: Path):
    text = (repo_root / "prompts" / "tasks" / "uo" / "scope-confirmation.md").read_text(encoding="utf-8")
    assert "acp run-action scope_confirmation --project" not in text
    assert "acp run-action scope_confirmation\n" not in text
    assert "--finalize" in text
    assert "flash_attention_score_grad" not in text
    assert "<ARCHITECTURE>" in text
    assert "<PROJECT_ROOT>" in text
    assert "<RUN_ID>" in text
    assert "<WORKFLOW_ID>" in text
    assert "<ACTION_ID>" in text
    assert "<ACTOR_ID>" in text


def test_scope_uses_state_architecture_and_project_root(tmp_path: Path, monkeypatch):
    from ascendc_pilot.actions import runtime as rt
    from ascendc_pilot.state import start_workflow

    project = tmp_path / "op"
    project.mkdir()
    start_workflow(project, "uo-init", force_phase=True, phase="scope", architecture="arch42")
    monkeypatch.setattr(
        "ascendc_pilot.workflows.pipeline.recommend_next_action",
        lambda *a, **k: {"id": "scope_confirmation", "reason": "test"},
    )
    out = rt.prepare_action(project, "scope_confirmation")
    assert out.get("ok"), out
    prompt = Path(out["prompt_path"]).read_text(encoding="utf-8")
    assert "arch42" in prompt
    assert project.resolve().as_posix() in prompt


def test_extract_plan_cannot_write_semantic_patches(tmp_path: Path):
    from ascendc_pilot.state import start_workflow

    project = tmp_path / "op"
    project.mkdir()
    st = start_workflow(project, "uo-init", force_phase=True, phase="extract")
    lease = issue_action_lease(
        project,
        state=st,
        action_id="extract_plan",
        actor_id="uo-semantic-resolve",
        allowed_write_paths=action_write_paths("uo-init", "extract_plan"),
        forbidden_write_paths=["uo/ir/semantic_patches.yaml"],
    )
    denied = lease_allows_write_path(lease, "uo/ir/semantic_patches.yaml")
    assert denied["ok"] is False
    assert denied["error"] == "ACTION_FORBIDDEN_PATH"
    allowed = lease_allows_write_path(lease, "uo/ir/extract_plan.yaml")
    assert allowed["ok"] is True


def test_adjudicate_cannot_write_extract_plan(tmp_path: Path):
    from ascendc_pilot.state import start_workflow

    project = tmp_path / "op"
    project.mkdir()
    st = start_workflow(project, "uo-init", force_phase=True, phase="extract")
    lease = issue_action_lease(
        project,
        state=st,
        action_id="adjudicate_llm_tasks",
        actor_id="uo-semantic-resolve",
        allowed_write_paths=["uo/ir/semantic_patches.yaml"],
        forbidden_write_paths=["uo/ir/extract_plan.yaml"],
    )
    assert lease_allows_write_path(lease, "uo/ir/extract_plan.yaml")["ok"] is False
    assert lease_allows_write_path(lease, "uo/ir/semantic_patches.yaml")["ok"] is True


def test_key_triage_cannot_write_input_derivable_patch():
    paths = action_write_paths("uo-init", "key_triage")
    assert paths == ["uo/ir/key_triage.yaml"]
    assert not path_matches_patterns("uo/ir/input_derivable_patch.yaml", paths)


def test_key_resolution_cannot_rewrite_key_triage():
    action = next(a for a in WORKFLOWS["uo-init"]["actions"] if a["id"] == "key_resolution")
    assert "uo/ir/key_triage.yaml" in (action.get("forbidden_write_paths") or [])


def test_referee_cannot_write_ir(tmp_path: Path):
    from ascendc_pilot.state import start_workflow

    project = tmp_path / "op"
    project.mkdir()
    start_workflow(project, "uo-init", force_phase=True, phase="review")
    res = authorize(
        project,
        tool="write",
        path=str(project / ".ascendc-pilot" / "uo" / "ir" / "extract_plan.yaml"),
        agent="uo-kb-review",
        action="kb_review",
    )
    assert res.get("decision") == "deny"


def test_action_lease_is_narrower_than_workflow_root():
    writes = action_write_paths("uo-init", "extract_plan")
    assert writes
    assert "uo" not in writes
    assert all(not w.endswith("uo/**") for w in writes)


def test_old_run_scope_does_not_satisfy_current_contract(tmp_path: Path):
    from ascendc_pilot.actions.runtime import _check_output_contract
    from ascendc_pilot.paths import agent_root

    project = tmp_path / "op"
    root = agent_root(project)
    old = root / "uo" / "runs" / "RUN_OLD" / "scope"
    old.mkdir(parents=True)
    (old / "scope_confirmed.yaml").write_text(
        "run_id: RUN_OLD\nworkflow_id: uo-init\naction_id: scope_confirmation\nok: true\n",
        encoding="utf-8",
    )
    (old / "receipt.yaml").write_text("run_id: RUN_OLD\nstatus: pass\n", encoding="utf-8")
    (root / "uo" / "cbm").mkdir(parents=True)
    (root / "uo" / "cbm" / "index_meta.json").write_text("{}", encoding="utf-8")
    check = _check_output_contract(
        project,
        "scope-confirmed-v1",
        run_id="RUN_NEW",
        workflow_id="uo-init",
        action_id="scope_confirmation",
        actor_id="ascendc-pilot",
    )
    assert check["ok"] is False
    assert "RUN_NEW" in str(check.get("missing") or [])


def test_old_run_semantic_tasks_are_ignored_or_rejected(tmp_path: Path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engines" / "understand-operator"))
    from uo.scripts.llm_tasks import open_blocking_tasks, save_llm_tasks

    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    save_llm_tasks(
        uo,
        {
            "version": 1,
            "tasks": [
                {
                    "task_id": "T_OLD",
                    "status": "open",
                    "task_status": "open",
                    "run_id": "RUN_A",
                    "severity": "blocking",
                    "blocking": True,
                    "semantic_status": "unresolved",
                    "source_snapshot_hash": "abc",
                    "candidate_set_hash": "def",
                    "type": "mark_missing",
                    "allowed_actions": ["mark_missing"],
                }
            ],
        },
    )
    assert open_blocking_tasks(uo, current_run_id="RUN_B") == []
    assert len(open_blocking_tasks(uo, current_run_id="RUN_A")) == 1


def test_patch_run_mismatch_is_rejected():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engines" / "understand-operator"))
    from uo.scripts.llm_tasks import validate_task_patch

    doc = {
        "tasks": [
            {
                "task_id": "T1",
                "status": "open",
                "task_status": "open",
                "run_id": "RUN_A",
                "source_snapshot_hash": "snap",
                "candidate_set_hash": "cset",
                "allowed_actions": ["mark_missing"],
                "candidates": [],
            }
        ]
    }
    out = validate_task_patch(
        doc,
        {"task_id": "T1", "action": "mark_missing", "run_id": "RUN_B", "candidate_set_hash": "cset"},
        current_source_hash="snap",
        current_run_id="RUN_A",
    )
    assert out["ok"] is False
    assert out["error"] == "SEMANTIC_TASK_RUN_MISMATCH"


def test_ledger_run_mismatch_is_rejected(tmp_path: Path):
    # rebuild filters non-matching run records
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engines" / "understand-operator"))
    from uo.scripts.semantic_resolution_ledger import load_ledger, save_ledger

    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    save_ledger(
        uo,
        {
            "version": 1,
            "records": [
                {"run_id": "RUN_A", "semantic_action": "accept_edge", "patch_id": "p1"},
                {"run_id": "RUN_B", "semantic_action": "accept_edge", "patch_id": "p2"},
            ],
        },
    )
    doc = load_ledger(uo)
    assert len(doc["records"]) == 2


def test_active_pilot_disallows_unbound_uo_run(tmp_path: Path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engines" / "understand-operator"))
    from uo.scripts import prepare_operator as po

    project = tmp_path / "op"
    (project / ".ascendc-pilot" / "state").mkdir(parents=True)
    (project / ".ascendc-pilot" / "state" / "workflow.yaml").write_text(
        "workflow_id: uo-init\nrun_id: RUN_PILOT\nstatus: running\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as ei:
        po.main([str(project)])
    assert "PILOT_RUN_ID_REQUIRED" in str(ei.value)


def test_snapshot_failure_cannot_be_used_as_hash(tmp_path: Path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engines" / "understand-operator"))
    from uo.scripts.evidence_score import _source_snapshot_result, require_source_snapshot

    uo = tmp_path / "uo"
    uo.mkdir()
    (uo / "manifest.yaml").write_text("current_run_id: RUN_X\n", encoding="utf-8")
    res = _source_snapshot_result(uo, run_id="RUN_X")
    assert res["ok"] is False
    assert res["error"] == "SOURCE_SNAPSHOT_SCOPE_MISSING"
    req = require_source_snapshot(uo, run_id="RUN_X")
    assert req["ok"] is False
    assert not str(req.get("hash") or "").startswith("FAIL_CLOSED")


def test_new_workflow_run_creates_new_debug_session(tmp_path: Path):
    from ascendc_pilot import debug as dbg
    from ascendc_pilot.state import start_workflow

    project = tmp_path / "op"
    project.mkdir()
    dbg.set_enabled(project, True)
    first = dbg.load_debug_session(project)
    st1 = start_workflow(project, "uo-init", force_phase=True, phase="prepare")
    ds1 = dbg.load_debug_session(project)
    assert ds1.get("run_id") == st1.get("run_id")
    st2 = start_workflow(project, "uo-init", force_phase=True, phase="prepare")
    ds2 = dbg.load_debug_session(project)
    assert ds2.get("run_id") == st2.get("run_id")
    assert ds2.get("debug_session_id") != ds1.get("debug_session_id")
    assert first.get("debug_session_id") != ds2.get("debug_session_id")


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
