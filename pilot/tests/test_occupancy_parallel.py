"""UO-bound product locks: parallel families, shared query, digest STALE."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ascendc_pilot.actions.runtime import finalize_action, prepare_action
from ascendc_pilot.occupancy import (
    SESSION_ENV,
    apply_stale_confidence,
    bind_session,
    get_session_binding,
    list_shared_runs,
    live_exclusive_lock,
    migrate_legacy_slot,
    occupancy_status_payload,
    product_locks_path,
    publish_uo_digest,
    read_product_locks,
    session_bindings_path,
    shared_live_state_path,
    slot_state_path,
)
from ascendc_pilot.paths import ensure_agent_layout, state_root
from ascendc_pilot.run_resume import needs_resume_decision
from ascendc_pilot.state import load_state, release_live_execution, start_workflow


@pytest.fixture(autouse=True)
def _isolate_control_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "UO_ARCH",
        "ASCENDC_ARCH",
        "ASCENDC_ARCHITECTURE",
        SESSION_ENV,
        "ASCENDC_WORKFLOW_ID",
    ):
        monkeypatch.delenv(key, raising=False)


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_uo_init_live_does_not_block_tg_init(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    uo = start_workflow(tmp_path, "uo-init", architecture="arch35")
    assert needs_resume_decision(tmp_path, "tg-init") is False
    tg = start_workflow(tmp_path, "tg-init", architecture="arch35")
    assert tg.get("ok") is True
    uo_slot = slot_state_path(tmp_path, "uo", arch="arch35")
    tg_slot = slot_state_path(tmp_path, "tg", arch="arch35")
    assert uo_slot.is_file()
    assert tg_slot.is_file()
    assert load_state(tmp_path, workflow_id="uo-init")["run_id"] == uo["run_id"]
    assert load_state(tmp_path, workflow_id="tg-init")["run_id"] == tg["run_id"]
    assert live_exclusive_lock(tmp_path, "uo")
    assert live_exclusive_lock(tmp_path, "tg")


def test_uo_query_start_does_not_take_exclusive_lock(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-query", architecture="arch35")
    assert live_exclusive_lock(tmp_path, "uo") is None
    locks = read_product_locks(tmp_path)
    assert not (locks.get("locks") or {})
    assert list_shared_runs(tmp_path)


def test_finalize_kb_lookup_releases_ephemeral_query(tmp_path: Path) -> None:
    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    uo_prod = op / ".ascendc-pilot" / "arch35" / "uo"
    uo_prod.mkdir(parents=True, exist_ok=True)
    (uo_prod / "Demo.arch35.uo").write_bytes(b"SQLite format 3\x00")
    started = start_workflow(op, "uo-query", architecture="arch35", intent="q?")
    prep = prepare_action(op, "kb_lookup")
    assert prep.get("ok"), prep
    fin = finalize_action(op, "kb_lookup")
    assert fin.get("ok") is True, fin
    assert (fin.get("complete") or {}).get("ok") is True
    assert not load_state(op, workflow_id="uo-query")
    live = shared_live_state_path(op, started["run_id"], arch="arch35")
    assert not live.is_file()


def test_two_query_runs_can_coexist(tmp_path: Path, monkeypatch) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    monkeypatch.setenv(SESSION_ENV, "ses_a")
    a = start_workflow(tmp_path, "uo-query", architecture="arch35")
    monkeypatch.setenv(SESSION_ENV, "ses_b")
    b = start_workflow(tmp_path, "uo-query", architecture="arch35")
    assert a["run_id"] != b["run_id"]
    assert shared_live_state_path(tmp_path, a["run_id"], arch="arch35").is_file()
    assert shared_live_state_path(tmp_path, b["run_id"], arch="arch35").is_file()
    runs = list_shared_runs(tmp_path)
    assert {row.get("run_id") for row in runs} >= {a["run_id"], b["run_id"]}


def test_uo_update_publish_marks_binding_stale_and_caps_confidence(
    tmp_path: Path, monkeypatch
) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    monkeypatch.setenv(SESSION_ENV, "ses_old")
    bind_session(
        tmp_path,
        session_id="ses_old",
        architecture="arch35",
        uo_path="/.ascendc-pilot/arch35/uo/Demo.arch35.uo",
        digest="digest-old",
        workflow_id="uo-query",
        stale=False,
    )
    published = publish_uo_digest(
        tmp_path, architecture="arch35", digest="digest-new"
    )
    assert "ses_old" in (published.get("stale_sessions") or [])
    binding = get_session_binding(tmp_path, "ses_old")
    assert binding and binding.get("stale") is True
    capped = apply_stale_confidence(
        {"ok": True, "confidence": "high", "answer": {"confidence": "source_verified"}},
        tmp_path,
        architecture="arch35",
        session_id="ses_old",
    )
    assert capped.get("confidence") == "medium"
    assert capped["answer"]["confidence"] == "medium"
    assert capped.get("reason_code") == "UO_DIGEST_CHANGED"
    assert capped.get("uo_freshness", {}).get("stale") is True


def test_same_family_second_start_still_needs_decision(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    assert needs_resume_decision(tmp_path, "uo-init") is True
    assert needs_resume_decision(tmp_path, "uo-update") is True
    assert needs_resume_decision(tmp_path, "uo-query") is False


def test_release_clears_session_occupancy(tmp_path: Path, monkeypatch) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    monkeypatch.setenv(SESSION_ENV, "ses_done")
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    bound = get_session_binding(tmp_path, "ses_done")
    assert bound and bound.get("occupancy_group") == "uo"
    release_live_execution(
        tmp_path, reason="workflow_passed", state=load_state(tmp_path)
    )
    assert live_exclusive_lock(tmp_path, "uo") is None
    bound = get_session_binding(tmp_path, "ses_done")
    assert bound
    assert bound.get("occupancy_group") == ""
    assert bound.get("released") is True


def test_legacy_active_run_migrates_into_uo_slot(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    legacy = state_root(tmp_path, arch="arch35") / "workflow.yaml"
    _write(
        legacy,
        {
            "workflow_id": "uo-init",
            "run_id": "RUN_LEGACY",
            "architecture": "arch35",
            "status": "running",
            "phase": "prepare",
        },
    )
    migrated = migrate_legacy_slot(tmp_path, arch="arch35")
    assert migrated.get("migrated") is True
    slot = slot_state_path(tmp_path, "uo", arch="arch35")
    assert slot.is_file()
    lock = live_exclusive_lock(tmp_path, "uo")
    assert lock and lock.get("run_id") == "RUN_LEGACY"
    assert product_locks_path(tmp_path).is_file()


def test_occupancy_status_exposes_binding_and_locks(
    tmp_path: Path, monkeypatch
) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    monkeypatch.setenv(SESSION_ENV, "ses_status")
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    assert session_bindings_path(tmp_path).is_file()
    payload = occupancy_status_payload(tmp_path)
    assert "uo" in (payload.get("product_locks") or {})
    assert (payload.get("session_binding") or {}).get("session_id") == "ses_status"


def test_ce_apply_can_run_parallel_with_tg_solve_on_snapshot(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    tg = start_workflow(tmp_path, "tg-solve", architecture="arch35", phase="gate", force_phase=True)
    ce = start_workflow(tmp_path, "ce-apply", architecture="arch35")
    assert tg.get("ok") is True
    assert ce.get("ok") is True


def test_ce_apply_conflicts_with_uo_update(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-update", architecture="arch35")
    with pytest.raises(RuntimeError, match="资源事务冲突"):
        start_workflow(tmp_path, "ce-apply", architecture="arch35")


def test_resource_sets_uo_init_does_not_conflict_tg_init() -> None:
    from ascendc_pilot.workflows.specs import resource_sets_conflict

    assert resource_sets_conflict("uo-init", "tg-init") is False
    assert resource_sets_conflict("ce-apply", "tg-solve") is False
    assert resource_sets_conflict("ce-apply", "uo-update") is True

