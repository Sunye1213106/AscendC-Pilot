"""Control-plane tests for deterministic auto-dispatch."""

from __future__ import annotations

from pathlib import Path


def test_drive_drains_full_uo_pipeline_without_host_engine_guess(monkeypatch, tmp_path: Path, capsys):
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
    err = capsys.readouterr().err
    assert "[acp-auto] run prepare" in err
    assert "[acp-auto] prepare ok" in err
    assert "still running" not in err
    assert "Select-Object" not in err


def test_drive_stops_before_tg_llm_actor(monkeypatch, tmp_path: Path):
    import ascendc_pilot.state as state_mod
    import ascendc_pilot.workflows as workflows_mod
    from ascendc_pilot.actions.drive import drive_until_interaction

    state = {"workflow_id": "tg-solve", "phase": "construct", "status": "running"}
    monkeypatch.setattr(state_mod, "load_state", lambda _root: dict(state))
    monkeypatch.setattr(
        state_mod,
        "describe_next",
        lambda _root: {
            "ok": True,
            "recommended_next_action": {
                "id": "construct_cases",
                "reason": "pipeline_incomplete",
            },
        },
    )
    monkeypatch.setattr(
        workflows_mod,
        "action_by_id",
        lambda *_args, **_kwargs: {
            "id": "construct_cases",
            "execution_mode": "subagent",
            "agent_id": "tg-analyst",
            "role_id": "producer",
            "task_prompt_id": "tg/construct-cases",
            "output_contract_id": "tg-construct-staging-v1",
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
    assert result["next"]["actor_id"] == "tg-analyst"
    assert result["next"]["execution_kind"] == "subagent"
    assert result["recommended_command"] == "pilot_run"
    assert called is False


def test_drive_continues_when_primary_interactive_autofinalizes(monkeypatch, tmp_path: Path):
    import ascendc_pilot.state as state_mod
    import ascendc_pilot.workflows as workflows_mod
    from ascendc_pilot.actions.drive import drive_until_interaction

    state = {"workflow_id": "tg-plan", "phase": "approve", "status": "running"}
    prepared: list[str] = []

    def describe_next(_root: Path):
        if "plan_approve" in prepared:
            return {
                "ok": True,
                "recommended_next_action": {"id": None, "reason": "pipeline_complete"},
            }
        return {
            "ok": True,
            "recommended_next_action": {
                "id": "plan_approve",
                "reason": "pipeline_incomplete",
            },
        }

    monkeypatch.setattr(state_mod, "load_state", lambda _root: dict(state))
    monkeypatch.setattr(state_mod, "describe_next", describe_next)
    monkeypatch.setattr(
        workflows_mod,
        "action_by_id",
        lambda *_args, **_kwargs: {
            "id": "plan_approve",
            "execution_mode": "primary_interactive",
            "agent_id": "ascendc-pilot",
            "role_id": "controller",
        },
    )
    monkeypatch.setattr(
        workflows_mod,
        "get_workflow",
        lambda *_args, **_kwargs: {
            "transitions": [],
            "terminal_ready_states": ["approve"],
        },
    )
    monkeypatch.setattr(
        state_mod,
        "complete_workflow",
        lambda _root: {"ok": True, "state": {**state, "status": "passed"}},
    )

    def prepare(_root: Path, action_id: str):
        prepared.append(action_id)
        return {"ok": True, "auto_finalize": True, "auto_skip_human_gate": True}

    result = drive_until_interaction(tmp_path, prepare=prepare)
    assert prepared == ["plan_approve"]
    assert result.get("ok") is True
    assert result.get("stop_reason") in {"workflow_complete", "interaction_required"}


def test_drive_continues_when_primary_review_autofinalizes(monkeypatch, tmp_path: Path):
    """PASS must drain bind_promote in the same turn, not stop at primary_review."""
    import ascendc_pilot.state as state_mod
    import ascendc_pilot.workflows as workflows_mod
    from ascendc_pilot.actions.drive import drive_until_interaction

    state = {"workflow_id": "tg-init", "phase": "bind", "status": "running"}
    prepared: list[str] = []

    def describe_next(_root: Path):
        if "bind_promote" in prepared:
            return {
                "ok": True,
                "recommended_next_action": {"id": None, "reason": "pipeline_complete"},
            }
        if "bind_review" in prepared:
            return {
                "ok": True,
                "recommended_next_action": {
                    "id": "bind_promote",
                    "reason": "pipeline_incomplete",
                },
            }
        return {
            "ok": True,
            "recommended_next_action": {
                "id": "bind_review",
                "reason": "pipeline_incomplete",
            },
        }

    def action_by_id(_workflow_id: str, action_id: str, **_kwargs):
        if action_id == "bind_review":
            return {
                "id": "bind_review",
                "execution_mode": "primary_review",
                "agent_id": "ascendc-pilot",
                "role_id": "controller",
            }
        return {
            "id": action_id,
            "execution_mode": "deterministic",
            "agent_id": "deterministic-tg-engine",
            "role_id": "deterministic_engine",
        }

    monkeypatch.setattr(state_mod, "load_state", lambda _root: dict(state))
    monkeypatch.setattr(state_mod, "describe_next", describe_next)
    monkeypatch.setattr(workflows_mod, "action_by_id", action_by_id)
    monkeypatch.setattr(
        workflows_mod,
        "get_workflow",
        lambda *_args, **_kwargs: {
            "transitions": [],
            "terminal_ready_states": ["bind"],
        },
    )
    monkeypatch.setattr(
        state_mod,
        "complete_workflow",
        lambda _root: {"ok": True, "state": {**state, "status": "passed"}},
    )

    def prepare(_root: Path, action_id: str):
        prepared.append(action_id)
        if action_id == "bind_review":
            return {
                "ok": True,
                "auto_finalize": True,
                "message_zh": "主控裁判已放行，本轮继续 bind_promote。",
            }
        return {"ok": True, "auto_finalize": True}

    result = drive_until_interaction(tmp_path, prepare=prepare)
    assert prepared == ["bind_review", "bind_promote"]
    assert result.get("ok") is True
    assert result.get("stop_reason") == "workflow_complete"
    step = result.get("host_step") or {}
    assert step.get("kind") != "primary_review"
    assert step.get("action_id") != "bind_review"


def test_drive_primary_review_stops_without_pass(monkeypatch, tmp_path: Path):
    import ascendc_pilot.state as state_mod
    import ascendc_pilot.workflows as workflows_mod
    from ascendc_pilot.actions.drive import drive_until_interaction

    state = {"workflow_id": "tg-init", "phase": "bind", "status": "running"}
    prepared: list[str] = []
    monkeypatch.setattr(state_mod, "load_state", lambda _root: dict(state))
    monkeypatch.setattr(
        state_mod,
        "describe_next",
        lambda _root: {
            "ok": True,
            "recommended_next_action": {
                "id": "bind_review",
                "reason": "pipeline_incomplete",
            },
        },
    )
    monkeypatch.setattr(
        workflows_mod,
        "action_by_id",
        lambda *_args, **_kwargs: {
            "id": "bind_review",
            "execution_mode": "primary_review",
            "agent_id": "ascendc-pilot",
            "role_id": "controller",
        },
    )

    def prepare(_root: Path, action_id: str):
        prepared.append(action_id)
        return {
            "ok": True,
            "host_step_kind": "primary_review",
            "harness_path": "h.yaml",
            "bind_path": "b.yaml",
            "message_zh": "请通读 harness.yaml 与 bind.yaml。下一发 PASS。",
        }

    result = drive_until_interaction(tmp_path, prepare=prepare)
    assert prepared == ["bind_review"]
    assert result.get("ok") is True
    assert result.get("stop_reason") == "interaction_required"
    assert (result.get("prepare") or {}).get("host_step_kind") == "primary_review"
    step = result.get("host_step") or {}
    assert step.get("kind") == "primary_review"
    assert "PASS" in str(step.get("message_zh") or result.get("message_zh") or "")


def test_drive_continues_when_primary_review_rework(monkeypatch, tmp_path: Path):
    import ascendc_pilot.state as state_mod
    import ascendc_pilot.workflows as workflows_mod
    from ascendc_pilot.actions.drive import drive_until_interaction

    state = {"workflow_id": "tg-init", "phase": "bind", "status": "running"}
    prepared: list[str] = []

    def describe_next(_root: Path):
        if "bind_review" in prepared:
            return {
                "ok": True,
                "recommended_next_action": {
                    "id": "bind_init",
                    "reason": "pipeline_incomplete",
                },
            }
        return {
            "ok": True,
            "recommended_next_action": {
                "id": "bind_review",
                "reason": "pipeline_incomplete",
            },
        }

    def action_by_id(_workflow_id: str, action_id: str, **_kwargs):
        if action_id == "bind_review":
            return {
                "id": "bind_review",
                "execution_mode": "primary_review",
                "agent_id": "ascendc-pilot",
                "role_id": "controller",
            }
        return {
            "id": action_id,
            "execution_mode": "subagent",
            "agent_id": "tg-analyst",
            "role_id": "producer",
        }

    monkeypatch.setattr(state_mod, "load_state", lambda _root: dict(state))
    monkeypatch.setattr(state_mod, "describe_next", describe_next)
    monkeypatch.setattr(workflows_mod, "action_by_id", action_by_id)

    def prepare(_root: Path, action_id: str):
        prepared.append(action_id)
        return {
            "ok": True,
            "continue_drive": True,
            "rework": ["bind"],
            "message_zh": "裁判未通过，只重开 bind 切片。",
        }

    result = drive_until_interaction(tmp_path, prepare=prepare)
    assert prepared == ["bind_review"]
    assert result.get("ok") is True
    assert result.get("stop_reason") == "interaction_required"
    assert (result.get("next") or {}).get("action_id") == "bind_init"
    assert (result.get("next") or {}).get("execution_kind") == "subagent"


def test_drive_continues_when_plan_narrate_autofinalizes(monkeypatch, tmp_path: Path):
    """plan_narrate capture must drain plan_promote in the same turn."""
    import ascendc_pilot.state as state_mod
    import ascendc_pilot.workflows as workflows_mod
    from ascendc_pilot.actions.drive import drive_until_interaction

    state = {"workflow_id": "tg-plan", "phase": "fuse", "status": "running"}
    prepared: list[str] = []

    def describe_next(_root: Path):
        if "plan_promote" in prepared:
            return {
                "ok": True,
                "recommended_next_action": {"id": None, "reason": "pipeline_complete"},
            }
        if "plan_narrate" in prepared:
            return {
                "ok": True,
                "recommended_next_action": {
                    "id": "plan_promote",
                    "reason": "pipeline_incomplete",
                },
            }
        return {
            "ok": True,
            "recommended_next_action": {
                "id": "plan_narrate",
                "reason": "pipeline_incomplete",
            },
        }

    def action_by_id(_workflow_id: str, action_id: str, **_kwargs):
        if action_id == "plan_narrate":
            return {
                "id": "plan_narrate",
                "execution_mode": "primary_review",
                "agent_id": "ascendc-pilot",
                "role_id": "controller",
            }
        return {
            "id": action_id,
            "execution_mode": "deterministic",
            "agent_id": "deterministic-tg-engine",
            "role_id": "deterministic_engine",
        }

    monkeypatch.setattr(state_mod, "load_state", lambda _root: dict(state))
    monkeypatch.setattr(state_mod, "describe_next", describe_next)
    monkeypatch.setattr(workflows_mod, "action_by_id", action_by_id)
    monkeypatch.setattr(
        workflows_mod,
        "get_workflow",
        lambda *_args, **_kwargs: {
            "transitions": [],
            "terminal_ready_states": ["fuse"],
        },
    )
    monkeypatch.setattr(
        state_mod,
        "complete_workflow",
        lambda _root: {"ok": True, "state": {**state, "status": "passed"}},
    )

    def prepare(_root: Path, action_id: str):
        prepared.append(action_id)
        if action_id == "plan_narrate":
            return {
                "ok": True,
                "auto_finalize": True,
                "message_zh": "plan_narrate 三节散文已捕获，继续 plan_promote。",
            }
        return {"ok": True, "auto_finalize": True}

    result = drive_until_interaction(tmp_path, prepare=prepare)
    assert prepared == ["plan_narrate", "plan_promote"]
    assert result.get("ok") is True
    assert result.get("stop_reason") == "workflow_complete"
    assert (result.get("host_step") or {}).get("kind") != "primary_review"


def test_drive_primary_interactive_stops_with_ask(monkeypatch, tmp_path: Path):
    import ascendc_pilot.state as state_mod
    import ascendc_pilot.workflows as workflows_mod
    from ascendc_pilot.actions.drive import drive_until_interaction

    state = {"workflow_id": "tg-plan", "phase": "approve", "status": "running"}
    monkeypatch.setattr(state_mod, "load_state", lambda _root: dict(state))
    monkeypatch.setattr(
        state_mod,
        "describe_next",
        lambda _root: {
            "ok": True,
            "recommended_next_action": {
                "id": "plan_approve",
                "reason": "pipeline_incomplete",
            },
        },
    )
    monkeypatch.setattr(
        workflows_mod,
        "action_by_id",
        lambda *_args, **_kwargs: {
            "id": "plan_approve",
            "execution_mode": "primary_interactive",
            "agent_id": "ascendc-pilot",
            "role_id": "controller",
        },
    )

    def prepare(_root: Path, _action_id: str):
        return {
            "ok": True,
            "needs_human_decision": True,
            "ask_question": {
                "header": "批准规划？",
                "options": [{"label": "批准", "value": "approve"}],
            },
        }

    result = drive_until_interaction(tmp_path, prepare=prepare)
    assert result["ok"] is True
    assert result["stop_reason"] == "interaction_required"
    assert result.get("ask_question", {}).get("options", [{}])[0].get("value") == "approve"
    step = result.get("host_step") or {}
    if step:
        assert step.get("kind") == "ask_human"


def test_drive_surfaces_engine_error_on_failed_action(monkeypatch, tmp_path: Path):
    import ascendc_pilot.state as state_mod
    import ascendc_pilot.workflows as workflows_mod
    from ascendc_pilot.actions.drive import drive_until_interaction

    state = {"workflow_id": "uo-update", "phase": "detect", "status": "running"}
    monkeypatch.setattr(state_mod, "load_state", lambda _root: dict(state))
    monkeypatch.setattr(
        state_mod,
        "describe_next",
        lambda _root: {
            "ok": True,
            "recommended_next_action": {
                "id": "detect_changes",
                "reason": "pipeline_incomplete",
            },
        },
    )
    monkeypatch.setattr(
        workflows_mod,
        "action_by_id",
        lambda *_args, **_kwargs: {
            "id": "detect_changes",
            "execution_mode": "deterministic",
            "agent_id": "deterministic-uo-engine",
            "role_id": "deterministic_engine",
            "output_contract_id": "change-detect-v1",
        },
    )

    def prepare(_root: Path, _action_id: str):
        return {
            "ok": False,
            "engine": {
                "ok": False,
                "error": "manifest.source.revision is unknown; run /uo-init first",
            },
            "finalize": {"ok": False, "message_zh": "Finalize 失败：Checker/Output Contract 未通过"},
        }

    result = drive_until_interaction(tmp_path, prepare=prepare)
    assert result["ok"] is False
    assert result["stop_reason"] == "deterministic_action_failed"
    assert "unknown" in str(result.get("message_zh") or "")
    step = result.get("host_step") or {}
    assert step.get("kind") == "failed"
    assert "unknown" in str(step.get("message_zh") or "")
    assert "unknown" in str(step.get("error_detail") or result.get("error") or "")
    assert step.get("failed_action") == "detect_changes"


def test_drive_surfaces_nested_cann_env_error(monkeypatch, tmp_path: Path):
    import ascendc_pilot.state as state_mod
    import ascendc_pilot.workflows as workflows_mod
    from ascendc_pilot.actions.drive import drive_until_interaction

    state = {"workflow_id": "uo-update", "phase": "apply", "status": "running"}
    monkeypatch.setattr(state_mod, "load_state", lambda _root: dict(state))
    monkeypatch.setattr(
        state_mod,
        "describe_next",
        lambda _root: {
            "ok": True,
            "recommended_next_action": {
                "id": "apply_update",
                "reason": "pipeline_incomplete",
            },
        },
    )
    monkeypatch.setattr(
        workflows_mod,
        "action_by_id",
        lambda *_args, **_kwargs: {
            "id": "apply_update",
            "execution_mode": "deterministic",
            "agent_id": "deterministic-uo-engine",
            "role_id": "deterministic_engine",
            "output_contract_id": "update-apply-v1",
        },
    )

    def prepare(_root: Path, _action_id: str):
        return {
            "ok": False,
            "engine": {
                "ok": False,
                "engine": "apply_update",
                "status": "fail",
                "action_results": [
                    {
                        "action": "prepare_layout",
                        "ok": False,
                        "result": {
                            "ok": False,
                            "error": "CANN_ENV_NOT_READY",
                            "message_zh": "UO 解析前 CANN 环境未就绪。请设置 UO_CANN_ROOT。",
                            "issues": ["CANN packages not found"],
                        },
                    }
                ],
            },
            "finalize": {"ok": False, "message_zh": "Finalize 失败：Checker/Output Contract 未通过"},
        }

    result = drive_until_interaction(tmp_path, prepare=prepare)
    assert result["ok"] is False
    msg = str(result.get("message_zh") or "")
    assert "UO_CANN_ROOT" in msg
    assert msg != "deterministic_action_failed"
    step = result.get("host_step") or {}
    assert "UO_CANN_ROOT" in str(step.get("message_zh") or "")
    assert "UO_CANN_ROOT" in str(step.get("error_detail") or result.get("error") or "")

