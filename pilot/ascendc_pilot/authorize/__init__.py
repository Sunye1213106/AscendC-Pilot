"""Authorize tool invocations for AscendC-Pilot (OpenCode plugin hook).

State / Workflow Spec / Action Lease aware. Soft control-plane only — not OS security.
On human_required / containment lease, tools are hard-denied before execution.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ascendc_pilot.authorize.lease import (
    CONTAINMENT_COMMAND_PREFIXES,
    MODE_CONTAINMENT,
    MODE_REWORK,
    REWORK_COMMAND_PREFIXES,
    authorization_mode_for_status,
    command_matches_prefixes,
    extract_pilot_command,
    is_lease_revoked,
    load_lease,
)

# Direct domain CLIs that must go through Pilot run-action
_DENY_BASH = [
    re.compile(r"\bpython(?:3)?\b.*\bbuild_layered_kb\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bcheck_final_confidence\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bprepare_operator\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bexport_kb_graph\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bcheck_kb_integrity\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bclassify_input_derivable\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bmacro_scope_scan\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\breview_checkpoint\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bfinalize_scope\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bextract_build_evidence\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bsource_closure\.py\b", re.I),
    re.compile(r"\bpython(?:3)?\b.*\bstage_cbm_scope\.py\b", re.I),
    re.compile(r"\btg-solve\b", re.I),
    re.compile(r"\btg-plan\b", re.I),
    re.compile(r"\btg-init\b", re.I),
    re.compile(r"\btg-contract\b", re.I),
    re.compile(r"\buo-init\b", re.I),
]

_ALLOW_BASH = [
    re.compile(r"^\s*acp(\s|$)"),
    re.compile(r"^\s*python(?:3)?\s+-m\s+ascendc_pilot(\s|$)"),
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

# Pilot formal scope artifacts — never agent-writable in containment
_FORMAL_ARTIFACT_NAMES = (
    "installed_skill_check.yaml",
    "semantic_enrichment.yaml",
    "manifest.yaml",
    "scope_confirmed.yaml",
    "scope_review.yaml",
    "scope_scan.yaml",
    "receipt.yaml",
    "context.yaml",
)

_ENGINE_SOURCE_MARKERS = (
    "prepare_operator.py",
    "macro_scope_scan.py",
    "review_checkpoint.py",
    "finalize_scope.py",
    "extract_build_evidence.py",
    "source_closure.py",
    "stage_cbm_scope.py",
    "/engines/understand-operator/",
    "/engines/testcase-generation/",
    "ascendc_pilot/",
)

_PRIMARY_AGENTS = frozenset({"ascendc-pilot", "ascendc_agent", ""})
_PASS_THROUGH_AGENTS = frozenset(
    {
        "build",
        "plan",
        "general",
        "general-purpose",
        "generalpurpose",
        "ask",
        "debug",
    }
)
_PILOT_AGENT_PREFIXES = ("uo-", "tg-", "deterministic-", "ce-")


def _project_root_for_path(project_root: Path | None, path_s: str) -> Path | None:
    """Prefer operator package that owns ``path`` when it embeds ``.ascendc-pilot``."""
    norm = (path_s or "").replace("\\", "/")
    marker = "/.ascendc-pilot/"
    idx = norm.lower().find(marker)
    if idx > 0:
        candidate = Path(norm[:idx])
        if (candidate / ".ascendc-pilot").is_dir() or candidate.is_dir():
            return candidate.resolve()
    return project_root.resolve() if project_root is not None else None


def _load_active_action(project_root: Path | None) -> dict[str, Any]:
    if project_root is None:
        return {}
    try:
        from ascendc_pilot.paths import agent_root

        path = agent_root(project_root) / "state" / "active_action.yaml"
        if not path.is_file():
            return {}
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _remap_primary_actor(
    project_root: Path | None,
    agent_l: str,
    action_id: str,
) -> tuple[str, str]:
    """When hooks mislabel producer writes as primary, trust prepared active_action.

    Only for write tools — Task dispatch must keep agent=primary.
    """
    if agent_l not in _PRIMARY_AGENTS:
        return agent_l, action_id
    active = _load_active_action(project_root)
    actor = str(active.get("actor_id") or "").strip().lower()
    act = str(active.get("action_id") or "").strip()
    if not actor or actor in _PRIMARY_AGENTS:
        return agent_l, action_id
    # Only remap when action matches (or caller omitted action and we fill it).
    if action_id and act and action_id != act:
        return agent_l, action_id
    return actor, action_id or act


def _fill_action_from_active(project_root: Path | None, action_id: str) -> str:
    if action_id:
        return action_id
    active = _load_active_action(project_root)
    return str(active.get("action_id") or "").strip()


def _is_pilot_family_agent(agent_l: str, meta: dict[str, Any] | None = None) -> bool:
    """True for ascendc-pilot and declared UO/TG/CE actors; False for Build/Plan/etc."""
    a = (agent_l or "").strip().lower()
    if a in _PRIMARY_AGENTS:
        return True
    if a in _PASS_THROUGH_AGENTS:
        return False
    if a.startswith(_PILOT_AGENT_PREFIXES):
        return True
    meta = meta or {}
    for act in meta.get("actions") or []:
        if not isinstance(act, dict):
            continue
        aid = str(act.get("agent_id") or "").strip().lower()
        if aid and aid == a:
            return True
        for actor in act.get("actors") or []:
            if str(actor).strip().lower() == a:
                return True
    # Unknown Tab agents behave like OpenCode Build (no harness).
    return False

_ROLE_WRITE_POLICY = {
    "producer": "formal",
    "referee": "review_only",
    "readonly_analyst": "none",
    "readonly_reviewer": "review_only",
    "deterministic_engine": "formal",
    "deterministic_checker": "checks_only",
}

_READ_TOOLS = frozenset({"read", "glob", "grep", "list", "search", "find"})
_WRITE_TOOLS = frozenset({"write", "edit", "apply_patch", "strreplace", "patch"})
_BASH_TOOLS = frozenset({"bash", "shell", "terminal"})
_TASK_TOOLS = frozenset({"task", "subagent", "task_tool"})
_QUESTION_TOOLS = frozenset({"question", "ask_user", "ask"})


def _ok(decision: str, reason_code: str, reason_zh: str, **extra: Any) -> dict[str, Any]:
    return {
        "ok": decision == "allow",
        "decision": decision,
        "reason_code": reason_code,
        "reason_zh": reason_zh,
        **extra,
    }


def _deny_not_authorized(
    reason: str,
    *,
    status: str = "",
    allowed_actions: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return _ok(
        "deny",
        "HARNESS_ACTION_NOT_AUTHORIZED",
        reason,
        error_code="HARNESS_ACTION_NOT_AUTHORIZED",
        reason=reason,
        status=status or None,
        allowed_actions=list(allowed_actions or CONTAINMENT_COMMAND_PREFIXES[:5]),
        **extra,
    )


def _load_context(project_root: Path | None) -> dict[str, Any]:
    if project_root is None:
        return {}
    try:
        from ascendc_pilot.state import load_state
        from ascendc_pilot.workflows import actions_for_phase, get_workflow

        state = load_state(project_root)
        if not state:
            return {"state": {}, "meta": {}, "allowed_actions": []}
        wid = str(state.get("workflow_id") or "")
        phase = str(state.get("phase") or "")
        meta = get_workflow(wid) if wid else {}
        actions = actions_for_phase(wid, phase) if wid and phase else []
        lease = load_lease(project_root)
        return {
            "state": state,
            "meta": meta,
            "allowed_actions": actions,
            "workflow_id": wid,
            "phase": phase,
            "lease": lease,
        }
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
    project_marker: str = ".ascendc-pilot",
) -> bool:
    """True if path is under an allowed write root (canonical path containment)."""
    if not write_roots:
        return True
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        resolved = Path(str(path).replace("\\", "/"))

    norm = str(resolved).replace("\\", "/")
    if f"/{project_marker}/runs/" in norm or f"/{project_marker}/state/" in norm:
        return True
    if norm.rstrip("/").endswith(f"/{project_marker}/runs") or norm.rstrip("/").endswith(
        f"/{project_marker}/state"
    ):
        return True

    agent_base: Path | None = None
    if project_root is not None:
        try:
            from ascendc_pilot.paths import agent_root

            agent_base = agent_root(project_root)
        except Exception:  # noqa: BLE001
            agent_base = Path(project_root).resolve() / project_marker
    else:
        parts = norm.split(f"/{project_marker}/")
        if len(parts) >= 2:
            agent_base = Path(parts[0]) / project_marker

    if agent_base is None:
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


def _is_formal_artifact(norm: str) -> bool:
    base = norm.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return base in _FORMAL_ARTIFACT_NAMES or any(
        f"/{name}" in norm.replace("\\", "/").lower() for name in _FORMAL_ARTIFACT_NAMES
    )


def _is_pilot_internal_path(norm: str) -> bool:
    n = norm.replace("\\", "/").lower()
    return (
        "/.ascendc-pilot/" in n
        or n.endswith("/.ascendc-pilot")
        or "/ascendc_pilot/" in n
        or any(m.lower() in n for m in _ENGINE_SOURCE_MARKERS)
    )


def _is_engine_source(norm: str) -> bool:
    n = norm.replace("\\", "/").lower()
    return any(m.lower() in n for m in _ENGINE_SOURCE_MARKERS)


def _declared_phase_actors(
    allowed: list[dict[str, Any]],
    meta: dict[str, Any],
    project_root: Path | None = None,
) -> set[str]:
    """Actors declared on current-phase actions only (not all workflow agents)."""
    declared: set[str] = set()
    for a in allowed:
        aid = a.get("agent_id")
        if aid:
            declared.add(str(aid).lower())
        for act in a.get("actors") or []:
            declared.add(str(act).lower())
    declared.add("ascendc-pilot")
    declared.add("human")
    # Prepared producer is always dispatchable even if phase listing is incomplete.
    active = _load_active_action(project_root)
    actor = str(active.get("actor_id") or "").strip().lower()
    if actor:
        declared.add(actor)
    return declared


def _normalize_cmd(command: str) -> str:
    extracted = extract_pilot_command(command)
    if extracted:
        return extracted
    cmd = " ".join(str(command or "").strip().split())
    for sep in ("|", ">", "<", "&&", "||", ";"):
        if sep in cmd:
            cmd = cmd.split(sep, 1)[0].strip()
    return cmd


def _is_containment_pilot_command(command: str) -> bool:
    return command_matches_prefixes(command, CONTAINMENT_COMMAND_PREFIXES)


def _is_rework_pilot_command(
    command: str,
    *,
    failed_action: str = "",
    recovery_actions: list[str] | None = None,
) -> bool:
    """True if command is a legal rework recovery / retry command."""
    if not command_matches_prefixes(command, REWORK_COMMAND_PREFIXES):
        return False
    cmd_l = _normalize_cmd(command).lower()
    # advance / complete never legal in rework
    if " advance" in f" {cmd_l}" or " complete" in f" {cmd_l}":
        return False
    if " run-action " in f" {cmd_l} " or cmd_l.endswith(" run-action"):
        allowed_ids: list[str] = []
        if failed_action:
            allowed_ids.append(failed_action.lower())
        for rid in recovery_actions or []:
            if rid:
                allowed_ids.append(str(rid).lower())
        if failed_action == "apply_semantic_patch" and "adjudicate_llm_tasks" not in allowed_ids:
            allowed_ids.append("adjudicate_llm_tasks")
        if not allowed_ids:
            return True
        return any(f"run-action {aid}" in cmd_l for aid in allowed_ids)
    return True


def _is_acp_cli(command: str) -> bool:
    cmd = _normalize_cmd(command)
    return bool(_ALLOW_BASH[0].search(cmd) or _ALLOW_BASH[1].search(cmd))


def _is_acp_start(command: str) -> bool:
    cmd_l = _normalize_cmd(command).lower()
    return (
        cmd_l.startswith("acp start")
        or cmd_l.startswith("python -m ascendc_pilot start")
        or cmd_l.startswith("python3 -m ascendc_pilot start")
    )


def authorize(
    project_root: Path | None = None,
    *,
    tool: str,
    command: str = "",
    path: str = "",
    agent: str = "",
    action: str = "",
    lease_id: str = "",
) -> dict[str, Any]:
    """Return {ok, decision, reason_zh, reason_code}.

    Soft control-plane gate — not OS-level security. Bypass via other tabs/terminals
    still cannot obtain acp `passed` without receipts + complete.

    Authorization mode is derived from workflow *status* only (never overridden by a
    stale containment lease). Lease is advisory evidence of what was issued.
    """
    tool_l = (tool or "").strip().lower()
    cmd_raw = (command or "").strip()
    # Authorize against extracted acp CLI when present (cd … && acp …).
    cmd = extract_pilot_command(cmd_raw) or cmd_raw
    path_s = path or ""
    agent_l = (agent or "").strip().lower()
    action_id = (action or "").strip()
    lease_id_s = (lease_id or "").strip()

    # Write path under <op>/.ascendc-pilot/… may arrive with a wrong project_root
    # (workspace parent). Prefer the operator package that owns the artifact.
    # Task path is usually the subagent name — never treat it as a filesystem path.
    if tool_l in _TASK_TOOLS:
        project_root = Path(project_root).resolve() if project_root is not None else None
    else:
        project_root = _project_root_for_path(project_root, path_s)

    # Remap primary→producer only for writes (hook mislabel). Task must stay primary.
    if tool_l in _WRITE_TOOLS:
        agent_l, action_id = _remap_primary_actor(project_root, agent_l, action_id)
    else:
        action_id = _fill_action_from_active(project_root, action_id)

    ctx = _load_context(project_root)
    meta = ctx.get("meta") or {}
    state = ctx.get("state") or {}
    allowed = ctx.get("allowed_actions") or []
    lease = ctx.get("lease") or {}
    role = _agent_role(meta, agent_l) if agent_l else None
    status = str(state.get("status") or "")
    auth_mode = authorization_mode_for_status(status) if state else "normal"

    # Non-Pilot tabs (Build / Plan / …): full pass-through even if a leftover
    # human_required run exists under .ascendc-pilot.
    if not _is_pilot_family_agent(agent_l, meta if isinstance(meta, dict) else {}):
        return _ok(
            "allow",
            "HARNESS_INACTIVE",
            "非 Pilot agent：不套用 Harness（与 Build/Plan 相同）",
            status=status or None,
            agent=agent_l or None,
        )

    # Explicit old lease reuse check
    if lease_id_s and project_root is not None and is_lease_revoked(project_root, lease_id_s):
        return _deny_not_authorized(
            "LEASE_REVOKED: provided lease is no longer valid",
            status=status,
            error_detail="LEASE_REVOKED",
            lease_id=lease_id_s,
        )

    # --- question / report to user: always allowed ---
    if tool_l in _QUESTION_TOOLS:
        return _ok("allow", "QUESTION_OK", "允许向用户提问或报告", status=status or None)

    # --- Always allow starting a new run (escape hatch from failed/human/rework) ---
    if tool_l in _BASH_TOOLS and _is_acp_start(cmd):
        return _ok(
            "allow",
            "HARNESS_START",
            "允许 acp start（新建或复用 run）",
            status=status or None,
            command=cmd[:200],
        )

    lf = state.get("last_failure") if isinstance(state.get("last_failure"), dict) else {}
    failed_action = str(lf.get("action_id") or lease.get("action_id") or "")
    recovery_actions = [str(x) for x in (lf.get("recovery_actions") or []) if str(x).strip()]
    if failed_action == "apply_semantic_patch" and "adjudicate_llm_tasks" not in recovery_actions:
        recovery_actions = list(recovery_actions) + ["adjudicate_llm_tasks"]

    # ========== STATUS-AUTHORITATIVE GATES ==========
    # Mode comes from status. Lease mode must not escalate rework → containment.

    if auth_mode == MODE_CONTAINMENT:
        allowed_cmds = list(CONTAINMENT_COMMAND_PREFIXES)
        if tool_l in _BASH_TOOLS:
            if _is_containment_pilot_command(cmd):
                return _ok(
                    "allow",
                    "CONTAINMENT_HARNESS",
                    f"失败收敛模式（status={status}）仅允许恢复类 acp 命令",
                    status=status,
                    command=cmd[:200],
                    allowed_actions=allowed_cmds[:8],
                )
            if _is_acp_cli(cmd):
                return _deny_not_authorized(
                    f"Current run is {status}; acp domain steps are revoked",
                    status=status,
                    command=cmd[:200],
                    allowed_actions=allowed_cmds[:8],
                )
            return _deny_not_authorized(
                f"Current run is {status}; bash not authorized",
                status=status,
                command=cmd[:200],
                allowed_actions=allowed_cmds[:8],
            )
        if tool_l in _READ_TOOLS | _WRITE_TOOLS | _TASK_TOOLS:
            return _deny_not_authorized(
                f"Current run is {status}; {tool_l} not authorized",
                status=status,
                path=path_s,
                tool=tool_l,
                allowed_actions=allowed_cmds[:8],
            )
        return _deny_not_authorized(
            f"Current run is {status}; tool {tool_l!r} not authorized",
            status=status,
            tool=tool_l,
            allowed_actions=allowed_cmds[:8],
        )

    if auth_mode == MODE_REWORK:
        if tool_l in _BASH_TOOLS:
            if _is_rework_pilot_command(
                cmd, failed_action=failed_action, recovery_actions=recovery_actions
            ):
                return _ok(
                    "allow",
                    "REWORK_HARNESS",
                    f"返工模式允许重试失败 Action / 恢复命令"
                    + (f"（action={failed_action}）" if failed_action else ""),
                    status=status,
                    action=failed_action or None,
                    recovery_actions=recovery_actions,
                    command=cmd[:200],
                )
            if _is_acp_cli(cmd):
                return _deny_not_authorized(
                    "rework_required: only retry of failed action / recovery acp commands allowed",
                    status=status,
                    command=cmd[:200],
                    allowed_actions=[
                        "acp next",
                        "acp status",
                        "acp inspect-failure",
                        f"acp run-action {failed_action}" if failed_action else "acp run-action <failed>",
                        *[f"acp run-action {r}" for r in recovery_actions[:3]],
                        "acp uo-scope …",
                        "acp abort",
                        "acp start",
                    ],
                )
            for pat in _DENY_BASH:
                if pat.search(cmd):
                    return _deny_not_authorized(
                        "rework_required: domain CLI bypass denied",
                        status=status,
                        command=cmd[:200],
                    )
            if agent_l in _PRIMARY_AGENTS:
                return _ok(
                    "ask",
                    "BASH_NOT_HARNESS",
                    "返工模式默认仅允许 acp *；其他 bash 需人工确认",
                    command=cmd[:200],
                )
            return _ok(
                "ask",
                "NON_PRIMARY_BASH",
                "非 primary 代理 bash 需确认",
                command=cmd[:200],
            )

        if tool_l in _WRITE_TOOLS and _is_formal_artifact(path_s.replace("\\", "/")):
            # Allow writes only when declaring the failed action (producer rework)
            if not action_id or (
                failed_action
                and action_id != failed_action
                and action_id not in recovery_actions
            ):
                return _deny_not_authorized(
                    "rework_required: formal artifact writes require failed action_id",
                    status=status,
                    path=path_s,
                    action=action_id or None,
                )
        if tool_l in _READ_TOOLS and _is_engine_source(path_s):
            base = path_s.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if base.endswith(".py") and any(
                base == m.lower()
                for m in (
                    "prepare_operator.py",
                    "macro_scope_scan.py",
                    "review_checkpoint.py",
                    "finalize_scope.py",
                )
            ):
                return _deny_not_authorized(
                    "rework_required: reading engine source not authorized",
                    status=status,
                    path=path_s,
                )
        # Fall through to normal tool policies for read/write/task under rework

    # ========== NORMAL / REWORK fall-through (running or allowed rework tools) ==========

    # --- bash / shell ---
    if tool_l in _BASH_TOOLS:
        # Deny shell redirects / writers aimed at formal pilot artifacts (fence bypass).
        cmd_l = cmd.lower().replace("\\", "/")
        if ".ascendc-pilot/" in cmd_l and any(
            tok in cmd_l
            for tok in (
                " >",
                ">>",
                " tee ",
                "set-content",
                "out-file",
                "add-content",
                "ni ",
                "new-item",
                "echo ",
                "printf ",
                "cat >",
                "copy ",
                "move ",
                "mv ",
                "cp ",
            )
        ):
            return _ok(
                "deny",
                "BASH_PROTECTED_WRITE",
                "禁止用 bash 写入 .ascendc-pilot 正式产物以绕过 Write 围栏；请由声明 actor 用 Write 或 acp run-action",
                error_code="HARNESS_ACTION_NOT_AUTHORIZED",
                command=cmd[:200],
            )
        for pat in _ALLOW_BASH:
            if pat.search(cmd):
                return _ok(
                    "allow",
                    "HARNESS_CLI",
                    "允许 acp CLI",
                    workflow_id=ctx.get("workflow_id"),
                    phase=ctx.get("phase"),
                )
        for pat in _DENY_BASH:
            if pat.search(cmd):
                return _ok(
                    "deny",
                    "DOMAIN_CLI_BYPASS",
                    "禁止直调领域脚本/CLI；请经 acp run-action 执行",
                    error_code="HARNESS_ACTION_NOT_AUTHORIZED",
                    command=cmd[:200],
                )
        if agent_l in _PRIMARY_AGENTS:
            return _ok(
                "ask",
                "BASH_NOT_HARNESS",
                "AscendC-Pilot 默认仅允许 acp *；其他 bash 需人工确认",
                command=cmd[:200],
            )
        return _ok(
            "ask",
            "NON_PRIMARY_BASH",
            "非 primary 代理 bash 需确认；领域执行请用 acp run-action",
            command=cmd[:200],
        )

    # --- read / glob / grep ---
    if tool_l in _READ_TOOLS:
        norm = path_s.replace("\\", "/")
        if state and status == "running" and _is_engine_source(norm) and "engines/" in norm.lower():
            base = norm.rsplit("/", 1)[-1].lower()
            if base.endswith(".py") and any(
                base == m.lower()
                for m in (
                    "prepare_operator.py",
                    "macro_scope_scan.py",
                    "review_checkpoint.py",
                    "finalize_scope.py",
                )
            ):
                return _ok(
                    "deny",
                    "ENGINE_SOURCE_DENIED",
                    "禁止读取领域引擎脚本以手工绕过 acp；请使用 acp 包装命令",
                    error_code="HARNESS_ACTION_NOT_AUTHORIZED",
                    path=path_s,
                )
        return _ok("allow", "READ_OK", "读取授权通过", tool=tool_l, path=path_s or None)

    # --- task / subagent spawn ---
    if tool_l in _TASK_TOOLS:
        if agent_l in _PRIMARY_AGENTS:
            target = path_s or cmd
            declared_actors = _declared_phase_actors(allowed, meta, project_root)
            target_l = target.strip().lower()
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
    if tool_l in _WRITE_TOOLS:
        norm = path_s.replace("\\", "/")
        write_roots = list(meta.get("write_roots") or [])

        if _is_formal_artifact(norm) and auth_mode == MODE_CONTAINMENT:
            return _deny_not_authorized(
                "Writing formal acp artifacts not authorized in failure state",
                status=status,
                path=path_s,
            )

        action_row = None
        if action_id:
            action_row = _action_by_id(allowed, action_id)
            # In rework, allow the failed action even if describe_next emptied allowed_actions
            if action_row is None and auth_mode == MODE_REWORK and failed_action and (
                action_id == failed_action or action_id in recovery_actions
            ):
                action_row = {"id": action_id}
            if action_row is None and state and auth_mode != MODE_REWORK:
                return _ok(
                    "deny",
                    "ACTION_NOT_ALLOWED",
                    f"动作 {action_id!r} 不在当前阶段「{ctx.get('phase')}」允许列表中",
                    action=action_id,
                    phase=ctx.get("phase"),
                    allowed_action_ids=[a.get("id") for a in allowed],
                )
            if action_row is not None:
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

        if agent_l in _PRIMARY_AGENTS and _is_protected_write(norm):
            return _ok(
                "deny",
                "PRIMARY_PROTECTED_WRITE",
                "正式 IR/summary/checks/review/TG 产物须由声明的 Producer/Referee/Engine 经 Pilot 写入",
                path=path_s,
                action=action_id,
            )

        if write_roots and norm and state and not _path_in_write_roots(
            path_s or norm, write_roots, project_root=project_root
        ):
            if ".ascendc-pilot" in norm or "/uo/" in norm or "/tg/" in norm:
                return _ok(
                    "deny",
                    "WRITE_ROOT_DENIED",
                    f"写路径不在当前工作流 write_roots {write_roots} 内",
                    path=path_s,
                    write_roots=write_roots,
                )

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

        if _is_protected_write(norm) and state and not action_id and agent_l not in _PRIMARY_AGENTS:
            return _ok(
                "deny",
                "ACTION_REQUIRED",
                "写入正式产物必须声明当前阶段的 action_id",
                path=path_s,
                phase=ctx.get("phase"),
            )

        if agent_l and agent_l not in _PRIMARY_AGENTS and _is_protected_write(norm):
            from ascendc_pilot.agents_registry import (
                agent_write_scopes,
                path_matches_scope,
                rel_under_agent_dir,
            )

            scopes = agent_write_scopes(agent_l, project_root)
            if scopes:
                rel = rel_under_agent_dir(path_s or norm, project_root)
                if rel is None:
                    rel_try = norm
                    marker = "/.ascendc-pilot/"
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
