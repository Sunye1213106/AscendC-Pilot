"""Control-plane soundness trajectories (Wave 3–6)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "engines" / "code-engineering"))

from ascendc_pilot.agents_registry import load_agent_meta
from ascendc_pilot.environment_capabilities import run_source_scope_roots
from ascendc_pilot.local_extension import bootstrap_local_capability
from ascendc_pilot.occupancy import publish_uo_digest, bind_session, get_session_binding, SESSION_ENV
from ascendc_pilot.paths import ensure_agent_layout
from ascendc_pilot.router import route
from ascendc_pilot.source_snapshot import materialize_source_snapshot
from ascendc_pilot.state import start_workflow
from ascendc_pilot.user_goal import (
    GOAL_CE_CHANGE,
    ensure_goal_for_intent,
    mark_workflow_passed,
    route_natural_goal,
)
from ascendc_pilot.workflows.specs import resource_sets_conflict, WORKFLOWS


def _dump(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_two_session_families_do_not_share_lease_slot() -> None:
    assert resource_sets_conflict("tg-solve", "ce-plan") is False
    assert resource_sets_conflict("tg-solve", "ce-apply") is False


def test_snapshot_isolates_tg_solve_from_ce_apply(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ASCENDC_SNAPSHOT_CACHE", str(tmp_path / "cache"))
    (tmp_path / "op_host").mkdir()
    (tmp_path / "op_host" / "a.cpp").write_text("int x;\n", encoding="utf-8")
    ident = materialize_source_snapshot(tmp_path)
    assert ident.get("ok") is True
    assert Path(ident["workspace_path"]).is_dir()
    assert resource_sets_conflict("ce-apply", "tg-solve") is False
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "tg-solve", architecture="arch35", phase="gate", force_phase=True)
    start_workflow(tmp_path, "ce-apply", architecture="arch35")


def test_source_snapshot_copies_uncommitted_overlay(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    monkeypatch.setenv("ASCENDC_SNAPSHOT_CACHE", str(tmp_path / "cache"))
    host = tmp_path / "op_host"
    host.mkdir()
    src = host / "a.cpp"
    src.write_text("int x;\n", encoding="utf-8")
    git_kw = {"cwd": tmp_path, "check": True, "capture_output": True, "text": True, "encoding": "utf-8"}
    subprocess.run(["git", "init"], **git_kw)
    subprocess.run(["git", "add", "op_host/a.cpp"], **git_kw)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.t", "commit", "-m", "base"],
        **git_kw,
    )
    src.write_text("int x = 1;\n", encoding="utf-8")
    ident = materialize_source_snapshot(tmp_path)
    copied = Path(ident["workspace_path"]) / "op_host" / "a.cpp"
    assert copied.read_text(encoding="utf-8") == "int x = 1;\n"


def test_harness_failure_certificate_must_fail(tmp_path: Path) -> None:
    from ascendc_pilot.actions.scenario_certificate import evaluate_scenario_certificate

    op = tmp_path / "op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    dest = op / ".ascendc-pilot" / "arch35" / "tg" / "closure" / "scenarios"
    _dump(dest / "construct.yaml", {"scenarios": [{"id": "P-CAST"}]})
    _dump(dest / "harness_results.yaml", {"runs": [{"id": "P-CAST", "ok": False, "reason": "assert"}]})
    cert = evaluate_scenario_certificate(op, architecture="arch35")
    assert cert["ok"] is False
    assert cert["required_harness_receipts_all_pass"] is False


def test_uo_update_marks_old_sessions_stale(tmp_path: Path, monkeypatch) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    monkeypatch.setenv(SESSION_ENV, "ses_old")
    bind_session(
        tmp_path,
        session_id="ses_old",
        architecture="arch35",
        uo_path="/.ascendc-pilot/arch35/uo/Demo.arch35.uo",
        digest="digest-old",
        workflow_id="tg-solve",
        stale=False,
    )
    publish_uo_digest(tmp_path, architecture="arch35", digest="digest-new")
    binding = get_session_binding(tmp_path, "ses_old")
    assert binding and binding.get("stale") is True


def test_investigator_has_bounded_ro_search_not_free_grep() -> None:
    caps = WORKFLOWS["uo-investigate"]["actions"][0]["capability_ids"]
    assert "readonly-source-search" in caps
    meta = load_agent_meta("uo-gap-investigator")
    tags = set(meta.get("machine_constraints") or meta.get("forbidden") or [])
    assert "no_free_repo_search" in tags


def test_ro_search_refuses_repo_root(tmp_path: Path) -> None:
    (tmp_path / "op_host").mkdir()
    roots = run_source_scope_roots(tmp_path)
    assert all(p.name != tmp_path.name or p != tmp_path.resolve() for p in roots) or True
    assert tmp_path.resolve() not in {p.resolve() for p in roots}


def test_goal_router_ce_chain(tmp_path: Path) -> None:
    hit = route_natural_goal("验证这次改动")
    assert hit and hit["workflow_id"] == "ce-plan"
    assert route("验证这次改动").get("method") == "goal_router"
    goal = ensure_goal_for_intent(
        tmp_path,
        intent_text="验证这次改动",
        architecture="arch35",
        workflow_id="ce-plan",
        op_name="DemoOp",
    )
    assert goal and goal["goal_id"] == GOAL_CE_CHANGE
    adv = mark_workflow_passed(tmp_path, "ce-plan")
    assert adv and adv["next_workflow_id"] == "ce-apply"


def test_local_capability_bootstrap_writes_stub(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    out = bootstrap_local_capability(tmp_path, "case_builder", architecture="arch35")
    assert out.get("ok") is True
    impl = Path(out["implementation"])
    assert impl.is_file()
    assert "local" in impl.as_posix()
    assert "run_replay.sh" not in impl.read_text(encoding="utf-8")
