# -*- coding: utf-8 -*-
"""host-context must not remap Primary onto a finalized producer actor."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.host_context import _active_action_payload, build_host_context
from ascendc_pilot.paths import ensure_agent_layout, state_root
from ascendc_pilot.state import start_workflow


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_active_action_payload_suppresses_actor_when_finalized(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    active = state_root(tmp_path, arch="arch35") / "active_action.yaml"
    _write(
        active,
        "action_id: verify\n"
        "actor_id: deterministic-uo-engine\n"
        "status: finalized\n",
    )
    payload = _active_action_payload(tmp_path, arch="arch35")
    assert payload["action_id"] == "verify"
    assert payload["status"] == "finalized"
    assert payload["actor_id"] == ""


def test_active_action_payload_keeps_actor_when_prepared(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch35")
    active = state_root(tmp_path, arch="arch35") / "active_action.yaml"
    _write(
        active,
        "action_id: verify\n"
        "actor_id: deterministic-uo-engine\n"
        "status: prepared\n",
    )
    payload = _active_action_payload(tmp_path, arch="arch35")
    assert payload["actor_id"] == "deterministic-uo-engine"
    assert payload["status"] == "prepared"


def test_host_context_finalized_clears_actor_for_complete(tmp_path: Path) -> None:
    (tmp_path / "op_host" / "arch35").mkdir(parents=True)
    start_workflow(tmp_path, "uo-init", architecture="arch35")
    active = state_root(tmp_path, arch="arch35") / "active_action.yaml"
    _write(
        active,
        "action_id: verify\n"
        "actor_id: deterministic-uo-engine\n"
        "status: finalized\n",
    )
    ctx = build_host_context(tmp_path, architecture="arch35")
    assert ctx.get("ok") is True
    assert ctx.get("active_action_status") == "finalized"
    assert ctx.get("actor_id") == ""
    assert ctx.get("action_id") == "verify"
