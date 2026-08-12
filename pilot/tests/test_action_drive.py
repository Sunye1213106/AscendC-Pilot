"""Control-plane tests for deterministic auto-dispatch."""

from __future__ import annotations

from pathlib import Path


def test_drive_drains_full_uo_pipeline_without_host_engine_guess(monkeypatch, tmp_path: Path):
    import ascendc_pilot.state as state_mod
    import ascendc_pilot.workflows as workflows_mod
    from ascendc_pilot.actions.drive import drive_until_interaction

    phases = ["prepare", "extract", "analyze", "commit", "verify"]
    action_for_phase = {phase: phase for phase in phases}
    current = {"workflow_id": "uo-init", "phase": "prepare", "status": "running"}
    done: set[str] = set()

    transitions = [
        {"from": phases[i], "to": phases[i + 1], "kind": "forward"}
        for i in range(len(phases) - 1)
    ]
    meta = {
        "transitions": transitions,
        "terminal_ready_states": ["verify"],
    }

    def load_state(_root: Path):
        return dict(current)

    def describe_next(_root: Path):
        action_id = action_for_phase[current["phase"]]
        if action_id not in done:
            return {
                "ok": True,
                "recommended_next_action": {
                    "id": action_id,
                    "reason": "pipeline_incomplete",
                },
            }
        return {
            "ok": True,
            "recommended_next_action": {
                "id": None,
                "reason": "pipeline_complete",
            },
        }

    def advance_phase(_root: Path, target: str):
        current["phase"] = target
        return {"ok": True, "state": dict(current)}

    def complete_workflow(_root: Path):
        current["status"] = "passed"
        return {"ok": True, "state": dict(current)}

    def action_by_id(_workflow_id: str, action_id: str, **_kwargs):
        return {
            "id": action_id,
            "execution_mode": "deterministic",
            "agent_id": "deterministic-uo-engine",
            "role_id": "deterministic_engine",
            "task_prompt_id": None,
            "output_contract_id": f"uo-{action_id}-v1",
        }

    prepared: list[str] = []

    def prepare(_root: Path, action_id: str):
        prepared.append(action_id)
        done.add(action_id)
        return {"ok": True, "auto_finalize": True}

    monkeypatch.setattr(state_mod, "load_state", load_state)
    monkeypatch.setattr(state_mod, "describe_next", describe_next)
    monkeypatch.setattr(state_mod, "advance_phase", advance_phase)
    monkeypatch.setattr(state_mod, "complete_workflow", complete_workflow)
    monkeypatch.setattr(workflows_mod, "action_by_id", action_by_id)
    monkeypatch.setattr(workflows_mod, "get_workflow", lambda *_args, **_kwargs: meta)

    result = drive_until_interaction(tmp_path, prepare=prepare)

    assert result["ok"] is True
    assert result["stop_reason"] == "workflow_complete"
    assert result["status"] == "passed"
    assert prepared == phases
    assert all(
        row.get("actor_id") == "deterministic-uo-engine"
        for row in result["executed"]
        if row.get("action_id")
    )
    sync = ((result.get("todo") or {}).get("todo_sync") or {})
    assert sync.get("force") is True
    assert sync.get("after_auto") is True
    assert "立刻" in str(sync.get("instruction_zh") or "")


def test_drive_stops_before_tg_llm_actor(monkeypatch, tmp_path: Path):
    import ascendc_pilot.state as state_mod
    import ascendc_pilot.workflows as workflows_mod
    from ascendc_pilot.actions.drive import drive_until_interaction

    state = {"workflow_id": "tg-solve", "phase": "lemma", "status": "running"}
    monkeypatch.setattr(state_mod, "load_state", lambda _root: dict(state))
    monkeypatch.setattr(
        state_mod,
        "describe_next",
        lambda _root: {
            "ok": True,
            "recommended_next_action": {
                "id": "lemma_mine",
                "reason": "pipeline_incomplete",
            },
        },
    )
    monkeypatch.setattr(
        workflows_mod,
        "action_by_id",
        lambda *_args, **_kwargs: {
            "id": "lemma_mine",
            "execution_mode": "subagent",
            "agent_id": "tg-lemma-producer",
            "role_id": "producer",
            "task_prompt_id": "tg/lemma-mine",
            "output_contract_id": "lemma-mine-v1",
        },
    )

    called = False

    def prepare(_root: Path, _action_id: str):
        nonlocal called
        called = True
        return {"ok": True}

    result = drive_until_interaction(tmp_path, prepare=prepare)

    assert result["ok"] is True
    assert result["stop_reason"] == "interaction_required"
    assert result["next"]["actor_id"] == "tg-lemma-producer"
    assert result["next"]["execution_kind"] == "subagent"
    assert result["recommended_command"] == "acp run-action lemma_mine"
    assert called is False
