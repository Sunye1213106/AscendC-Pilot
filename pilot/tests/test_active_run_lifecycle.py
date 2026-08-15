"""Active-run pointer + multi-architecture lifecycle regressions."""

from __future__ import annotations

import os
from pathlib import Path

from ascendc_pilot.active_run import active_architecture, active_run_path, read_active_run
from ascendc_pilot.host_context import build_host_context
from ascendc_pilot.paths import discover_arch, ensure_agent_layout, state_root
from ascendc_pilot.state import load_state, start_workflow
from ascendc_pilot.state.machine import describe_next


def _clear_arch_env(monkeypatch) -> None:
    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        monkeypatch.delenv(key, raising=False)


def test_start_writes_active_run_pointer(tmp_path: Path, monkeypatch) -> None:
    _clear_arch_env(monkeypatch)
    ensure_agent_layout(tmp_path, arch="arch35")
    state = start_workflow(tmp_path, "uo-init", architecture="arch35")
    doc = read_active_run(tmp_path)
    assert doc is not None
    assert doc.get("architecture") == "arch35"
    assert doc.get("run_id") == state["run_id"]
    assert doc.get("workflow_id") == "uo-init"
    assert active_run_path(tmp_path).is_file()


def test_multiarch_active_run_selects_current_not_ambiguous(
    tmp_path: Path, monkeypatch
) -> None:
    """arch22 historical + arch35 current → discover/host-context/next use arch35."""
    _clear_arch_env(monkeypatch)
    ensure_agent_layout(tmp_path, arch="arch22")
    ensure_agent_layout(tmp_path, arch="arch35")

    start_workflow(tmp_path, "uo-init", architecture="arch22")
    _clear_arch_env(monkeypatch)
    assert (state_root(tmp_path, arch="arch22") / "workflow.yaml").is_file()

    state35 = start_workflow(tmp_path, "uo-init", architecture="arch35")
    _clear_arch_env(monkeypatch)

    assert active_architecture(tmp_path) == "arch35"
    assert discover_arch(tmp_path) == "arch35"

    st = load_state(tmp_path)
    assert st.get("architecture") == "arch35"
    assert st.get("run_id") == state35["run_id"]

    ctx = build_host_context(tmp_path, architecture="")
    assert ctx.get("ok") is True
    assert ctx.get("architecture") == "arch35"
    assert ctx.get("run_id") == state35["run_id"]
    assert "arch35" in str(ctx.get("workflow_state_path") or "")

    nxt = describe_next(tmp_path)
    assert nxt.get("ok") is not False or "workflow" in str(nxt).lower()
    # describe_next returns ok True with allowed actions when running.
    assert load_state(tmp_path).get("architecture") == "arch35"


def test_ensure_agent_layout_without_arch_uses_active_run(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression: run-action → run_dir → ensure_agent_layout() with no arch.

    After ``acp start --architecture arch35``, active_run is pinned. Subsequent
    helpers must discover that arch without requiring UO_ARCH env.
    """
    from ascendc_pilot.runs import run_dir

    _clear_arch_env(monkeypatch)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    state = start_workflow(tmp_path, "uo-init", architecture="arch35")
    _clear_arch_env(monkeypatch)

    ensure_agent_layout(tmp_path)  # no arch= — must use active_run
    path = run_dir(tmp_path, state["run_id"])
    assert "arch35" in path.as_posix()
    assert path.is_dir()
    _clear_arch_env(monkeypatch)
    ensure_agent_layout(tmp_path, arch="arch22")
    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "uo-init", architecture="arch22")
    _clear_arch_env(monkeypatch)
    start_workflow(tmp_path, "uo-query", architecture="arch35")
    _clear_arch_env(monkeypatch)
    from ascendc_pilot.active_run import clear_active_run

    assert active_architecture(tmp_path) == "arch22"
    start_workflow(tmp_path, "tg-init", architecture="arch35")
    _clear_arch_env(monkeypatch)

    # Wipe pointer → two exclusive trees remain, no active selection.
    clear_active_run(tmp_path)
    try:
        discover_arch(tmp_path)
        raise AssertionError("expected ARCHITECTURE_AMBIGUOUS")
    except ValueError as exc:
        assert "ARCHITECTURE_AMBIGUOUS" in str(exc) or "multiple architectures" in str(exc)

    ctx = build_host_context(tmp_path, architecture="")
    assert ctx.get("ok") is False
    assert ctx.get("error") == "ARCHITECTURE_AMBIGUOUS"


def test_cross_process_helpers_use_active_run_not_env_only(
    tmp_path: Path, monkeypatch
) -> None:
    """Same class of bug as migrate/ensure: helpers that used resolve_arch(None).

    Simulates a fresh ``acp`` subprocess after start: no UO_ARCH, but
    active_run.yaml is on disk.
    """
    from ascendc_pilot.actions.engines import _resolve_tg_ctx
    from ascendc_pilot.paths import uo_codemap_path
    from ascendc_pilot.workspace import OperatorWorkspace

    _clear_arch_env(monkeypatch)
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    _clear_arch_env(monkeypatch)  # drop in-process pin from start_workflow

    tg = _resolve_tg_ctx(tmp_path, {"op_name": tmp_path.name})
    assert tg.get("architecture") == "arch35"

    ws = OperatorWorkspace.resolve(tmp_path, allow_pilot_checkout=True)
    assert ws.arch == "arch35"

    codemap = uo_codemap_path(tmp_path, tmp_path.name)
    assert ".arch35.uo" in codemap.name
