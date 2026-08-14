"""Authorize tool invocations for AscendC-Pilot (OpenCode plugin hook).

State / Workflow Spec / Action Lease aware. Soft control-plane only — not OS security.
On human_required / containment lease, tools are hard-denied before execution.
"""

from __future__ import annotations

import json
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

# Read-only path / structure probes (prefer Read/Glob tools for file contents).
# grep/rg/Select-String allowed as locate-only (policy: code-access); not evidence alone.
_ALLOW_BASH_READONLY_HEAD = [
    # Unix / cmd listing & cwd
    re.compile(r"^\s*(ls|dir|tree|pwd)\b", re.I),
    # Locate-only search (no writes; still blocked if redirected into .ascendc-pilot)
    re.compile(r"^\s*(grep|rg|ripgrep|findstr)\b", re.I),
    re.compile(r"^\s*(Select-String|sls)\b", re.I),
    # PowerShell listing / path probes / navigation
    re.compile(
        r"^\s*(Get-ChildItem|gci|Get-Item|gi|Get-Location|gl|"
        r"Test-Path|Resolve-Path|Get-Command|gcm|where(?:\.exe)?|"
        r"cd|Set-Location|sl|Push-Location|Pop-Location)\b",
        re.I,
    ),
]
# Safe pipeline stages after a readonly head (still no writes).
_ALLOW_BASH_READONLY_PIPE = [
    re.compile(
        r"^\s*(Select-Object|select|Format-Table|ft|Format-List|fl|"
        r"Where-Object|where|\?|Sort-Object|sort|Measure-Object|measure|"
        r"Group-Object|ForEach-Object|%|Select-String|sls)\b",
        re.I,
    ),
]

# Shell writers into .ascendc-pilot — word boundaries so "cp " does not match "acp ".
_BASH_PROTECTED_WRITE_RES = [
    re.compile(r"\s>>?"),
    re.compile(r"(^|[\s|;&])tee(\s|$)"),
    re.compile(r"\bset-content\b"),
    re.compile(r"\bout-file\b"),
    re.compile(r"\badd-content\b"),
    re.compile(r"(^|[\s|;&])ni(\s|$)"),
    re.compile(r"\bnew-item\b"),
    re.compile(r"(^|[\s|;&])echo(\s|$)"),
    re.compile(r"(^|[\s|;&])printf(\s|$)"),
    re.compile(r"\bcat\s*>"),
    re.compile(r"\bcopy(\s|$)"),
    re.compile(r"\bmove(\s|$)"),
    re.compile(r"(^|[\s|;&])mv(\s|$)"),
    re.compile(r"(^|[\s|;&])cp(\s|$)"),
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
    "scope_validated.yaml",
    "scope_" + "confirmed.yaml",  # legacy layout; deny writes, no auto-migrate
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


def _is_pilot_project_root(project_root: Path | None) -> bool:
    if project_root is None:
        return False
    try:
        from ascendc_pilot.paths import agent_root

        return (agent_root(Path(project_root)) / "state" / "workflow.yaml").is_file()
    except Exception:  # noqa: BLE001
        return False


def _read_last_project_cache() -> Path | None:
    """OpenCode plugin cache of the last live Pilot operator root."""
    cache = Path.home() / ".config" / "opencode" / "ascendc-last-project"
    try:
        if not cache.is_file():
            return None
        root = Path(cache.read_text(encoding="utf-8").strip())
        if _is_pilot_project_root(root):
            return root.resolve()
    except Exception:  # noqa: BLE001
        return None
    return None


def _read_pending_dispatch_project() -> Path | None:
    """Operator root from the last ``dispatch_subagent`` handoff (pilot_run).

    OpenCode Task hooks often re-detect cwd / a short Task description and miss
    the stub path. ``ascendc-pending-dispatch.json`` is written with the live
    operator before Primary calls Task — that is the source of truth.
    """
    cache = Path.home() / ".config" / "opencode" / "ascendc-pending-dispatch.json"
    try:
        if not cache.is_file():
            return None
        rec = json.loads(cache.read_text(encoding="utf-8"))
        if not isinstance(rec, dict):
            return None
        root = Path(str(rec.get("project") or "").strip())
        if _is_pilot_project_root(root):
            return root.resolve()
    except Exception:  # noqa: BLE001
        return None
    return None


def _resolve_task_project_root(project_root: Path | None) -> Path | None:
    """Task hooks often pass workspace cwd (no workflow). Prefer last live Pilot root."""
    if _is_pilot_project_root(project_root):
        return Path(project_root).resolve()
    pending = _read_pending_dispatch_project()
    if pending is not None:
        return pending
    cached = _read_last_project_cache()
    if cached is not None:
        return cached
    return Path(project_root).resolve() if project_root is not None else None


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
    Never remap after finalize/revoke (Primary must retain control-plane identity).
    """
    if agent_l not in _PRIMARY_AGENTS:
        return agent_l, action_id
    active = _load_active_action(project_root)
    status = str(active.get("status") or "").strip().lower()
    # Live lease only. finalized/revoked/empty must not re-attribute Primary writes.
    if status not in {"prepared", "running", "actor_running"}:
        return agent_l, action_id
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
    status = str(active.get("status") or "").strip().lower()
    if status not in {"prepared", "running", "actor_running"}:
        return ""
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
    "controller": "formal",
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
        # project_root selects the mode overlay so authorization sees the
        # same effective action set as the running workflow.
        meta = get_workflow(wid, project_root=project_root) if wid else {}
        actions = (
            actions_for_phase(wid, phase, project_root=project_root)
            if wid and phase
            else []
        )
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


def _split_shell_segments(command: str) -> list[str]:
    """Split on ``&&`` / ``;`` / ``|`` only outside quotes.

    findstr/Select-String patterns often embed ``\\|`` inside ``"..."``; a naive
    ``re.split`` on ``|`` falsely treats those as pipelines and denies readonly
    locate commands (NON_PRIMARY_BASH).
    """
    cmd = command or ""
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            elif ch == "\\" and i + 1 < n:
                # Keep escaped char inside quotes (e.g. findstr ``\|``).
                buf.append(cmd[i + 1])
                i += 2
                continue
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "&" and i + 1 < n and cmd[i + 1] == "&":
            seg = "".join(buf).strip()
            if seg:
                segments.append(seg)
            buf = []
            i += 2
            continue
        if ch in (";", "|"):
            seg = "".join(buf).strip()
            if seg:
                segments.append(seg)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    seg = "".join(buf).strip()
    if seg:
        segments.append(seg)
    return segments


def _is_readonly_inspect_bash(command: str) -> bool:
    """Allow ls / Get-ChildItem / pwd / cd … for structure probing (no writes)."""
    cmd = (command or "").strip()
    if not cmd:
        return False
    cmd_l = cmd.lower().replace("\\", "/")
    # Any redirect / shell writer → not readonly.
    if any(p.search(cmd_l) for p in _BASH_PROTECTED_WRITE_RES):
        return False
    # Split compound commands; every segment must be a readonly head or pipe stage.
    # Quote-aware: do not treat ``|`` inside ``"..."`` / ``'...'`` as a pipe.
    segments = _split_shell_segments(cmd)
    if not segments:
        return False
    if not any(p.search(segments[0]) for p in _ALLOW_BASH_READONLY_HEAD):
        return False
    for seg in segments[1:]:
        if any(p.search(seg) for p in _ALLOW_BASH_READONLY_HEAD):
            continue
        if any(p.search(seg) for p in _ALLOW_BASH_READONLY_PIPE):
            continue
        return False
    return True


def _uses_exploration_budget(tool_l: str, agent_l: str, action_id: str, workflow_id: str) -> bool:
    """Exploration budget mutates disk — never cache those authorize verdicts."""
    if tool_l not in (_BASH_TOOLS | _READ_TOOLS | frozenset({"grep", "glob"})):
        return False
    if workflow_id == "uo-query" or agent_l == "uo-query" or action_id == "kb_lookup":
        return True
    return False


def _is_containment_method_read(path_s: str, project_root: Path | None) -> bool:
    """Allow reading session method/prompt/skill text while run is contained."""
    if not path_s:
        return False
    norm = path_s.replace("\\", "/").lower()
    # Action session pack (always under .ascendc-pilot/.../runs/.../actions/...)
    if "/.ascendc-pilot/" in norm and "/runs/" in norm and "/actions/" in norm:
        base = norm.rsplit("/", 1)[-1]
        if base in {
            "method.md",
            "prompt.md",
            "bundle.yaml",
            "task_prompt_stub.md",
            "skill.md",
            "action_result.yaml",
        }:
            return True
        if "/refs/" in norm or norm.endswith("/refs") or "/method/" in norm:
            return True
    # Host-installed cognitive / workflow skills (read-only method delivery)
    if "/skills/" in norm and norm.endswith("skill.md"):
        return True
    if "/cognitive-skills/" in norm and (
        norm.endswith("skill.md") or "/references/" in norm or "/capabilities/" in norm
    ):
        return True
    return False


def authorize(
    project_root: Path | None = None,
    *,
    tool: str,
    command: str = "",
    path: str = "",
    agent: str = "",
    action: str = "",
    lease_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Authorize with optional in-process verdict cache (hot under serve-authorize)."""
    tool_l = (tool or "").strip().lower()
    agent_l = (agent or "").strip().lower()
    action_id = (action or "").strip()
    lease_id_s = (lease_id or "").strip()
    session_id_s = (session_id or "").strip()

    # Identity from Host Session Driver ticket (child session registry).
    if session_id_s:
        try:
            from ascendc_pilot.authorize.session_registry import lookup_child_session

            binding = lookup_child_session(session_id_s)
            if binding:
                if binding.get("actor_id") and not agent_l:
                    agent_l = str(binding["actor_id"]).strip().lower()
                if binding.get("action_id") and not action_id:
                    action_id = str(binding["action_id"]).strip()
                if binding.get("lease_id") and not lease_id_s:
                    lease_id_s = str(binding["lease_id"]).strip()
                if binding.get("project") and project_root is None:
                    project_root = Path(str(binding["project"]))
        except Exception:  # noqa: BLE001
            pass

    cache_key = None
    try:
        from ascendc_pilot.authorize import cache as auth_cache

        skip_budget = _uses_exploration_budget(tool_l, agent_l, action_id, "")
        if not skip_budget:
            cache_key = auth_cache.build_cache_key(
                Path(project_root).resolve() if project_root is not None else None,
                tool=tool_l,
                command=command or "",
                path=path or "",
                agent=agent_l,
                action=action_id,
                lease_id=lease_id_s,
            )
            cached = auth_cache.get(cache_key)
            if cached is not None:
                return cached
    except Exception:  # noqa: BLE001
        cache_key = None

    verdict = _authorize_impl(
        project_root,
        tool=tool,
        command=command,
        path=path,
        agent=agent_l or agent,
        action=action_id or action,
        lease_id=lease_id_s or lease_id,
    )
    try:
        from ascendc_pilot.authorize import cache as auth_cache

        wid = str(verdict.get("workflow_id") or "")
        if cache_key is not None and not _uses_exploration_budget(
            tool_l, agent_l, action_id, wid
        ):
            auth_cache.put(cache_key, verdict)
    except Exception:  # noqa: BLE001
        pass
    return verdict


def _authorize_impl(
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
    # OpenCode cwd is often the workspace (e.g. D:\TEST) while the live run lives
    # under the operator package — recover via last-project cache (ses_062d).
    if tool_l in _TASK_TOOLS:
        project_root = _resolve_task_project_root(
            Path(project_root).resolve() if project_root is not None else None
        )
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

    # --- uo-query exploration budget (claim-driven Explore) ---
    wid_state = str(state.get("workflow_id") or "")
    if (
        project_root is not None
        and state
        and (wid_state == "uo-query" or agent_l == "uo-query" or action_id == "kb_lookup")
        and tool_l in (_BASH_TOOLS | _READ_TOOLS | frozenset({"grep", "glob"}))
    ):
        from ascendc_pilot.authorize.exploration_budget import (
            DUP_REASON,
            HARD_REASON,
            check_and_record,
        )

        run_id = str(state.get("run_id") or "")
        act = action_id or str(lease.get("action_id") or "kb_lookup")
        if run_id:
            budget = check_and_record(
                project_root,
                run_id=run_id,
                action_id=act,
                tool=tool_l,
                command=cmd,
                path=path_s,
            )
            if not budget.get("ok") and budget.get("reason_code") in {HARD_REASON, DUP_REASON}:
                return _ok(
                    "deny",
                    str(budget.get("reason_code")),
                    str(budget.get("message_zh") or "探索预算拒绝"),
                    status=status or None,
                    tool=tool_l,
                    command=cmd[:200] if cmd else None,
                    path=path_s or None,
                    exploration_budget=budget.get("budget"),
                )
            # Soft warning is advisory; fall through to normal allow path.

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
    from ascendc_pilot.recovery import filter_executable_recovery_actions

    wid = str(state.get("workflow_id") or "uo-init")
    recovery_actions = filter_executable_recovery_actions(
        [str(x) for x in (lf.get("recovery_actions") or []) if str(x).strip()],
        workflow_id=wid,
    )

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
        # Containment may Read failed Action IR / session pack for inspect
        # (product: human_required must not blind the host to the broken artifact).
        # Also allow method/prompt/skill text so Host can re-load domain method
        # after abort without being stuck behind containment.
        if tool_l in _READ_TOOLS and path_s and project_root is not None:
            rel_try = str(path_s).replace("\\", "/")
            marker = "/.ascendc-pilot/"
            rel = rel_try.split(marker, 1)[1] if marker in rel_try else ""
            fail_aid = str(failed_action or "").strip()
            allow_inspect = False
            if fail_aid and rel.startswith("runs/") and f"/actions/{fail_aid}/" in rel:
                allow_inspect = True
            if fail_aid and rel:
                try:
                    from ascendc_pilot.ownership import (
                        action_read_paths,
                        action_write_paths,
                        path_matches_patterns,
                    )
                    from ascendc_pilot.state import load_state

                    st = load_state(project_root) or {}
                    wid = str(st.get("workflow_id") or "uo-init")
                    rid = str(st.get("run_id") or "")
                    patterns = list(action_read_paths(wid, fail_aid, run_id=rid) or [])
                    patterns.extend(action_write_paths(wid, fail_aid, run_id=rid) or [])
                    if patterns and path_matches_patterns(rel, [str(x) for x in patterns]):
                        allow_inspect = True
                except Exception:  # noqa: BLE001
                    pass
            if not allow_inspect and _is_containment_method_read(path_s, project_root):
                allow_inspect = True
            if allow_inspect:
                return _ok(
                    "allow",
                    "CONTAINMENT_INSPECT_READ",
                    f"失败收敛模式允许读取失败 Action / method 文本以便 inspect（status={status}）",
                    status=status,
                    path=path_s,
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
            if _is_readonly_inspect_bash(cmd_raw if cmd_raw else cmd):
                return _ok(
                    "allow",
                    "BASH_READONLY_INSPECT",
                    "返工模式允许只读探查（ls/Get-ChildItem/pwd/cd/…）",
                    status=status,
                    command=cmd[:200],
                )
            if agent_l in _PRIMARY_AGENTS:
                return _ok(
                    "ask",
                    "BASH_NOT_HARNESS",
                    "返工模式默认仅允许 acp * 与只读探查；其他 bash 需人工确认",
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
        if agent_l and agent_l not in _PRIMARY_AGENTS:
            from ascendc_pilot.agents_registry import forbidden_blocks_bash

            forbid_bash = forbidden_blocks_bash(agent_l, cmd, project_root=project_root)
            if forbid_bash:
                return _ok(
                    "deny",
                    forbid_bash,
                    f"代理 {agent_l} 的 forbidden 禁止该 bash 命令",
                    agent=agent_l,
                    command=cmd[:200],
                )
        # Harness CLI first: acp * is the authorized writer into .ascendc-pilot/.
        # Must run before the protected-write heuristic — naive token "cp " matches
        # inside "acp " and falsely denied record-index when args contain the path.
        for pat in _ALLOW_BASH:
            if pat.search(cmd):
                return _ok(
                    "allow",
                    "HARNESS_CLI",
                    "允许 acp CLI",
                    workflow_id=ctx.get("workflow_id"),
                    phase=ctx.get("phase"),
                )
        # Deny shell redirects / writers aimed at formal pilot artifacts (fence bypass).
        # Word-boundary patterns: "cp " must not match the trailing "cp " of "acp ".
        cmd_l = cmd.lower().replace("\\", "/")
        if ".ascendc-pilot/" in cmd_l and any(p.search(cmd_l) for p in _BASH_PROTECTED_WRITE_RES):
            return _ok(
                "deny",
                "BASH_PROTECTED_WRITE",
                "禁止用 bash 写入 .ascendc-pilot 正式产物以绕过 Write 围栏；请由声明 actor 用 Write 或 acp run-action",
                error_code="HARNESS_ACTION_NOT_AUTHORIZED",
                command=cmd[:200],
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
        # Structure probes: ls / Get-ChildItem / pwd / cd … (no writes / no domain CLI).
        if _is_readonly_inspect_bash(cmd_raw if cmd_raw else cmd):
            return _ok(
                "allow",
                "BASH_READONLY_INSPECT",
                "允许只读探查（ls/Get-ChildItem/pwd/cd/…）",
                workflow_id=ctx.get("workflow_id"),
                phase=ctx.get("phase"),
                command=cmd[:200],
            )
        if agent_l in _PRIMARY_AGENTS:
            return _ok(
                "ask",
                "BASH_NOT_HARNESS",
                "AscendC-Pilot 默认仅允许 acp * 与只读探查（ls/Get-ChildItem/…）；其他 bash 需人工确认",
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

        # Action lease read intersection: agent read_scopes ceiling AND precise Action paths.
        if agent_l and agent_l not in _PRIMARY_AGENTS and state and path_s:
            from ascendc_pilot.agents_registry import (
                agent_read_scopes,
                path_matches_scope,
                rel_under_agent_dir,
            )
            from ascendc_pilot.authorize.lease import lease_allows_read_path

            # Reuse lease already loaded in _load_context (avoid double YAML read).
            if lease and str(lease.get("status") or "") == "active":
                if lease.get("run_id") and str(lease.get("run_id")) != str(state.get("run_id") or ""):
                    return _ok(
                        "deny",
                        "ACTION_READ_OWNER_MISMATCH",
                        "lease.run_id 与当前 workflow run 不一致",
                        lease_run_id=lease.get("run_id"),
                        run_id=state.get("run_id"),
                        path=path_s,
                    )
                if action_id and lease.get("action_id") and str(lease.get("action_id")) != action_id:
                    return _ok(
                        "deny",
                        "ACTION_READ_OWNER_MISMATCH",
                        "lease.action_id 与声明 action 不一致",
                        lease_action_id=lease.get("action_id"),
                        action_id=action_id,
                        path=path_s,
                    )
                if lease.get("actor_id") and agent_l and str(lease.get("actor_id")).lower() != agent_l:
                    return _ok(
                        "deny",
                        "ACTION_READ_OWNER_MISMATCH",
                        "lease.actor_id 与当前代理不一致",
                        lease_actor_id=lease.get("actor_id"),
                        agent=agent_l,
                        path=path_s,
                    )

                rel = rel_under_agent_dir(path_s or norm, project_root)
                if rel is None:
                    rel_try = norm
                    marker = "/.ascendc-pilot/"
                    if marker in rel_try:
                        rel = rel_try.split(marker, 1)[1]
                    elif "uo/" in rel_try or rel_try.startswith("uo/"):
                        idx = rel_try.find("uo/")
                        rel = rel_try[idx:]
                    elif "tg/" in rel_try or rel_try.startswith("tg/"):
                        idx = rel_try.find("tg/")
                        rel = rel_try[idx:]
                    else:
                        rel = None

                if rel is not None:
                    scopes = agent_read_scopes(agent_l, project_root)
                    if scopes and not path_matches_scope(rel, scopes):
                        # Namespaced method/source scopes need absolute-path matching.
                        from ascendc_pilot.agents_registry import scope_allows_path

                        if not scope_allows_path(path_s or norm, scopes, project_root=project_root):
                            return _ok(
                                "deny",
                                "ACTION_READ_SCOPE_DENIED",
                                f"代理 {agent_l} 不得读取声明 read_scopes 之外的路径",
                                path=path_s,
                                agent=agent_l,
                                read_scopes=scopes,
                                rel=rel,
                            )
                    if lease.get("allowed_read_paths") or lease.get("forbidden_read_paths"):
                        path_check = lease_allows_read_path(lease, rel)
                        if not path_check.get("ok"):
                            return _ok(
                                "deny",
                                str(path_check.get("error") or "ACTION_READ_SCOPE_DENIED"),
                                "当前 Action lease 不允许读取该路径",
                                path=path_s,
                                rel=rel,
                                allowed_read_paths=lease.get("allowed_read_paths") or [],
                                forbidden_read_paths=lease.get("forbidden_read_paths") or [],
                            )
                else:
                    # Outside .ascendc-pilot: method roots (cognitive-skills) OR
                    # confirmed-scope operator sources.
                    from ascendc_pilot.agents_registry import (
                        agent_read_scopes,
                        scope_allows_path,
                    )
                    from ascendc_pilot.authorize.lease import lease_allows_source_path

                    scopes = agent_read_scopes(agent_l, project_root)
                    if scopes and scope_allows_path(path_s, scopes, project_root=project_root):
                        # method: / source: agent ceiling matched
                        pass
                    else:
                        src_rel = None
                        if project_root is not None:
                            try:
                                src_rel = (
                                    Path(path_s)
                                    .resolve()
                                    .relative_to(Path(project_root).resolve())
                                    .as_posix()
                                )
                            except Exception:  # noqa: BLE001
                                src_rel = None
                        if src_rel is None:
                            return _ok(
                                "deny",
                                "ACTION_SOURCE_SCOPE_DENIED",
                                "禁止读取算子 project_root / method root / confirmed scope 之外的路径",
                                path=path_s,
                            )
                        src_check = lease_allows_source_path(lease, src_rel)
                        if not src_check.get("ok"):
                            return _ok(
                                "deny",
                                str(src_check.get("error") or "ACTION_SOURCE_SCOPE_DENIED"),
                                "当前 Action lease 不允许读取该算子源码路径（confirmed scope）",
                                path=path_s,
                                rel=src_rel,
                                allowed_source_roots=lease.get("allowed_source_roots") or [],
                            )

        return _ok("allow", "READ_OK", "读取授权通过", tool=tool_l, path=path_s or None)

    # --- task / subagent spawn ---
    if tool_l in _TASK_TOOLS:
        if agent_l in _PRIMARY_AGENTS:
            # Defense in depth: empty prompt may arrive as --command when plugin
            # forwards stub text; bare "{}" / empty must never spawn a producer.
            prompt_probe = (cmd_raw or "").strip()
            if prompt_probe in {"{}", "null", "undefined"} or (
                prompt_probe.startswith("{")
                and prompt_probe.endswith("}")
                and len(prompt_probe) <= 4
            ):
                return _ok(
                    "deny",
                    "TASK_PROMPT_EMPTY",
                    "Task prompt 为空或无效（禁止 {}）；须原样使用 prepare 的 task_prompt_stub",
                    tool=tool_l,
                )
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

        # Agent ceiling ∩ Action lease BEFORE workflow write_roots / role
        # (plan order: Agent → Lease → Workflow → Role).
        if agent_l and agent_l not in _PRIMARY_AGENTS:
            from ascendc_pilot.agents_registry import (
                agent_write_scopes,
                forbidden_blocks_write,
                path_matches_scope,
                rel_under_agent_dir,
            )
            from ascendc_pilot.authorize.lease import lease_allows_write_path, load_lease

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

            if rel is not None:
                forbid_code = forbidden_blocks_write(agent_l, rel, project_root=project_root)
                if forbid_code:
                    return _ok(
                        "deny",
                        forbid_code,
                        f"代理 {agent_l} 的 forbidden 禁止写入该路径",
                        path=path_s,
                        agent=agent_l,
                        rel=rel,
                    )

                scopes = agent_write_scopes(agent_l, project_root)
                # Empty write_scopes ⇒ no writes (write_outside_declared_scope).
                if not path_matches_scope(rel, scopes):
                    return _ok(
                        "deny",
                        "AGENT_WRITE_SCOPE",
                        f"代理 {agent_l} 不得写入声明 write_scopes 之外的路径",
                        path=path_s,
                        agent=agent_l,
                        write_scopes=scopes,
                        rel=rel,
                    )

                # Reuse lease from _load_context (avoid double YAML read).
                if lease and str(lease.get("status") or "") == "active":
                    if lease.get("run_id") and state and str(lease.get("run_id")) != str(state.get("run_id") or ""):
                        return _ok(
                            "deny",
                            "ACTION_RUN_MISMATCH",
                            "lease.run_id 与当前 workflow run 不一致",
                            lease_run_id=lease.get("run_id"),
                            run_id=state.get("run_id"),
                        )
                    if action_id and lease.get("action_id") and str(lease.get("action_id")) != action_id:
                        return _ok(
                            "deny",
                            "ACTION_OWNER_MISMATCH",
                            "lease.action_id 与声明 action 不一致",
                            lease_action_id=lease.get("action_id"),
                            action_id=action_id,
                        )
                    if lease.get("actor_id") and agent_l and str(lease.get("actor_id")).lower() != agent_l:
                        return _ok(
                            "deny",
                            "ACTION_OWNER_MISMATCH",
                            "lease.actor_id 与当前代理不一致",
                            lease_actor_id=lease.get("actor_id"),
                            agent=agent_l,
                        )
                    path_check = lease_allows_write_path(lease, rel)
                    if not path_check.get("ok"):
                        return _ok(
                            "deny",
                            str(path_check.get("error") or "ACTION_WRITE_SCOPE_DENIED"),
                            "当前 Action lease 不允许写入该路径",
                            path=path_s,
                            rel=rel,
                            allowed_write_paths=lease.get("allowed_write_paths") or [],
                            forbidden_write_paths=lease.get("forbidden_write_paths") or [],
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

    return _ok(
        "deny",
        "TOOL_UNKNOWN",
        "Pilot agent 未知 tool：fail-closed（不再默认放行）",
        tool=tool_l,
        agent=agent_l or None,
    )
