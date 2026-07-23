"""Authorize tool invocations for AscendC Agent (OpenCode plugin hook).

State / Workflow Spec aware: validates workflow, phase, action, agent role,
and write roots. Soft control-plane only — not OS-level security.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Direct domain CLIs that must go through Harness wrappers
_DENY_BASH = [
    re.compile(r"\bpython(?:3)?\b.*\bbuild_layered_kb\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bcheck_final_confidence\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bprepare_operator\.py\b", re.I),
    re.compile(r"\btg-solve\b", re.I),
    re.compile(r"\btg-plan\b", re.I),
    re.compile(r"\btg-init\b", re.I),
    re.compile(r"\buo-init\b", re.I),
]

_ALLOW_BASH = [
    re.compile(r"^\s*harness(\s|$)"),
    re.compile(r"^\s*python(?:3)?\s+-m\s+ascendc_harness(\s|$)"),
]

# Formal product paths — require matching producer/referee/engine action
_PROTECTED_MARKERS = (
    "/ir/",
    "/summary/",
    "/checks/",
    "/review/",
    "/realization/",
    "/init/audit_report",
    "/plan/levels/",
    "/solve/",
    "/contracts/",  # retired; still deny
)

_PRIMARY_AGENTS = frozenset({"ascendc-agent", "ascendc_agent", ""})

_ROLE_WRITE_POLICY = {
    "producer": "formal",
    "referee": "review_only",
    "readonly_analyst": "none",
    "readonly_reviewer": "review_only",
    "deterministic_engine": "formal",
    "deterministic_checker": "checks_only",
}


def _ok(decision: str, reason_code: str, reason_zh: str, **extra: Any) -> dict[str, Any]:
    return {
        "ok": decision == "allow",
        "decision": decision,
        "reason_code": reason_code,
        "reason_zh": reason_zh,
        **extra,
    }


def _load_context(project_root: Path | None) -> dict[str, Any]:
    if project_root is None:
        return {}
    try:
        from ascendc_harness.state import load_state
        from ascendc_harness.workflows import actions_for_phase, get_workflow

        state = load_state(project_root)
        if not state:
            return {"state": {}, "meta": {}, "allowed_actions": []}
        wid = str(state.get("workflow_id") or "")
        phase = str(state.get("phase") or "")
        meta = get_workflow(wid) if wid else {}
        actions = actions_for_phase(wid, phase) if wid and phase else []
        return {"state": state, "meta": meta, "allowed_actions": actions, "workflow_id": wid, "phase": phase}
    except Exception as exc:  # noqa: BLE001
        return {"state": {}, "meta": {}, "allowed_actions": [], "error": str(exc)[:200]}


def _agent_role(meta: dict[str, Any], agent: str) -> str | None:
    agent_l = agent.strip().lower()
    for row in meta.get("agents") or []:
        if isinstance(row, dict) and str(row.get("id") or "").lower() == agent_l:
            return str(row.get("role") or "")
    return None


def _action_by_id(actions: list[dict[str, Any]], action_id: str) -> dict[str, Any] | None:
    for a in actions:
        if str(a.get("id") or "") == action_id:
            return a
    return None


def _path_in_write_roots(norm: str, write_roots: list[str], project_marker: str = ".ascendc-agent") -> bool:
    """True if path is under an allowed write root (relative to agent layout)."""
    if not write_roots:
        return True
    # Normalize to look for .ascendc-agent/<root>/...
    for root in write_roots:
        root_s = str(root).replace("\\", "/").strip("/")
        markers = [
            f"/{project_marker}/{root_s}/",
            f"/{project_marker}/{root_s}",
            f"/{root_s}/",
        ]
        # Also allow bare root segment after agent dir
        if any(m in norm or norm.endswith(m.rstrip("/")) for m in markers):
            return True
        # uo/review style nested roots
        if "/" in root_s and f"/{root_s}/" in norm:
            return True
    # Always allow runs/state under agent dir for harness itself
    if f"/{project_marker}/runs/" in norm or f"/{project_marker}/state/" in norm:
        return True
    return False


def _is_protected_write(norm: str) -> bool:
    return any(m in norm for m in _PROTECTED_MARKERS)


def _is_review_path(norm: str) -> bool:
    return "/review/" in norm or norm.endswith("_review.yaml") or "audit_report" in norm


def _is_checks_path(norm: str) -> bool:
    return "/checks/" in norm


def authorize(
    project_root: Path | None = None,
    *,
    tool: str,
    command: str = "",
    path: str = "",
    agent: str = "",
    action: str = "",
) -> dict[str, Any]:
    """Return {ok, decision, reason_zh, reason_code}.

    Soft control-plane gate — not OS-level security. Bypass via other tabs/terminals
    still cannot obtain harness `passed` without receipts + complete.
    """
    tool_l = (tool or "").strip().lower()
    cmd = (command or "").strip()
    path_s = path or ""
    agent_l = (agent or "").strip().lower()
    action_id = (action or "").strip()

    ctx = _load_context(project_root)
    meta = ctx.get("meta") or {}
    state = ctx.get("state") or {}
    allowed = ctx.get("allowed_actions") or []
    role = _agent_role(meta, agent_l) if agent_l else None

    # --- bash / shell ---
    if tool_l in {"bash", "shell", "terminal"}:
        for pat in _ALLOW_BASH:
            if pat.search(cmd):
                return _ok(
                    "allow",
                    "HARNESS_CLI",
                    "允许 harness CLI",
                    workflow_id=ctx.get("workflow_id"),
                    phase=ctx.get("phase"),
                )
        for pat in _DENY_BASH:
            if pat.search(cmd):
                return _ok(
                    "deny",
                    "DOMAIN_CLI_BYPASS",
                    "禁止直调领域脚本/CLI；请经 harness 包装执行",
                    command=cmd[:200],
                )
        if agent_l in _PRIMARY_AGENTS:
            return _ok(
                "ask",
                "BASH_NOT_HARNESS",
                "AscendC Agent 默认仅允许 harness *；其他 bash 需人工确认",
                command=cmd[:200],
            )
        # Subagent producers may run harness-wrapped flows; still deny domain CLIs (above)
        return _ok("allow", "NON_PRIMARY", "非 primary 代理放行（仍禁止领域 CLI 直调）")

    # --- task / subagent spawn ---
    if tool_l in {"task", "subagent", "task_tool"}:
        if agent_l in _PRIMARY_AGENTS:
            # Primary may spawn Task for declared actors of current phase actions
            target = path_s or cmd  # plugin may pass agent name in path/command
            declared_actors: set[str] = set()
            for a in allowed:
                aid = a.get("agent_id")
                if aid:
                    declared_actors.add(str(aid).lower())
                for act in a.get("actors") or []:
                    declared_actors.add(str(act).lower())
            for row in meta.get("agents") or []:
                if isinstance(row, dict) and row.get("id"):
                    declared_actors.add(str(row["id"]).lower())
            target_l = target.strip().lower()
            if target_l and declared_actors and target_l not in declared_actors and not target_l.startswith("uo-") and not target_l.startswith("tg-"):
                return _ok(
                    "deny",
                    "TASK_AGENT_UNKNOWN",
                    f"当前阶段未声明子代理 {target!r}",
                    agent=target,
                    phase=ctx.get("phase"),
                )
            return _ok(
                "allow",
                "TASK_OK",
                "允许启动当前工作流声明的子代理任务",
                phase=ctx.get("phase"),
                workflow_id=ctx.get("workflow_id"),
            )
        return _ok("allow", "TASK_NON_PRIMARY", "非 primary 任务放行")

    # --- write / edit / apply_patch ---
    if tool_l in {"write", "edit", "apply_patch", "strreplace", "patch"}:
        norm = path_s.replace("\\", "/")
        write_roots = list(meta.get("write_roots") or [])

        # Action must be currently allowed when provided
        action_row = None
        if action_id:
            action_row = _action_by_id(allowed, action_id)
            if action_row is None and state:
                return _ok(
                    "deny",
                    "ACTION_NOT_ALLOWED",
                    f"动作 {action_id!r} 不在当前阶段「{ctx.get('phase')}」允许列表中",
                    action=action_id,
                    phase=ctx.get("phase"),
                    allowed_action_ids=[a.get("id") for a in allowed],
                )
            actors = [str(x).lower() for x in (action_row.get("actors") or [])]
            if not actors and action_row.get("agent_id"):
                actors = [str(action_row["agent_id"]).lower()]
            if actors and agent_l and agent_l not in _PRIMARY_AGENTS and agent_l not in actors:
                return _ok(
                    "deny",
                    "ACTOR_MISMATCH",
                    f"代理 {agent_l!r} 不是动作 {action_id!r} 的声明 actor",
                    action=action_id,
                    actors=actors,
                )

        # Primary must not freely write formal products
        if agent_l in _PRIMARY_AGENTS and _is_protected_write(norm):
            return _ok(
                "deny",
                "PRIMARY_PROTECTED_WRITE",
                "正式 IR/summary/checks/review/TG 产物须由声明的 Producer/Referee/Engine 经 Harness 写入",
                path=path_s,
                action=action_id,
            )

        # Write roots from workflow spec
        if write_roots and norm and state and not _path_in_write_roots(norm, write_roots):
            # Allow only if not under .ascendc-agent at all (scratch) — still deny protected
            if ".ascendc-agent" in norm or "/uo/" in norm or "/tg/" in norm:
                return _ok(
                    "deny",
                    "WRITE_ROOT_DENIED",
                    f"写路径不在当前工作流 write_roots {write_roots} 内",
                    path=path_s,
                    write_roots=write_roots,
                )

        # Role-aware protected writes
        if _is_protected_write(norm) and role:
            policy = _ROLE_WRITE_POLICY.get(role, "none")
            if policy == "none":
                return _ok(
                    "deny",
                    "ROLE_READONLY",
                    f"角色 {role} 不可写正式产物",
                    path=path_s,
                    agent=agent_l,
                )
            if policy == "review_only" and not _is_review_path(norm):
                return _ok(
                    "deny",
                    "REFEREE_WRITE_SCOPE",
                    "Referee/Reviewer 仅可写 review/audit 产物，不可改 IR/summary",
                    path=path_s,
                    agent=agent_l,
                )
            if policy == "checks_only" and not _is_checks_path(norm):
                return _ok(
                    "deny",
                    "CHECKER_WRITE_SCOPE",
                    "Checker 仅可写 checks 产物",
                    path=path_s,
                    agent=agent_l,
                )

        # Formal product write without action when workflow active
        if _is_protected_write(norm) and state and not action_id and agent_l not in _PRIMARY_AGENTS:
            return _ok(
                "deny",
                "ACTION_REQUIRED",
                "写入正式产物必须声明当前阶段的 action_id",
                path=path_s,
                phase=ctx.get("phase"),
            )

        return _ok(
            "allow",
            "WRITE_OK",
            "写路径授权通过",
            path=path_s,
            action=action_id or None,
            agent=agent_l or None,
            role=role,
            workflow_id=ctx.get("workflow_id"),
            phase=ctx.get("phase"),
        )

    return _ok("allow", "TOOL_DEFAULT", "默认放行", tool=tool_l)
