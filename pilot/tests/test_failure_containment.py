"""Failure containment: Observation → state → next → authorize hard deny."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from ascendc_pilot.authorize import authorize
from ascendc_pilot.authorize.lease import (
    issue_action_lease,
    load_lease,
    revoke_active_lease,
)
from ascendc_pilot.observation import (
    ENVIRONMENT_INVARIANT,
    FORMAT_TRANSPORT,
    apply_observation,
    build_observation,
    classify_failure,
    record_pilot_result,
)
from ascendc_pilot.state import describe_next, load_state, save_state, start_workflow


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_classify_uo_scope_finalize_is_environment_invariant():
    c = classify_failure(
        step_id="uo_scope_finalize",
        action_id="prepare",
        source="uo_scope",
        messages=[
            "installed_skill_check.consistent is not true",
        ],
    )
    assert c["failure_class"] == ENVIRONMENT_INVARIANT
    assert c["retryable"] is False
    assert c["recommended_transition"] == "human_required"


def test_classify_plan_ingest_required_is_format_transport_not_human():
    c = classify_failure(
        error_code="PLAN_INGEST_REQUIRED",
        action_id="plan_promote",
        source="finalize_action",
        execution_mode="deterministic",
        workflow_id="tg-plan",
        phase="validate",
        messages=["缺少 Plan Owner YAML"],
    )
    assert c["failure_class"] == FORMAT_TRANSPORT
    assert c["retryable"] is True
    assert c["recommended_transition"] == "rework_required"


def test_classify_cann_env_not_ready_is_environment_invariant():
    c = classify_failure(
        error_code="CANN_ENV_NOT_READY",
        action_id="apply_update",
        source="finalize_action",
        messages=["UO 解析前 CANN 环境未就绪。请设置 UO_CANN_ROOT。"],
    )
    assert c["failure_class"] == ENVIRONMENT_INVARIANT
    assert c["retryable"] is False
    assert c["recommended_transition"] == "human_required"


def test_classify_include_heal_unresolved_reworks_to_propose():
    c = classify_failure(
        error_code="INCLUDE_HEAL_UNRESOLVED",
        action_id="prepare",
        source="finalize_action",
        execution_mode="deterministic",
        workflow_id="uo-init",
        phase="prepare",
        messages=["include-heal 在当前 cann_root 下仍找不到"],
    )
    assert c["recommended_transition"] == "rework_required"
    assert c["retryable"] is True
    assert "propose_include_heal" in (c.get("rework_action_ids") or [])


def test_finalize_failure_updates_state(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    issue_action_lease(tmp_path, action_id="prepare", mode="normal")
    old_lease = load_lease(tmp_path)
    assert old_lease.get("status") == "active"

    with patch(
        "uo_init.pilot_engines.ENGINES",
        {
            "scope_validate": lambda _root, _ctx: {
                "ok": False,
                "messages": [
                    "installed_skill_check.consistent is not true",
                ],
            }
        },
    ):
        from ascendc_pilot.uo_scope import run_uo_scope

        result = run_uo_scope(tmp_path, "validate", op_name=tmp_path.name)

    assert result.get("status") == "human_required" or (result.get("applied") or {}).get("ok") is False
    st = load_state(tmp_path)
    assert st.get("last_failure") is not None
    assert st["status"] == "human_required"
    assert st["last_failure"]["failure_class"] == ENVIRONMENT_INVARIANT
    assert st["last_failure"]["retryable"] is False
    assert st["last_failure"]["error_code"] in {
        "UO_SCOPE_FINALIZE_INVARIANT_FAILED",
        "SCOPE_VALIDATE_VALIDATE_FAILED",
        "UO_SCOPE_VALIDATE_INVARIANT_FAILED",
        "SCOPE_VALIDATE_INVARIANT_FAILED",
    }
    # validate step must still classify as non-retryable environment invariant.
    assert "INVARIANT" in st["last_failure"]["error_code"] or st["last_failure"][
        "failure_class"
    ] == ENVIRONMENT_INVARIANT
    assert st.get("last_observation_id")
    assert st.get("failure_card")
    obs = result.get("observation") or {}
    assert obs.get("outcome") == "failed"
    # Old authorization revoked; containment lease active
    lease = load_lease(tmp_path)
    assert lease.get("mode") == "containment"
    assert lease.get("status") == "active"
    assert old_lease.get("lease_id") != lease.get("lease_id")


def test_next_after_failure_no_normal_actions(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    record_pilot_result(
        tmp_path,
        ok=False,
        action_id="prepare",
        step_id="uo_scope_finalize",
        messages=[
            "installed_skill_check.consistent is not true",
        ],
        source="uo_scope",
    )
    nxt = describe_next(tmp_path)
    assert nxt["status"] == "human_required"
    assert nxt["allowed_actions"] == []
    assert nxt["rework_targets"] == []
    assert "prepare" not in str(nxt.get("allowed_actions"))
    assert nxt.get("human_required", {}).get("required_actor") == "maintainer"
    legal = nxt["human_required"]["legal_actions"]
    assert "inspect_failure" in legal
    assert "abort_run" in legal
    assert nxt.get("needs_human_decision") is True
    ask = nxt.get("ask_question") or {}
    assert ask.get("options")
    values = {o.get("value") for o in ask["options"]}
    assert "retry_after_environment_fix" in values
    assert "abort_run" in values
    lf = nxt.get("last_failure") or {}
    assert lf.get("failure_class") == ENVIRONMENT_INVARIANT


def test_glob_read_denied_after_human_required(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    record_pilot_result(
        tmp_path,
        ok=False,
        action_id="prepare",
        step_id="uo_scope_finalize",
        messages=["installed_skill_check.consistent is not true"],
        source="uo_scope",
    )
    # Engine scripts stay denied (bypass surface).
    verdict = authorize(
        tmp_path,
        tool="read",
        path=str(tmp_path / "engines" / "understand-operator" / "prepare_operator.py"),
        agent="ascendc-pilot",
    )
    assert verdict.get("ok") is False
    assert verdict.get("error_code") == "HARNESS_ACTION_NOT_AUTHORIZED"
    assert verdict.get("decision") == "deny"

    # Primary diagnostic glob of the operator tree is allowed.
    glob_ok = authorize(
        tmp_path,
        tool="glob",
        path=str(tmp_path / "**"),
        agent="ascendc-pilot",
    )
    assert glob_ok.get("decision") == "allow", glob_ok
    assert glob_ok.get("reason_code") == "CONTAINMENT_PRIMARY_READ"


def test_user_prefixed_agents_are_not_pilot_family(tmp_path: Path):
    """User Tabs named ce-helper / tg-playground / uo-personal must not get harness."""
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    for agent in ("ce-helper", "tg-playground", "uo-personal", "ascendc-debug-local"):
        v = authorize(tmp_path, tool="bash", command="dir", agent=agent)
        assert v.get("decision") == "allow", (agent, v)
        assert v.get("reason_code") == "HARNESS_INACTIVE", (agent, v)
        v2 = authorize(
            tmp_path,
            tool="write",
            path=str(tmp_path / "notes.txt"),
            agent=agent,
        )
        assert v2.get("decision") == "allow", (agent, v2)


def test_write_formal_artifact_denied_after_failure(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    record_pilot_result(
        tmp_path,
        ok=False,
        action_id="prepare",
        step_id="uo_scope_finalize",
        messages=["installed_skill_check.consistent is not true"],
        source="uo_scope",
    )
    targets = [
        tmp_path / ".ascendc-pilot" / "uo" / "runs" / "r" / "scope" / "installed_skill_check.yaml",
        tmp_path / ".ascendc-pilot" / "uo" / "manifest.yaml",
        tmp_path / ".ascendc-pilot" / "uo" / "runs" / "r" / "scope" / "scope_validated.yaml",
    ]
    for path in targets:
        before = path.exists()
        content_before = path.read_text(encoding="utf-8") if before else None
        verdict = authorize(
            tmp_path,
            tool="write",
            path=str(path),
            agent="ascendc-pilot",
            action="prepare",
        )
        assert verdict.get("ok") is False
        assert verdict.get("error_code") == "HARNESS_ACTION_NOT_AUTHORIZED"
        # authorize does not execute writes — file unchanged
        if before:
            assert path.read_text(encoding="utf-8") == content_before
        else:
            assert not path.exists()


def test_repeated_retryable_failure_upgrades(tmp_path: Path):
    start_workflow(tmp_path, "uo-investigate", phase="investigate", force_phase=True, architecture="arch35")
    st = load_state(tmp_path)
    st["retry_budget"] = 2
    save_state(tmp_path, st)

    def _fail_once():
        return record_pilot_result(
            tmp_path,
            ok=False,
            action_id="investigate",
            step_id="action_finalize",
            error_code="ACTION_FINALIZE_FAILED_INVESTIGATE",
            messages=["output_contract_failed"],
            source="finalize_action",
            explicit_class="checker_gate",
        )

    r1 = _fail_once()
    assert r1["status"] == "rework_required"
    assert load_state(tmp_path)["no_progress_streak"] == 1

    r2 = _fail_once()
    # streak 2 >= budget 2 → human_required / retry_exhausted
    assert r2["status"] == "human_required"
    assert load_state(tmp_path)["no_progress_streak"] >= 2
    assert load_state(tmp_path)["last_failure"]["failure_class"] in {
        "retry_exhausted",
        ENVIRONMENT_INVARIANT,
        "checker_gate",
    }
    # After upgrade, last_failure should be retry_exhausted
    assert load_state(tmp_path)["last_failure"]["failure_class"] == "retry_exhausted"


def test_deterministic_quality_failure_is_human_required(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="analyze", force_phase=True, architecture="arch35")
    recorded = record_pilot_result(
        tmp_path,
        ok=False,
        action_id="analyze",
        step_id="action_finalize",
        messages=["output_contract_failed"],
        source="finalize_action",
        explicit_class="checker_gate",
        findings=[{"code": "UNROOTED_TILING_KEYS", "message": "Mode::ON is unrooted"}],
    )
    assert recorded["status"] == "human_required"
    nxt = describe_next(tmp_path)
    assert nxt["status"] == "human_required"
    assert nxt["allowed_actions"] == []
    assert nxt["rework_targets"] == []
    legal = nxt["human_required"]["legal_actions"]
    assert "inspect_failure" in legal
    assert "abort_run" in legal
    assert "retry_failed_action" not in legal
    assert "retry_after_environment_fix" not in legal
    lf = nxt.get("last_failure") or {}
    assert lf.get("rework_action_ids") == []
    assert any(f.get("code") == "UNROOTED_TILING_KEYS" for f in (lf.get("findings") or []))


def test_preferred_failure_text_uses_engine_errors_list():
    from ascendc_pilot.actions.failure_text import preferred_failure_text

    text = preferred_failure_text(
        {
            "ok": False,
            "errors": ["mapping prefix: api_arg requires uo_id"],
        }
    )
    assert "prefix" in text
    assert "uo_id" in text


def test_validate_init_mapping_errors_rework_bind(tmp_path: Path):
    start_workflow(tmp_path, "tg-init", phase="validate", force_phase=True, architecture="arch35")
    recorded = record_pilot_result(
        tmp_path,
        ok=False,
        action_id="validate_init",
        step_id="action_finalize",
        error_code="INIT_INVALID",
        messages=["mapping prefix: api_arg requires uo_id"],
        source="finalize_action",
    )
    assert recorded["status"] == "rework_required"
    lf = recorded.get("last_failure") or {}
    assert "bind_init" in (lf.get("rework_action_ids") or [])


def test_llm_checker_failure_reworks_that_action_with_findings(tmp_path: Path):
    start_workflow(tmp_path, "uo-investigate", phase="investigate", force_phase=True, architecture="arch35")
    recorded = record_pilot_result(
        tmp_path,
        ok=False,
        action_id="investigate",
        step_id="action_finalize",
        messages=["output_contract_failed"],
        source="finalize_action",
        explicit_class="checker_gate",
        findings=[{"code": "OUTPUT_CONTRACT_FAILED", "message": "report.yaml missing findings"}],
    )
    assert recorded["status"] == "rework_required"
    nxt = describe_next(tmp_path)
    assert nxt["status"] == "rework_required"
    assert nxt["allowed_actions"] == []
    assert nxt["rework_targets"]
    assert nxt["rework_targets"][0]["action_id"] == "investigate"
    lf = nxt.get("last_failure") or {}
    assert lf.get("rework_action_ids") == ["investigate"]
    assert any(f.get("code") == "OUTPUT_CONTRACT_FAILED" for f in (lf.get("findings") or []))


def test_transient_failure_may_retry_deterministic_action(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="analyze", force_phase=True, architecture="arch35")
    recorded = record_pilot_result(
        tmp_path,
        ok=False,
        action_id="analyze",
        step_id="action_finalize",
        messages=["timeout waiting for clang"],
        source="finalize_action",
        explicit_class="transient_tool",
    )
    assert recorded["status"] == "rework_required"
    nxt = describe_next(tmp_path)
    # Transient retries the failed Action itself; it is not an LLM rework.
    assert nxt["status"] == "rework_required"
    assert nxt["rework_targets"]
    assert nxt["rework_targets"][0]["action_id"] == "analyze"


def test_rework_required_next_returns_targets_only(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="analyze", force_phase=True, architecture="arch35")
    record_pilot_result(
        tmp_path,
        ok=False,
        action_id="analyze",
        step_id="action_finalize",
        messages=["output_contract_failed"],
        source="finalize_action",
        explicit_class="checker_gate",
    )
    nxt = describe_next(tmp_path)
    assert nxt["status"] == "human_required"
    assert nxt["allowed_actions"] == []
    assert nxt["rework_targets"] == []


def test_old_lease_not_reusable(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    lease = issue_action_lease(tmp_path, action_id="prepare", mode="normal")
    lid = str(lease["lease_id"])
    revoke_active_lease(tmp_path, reason="test")
    issue_action_lease(tmp_path, action_id="_containment", mode="containment")

    verdict = authorize(
        tmp_path,
        tool="bash",
        command="acp uo-scope scan",
        agent="ascendc-pilot",
        lease_id=lid,
    )
    assert verdict.get("ok") is False
    assert "LEASE_REVOKED" in str(verdict.get("reason") or "") or verdict.get(
        "error_code"
    ) == "HARNESS_ACTION_NOT_AUTHORIZED"


def test_normal_flow_not_blocked(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    nxt = describe_next(tmp_path)
    assert nxt["status"] == "running"
    assert any(a.get("id") == "prepare" for a in nxt["allowed_actions"])

    # Normal acp CLI allowed
    assert authorize(tmp_path, tool="bash", command="acp next --project .").get("ok") is True
    # Normal project read allowed
    src = tmp_path / "op.cpp"
    _write(src, "int main() { return 0; }\n")
    assert authorize(tmp_path, tool="read", path=str(src), agent="ascendc-pilot").get("ok") is True

    # Prepare issues normal lease
    issue_action_lease(tmp_path, action_id="prepare", mode="normal")
    assert load_lease(tmp_path).get("mode") == "normal"
    assert authorize(
        tmp_path,
        tool="bash",
        command="acp run-action prepare --project .",
        agent="ascendc-pilot",
    ).get("ok") is True


def test_observation_persisted_to_run_dir(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    obs = build_observation(
        tmp_path,
        outcome="failed",
        action_id="prepare",
        step_id="uo_scope_finalize",
        messages=["installed_skill_check.consistent is not true"],
        source="uo_scope",
    )
    applied = apply_observation(tmp_path, obs)
    assert applied.get("ok") is False
    from ascendc_pilot.paths import runs_root

    run_id = load_state(tmp_path)["run_id"]
    run_dir = runs_root(tmp_path) / run_id
    obs_dir = run_dir / "observations"
    assert obs_dir.is_dir()
    assert list(obs_dir.glob("OBS_*.yaml"))
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "ObservationRecorded" in events
    assert "HumanRequired" in events


def test_uo_query_task_allowed_during_containment(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    record_pilot_result(
        tmp_path,
        ok=False,
        action_id="prepare",
        step_id="uo_scope_finalize",
        messages=["installed_skill_check.consistent is not true"],
        source="uo_scope",
    )
    verdict = authorize(
        tmp_path,
        tool="task",
        path="uo-query",
        command="uo-query",
        agent="ascendc-pilot",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") == "TASK_OK"


def test_containment_does_not_follow_other_session(tmp_path: Path, monkeypatch):
    from ascendc_pilot.occupancy import SESSION_ENV, bind_session

    monkeypatch.setenv(SESSION_ENV, "ses_old")
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    state = load_state(tmp_path) or {}
    bind_session(
        tmp_path,
        session_id="ses_old",
        run_id=str(state.get("run_id") or ""),
        workflow_id="uo-init",
        architecture="arch35",
    )
    record_pilot_result(
        tmp_path,
        ok=False,
        action_id="prepare",
        step_id="uo_scope_finalize",
        messages=["installed_skill_check.consistent is not true"],
        source="uo_scope",
    )
    monkeypatch.setenv(SESSION_ENV, "ses_new")
    producer = authorize(
        tmp_path,
        tool="task",
        path="uo-semantic-resolve",
        command="uo-semantic-resolve",
        agent="ascendc-pilot",
    )
    assert producer.get("reason_code") != "HARNESS_ACTION_NOT_AUTHORIZED", producer
    query = authorize(
        tmp_path,
        tool="task",
        path="uo-query",
        command="uo-query",
        agent="ascendc-pilot",
    )
    assert query.get("decision") == "allow", query
