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
            "semantic_enrichment.yaml status must be pending, complete, or degraded",
        ],
    )
    assert c["failure_class"] == ENVIRONMENT_INVARIANT
    assert c["retryable"] is False
    assert c["recommended_transition"] == "human_required"


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
                    "semantic_enrichment.yaml status must be pending, complete, or degraded",
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
            "semantic_enrichment.yaml status must be pending, complete, or degraded",
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
    # Paths outside the failed Action's contract must stay denied.
    # (Contract-matched IR under prepare may be allowed as CONTAINMENT_INSPECT_READ.)
    for tool, path in [
        ("read", str(tmp_path / "engines" / "understand-operator" / "prepare_operator.py")),
        ("grep", "finalize_scope"),
    ]:
        verdict = authorize(tmp_path, tool=tool, path=path, agent="ascendc-pilot")
        assert verdict.get("ok") is False
        assert verdict.get("error_code") == "HARNESS_ACTION_NOT_AUTHORIZED"
        assert verdict.get("decision") == "deny"


def test_build_agent_passthrough_during_containment(tmp_path: Path):
    """Tab→Build must escape harness even with human_required leftover run."""
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    record_pilot_result(
        tmp_path,
        ok=False,
        action_id="prepare",
        step_id="uo_scope_finalize",
        messages=["installed_skill_check.consistent is not true"],
        source="uo_scope",
    )
    for agent in ("Build", "build", "plan", "Plan"):
        v = authorize(tmp_path, tool="bash", command="dir", agent=agent)
        assert v.get("decision") == "allow", (agent, v)
        assert v.get("reason_code") == "HARNESS_INACTIVE"
        v2 = authorize(
            tmp_path,
            tool="write",
            path=str(tmp_path / "notes.txt"),
            agent=agent,
        )
        assert v2.get("decision") == "allow", (agent, v2)
    deny = authorize(tmp_path, tool="bash", command="dir", agent="ascendc-pilot")
    assert deny.get("decision") == "deny"


def test_write_formal_artifact_denied_after_failure(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    record_pilot_result(
        tmp_path,
        ok=False,
        action_id="prepare",
        step_id="uo_scope_finalize",
        messages=["semantic_enrichment.yaml status must be pending, complete, or degraded"],
        source="uo_scope",
    )
    targets = [
        tmp_path / ".ascendc-pilot" / "uo" / "runs" / "r" / "scope" / "installed_skill_check.yaml",
        tmp_path / ".ascendc-pilot" / "uo" / "runs" / "r" / "scope" / "semantic_enrichment.yaml",
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


def test_direct_domain_script_denied_after_failure(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    record_pilot_result(
        tmp_path,
        ok=False,
        action_id="prepare",
        step_id="uo_scope_finalize",
        messages=["installed_skill_check.consistent is not true"],
        source="uo_scope",
    )
    for cmd in [
        "python prepare_operator.py",
        "python macro_scope_scan.py --project .",
        "python3 review_checkpoint.py",
        "python engines/understand-operator/uo/scripts/finalize_scope.py",
    ]:
        verdict = authorize(tmp_path, tool="bash", command=cmd, agent="ascendc-pilot")
        assert verdict.get("ok") is False
        assert verdict.get("error_code") == "HARNESS_ACTION_NOT_AUTHORIZED"


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


def test_ses_0711_replay_finalize_containment(tmp_path: Path):
    """Replay the ses_0711 failure shape: finalize fails → only recovery commands legal."""
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    issue_action_lease(tmp_path, action_id="prepare", mode="normal")

    # Simulate earlier successful domain steps having run (state still running).
    assert load_state(tmp_path)["status"] == "running"

    with patch(
        "uo_init.pilot_engines.ENGINES",
        {
            "scope_validate": lambda _root, _ctx: {
                "ok": False,
                "messages": [
                    "installed_skill_check.consistent is not true",
                    "semantic_enrichment.yaml status must be pending, complete, or degraded",
                ],
            }
        },
    ):
        from ascendc_pilot.uo_scope import run_uo_scope

        fin = run_uo_scope(tmp_path, "validate", op_name=tmp_path.name)

    assert fin.get("status") == "human_required" or (fin.get("applied") or {}).get("ok") is False
    st = load_state(tmp_path)
    assert st["status"] == "human_required"
    assert st["phase"] == "prepare"

    nxt = describe_next(tmp_path)
    assert nxt["allowed_actions"] == []
    assert nxt["status"] == "human_required"

    # Legal recovery bash
    for cmd in [
        "acp next --project .",
        "acp inspect-failure --project .",
        "acp retry-after-environment-fix --project .",
        "acp abort --project .",
        "acp status --project .",
    ]:
        v = authorize(tmp_path, tool="bash", command=cmd, agent="ascendc-pilot")
        assert v.get("ok") is True, cmd

    # Illegal after failure
    illegal = [
        ("glob", str(tmp_path / ".ascendc-pilot" / "uo" / "**"), ""),
        ("grep", "prepare_operator", ""),
        ("read", str(tmp_path / "engines" / "understand-operator" / "uo" / "scripts" / "prepare_operator.py"), ""),
        ("write", str(tmp_path / ".ascendc-pilot" / "uo" / "manifest.yaml"), ""),
        ("bash", "", "python prepare_operator.py"),
        ("bash", "", "acp uo-scope scan --project ."),
        ("bash", "", "acp run-action prepare --project ."),
        ("bash", "", "acp advance extract --project ."),
    ]
    for tool, path, cmd in illegal:
        v = authorize(
            tmp_path,
            tool=tool,
            path=path,
            command=cmd,
            agent="ascendc-pilot",
            action="prepare",
        )
        assert v.get("ok") is False, (tool, path, cmd)
        assert v.get("error_code") == "HARNESS_ACTION_NOT_AUTHORIZED"


def test_observation_persisted_to_run_dir(tmp_path: Path):
    start_workflow(tmp_path, "uo-init", phase="prepare", force_phase=True, architecture="arch35")
    obs = build_observation(
        tmp_path,
        outcome="failed",
        action_id="prepare",
        step_id="uo_scope_finalize",
        messages=["semantic_enrichment.yaml status must be pending, complete, or degraded"],
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
