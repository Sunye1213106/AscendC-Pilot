"""W1/W2 hardening: env capabilities, source scope, adjudicate no-op, identity budget."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ascendc_pilot.authorize import authorize
from ascendc_pilot.authorize.lease import (
    issue_action_lease,
    lease_allows_source_path,
    load_lease,
)
from ascendc_pilot.environment_capabilities import (
    build_environment_capabilities,
    source_scope_for_lease,
    write_environment_capabilities,
)
from ascendc_pilot.observation import (
    IDENTITY_CONTRACT,
    NON_SEMANTIC_BURN_CLASSES,
    apply_observation,
    classify_failure,
    new_observation_id,
)
from ascendc_pilot.paths import ensure_agent_layout, uo_root
from ascendc_pilot.runs import issue_receipt
from ascendc_pilot.spec_hashes import workflow_spec_hash
from ascendc_pilot.state import load_state, save_state, start_workflow


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def _issue(project: Path, action_id: str, *, actor_id: str = "deterministic-uo-engine") -> None:
    issue_receipt(
        project,
        actor_type="producer",
        actor_id=actor_id,
        action_id=action_id,
        workflow_spec_hash=workflow_spec_hash("uo-init"),
        input_hashes={"a": "1"},
        output_hashes={"a": "1"},
        checker_result={"ok": True},
        nonce=action_id,
        _internal=True,
    )


def test_environment_capabilities_written_on_prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_agent_layout(tmp_path)
    (tmp_path / "op_host").mkdir()
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    monkeypatch.setattr(
        "ascendc_pilot.workflows.pipeline.recommend_next_action",
        lambda *a, **k: {"id": "adjudicate_llm_tasks", "reason": "test"},
    )
    _write(uo_root(tmp_path) / "ir" / "llm_tasks.yaml", {"version": 1, "tasks": [], "run_id": load_state(tmp_path)["run_id"]})
    from ascendc_pilot.actions.runtime import prepare_action

    prep = prepare_action(tmp_path, "adjudicate_llm_tasks")
    assert prep.get("ok") is True, prep
    sdir = Path(prep["session_dir"])
    env = sdir / "environment_capabilities.yaml"
    assert env.is_file()
    data = yaml.safe_load(env.read_text(encoding="utf-8"))
    assert data["kind"] == "environment_capabilities"
    assert data["project_root"]
    assert "tools" in data
    session = yaml.safe_load((sdir / "session.yaml").read_text(encoding="utf-8"))
    reads = [str(p) for p in (session.get("allowed_read_paths") or [])]
    assert any(
        "environment_capabilities" in p or "actions/adjudicate_llm_tasks" in p for p in reads
    )
    stub_path = sdir / "task_prompt_stub.md"
    if stub_path.is_file():
        assert "environment:" in stub_path.read_text(encoding="utf-8")


def test_source_scope_lease_and_authorize_deny(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    (tmp_path / "op_host").mkdir()
    (tmp_path / "op_host" / "a.cpp").write_text("int x;\n", encoding="utf-8")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "b.cpp").write_text("int y;\n", encoding="utf-8")
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    scope = source_scope_for_lease(tmp_path)
    assert "op_host" in scope["allowed_source_roots"]
    lease = issue_action_lease(
        tmp_path,
        action_id="extract_plan",
        actor_id="uo-semantic-resolve",
        mode="normal",
        allowed_source_roots=scope["allowed_source_roots"],
        allowed_source_files=[],
        allowed_read_paths=["uo/ir/**", "runs/**"],
    )
    assert lease_allows_source_path(lease, "op_host/a.cpp").get("ok") is True
    assert lease_allows_source_path(lease, "outside/b.cpp").get("ok") is False

    ok_in = authorize(
        tmp_path,
        tool="read",
        path=str(tmp_path / "op_host" / "a.cpp"),
        agent="uo-semantic-resolve",
        action="extract_plan",
    )
    assert ok_in.get("ok") is True, ok_in

    denied = authorize(
        tmp_path,
        tool="read",
        path=str(tmp_path / "outside" / "b.cpp"),
        agent="uo-semantic-resolve",
        action="extract_plan",
    )
    assert denied.get("ok") is False
    assert "SOURCE_SCOPE" in str(denied.get("reason_code") or denied.get("error_code") or "")


def test_adjudicate_noop_when_no_open_blocking(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    run_id = load_state(tmp_path)["run_id"]
    for aid in ("detect_score_pre", "extract_plan", "detect_score_post"):
        actor = "uo-semantic-resolve" if aid == "extract_plan" else "deterministic-uo-engine"
        _issue(tmp_path, aid, actor_id=actor)
    uo = uo_root(tmp_path)
    _write(
        uo / "ir" / "llm_tasks.yaml",
        {
            "version": 1,
            "run_id": run_id,
            "tasks": [],
        },
    )
    from ascendc_pilot.actions.runtime import prepare_action

    prep = prepare_action(tmp_path, "adjudicate_llm_tasks")
    assert prep.get("ok") is True, prep
    assert prep.get("finalize_required") is True
    assert prep.get("auto_finalize") is not True
    assert "finalize" in str(prep.get("recommended_command") or "")
    assert prep.get("dispatch_task") is False
    na = Path(prep["session_dir"]) / "not_applicable.yaml"
    assert na.is_file()
    assert yaml.safe_load(na.read_text(encoding="utf-8"))["status"] == "semantic_patch_not_applicable"
    patches = yaml.safe_load((uo / "ir" / "semantic_patches.yaml").read_text(encoding="utf-8"))
    assert patches["status"] == "semantic_patch_not_applicable"
    assert patches["patches"] == []
    fin = prep.get("finalize") or {}
    assert fin.get("ok") is True, fin


def test_identity_failure_does_not_burn_semantic_budget(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    st = load_state(tmp_path)
    st["retry_budget"] = 2
    st["no_progress_streak"] = 0
    save_state(tmp_path, st)

    clf = classify_failure(error_code="ARTIFACT_SESSION_MISMATCH", messages=["session drift"])
    assert clf["failure_class"] == IDENTITY_CONTRACT
    assert IDENTITY_CONTRACT in NON_SEMANTIC_BURN_CLASSES

    obs = {
        "observation_id": new_observation_id(),
        "ok": False,
        "outcome": "failure",
        "action_id": "adjudicate_llm_tasks",
        "step_id": "action_finalize",
        "error_code": "ARTIFACT_SESSION_MISMATCH",
        "failure_class": IDENTITY_CONTRACT,
        "retryable": True,
        "failure_fingerprint": "fp_identity_1",
        "messages": ["ARTIFACT_SESSION_MISMATCH"],
    }
    apply_observation(tmp_path, obs)
    st1 = load_state(tmp_path)
    assert int(st1.get("no_progress_streak") or 0) == 0
    assert st1.get("status") == "rework_required"

    obs = dict(obs)
    obs["observation_id"] = new_observation_id()
    apply_observation(tmp_path, obs)
    st2 = load_state(tmp_path)
    assert int(st2.get("no_progress_streak") or 0) == 0
    assert st2.get("last_failure", {}).get("failure_class") != "retry_exhausted"


def test_forbidden_extract_plan_keys_single_source() -> None:
    from ascendc_pilot.actions import runtime as rt
    from uo.scripts.extract_plan_io import FORBIDDEN_EXTRACT_PLAN_KEYS

    assert rt._EXTRACT_PLAN_FORBID_FIELDS == FORBIDDEN_EXTRACT_PLAN_KEYS


def test_build_environment_capabilities_shape(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    (tmp_path / "op_kernel").mkdir()
    data = build_environment_capabilities(tmp_path, architecture="arch35", run_id="R1")
    assert data["architecture"] == "arch35"
    assert "op_kernel" in data["source_scope"]["roots"]
    path = write_environment_capabilities(tmp_path / "sess", tmp_path, architecture="arch35")
    assert path.is_file()


def test_containment_inspect_uses_action_contract_paths(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", phase="extract", force_phase=True)
    st = load_state(tmp_path)
    st["status"] = "human_required"
    st["last_failure"] = {"action_id": "extract_plan", "failure_class": "retry_exhausted"}
    save_state(tmp_path, st)
    issue_action_lease(tmp_path, action_id="_containment", mode="containment")

    plan = uo_root(tmp_path) / "ir" / "extract_plan.yaml"
    _write(plan, {"version": 1, "items": []})
    ok = authorize(
        tmp_path,
        tool="read",
        path=str(plan),
        agent="ascendc-pilot",
    )
    assert ok.get("ok") is True, ok
    assert ok.get("reason_code") == "CONTAINMENT_INSPECT_READ"

    other = uo_root(tmp_path) / "ir" / "llm_tasks.yaml"
    _write(other, {"tasks": []})
    denied = authorize(
        tmp_path,
        tool="read",
        path=str(other),
        agent="ascendc-pilot",
    )
    assert denied.get("ok") is False
