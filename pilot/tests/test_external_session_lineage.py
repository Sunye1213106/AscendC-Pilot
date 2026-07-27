"""Control-plane external session registry and resume lineage."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ascendc_pilot.actions.action_dispatch import prepare_resume_fields, record_continuation
from ascendc_pilot.actions.external_session_registry import (
    latest_external_session,
    load_registry,
    patch_external_session_id,
    register_external_session,
)
from ascendc_pilot.debug import is_enabled, patch_child_session_id, register_child, set_enabled


def _seed_active(tmp_path: Path, run_id: str = "r1", action_id: str = "adjudicate_llm_tasks") -> None:
    state = tmp_path / ".ascendc-pilot" / "state"
    state.mkdir(parents=True)
    (state / "active_action.yaml").write_text(
        f"run_id: {run_id}\naction_id: {action_id}\n", encoding="utf-8"
    )


def test_debug_off_real_patch_child_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ASCENDC_DEBUG", "0")
    assert is_enabled(tmp_path) is False
    _seed_active(tmp_path)
    out = register_child(
        tmp_path,
        parent_session_id="ses_primary",
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        dispatch_nonce="nonce_a",
    )
    assert out.get("ok") is True
    assert out.get("control_plane") is True
    # Pending registration has no bound child yet.
    latest = latest_external_session(tmp_path, run_id="r1", action_id="adjudicate_llm_tasks")
    assert latest.get("external_task_session_id") in {"", None}
    reg = load_registry(tmp_path, "r1", "adjudicate_llm_tasks")
    pending = [s for s in reg["sessions"] if not s.get("external_task_session_id")]
    assert len(pending) == 1

    patched = patch_child_session_id(
        tmp_path,
        child_session_id="ses_child_a",
        parent_session_id="ses_primary",
        action_id="adjudicate_llm_tasks",
        run_id="r1",
        registration_id=str(out.get("registration_id") or ""),
        dispatch_nonce="nonce_a",
    )
    assert patched.get("ok") is True, patched
    assert patched.get("control_plane") is True
    latest = latest_external_session(tmp_path, run_id="r1", action_id="adjudicate_llm_tasks")
    assert latest.get("external_task_session_id") == "ses_child_a"

    fields = prepare_resume_fields(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        workflow_status="rework_required",
    )
    assert fields["resume_required"] is True
    assert fields["resume_session_id"] == "ses_child_a"
    assert fields["resume_session_id"] != "ses_primary"


def test_debug_on_updates_external_and_mirror(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ASCENDC_DEBUG", "1")
    set_enabled(tmp_path, True)
    _seed_active(tmp_path)
    out = register_child(
        tmp_path,
        parent_session_id="ses_primary",
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        dispatch_nonce="nonce_dbg",
    )
    assert out.get("debug_mirrored") is True
    patched = patch_child_session_id(
        tmp_path,
        child_session_id="ses_child_dbg",
        parent_session_id="ses_primary",
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        registration_id=str(out.get("registration_id") or ""),
        dispatch_nonce="nonce_dbg",
    )
    assert patched.get("ok") is True
    assert patched.get("debug_mirrored") is True
    latest = latest_external_session(tmp_path, run_id="r1", action_id="adjudicate_llm_tasks")
    assert latest.get("external_task_session_id") == "ses_child_dbg"


def test_dispatch_nonce_cas(tmp_path: Path) -> None:
    reg = register_external_session(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        primary_session_id="ses_primary",
        dispatch_nonce="nonce_good",
    )
    bad = patch_external_session_id(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        external_task_session_id="ses_wrong",
        registration_id="",
        dispatch_nonce="nonce_other",
    )
    assert bad.get("ok") is False
    assert bad.get("error") == "registration_not_found"
    good = patch_external_session_id(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        external_task_session_id="ses_child",
        registration_id=str(reg.get("registration_id") or ""),
        dispatch_nonce="nonce_good",
    )
    assert good.get("ok") is True
    again = patch_external_session_id(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        external_task_session_id="ses_child",
        registration_id=str(reg.get("registration_id") or ""),
        dispatch_nonce="nonce_good",
    )
    assert again.get("ok") is True
    assert again.get("duplicate") is True or again.get("status") == "already_patched"


def test_concurrent_external_session_registration(tmp_path: Path) -> None:
    def _one(i: int) -> dict:
        return register_external_session(
            tmp_path,
            run_id="r1",
            action_id="adjudicate_llm_tasks",
            primary_session_id="ses_primary",
            dispatch_nonce=f"nonce_c_{i}",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_one, range(12)))
    assert all(r.get("ok") for r in results), results
    reg = load_registry(tmp_path, "r1", "adjudicate_llm_tasks")
    ids = {s.get("registration_id") for s in reg["sessions"]}
    nonces = {s.get("dispatch_nonce") for s in reg["sessions"]}
    assert len(ids) == 12
    assert len(nonces) == 12
    assert "" not in ids


def test_same_primary_does_not_verify_resume(tmp_path: Path) -> None:
    register_external_session(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        primary_session_id="ses_primary",
        external_task_session_id="ses_a",
    )
    cont = record_continuation(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        external_task_session_id="ses_b",
        primary_session_id="ses_primary",
        previous_external_task_session_id="ses_a",
        host_reported_resumed_from="",
    )
    assert cont["continuation_mode"] == "fork_with_context"
    assert cont["lineage_verified"] is False


def test_resume_verified_only_when_host_points_to_previous_child(tmp_path: Path) -> None:
    cont = record_continuation(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        external_task_session_id="ses_b",
        primary_session_id="ses_primary",
        previous_external_task_session_id="ses_a",
        host_reported_resumed_from="ses_a",
    )
    assert cont["continuation_mode"] == "resume"
    assert cont["lineage_verified"] is True


def test_prepare_resume_reads_control_plane(tmp_path: Path) -> None:
    register_external_session(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        primary_session_id="ses_primary",
        dispatch_nonce="nonce_resume",
    )
    patched = patch_external_session_id(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        external_task_session_id="ses_prev",
        primary_session_id="ses_primary",
        dispatch_nonce="nonce_resume",
    )
    assert patched.get("ok") is True, patched
    fields = prepare_resume_fields(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        workflow_status="rework_required",
    )
    assert fields["resume_required"] is True
    assert fields["resume_session_id"] == "ses_prev"


def test_patch_without_pending_registration_fails_closed(tmp_path: Path) -> None:
    bad = patch_external_session_id(
        tmp_path,
        run_id="r1",
        action_id="adjudicate_llm_tasks",
        external_task_session_id="ses_orphan",
        primary_session_id="ses_primary",
    )
    assert bad.get("ok") is False
    assert bad.get("error") == "no_pending_registration"


def _mp_register_worker(root: str, i: int, q) -> None:
    from pathlib import Path

    from ascendc_pilot.actions.external_session_registry import register_external_session

    q.put(
        register_external_session(
            Path(root),
            run_id="r1",
            action_id="adjudicate_llm_tasks",
            primary_session_id="ses_primary",
            dispatch_nonce=f"nonce_mp_{i}",
        )
    )


def test_concurrent_external_session_registration_multiprocess(tmp_path: Path) -> None:
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_mp_register_worker, args=(str(tmp_path), i, q)) for i in range(6)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0, p.exitcode
    results = [q.get(timeout=5) for _ in range(6)]
    assert all(r.get("ok") for r in results), results
    reg = load_registry(tmp_path, "r1", "adjudicate_llm_tasks")
    assert len({s.get("registration_id") for s in reg["sessions"]}) == 6
