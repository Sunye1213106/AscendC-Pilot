"""Reserved Harness workflows: optional workspace bootstrap.

Not in list_user_workflows(), no slash. ``auto`` is an alias of goal-intake.
Used only for the Primary Todo「获取 PR 代码」: isolated clone and fact return
(worktree / changed-files / operator_roots). Unique changed-files
``(operator, architecture)`` pairs are returned as facts (and may be pinned).
Does not invent deliverable workflows or start ``uo-init``.
"""

from __future__ import annotations

from typing import Any, Callable


def attach_goal_workflows(
    workflows: dict[str, dict[str, Any]],
    *,
    _act: Callable[..., dict[str, Any]],
    _st: Callable[..., dict[str, str]],
    _tr: Callable[..., dict[str, Any]],
) -> None:
    workflows.update(_build(_act=_act, _st=_st, _tr=_tr))


def _build(
    *,
    _act: Callable[..., dict[str, Any]],
    _st: Callable[..., dict[str, str]],
    _tr: Callable[..., dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        "auto": {
            "alias_of": "goal-intake",
            "reserved": True,
            "occupancy": "shared",
        },
        "goal-intake": {
            "slash": "",
            "reserved": True,
            "engine": "goal",
            "cognitive_skill_id": "testcase-generation",
            "requires_project": False,
            "requires_architecture": False,
            "requires_uo_product": False,
            "occupancy": "shared",
            "occupancy_group": "",
            "entry_state": "promote",
            "terminal_ready_states": ["promote"],
            "retry_budget": 3,
            "states": [
                _st("promote", "获取工作区并记录目标"),
            ],
            "transitions": [],
            "phase_gates": {"promote": []},
            "pipelines": {
                "promote": ["intent_promote"],
            },
            "complete_gates": [],
            "actions": [
                _act(
                    "intent_promote",
                    label_zh="获取 PR 工作区并记录目标（不解析自然语言）",
                    phases=["promote"],
                    workflow_id="goal-intake",
                    agent_id="deterministic-tg-engine",
                    role_id="deterministic_engine",
                    execution_mode="deterministic",
                    capability_ids=[],
                    task_prompt_id=None,
                    output_contract_id="intent-promoted-v1",
                    consumes_state=["intent"],
                ),
            ],
            "agents": [
                {"id": "deterministic-tg-engine", "role": "deterministic_engine"},
                {"id": "ascendc-pilot", "role": "controller"},
            ],
            "static_obligations": [],
            "dynamic_obligation_sources": [],
            "write_roots": ["runs", "state", "context"],
            "reset_policy": {
                "reinit_delete": [],
                "reinit_preserve": ["uo", "tg", "ce"],
                "reinit_wipe_runs": "current",
                "continue_scrub": "from_contracts",
            },
            "phases": ["promote"],
            "gates": [],
        },
    }
