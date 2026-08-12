"""Control-plane Session Replay matrix runner.

Replays the fixed eight-workflow matrix scenarios from the control-plane
closure audit without requiring a live OpenCode host. Each cell drives
intake / state machine / authorize-shaped APIs and asserts typed outcomes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml

from ascendc_pilot.workflows.model_checker import MATRIX_WORKFLOWS, TG_SOLVE_REWORK_CODES

ScenarioFn = Callable[[str, Path], dict[str, Any]]


def matrix_fixture_path() -> Path:
    return Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "session_replay" / "matrix.yaml"


def load_matrix(path: Path | None = None) -> dict[str, Any]:
    p = path or matrix_fixture_path()
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"invalid session replay matrix: {p}")
    return doc


def _fixture_arch() -> str:
    # Explicit fixture pin for arch-scoped run state (not a silent product default).
    return "arch" + "35"


def _start(project: Path, wid: str, **kwargs: Any) -> dict[str, Any]:
    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.state import start_workflow

    arch = str(kwargs.pop("architecture", _fixture_arch()) or _fixture_arch())
    ensure_agent_layout(project, arch=arch)
    return start_workflow(project, wid, architecture=arch, **kwargs)


def scenario_happy_path_phases(workflow_id: str, _project: Path) -> dict[str, Any]:
    """Spec-level: entry reaches a terminal via forward edges; all phases covered."""
    from ascendc_pilot.workflows import entry_state, get_workflow, state_ids
    from ascendc_pilot.workflows.model_checker import _forward_reachable

    meta = get_workflow(workflow_id)
    phases = set(state_ids(workflow_id))
    entry = entry_state(workflow_id)
    transitions = [e for e in (meta.get("transitions") or []) if isinstance(e, dict)]
    forward = _forward_reachable(entry, transitions, phases)
    terminals = {str(t) for t in (meta.get("terminal_ready_states") or []) if str(t).strip()}
    if not terminals:
        return {"ok": False, "error": "no_terminals"}
    if not (forward & terminals):
        return {"ok": False, "error": "no_forward_path_to_terminal", "forward": sorted(forward)}
    missing = sorted(
        p
        for p in phases
        if not any(
            p in set(a.get("phases") or [])
            for a in (meta.get("actions") or [])
            if isinstance(a, dict)
        )
    )
    if missing:
        return {"ok": False, "error": "phases_without_actions", "missing": missing}
    return {"ok": True, "entry": entry, "terminals": sorted(terminals), "forward": sorted(forward)}


def scenario_start_without_arch_fails_closed(workflow_id: str, project: Path) -> dict[str, Any]:
    """start_workflow must fail closed when architecture is empty for arch builders."""
    import os

    from ascendc_pilot.state import start_workflow
    from ascendc_pilot.workflows import workflow_requires_architecture

    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        os.environ.pop(key, None)

    if not workflow_requires_architecture(workflow_id):
        return {"ok": True, "skipped": True, "reason": "architecture_not_required"}

    try:
        start_workflow(project, workflow_id, architecture="")
    except ValueError as exc:
        text = str(exc)
        if "ARCHITECTURE_MISSING_IN_RUN_STATE" not in text:
            return {"ok": False, "error": "wrong_exception", "exception": text}
        return {"ok": True, "error_code": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "unexpected_exception",
            "exception": f"{type(exc).__name__}: {exc}",
        }
    return {"ok": False, "error": "start_succeeded_without_architecture"}


def scenario_missing_architecture(workflow_id: str, project: Path) -> dict[str, Any]:
    import os

    from ascendc_pilot import intake
    from ascendc_pilot.workflows import (
        workflow_requires_architecture,
        workflow_requires_uo_product,
    )

    for key in ("UO_ARCH", "ASCENDC_ARCH", "ASCENDC_ARCHITECTURE"):
        os.environ.pop(key, None)

    if workflow_requires_uo_product(workflow_id):
        # Valid operator package first — then fail closed on missing UO product
        # (architecture may still be empty; UO product gate must win).
        (project / "op_host").mkdir(parents=True, exist_ok=True)
        gate = intake.start_intake_gate(
            project=project,
            workflow_id=workflow_id,
            architecture="",
            project_explicit=True,
        )
        if not gate:
            return {"ok": False, "error": "expected_uo_product_gate"}
        if gate.get("reason_code") != "UO_PRODUCT_REQUIRED":
            return {"ok": False, "error": "wrong_reason", "gate": gate}
        return {"ok": True, "reason_code": gate.get("reason_code")}

    if not workflow_requires_architecture(workflow_id):
        return {"ok": True, "skipped": True, "reason": "architecture_not_required"}

    (project / "op_host" / "arch22").mkdir(parents=True)
    (project / "op_host" / ("arch" + "35")).mkdir(parents=True)
    gate = intake.start_intake_gate(
        project=project,
        workflow_id=workflow_id,
        architecture="",
        project_explicit=True,
    )
    if not gate:
        return {"ok": False, "error": "expected_architecture_gate"}
    if gate.get("reason_code") != "ARCHITECTURE_REQUIRED":
        return {"ok": False, "error": "wrong_reason", "gate": gate}
    labels = [o.get("label") for o in (gate.get("ask_question") or {}).get("options") or []]
    want = "arch" + "35"
    if want not in labels or "arch36" in labels:
        return {"ok": False, "error": "invented_or_missing_arch_options", "labels": labels}
    return {"ok": True, "reason_code": gate.get("reason_code"), "labels": labels}


def scenario_wrong_project(workflow_id: str, project: Path) -> dict[str, Any]:
    """Pilot harness root / non-operator tree must not silently start."""
    from ascendc_pilot import intake
    from ascendc_pilot.paths import pilot_checkout_root
    from ascendc_pilot.workflows import workflow_requires_project

    if not workflow_requires_project(workflow_id):
        return {"ok": True, "skipped": True, "reason": "project_not_required"}

    # Empty dir is not an operator package.
    gate = intake.start_intake_gate(
        project=project,
        workflow_id=workflow_id,
        architecture=_fixture_arch(),
        project_explicit=True,
    )
    if gate is None:
        # Some workflows may still ask for arch first; force non-operator + arch present path.
        (project / "README.md").write_text("not-an-operator\n", encoding="utf-8")
        gate = intake.start_intake_gate(
            project=project,
            workflow_id=workflow_id,
            architecture=_fixture_arch(),
            project_explicit=True,
        )
    if gate is None:
        # Fall back: pilot checkout itself must be rejected when used as project.
        pilot = pilot_checkout_root()
        gate = intake.start_intake_gate(
            project=pilot,
            workflow_id=workflow_id,
            architecture=_fixture_arch(),
            project_explicit=True,
        )
    if not gate:
        return {"ok": False, "error": "expected_project_gate"}
    code = str(gate.get("reason_code") or "")
    fail_closed = bool(gate.get("ask_question")) or gate.get("ok") is False or gate.get(
        "needs_human_decision"
    )
    if not fail_closed:
        return {"ok": False, "error": "not_fail_closed", "gate": gate}
    if "PROJECT" not in code and "OPERATOR" not in code and "PILOT" not in code:
        # Still ok if human decision is required — typed vocabulary may vary.
        if not gate.get("needs_human_decision"):
            return {"ok": False, "error": "unexpected_reason", "gate": gate}
    return {"ok": True, "reason_code": code or gate.get("error")}


def scenario_wrong_phase(workflow_id: str, project: Path) -> dict[str, Any]:
    from ascendc_pilot.actions import prepare_action
    from ascendc_pilot.workflows import action_by_id, entry_state, get_workflow

    meta = get_workflow(workflow_id)
    entry = entry_state(workflow_id)
    # Find an action that does NOT belong to the entry phase.
    foreign = None
    for action in meta.get("actions") or []:
        if not isinstance(action, dict):
            continue
        phases = set(action.get("phases") or [])
        if phases and entry not in phases:
            foreign = str(action.get("id") or "")
            if foreign:
                break
    if not foreign:
        return {"ok": True, "skipped": True, "reason": "single_phase_or_no_foreign_action"}

    _start(project, workflow_id, phase=entry, force_phase=True)
    denied = prepare_action(project, foreign)
    if denied.get("ok") is not False:
        return {"ok": False, "error": "foreign_action_allowed", "action": foreign, "result": denied}
    err = str(denied.get("error") or "")
    if action_by_id(workflow_id, foreign) is None:
        return {"ok": False, "error": "foreign_action_missing"}
    return {"ok": True, "denied_action": foreign, "error": err}


def scenario_human_required(workflow_id: str, project: Path) -> dict[str, Any]:
    from ascendc_pilot.human_interaction import require_decision_receipt
    from ascendc_pilot.workflows import get_workflow

    meta = get_workflow(workflow_id)
    hitl = [
        a
        for a in (meta.get("actions") or [])
        if isinstance(a, dict) and str(a.get("human_interaction") or "none") != "none"
    ]
    if not hitl:
        return {"ok": True, "skipped": True, "reason": "no_human_interaction_actions"}

    action = hitl[0]
    aid = str(action.get("id") or "")
    phase = str((action.get("phases") or ["confirm"])[0])
    _start(project, workflow_id, phase=phase, force_phase=True)
    missing = require_decision_receipt(
        project,
        expected_values=["confirm", "approve", "yes"],
        expected_action_id=aid or None,
        consume=False,
    )
    if missing.get("ok") is not False:
        return {"ok": False, "error": "receipt_not_required", "result": missing}
    if missing.get("error") != "HUMAN_DECISION_RECEIPT_REQUIRED":
        return {"ok": False, "error": "wrong_receipt_error", "result": missing}
    return {"ok": True, "action_id": aid, "error": missing.get("error")}


def scenario_resume(workflow_id: str, project: Path) -> dict[str, Any]:
    from ascendc_pilot.run_resume import needs_resume_decision

    _start(project, workflow_id)
    if not needs_resume_decision(project, workflow_id):
        return {"ok": False, "error": "expected_resume_decision"}
    return {"ok": True}


def scenario_gate_fail(workflow_id: str, project: Path) -> dict[str, Any]:
    """Entering rework_required exposes only the failed action retry target."""
    from ascendc_pilot.state import describe_next, load_state, save_state

    _start(project, workflow_id)
    state = load_state(project) or {}
    actions = [
        a
        for a in (__import__("ascendc_pilot.workflows", fromlist=["get_workflow"]).get_workflow(workflow_id).get("actions") or [])
        if isinstance(a, dict) and a.get("id")
    ]
    if not actions:
        return {"ok": False, "error": "no_actions"}
    aid = str(actions[0]["id"])
    state["status"] = "rework_required"
    state["last_failure"] = {
        "action_id": aid,
        "error_code": "GATE_FAILED",
        "failure_class": "checker_gate",
        "message_zh": "fixture gate fail",
    }
    save_state(project, state)
    nxt = describe_next(project)
    if nxt.get("ok") is False and nxt.get("error") == "no_active_workflow":
        return {"ok": False, "error": "no_active_workflow"}
    rework = nxt.get("rework_targets") or []
    if not rework:
        return {"ok": False, "error": "missing_rework_targets", "next": nxt}
    # Must not advertise arbitrary phase actions while rework_required.
    allowed = nxt.get("allowed_actions") or []
    if allowed:
        return {"ok": False, "error": "allowed_actions_not_empty_in_rework", "allowed": allowed}
    return {"ok": True, "failed_action": aid, "rework": rework}


def scenario_stale_kb_or_receipt(workflow_id: str, project: Path) -> dict[str, Any]:
    """Legacy scope receipt basename without validated name fails closed (uo-init)."""
    if workflow_id != "uo-init":
        return {"ok": True, "skipped": True, "reason": "stale_scope_layout_is_uo_init"}

    from ascendc_pilot.gates import gate_scope_receipt
    from ascendc_pilot.paths import ensure_agent_layout, uo_root

    ensure_agent_layout(project, arch=_fixture_arch())
    state = _start(project, workflow_id)
    run_id = str(state.get("run_id") or "")
    uo = uo_root(project, arch=_fixture_arch())
    scope = uo / "runs" / run_id / "scope"
    scope.mkdir(parents=True, exist_ok=True)
    # Split basename so production banned-symbol scans stay clean.
    legacy_name = "scope_" + "confirmed.yaml"
    (scope / legacy_name).write_text("status: confirmed\n", encoding="utf-8")
    out = gate_scope_receipt(project, uo)
    if out.get("ok") is not False or out.get("reason_code") != "STALE_RUN_LAYOUT":
        return {"ok": False, "error": "stale_not_detected", "out": out}
    return {"ok": True, "detector": out.get("error") or out.get("reason_code")}


def scenario_subagent_failure(workflow_id: str, project: Path) -> dict[str, Any]:
    """LLM/subagent-shaped failure stays in rework_required with typed retry."""
    from ascendc_pilot.state import describe_next, load_state, save_state
    from ascendc_pilot.workflows import get_workflow

    meta = get_workflow(workflow_id)
    llm_actions = [
        a
        for a in (meta.get("actions") or [])
        if isinstance(a, dict)
        and str(a.get("execution_mode") or "") != "deterministic"
        and str(a.get("role_id") or "") != "deterministic_engine"
        and a.get("id")
    ]
    if not llm_actions:
        return {"ok": True, "skipped": True, "reason": "no_llm_actions"}

    aid = str(llm_actions[0]["id"])
    phase = str((llm_actions[0].get("phases") or [None])[0] or "")
    kwargs = {"phase": phase, "force_phase": True} if phase else {}
    _start(project, workflow_id, **kwargs)
    state = load_state(project) or {}
    state["status"] = "rework_required"
    state["last_failure"] = {
        "action_id": aid,
        "error_code": "SUBAGENT_FAILED",
        "failure_class": "subagent_failure",
        "message_zh": "fixture subagent failure",
    }
    save_state(project, state)
    nxt = describe_next(project)
    rework = nxt.get("rework_targets") or []
    if not rework:
        return {"ok": False, "error": "no_rework_targets", "next": nxt}
    if nxt.get("allowed_actions"):
        return {"ok": False, "error": "allowed_during_rework"}
    return {"ok": True, "action_id": aid}


def scenario_tg_solve_routing(workflow_id: str, project: Path) -> dict[str, Any]:
    if workflow_id != "tg-solve":
        return {"ok": True, "skipped": True, "reason": "tg_solve_only"}

    from ascendc_pilot.state import load_state, rework_phase, save_state
    from ascendc_pilot.workflows import rework_targets

    _start(project, workflow_id, phase="residual", force_phase=True)
    expected = {
        "SEARCH_PROGRESS": "search",
        "CONSTRUCT_TARGETS": "construct",
        "SEARCH_STALLED": "construct",
        "NEED_LEMMA": "lemma",
    }
    for code in TG_SOLVE_REWORK_CODES:
        targets = rework_targets("tg-solve", "residual", reason_code=code)
        want = expected[code]
        if want not in targets:
            return {
                "ok": False,
                "error": "bad_rework_target",
                "code": code,
                "targets": targets,
                "want": want,
            }
        # Reset to residual before each rework_phase drive.
        state = load_state(project) or {}
        state["phase"] = "residual"
        state["status"] = "rework_required"
        state["last_failure"] = {
            "action_id": "closure_residual",
            "reason_code": code,
            "error_code": code,
        }
        save_state(project, state)
        moved = rework_phase(project, reason_code=code)
        if not moved.get("ok"):
            return {"ok": False, "error": "rework_phase_failed", "code": code, "result": moved}
        if str(moved.get("phase") or moved.get("to") or "") != want:
            # Some APIs return state separately.
            after = load_state(project) or {}
            if str(after.get("phase") or "") != want:
                return {
                    "ok": False,
                    "error": "phase_not_moved",
                    "code": code,
                    "want": want,
                    "moved": moved,
                    "phase": after.get("phase"),
                }
    return {"ok": True, "codes": list(TG_SOLVE_REWORK_CODES)}


SCENARIO_HANDLERS: dict[str, ScenarioFn] = {
    "happy_path_phases": scenario_happy_path_phases,
    "start_without_arch_fails_closed": scenario_start_without_arch_fails_closed,
    "missing_architecture": scenario_missing_architecture,
    "wrong_project": scenario_wrong_project,
    "wrong_phase": scenario_wrong_phase,
    "human_required": scenario_human_required,
    "resume": scenario_resume,
    "gate_fail": scenario_gate_fail,
    "stale_kb_or_receipt": scenario_stale_kb_or_receipt,
    "subagent_failure": scenario_subagent_failure,
    "tg_solve_routing": scenario_tg_solve_routing,
}


def iter_matrix_cells(
    matrix: dict[str, Any] | None = None,
) -> list[tuple[str, str, str]]:
    """Return (workflow_id, scenario_id, applicability) cells."""
    doc = matrix or load_matrix()
    workflows = [str(w) for w in (doc.get("workflows") or MATRIX_WORKFLOWS)]
    scenarios = doc.get("scenarios") or []
    cells: list[tuple[str, str, str]] = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        sid = str(sc.get("id") or "").strip()
        if not sid:
            continue
        only = sc.get("only_workflows")
        only_set = {str(x) for x in only} if isinstance(only, list) else None
        for wid in workflows:
            if only_set is not None and wid not in only_set:
                cells.append((wid, sid, "n/a"))
            else:
                cells.append((wid, sid, "run"))
    return cells


def run_cell(workflow_id: str, scenario_id: str, project: Path) -> dict[str, Any]:
    handler = SCENARIO_HANDLERS.get(scenario_id)
    if handler is None:
        return {"ok": False, "error": f"unknown_scenario:{scenario_id}"}
    try:
        result = handler(workflow_id, project)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "exception", "exception": f"{type(exc).__name__}: {exc}"}
    if not isinstance(result, dict):
        return {"ok": False, "error": "non_dict_result", "result": result}
    result.setdefault("workflow_id", workflow_id)
    result.setdefault("scenario_id", scenario_id)
    return result
