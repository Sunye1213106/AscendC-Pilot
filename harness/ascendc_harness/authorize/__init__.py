"""Authorize tool invocations for AscendC Agent (OpenCode plugin hook).

State / Workflow Spec aware: validates workflow, phase, action, agent role,
and write roots. Soft control-plane only — not OS-level security.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Direct domain CLIs that must go through Harness run-action
_DENY_BASH = [
    re.compile(r"\bpython(?:3)?\b.*\bbuild_layered_kb\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bcheck_final_confidence\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bprepare_operator\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bexport_kb_graph\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bcheck_kb_integrity\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bclassify_input_derivable\.py\b", re.I),
    re.compile(r"\btg-solve\b", re.I),
    re.compile(r"\btg-plan\b", re.I),
    re.compile(r"\btg-init\b", re.I),
    re.compile(r"\btg-contract\b", re.I),
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


def _path_in_write_roots(
    path: str | Path,
    write_roots: list[str],
    project_root: Path | None = None,
    project_marker: str = ".ascendc-agent",
) -> bool:
    """True if path is under an allowed write root (canonical path containment)."""
    if not write_roots:
        return True
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        resolved = Path(str(path).replace("\\", "/"))

    # Always allow runs/state under agent dir for harness itself
    norm = str(resolved).replace("\\", "/")
    if f"/{project_marker}/runs/" in norm or f"/{project_marker}/state/" in norm:
        return True
    if norm.rstrip("/").endswith(f"/{project_marker}/runs") or norm.rstrip("/").endswith(f"/{project_marker}/state"):
        return True

    agent_base: Path | None = None
    if project_root is not None:
        try:
            from ascendc_harness.paths import agent_root

            agent_base = agent_root(project_root)
        except Exception:  # noqa: BLE001
            agent_base = Path(project_root).resolve() / project_marker
    else:
        # Infer agent root from path markers
        parts = norm.split(f"/{project_marker}/")
        if len(parts) >= 2:
            agent_base = Path(parts[0]) / project_marker

    if agent_base is None:
        # Fallback: substring markers (legacy)
        for root in write_roots:
            root_s = str(root).replace("\\", "/").strip("/")
            if f"/{project_marker}/{root_s}/" in norm or norm.endswith(f"/{project_marker}/{root_s}"):
                return True
        return False

    for root in write_roots:
        root_s = str(root).replace("\\", "/").strip("/")
        allowed = (agent_base / root_s).resolve()
        try:
            resolved.relative_to(allowed)
            return True
        except ValueError:
            continue
    return False


def _is_protected_write(norm: str) -> bool:
    return any(m in norm for m in _PROTECTED_MARKERS)


def _is_review_path(norm: str) -> bool:
    return "/review/" in norm or norm.endswith("_review.yaml") or "audit_report" in norm


def _is_checks_path(norm: str) -> bool:
    return "/checks/" in norm


def _declared_phase_actors(allowed: list[dict[str, Any]], meta: dict[str, Any]) -> set[str]:
    """Actors declared on current-phase actions only (not all workflow agents)."""
    declared: set[str] = set()
    for a in allowed:
        aid = a.get("agent_id")
        if aid:
            declared.add(str(aid).lower())
        for act in a.get("actors") or []:
            declared.add(str(act).lower())
    # Primary may always be named
    declared.add("ascendc-agent")
    declared.add("human")
    return declared


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
                    "禁止直调领域脚本/CLI；请经 harness run-action 执行",
                    command=cmd[:200],
                )
        if agent_l in _PRIMARY_AGENTS:
            return _ok(
                "ask",
                "BASH_NOT_HARNESS",
                "AscendC Agent 默认仅允许 harness *；其他 bash 需人工确认",
                command=cmd[:200],
            )
        # Non-primary: still deny domain CLIs (above); other bash ask (not open allow)
        return _ok(
            "ask",
            "NON_PRIMARY_BASH",
            "非 primary 代理 bash 需确认；领域执行请用 harness run-action",
            command=cmd[:200],
        )

    # --- task / subagent spawn ---
    if tool_l in {"task", "subagent", "task_tool"}:
        if agent_l in _PRIMARY_AGENTS:
            target = path_s or cmd  # plugin may pass agent name in path/command
            declared_actors = _declared_phase_actors(allowed, meta)
            target_l = target.strip().lower()
            # No uo-/tg- prefix bypass — must be an explicitly declared phase actor.
            if target_l and declared_actors and target_l not in declared_actors:
                return _ok(
                    "deny",
                    "TASK_AGENT_UNKNOWN",
                    f"当前阶段未声明子代理 {target!r}",
                    agent=target,
                    phase=ctx.get("phase"),
                    declared_actors=sorted(declared_actors),
                )
            return _ok(
                "allow",
                "TASK_OK",
                "允许启动当前阶段声明的子代理任务",
                phase=ctx.get("phase"),
                workflow_id=ctx.get("workflow_id"),
            )
        return _ok("deny", "TASK_NON_PRIMARY", "非 primary 不得再派发 Task")

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

        # Write roots from workflow spec (canonical containment)
        if write_roots and norm and state and not _path_in_write_roots(
            path_s or norm, write_roots, project_root=project_root
        ):
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

        # Agent write_scopes (from agents-src) — real runtime boundary
        if agent_l and agent_l not in _PRIMARY_AGENTS and _is_protected_write(norm):
            from ascendc_harness.agents_registry import (
                agent_write_scopes,
                path_matches_scope,
                rel_under_agent_dir,
            )

            scopes = agent_write_scopes(agent_l, project_root)
            if scopes:
                rel = rel_under_agent_dir(path_s or norm, project_root)
                # Also accept bare tg/... style paths
                if rel is None:
                    rel_try = norm
                    marker = "/.ascendc-agent/"
                    if marker in rel_try:
                        rel = rel_try.split(marker, 1)[1]
                    elif "tg/" in rel_try or rel_try.startswith("tg/"):
                        idx = rel_try.find("tg/")
                        rel = rel_try[idx:]
                    elif "uo/" in rel_try or rel_try.startswith("uo/"):
                        idx = rel_try.find("uo/")
                        rel = rel_try[idx:]
                    else:
                        rel = rel_try.lstrip("/")
                if rel is not None and not path_matches_scope(rel, scopes):
                    return _ok(
                        "deny",
                        "AGENT_WRITE_SCOPE",
                        f"代理 {agent_l} 不得写入声明 write_scopes 之外的路径",
                        path=path_s,
                        agent=agent_l,
                        write_scopes=scopes,
                        rel=rel,
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
