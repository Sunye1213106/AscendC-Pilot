"""Structured Observation + failure classification + atomic state apply.

Harness-managed steps must return Observations (not raw stdout strings).
Failures atomically update run state before the CLI returns.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# --- Failure classes (stable machine vocabulary) ---
PRODUCER_OUTPUT = "producer_output"
CHECKER_GATE = "checker_gate"
TRANSIENT_TOOL = "transient_tool"
ENVIRONMENT_INVARIANT = "environment_invariant"
WORKFLOW_SPEC_ERROR = "workflow_spec_error"
POLICY_VIOLATION = "policy_violation"
RETRY_EXHAUSTED = "retry_exhausted"
# Identity / format / transport: retryable but must NOT burn semantic attempt budget.
IDENTITY_CONTRACT = "identity_contract"
FORMAT_TRANSPORT = "format_transport"

HUMAN_CLASSES = frozenset(
    {ENVIRONMENT_INVARIANT, WORKFLOW_SPEC_ERROR, POLICY_VIOLATION, RETRY_EXHAUSTED}
)
RETRYABLE_CLASSES = frozenset(
    {PRODUCER_OUTPUT, CHECKER_GATE, TRANSIENT_TOOL, IDENTITY_CONTRACT, FORMAT_TRANSPORT}
)
# Do not increment no_progress_streak / decrement retry_budget (semantic attempts).
NON_SEMANTIC_BURN_CLASSES = frozenset({IDENTITY_CONTRACT, FORMAT_TRANSPORT, TRANSIENT_TOOL})

# Legal recovery verbs surfaced to agents / humans
HUMAN_LEGAL_ACTIONS = (
    "inspect_failure",
    "retry_after_environment_fix",
    "abort_run",
)
CONTAINMENT_HARNESS_COMMANDS = (
    "acp next",
    "acp status",
    "acp inspect-failure",
    "acp retry-after-environment-fix",
    "acp abort",
)

# Stable error-code patterns → failure_class (English / machine tokens only)
_ENV_INVARIANT_PATTERNS = (
    re.compile(r"installed_skill_check", re.I),
    re.compile(r"semantic_enrichment", re.I),
    re.compile(r"MISSING_INSTALLED_SKILL", re.I),
    re.compile(r"skill[_\s-]?missing", re.I),
    re.compile(r"reinstall", re.I),
    re.compile(r"environment[_-]invariant", re.I),
    re.compile(r"layout[_-]missing", re.I),
    re.compile(r"invariant", re.I),
)
_TRANSIENT_PATTERNS = (
    re.compile(r"timeout", re.I),
    re.compile(r"timed?\s*out", re.I),
    re.compile(r"file[_-]?lock", re.I),
    re.compile(r"temporarily\s+unavailable", re.I),
    re.compile(r"EAGAIN|EBUSY|EWOULDBLOCK", re.I),
)
_SPEC_PATTERNS = (
    re.compile(r"no[_\s-]?forward[_\s-]?edge", re.I),
    re.compile(r"illegal[_\s-]?transition", re.I),
    re.compile(r"workflow[_-]spec", re.I),
    re.compile(r"unknown[_\s-]?phase", re.I),
    re.compile(r"unknown[_\s-]?step", re.I),
)
_POLICY_PATTERNS = (
    re.compile(r"DOMAIN_CLI_BYPASS", re.I),
    re.compile(r"HARNESS_ACTION_NOT_AUTHORIZED", re.I),
    re.compile(r"POLICY_VIOLATION", re.I),
    re.compile(r"LEASE_REVOKED", re.I),
)
_PRODUCER_PATTERNS = (
    re.compile(r"output[_-]contract", re.I),
    re.compile(r"missing[_\s-]?field", re.I),
    re.compile(r"PATCH_REQUIRED|STALE_PATCH|STALE_INVENTORY", re.I),
)
_IDENTITY_PATTERNS = (
    re.compile(r"ARTIFACT_SESSION_MISMATCH", re.I),
    re.compile(r"PRODUCER_DECLARED_IDENTITY", re.I),
    re.compile(r"ARTIFACT_IDENTITY", re.I),
    re.compile(r"action_session_id", re.I),
    re.compile(r"prepare_nonce", re.I),
)
_FORMAT_TRANSPORT_PATTERNS = (
    re.compile(r"yaml\s*(parse|error|scanner|composer)", re.I),
    re.compile(r"format[_\s-]?error", re.I),
    re.compile(r"literal[_-]?block", re.I),
    re.compile(r"JSONDecodeError|UnicodeDecodeError", re.I),
    re.compile(r"ECONNRESET|ConnectionReset|BrokenPipe", re.I),
)


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_observation_id() -> str:
    return f"OBS_{uuid.uuid4().hex[:12]}"


def classify_failure(
    *,
    error_code: str | None = None,
    messages: list[str] | None = None,
    step_id: str = "",
    action_id: str = "",
    source: str = "",
    explicit_class: str | None = None,
) -> dict[str, Any]:
    """Centralized failure classification. Do not scatter string checks in callers."""
    if explicit_class:
        fc = str(explicit_class)
        return {
            "failure_class": fc,
            "retryable": fc in RETRYABLE_CLASSES,
            "recommended_transition": (
                "human_required" if fc in HUMAN_CLASSES else "rework_required"
            ),
        }

    blob = " ".join(
        [
            str(error_code or ""),
            str(step_id or ""),
            str(action_id or ""),
            str(source or ""),
            *(str(m) for m in (messages or [])),
        ]
    )

    def _hit(pats: tuple[re.Pattern[str], ...]) -> bool:
        return any(p.search(blob) for p in pats)

    # uo-scope finalize failures are environment invariants (ses_0711), not agent rework
    step_l = str(step_id).lower().replace("-", "_")
    if step_l in {"finalize", "uo_scope_finalize", "finalize_scope"} or (
        source == "uo_scope" and "finalize" in step_l
    ):
        if not _hit(_TRANSIENT_PATTERNS):
            return {
                "failure_class": ENVIRONMENT_INVARIANT,
                "retryable": False,
                "recommended_transition": "human_required",
            }

    if _hit(_POLICY_PATTERNS):
        return {
            "failure_class": POLICY_VIOLATION,
            "retryable": False,
            "recommended_transition": "human_required",
        }
    # Missing required CLI args / agent usage errors → producer rework, not env
    if re.search(r"decision[_-]?required|missing[_-]?required|argument", blob, re.I):
        return {
            "failure_class": PRODUCER_OUTPUT,
            "retryable": True,
            "recommended_transition": "rework_required",
        }
    if _hit(_SPEC_PATTERNS):
        return {
            "failure_class": WORKFLOW_SPEC_ERROR,
            "retryable": False,
            "recommended_transition": "human_required",
        }
    if _hit(_ENV_INVARIANT_PATTERNS):
        return {
            "failure_class": ENVIRONMENT_INVARIANT,
            "retryable": False,
            "recommended_transition": "human_required",
        }
    if _hit(_TRANSIENT_PATTERNS):
        return {
            "failure_class": TRANSIENT_TOOL,
            "retryable": True,
            "recommended_transition": "rework_required",
        }
    if _hit(_IDENTITY_PATTERNS):
        return {
            "failure_class": IDENTITY_CONTRACT,
            "retryable": True,
            "recommended_transition": "rework_required",
        }
    if _hit(_FORMAT_TRANSPORT_PATTERNS):
        return {
            "failure_class": FORMAT_TRANSPORT,
            "retryable": True,
            "recommended_transition": "rework_required",
        }
    if _hit(_PRODUCER_PATTERNS) or source in {"finalize_action", "output_contract"}:
        # checker/output-contract failures that agents can rework
        if source in {"finalize_action", "checker", "gate"} and not _hit(_ENV_INVARIANT_PATTERNS):
            return {
                "failure_class": CHECKER_GATE,
                "retryable": True,
                "recommended_transition": "rework_required",
            }
        return {
            "failure_class": PRODUCER_OUTPUT,
            "retryable": True,
            "recommended_transition": "rework_required",
        }
    if source in {"advance", "complete", "gate", "checker", "finalize_action"}:
        return {
            "failure_class": CHECKER_GATE,
            "retryable": True,
            "recommended_transition": "rework_required",
        }

    # Default: treat unknown acp failures as reworkable checker-style
    return {
        "failure_class": CHECKER_GATE,
        "retryable": True,
        "recommended_transition": "rework_required",
    }


def failure_fingerprint(
    *,
    phase: str,
    action_id: str,
    step_id: str,
    error_code: str,
    open_obligation_ids: list[str] | None = None,
) -> str:
    payload = {
        "phase": phase or "",
        "action_id": action_id or "",
        "step_id": step_id or "",
        "error_code": error_code or "",
        "open_obligation_ids": sorted(open_obligation_ids or []),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_observation(
    project_root: Path | None = None,
    *,
    outcome: str,
    action_id: str = "",
    step_id: str = "",
    error_code: str | None = None,
    messages: list[str] | None = None,
    findings: list[dict[str, Any]] | None = None,
    source: str = "",
    explicit_class: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured Observation for a Pilot-managed execution result."""
    from ascendc_pilot.state import load_state

    state: dict[str, Any] = {}
    if project_root is not None:
        try:
            state = load_state(project_root) or {}
        except Exception:  # noqa: BLE001
            state = {}

    msgs = [str(m) for m in (messages or []) if str(m).strip()]
    finding_rows = list(findings or [])
    if not finding_rows and msgs:
        for msg in msgs:
            finding_rows.append(
                {
                    "code": _finding_code_from_message(msg),
                    "message": msg,
                    "evidence": {},
                }
            )

    if outcome == "success":
        classification = {
            "failure_class": None,
            "retryable": False,
            "recommended_transition": "running",
        }
        err = None
    else:
        classification = classify_failure(
            error_code=error_code,
            messages=msgs,
            step_id=step_id,
            action_id=action_id,
            source=source,
            explicit_class=explicit_class,
        )
        err = error_code or _default_error_code(
            action_id=action_id,
            step_id=step_id,
            failure_class=str(classification["failure_class"]),
            source=source,
        )

    open_ids = [
        str(it.get("id") or "")
        for it in (state.get("open_items") or [])
        if isinstance(it, dict) and it.get("id")
    ]
    obs: dict[str, Any] = {
        "observation_id": new_observation_id(),
        "run_id": state.get("run_id") or "",
        "workflow_id": state.get("workflow_id") or "",
        "phase": state.get("phase") or "",
        "action_id": action_id or "",
        "step_id": step_id or "",
        "outcome": outcome,
        "failure_class": classification.get("failure_class"),
        "error_code": err,
        "retryable": bool(classification.get("retryable")),
        "findings": finding_rows,
        "recommended_transition": classification.get("recommended_transition"),
        "legal_recovery_actions": [],
        "forbidden_recovery_actions": [],
        "source": source or "",
        "created_at": _now(),
        "failure_fingerprint": (
            failure_fingerprint(
                phase=str(state.get("phase") or ""),
                action_id=action_id or "",
                step_id=step_id or "",
                error_code=str(err or ""),
                open_obligation_ids=open_ids,
            )
            if outcome != "success"
            else None
        ),
    }
    if outcome != "success":
        if classification.get("recommended_transition") == "human_required":
            obs["legal_recovery_actions"] = list(HUMAN_LEGAL_ACTIONS)
            obs["forbidden_recovery_actions"] = [
                "glob_pilot_internals",
                "read_engine_source",
                "write_pilot_artifact",
                "direct_domain_cli",
                "continue_phase_actions",
                "advance",
            ]
        else:
            obs["legal_recovery_actions"] = ["retry_failed_action", "inspect_failure"]
            obs["forbidden_recovery_actions"] = [
                "advance",
                "direct_domain_cli",
                "write_pilot_artifact_outside_contract",
            ]
    if extra:
        obs["extra"] = dict(extra)
    return obs


def _finding_code_from_message(msg: str) -> str:
    m = str(msg).strip().lower()
    if "installed_skill" in m:
        return "INSTALLED_SKILL_CHECK_INVARIANT"
    if "semantic_enrichment" in m:
        return "SEMANTIC_ENRICHMENT_STATUS_INVALID"
    if "output" in m and "contract" in m:
        return "OUTPUT_CONTRACT_FAILED"
    slug = re.sub(r"[^a-z0-9]+", "_", m)[:48].strip("_").upper()
    return slug or "FINDING"


def _default_error_code(
    *,
    action_id: str,
    step_id: str,
    failure_class: str,
    source: str,
) -> str:
    step = (step_id or "").upper().replace("-", "_")
    act = (action_id or "").upper().replace("-", "_")
    if step in {"FINALIZE", "UO_SCOPE_FINALIZE", "FINALIZE_SCOPE"} or (
        source == "uo_scope" and "finalize" in (step_id or "").lower()
    ):
        if failure_class == ENVIRONMENT_INVARIANT:
            return "UO_SCOPE_FINALIZE_INVARIANT_FAILED"
        return "UO_SCOPE_FINALIZE_FAILED"
    if source == "finalize_action":
        return f"ACTION_FINALIZE_FAILED_{act}" if act else "ACTION_FINALIZE_FAILED"
    if source == "advance":
        return "GATE_FAILED"
    if failure_class == POLICY_VIOLATION:
        return "HARNESS_ACTION_NOT_AUTHORIZED"
    if failure_class == WORKFLOW_SPEC_ERROR:
        return "WORKFLOW_SPEC_ERROR"
    if act and step:
        return f"{act}_{step}_FAILED"
    if act:
        return f"{act}_FAILED"
    return "HARNESS_STEP_FAILED"


def persist_observation(project_root: Path, observation: dict[str, Any]) -> Path:
    """Append-only observation history under the current run dir."""
    from ascendc_pilot.runs import append_event, run_dir

    run_id = str(observation.get("run_id") or "")
    base = run_dir(project_root, run_id or None)
    obs_dir = base / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)
    oid = str(observation.get("observation_id") or new_observation_id())
    path = obs_dir / f"{oid}.yaml"
    if yaml is None:
        path.write_text(json.dumps(observation, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(
            yaml.safe_dump(observation, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    # Append-only index
    idx = base / "observations.jsonl"
    with idx.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(observation, ensure_ascii=False, default=str) + "\n")
    append_event(
        project_root,
        {
            "type": "ObservationRecorded",
            "observation_id": oid,
            "outcome": observation.get("outcome"),
            "failure_class": observation.get("failure_class"),
            "error_code": observation.get("error_code"),
            "action_id": observation.get("action_id"),
            "step_id": observation.get("step_id"),
        },
        run_id=run_id or None,
    )
    return path


def build_failure_summary(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": observation.get("action_id") or "",
        "step_id": observation.get("step_id") or "",
        "error_code": observation.get("error_code"),
        "failure_class": observation.get("failure_class"),
        "retryable": bool(observation.get("retryable")),
        "reason_code": observation.get("error_code") or "OBSERVATION_FAILED",
        "message_zh": _failure_message_zh(observation),
        "findings": list(observation.get("findings") or []),
        "observation_id": observation.get("observation_id"),
        "failure_fingerprint": observation.get("failure_fingerprint"),
        "recommended_transition": observation.get("recommended_transition"),
        "legal_recovery_actions": list(observation.get("legal_recovery_actions") or []),
        "forbidden_recovery_actions": list(observation.get("forbidden_recovery_actions") or []),
    }


def _failure_message_zh(observation: dict[str, Any]) -> str:
    findings = observation.get("findings") or []
    msgs = [str(f.get("message") or "") for f in findings if isinstance(f, dict)]
    msgs = [m for m in msgs if m]
    head = "；".join(msgs[:4]) if msgs else str(observation.get("error_code") or "执行失败")
    fc = observation.get("failure_class") or ""
    return f"[{fc}] {head}" if fc else head


def render_failure_card(state: dict[str, Any], observation: dict[str, Any] | None = None) -> str:
    """Stable, human-facing failure card — not LLM-summarized stdout."""
    lf = state.get("last_failure") if isinstance(state.get("last_failure"), dict) else {}
    obs = observation or {}
    phase = str(state.get("phase") or obs.get("phase") or "")
    action_id = str(lf.get("action_id") or obs.get("action_id") or "")
    step_id = str(lf.get("step_id") or obs.get("step_id") or "")
    status = str(state.get("status") or "")
    fc = str(lf.get("failure_class") or obs.get("failure_class") or "")
    code = str(lf.get("error_code") or obs.get("error_code") or "")
    findings = lf.get("findings") or obs.get("findings") or []
    lines = [
        f"当前阶段：{phase}",
        f"失败 Action：{action_id or '(unknown)'}",
        f"失败步骤：{step_id or '(unknown)'}",
        f"状态：{status}",
        "",
        f"失败类型：{fc}",
        f"错误代码：{code}",
        "",
        "失败项：",
    ]
    if findings:
        for f in findings:
            if isinstance(f, dict):
                lines.append(f"- {f.get('message') or f.get('code')}")
            else:
                lines.append(f"- {f}")
    else:
        lines.append(f"- {lf.get('message_zh') or '见 last_failure'}")
    lines.extend(
        [
            "",
            (
                "已进入返工模式：仅可重试失败 Action 及相关 acp 命令。"
                if status == "rework_required"
                else "自动执行已停止。当前 Action 权限已撤销。"
            ),
            "禁止直调领域脚本或修改 Pilot 正式产物绕过控制面。",
            "",
            "合法后续：",
        ]
    )
    legal = lf.get("legal_recovery_actions") or obs.get("legal_recovery_actions") or list(HUMAN_LEGAL_ACTIONS)
    label = {
        "inspect_failure": "查看结构化失败信息",
        "retry_after_environment_fix": "修复外部环境后重试",
        "abort_run": "终止本次运行",
        "retry_failed_action": "按 rework target 重试失败 Action",
    }
    for a in legal:
        lines.append(f"- {label.get(str(a), a)}")
    return "\n".join(lines)


def apply_observation(project_root: Path, observation: dict[str, Any]) -> dict[str, Any]:
    """Atomically persist observation and update run state + lease before CLI returns.

    Lease mode follows status:
      rework_required → rework lease (retry failed Action)
      human_required / blocked → containment lease
      success while rework_required → restore running + normal lease for action
    """
    from ascendc_pilot.authorize.lease import (
        issue_action_lease,
        issue_lease_for_status,
        revoke_active_lease,
    )
    from ascendc_pilot.runs import append_event
    from ascendc_pilot.state import _apply_progress, load_state, save_state

    project_root = Path(project_root).expanduser().resolve()
    obs = dict(observation)
    persist_observation(project_root, obs)

    state = load_state(project_root)
    if not state:
        return {"ok": False, "error": "no_active_workflow", "observation": obs}

    state["last_observation_id"] = obs.get("observation_id")
    append_event(
        project_root,
        {
            "type": "ActionExecuted",
            "observation_id": obs.get("observation_id"),
            "outcome": obs.get("outcome"),
            "action_id": obs.get("action_id"),
            "step_id": obs.get("step_id"),
        },
        run_id=str(state.get("run_id") or "") or None,
    )

    if obs.get("outcome") == "success":
        prev = str(state.get("status") or "running")
        # Successful rework step restores normal execution
        if prev == "rework_required":
            state["status"] = "running"
            state["last_failure"] = None
            state["failure_card"] = None
            state["no_progress_streak"] = 0
            state = _apply_progress(project_root, state)
            save_state(project_root, state)
            aid = str(obs.get("action_id") or "")
            if aid:
                issue_action_lease(project_root, state=state, action_id=aid, mode="normal")
            append_event(
                project_root,
                {
                    "type": "StateTransitioned",
                    "from_status": "rework_required",
                    "to_status": "running",
                    "reason": "rework_step_succeeded",
                    "action_id": obs.get("action_id"),
                    "observation_id": obs.get("observation_id"),
                },
                run_id=str(state.get("run_id") or "") or None,
            )
        elif prev == "running":
            state = _apply_progress(project_root, state)
            save_state(project_root, state)
        else:
            # Do not clobber human_required/blocked/failed on incidental success events
            save_state(project_root, state)
        return {"ok": True, "state": load_state(project_root), "observation": obs}

    # --- Failure path ---
    prev_status = str(state.get("status") or "running")
    summary = build_failure_summary(obs)
    state["last_failure"] = summary

    failed_gates = list(state.get("failed_gates") or [])
    gate_id = str(obs.get("step_id") or obs.get("action_id") or obs.get("error_code") or "step")
    failed_gates = [g for g in failed_gates if str(g.get("id") or g.get("gate") or "") != gate_id]
    failed_gates.append(
        {
            "id": gate_id,
            "gate": gate_id,
            "ok": False,
            "at": _now(),
            "detail": {
                "error_code": obs.get("error_code"),
                "failure_class": obs.get("failure_class"),
            },
        }
    )
    state["failed_gates"] = failed_gates

    # Revoke whatever lease was active (normal or prior)
    revoke_info = revoke_active_lease(project_root, reason="observation_failed")
    append_event(
        project_root,
        {
            "type": "ActionAuthorizationRevoked",
            "lease_id": revoke_info.get("lease_id"),
            "action_id": obs.get("action_id"),
            "reason": "observation_failed",
        },
        run_id=str(state.get("run_id") or "") or None,
    )

    fc = str(obs.get("failure_class") or CHECKER_GATE)
    retryable = bool(obs.get("retryable"))
    budget = int(state.get("retry_budget") if isinstance(state.get("retry_budget"), int) else 3)
    # Identity/format/transport must not burn semantic attempt budget (ses_0622).
    burns_semantic = fc not in NON_SEMANTIC_BURN_CLASSES

    fp = str(obs.get("failure_fingerprint") or "")
    prev_fp = str(state.get("last_failure_fingerprint") or "")
    if burns_semantic:
        if fp and fp == prev_fp:
            streak = int(state.get("no_progress_streak") or 0) + 1
        else:
            streak = 1
        state["no_progress_streak"] = streak
        state["last_failure_fingerprint"] = fp
    else:
        streak = int(state.get("no_progress_streak") or 0)

    if prev_status == "blocked":
        new_status = "blocked"
    elif fc in HUMAN_CLASSES or not retryable:
        new_status = "human_required"
    elif burns_semantic and streak >= budget:
        new_status = "human_required"
        summary = dict(summary)
        summary["failure_class"] = RETRY_EXHAUSTED
        summary["error_code"] = "RETRY_EXHAUSTED"
        summary["reason_code"] = "RETRY_EXHAUSTED"
        summary["retryable"] = False
        summary["message_zh"] = (
            f"相同失败连续 {streak} 次，重试预算（{budget}）耗尽；需人工介入"
        )
        summary["legal_recovery_actions"] = list(HUMAN_LEGAL_ACTIONS)
        state["last_failure"] = summary
        obs = dict(obs)
        obs["failure_class"] = RETRY_EXHAUSTED
        obs["retryable"] = False
        obs["error_code"] = "RETRY_EXHAUSTED"
    elif retryable and budget > 0:
        new_status = "rework_required"
        if burns_semantic:
            state["retry_budget"] = max(0, budget - 1)
    else:
        new_status = "human_required"

    state["status"] = new_status
    state["failure_card"] = render_failure_card(state, obs)
    state = _apply_progress(project_root, state)

    # Issue lease matching the *new* status (rework ≠ containment)
    issue_lease_for_status(
        project_root,
        state=state,
        action_id=str(obs.get("action_id") or ""),
    )

    save_state(project_root, state)

    event_type = "HumanRequired" if new_status == "human_required" else "ReworkRequired"
    if new_status == "blocked":
        event_type = "StateTransitioned"
    append_event(
        project_root,
        {
            "type": event_type,
            "from_status": prev_status,
            "to_status": new_status,
            "failure_class": state["last_failure"].get("failure_class"),
            "error_code": state["last_failure"].get("error_code"),
            "observation_id": obs.get("observation_id"),
            "no_progress_streak": streak,
            "lease_mode": "rework" if new_status == "rework_required" else "containment",
        },
        run_id=str(state.get("run_id") or "") or None,
    )
    append_event(
        project_root,
        {
            "type": "StateTransitioned",
            "from_status": prev_status,
            "to_status": new_status,
            "phase": state.get("phase"),
        },
        run_id=str(state.get("run_id") or "") or None,
    )
    if fc == POLICY_VIOLATION:
        append_event(
            project_root,
            {"type": "PolicyViolation", "observation_id": obs.get("observation_id")},
            run_id=str(state.get("run_id") or "") or None,
        )
    if obs.get("failure_class") in {CHECKER_GATE, ENVIRONMENT_INVARIANT} or source_gate(obs):
        append_event(
            project_root,
            {
                "type": "GateFailed",
                "error_code": obs.get("error_code"),
                "failure_class": state["last_failure"].get("failure_class"),
            },
            run_id=str(state.get("run_id") or "") or None,
        )

    fresh = load_state(project_root)
    return {
        "ok": False,
        "state": fresh,
        "observation": obs,
        "status": fresh.get("status"),
        "failure_card": fresh.get("failure_card"),
    }


def source_gate(obs: dict[str, Any]) -> bool:
    return str(obs.get("source") or "") in {"advance", "complete", "gate", "checker", "uo_scope"}


def record_pilot_result(
    project_root: Path,
    *,
    ok: bool,
    action_id: str = "",
    step_id: str = "",
    error_code: str | None = None,
    messages: list[str] | None = None,
    findings: list[dict[str, Any]] | None = None,
    source: str = "",
    explicit_class: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience: build Observation and apply it. Returns merged CLI payload fields."""
    obs = build_observation(
        project_root,
        outcome="success" if ok else "failed",
        action_id=action_id,
        step_id=step_id,
        error_code=error_code,
        messages=messages,
        findings=findings,
        source=source,
        explicit_class=explicit_class,
        extra=extra,
    )
    applied = apply_observation(project_root, obs)
    return {
        "observation": obs,
        "applied": applied,
        "status": (applied.get("state") or {}).get("status"),
        "last_failure": (applied.get("state") or {}).get("last_failure"),
        "failure_card": (applied.get("state") or {}).get("failure_card"),
    }


__all__ = [
    "CHECKER_GATE",
    "CONTAINMENT_HARNESS_COMMANDS",
    "ENVIRONMENT_INVARIANT",
    "HUMAN_LEGAL_ACTIONS",
    "POLICY_VIOLATION",
    "PRODUCER_OUTPUT",
    "RETRY_EXHAUSTED",
    "TRANSIENT_TOOL",
    "WORKFLOW_SPEC_ERROR",
    "apply_observation",
    "build_failure_summary",
    "build_observation",
    "classify_failure",
    "failure_fingerprint",
    "persist_observation",
    "record_pilot_result",
    "render_failure_card",
]
