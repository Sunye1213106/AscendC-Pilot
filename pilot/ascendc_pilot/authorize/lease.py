"""Action Lease — authorization bound to run *status*, not a free-floating fence.

Modes (status → lease):
  running          → normal
  rework_required  → rework   (retry failed Action only)
  human_required / blocked / failed → containment (recovery + start new run)

Lease never overrides status. Status is the sole authority for which mode applies.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.paths import agent_root, ensure_agent_layout

LEASE_FILENAME = "action_lease.yaml"
REVOKED_LOG = "revoked_leases.jsonl"

MODE_NORMAL = "normal"
MODE_REWORK = "rework"
MODE_CONTAINMENT = "containment"

NORMAL_ALLOWED_TOOLS = (
    "bash",
    "shell",
    "terminal",
    "question",
    "ask_user",
    "read",
    "glob",
    "grep",
    "write",
    "edit",
    "apply_patch",
    "strreplace",
    "patch",
    "task",
    "subagent",
    "task_tool",
)

REWORK_ALLOWED_TOOLS = (
    "bash",
    "shell",
    "terminal",
    "question",
    "ask_user",
    "read",
    "glob",
    "grep",
    "write",
    "edit",
    "apply_patch",
    "strreplace",
    "patch",
    "task",
    "subagent",
    "task_tool",
)

CONTAINMENT_ALLOWED_TOOLS = (
    "bash",
    "shell",
    "terminal",
    "question",
    "ask_user",
)

# Shared recovery surface for both rework and containment
_RECOVERY_CORE = (
    "acp next",
    "acp status",
    "acp inspect-failure",
    "acp abort",
    "acp block",
    "acp start",
    "python -m ascendc_pilot next",
    "python -m ascendc_pilot status",
    "python -m ascendc_pilot inspect-failure",
    "python -m ascendc_pilot abort",
    "python -m ascendc_pilot block",
    "python -m ascendc_pilot start",
    "python3 -m ascendc_pilot next",
    "python3 -m ascendc_pilot status",
    "python3 -m ascendc_pilot inspect-failure",
    "python3 -m ascendc_pilot abort",
    "python3 -m ascendc_pilot block",
    "python3 -m ascendc_pilot start",
)

CONTAINMENT_COMMAND_PREFIXES = _RECOVERY_CORE + (
    "acp retry-after-environment-fix",
    "acp debug",
    "python -m ascendc_pilot retry-after-environment-fix",
    "python -m ascendc_pilot debug",
    "python3 -m ascendc_pilot retry-after-environment-fix",
    "python3 -m ascendc_pilot debug",
)

REWORK_COMMAND_PREFIXES = _RECOVERY_CORE + (
    "acp run-action",
    "acp uo-scope",
    "acp context",
    "acp authorize",
    "acp debug",
    "python -m ascendc_pilot run-action",
    "python -m ascendc_pilot uo-scope",
    "python -m ascendc_pilot context",
    "python -m ascendc_pilot debug",
    "python3 -m ascendc_pilot run-action",
    "python3 -m ascendc_pilot uo-scope",
    "python3 -m ascendc_pilot context",
    "python3 -m ascendc_pilot debug",
)

NORMAL_COMMAND_PREFIXES = (
    "acp next",
    "acp status",
    "acp run-action",
    "acp advance",
    "acp uo-scope",
    "acp authorize",
    "acp context",
    "acp complete",
    "acp rework",
    "acp abort",
    "acp start",
    "python -m ascendc_pilot",
    "python3 -m ascendc_pilot",
)


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lease_path(project_root: Path) -> Path:
    return agent_root(project_root) / "state" / LEASE_FILENAME


def _dump(path: Path, data: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML required")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def _load(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def new_lease_id() -> str:
    return f"LEASE_{uuid.uuid4().hex[:12]}"


def load_lease(project_root: Path) -> dict[str, Any]:
    return _load(lease_path(project_root))


def authorization_mode_for_status(status: str) -> str:
    """Sole mapping from workflow status → authorization mode."""
    st = str(status or "").strip().lower()
    if st == "rework_required":
        return MODE_REWORK
    if st in {"human_required", "blocked", "failed"}:
        return MODE_CONTAINMENT
    return MODE_NORMAL


def _state_version(state: dict[str, Any]) -> int:
    v = state.get("state_version")
    if isinstance(v, int):
        return v
    return int(state.get("no_progress_streak") or 0) + len(state.get("failed_gates") or [])


def _defaults_for_mode(mode: str) -> tuple[list[str], list[str]]:
    if mode == MODE_CONTAINMENT:
        return list(CONTAINMENT_ALLOWED_TOOLS), list(CONTAINMENT_COMMAND_PREFIXES)
    if mode == MODE_REWORK:
        return list(REWORK_ALLOWED_TOOLS), list(REWORK_COMMAND_PREFIXES)
    return list(NORMAL_ALLOWED_TOOLS), list(NORMAL_COMMAND_PREFIXES)


def issue_action_lease(
    project_root: Path,
    *,
    state: dict[str, Any] | None = None,
    action_id: str,
    actor_id: str = "",
    mode: str = MODE_NORMAL,
    allowed_tools: list[str] | None = None,
    allowed_commands: list[str] | None = None,
    allowed_read_roots: list[str] | None = None,
    allowed_write_roots: list[str] | None = None,
    allowed_write_paths: list[str] | None = None,
    allowed_read_paths: list[str] | None = None,
    forbidden_write_paths: list[str] | None = None,
    forbidden_read_paths: list[str] | None = None,
    allowed_target_ids: list[str] | None = None,
    allowed_source_roots: list[str] | None = None,
    allowed_source_files: list[str] | None = None,
) -> dict[str, Any]:
    """Issue (replace) the active action lease for the given mode."""
    from ascendc_pilot.runs import append_event
    from ascendc_pilot.state import load_state

    ensure_agent_layout(project_root)
    st = state if state is not None else (load_state(project_root) or {})
    mode_l = str(mode or MODE_NORMAL).strip().lower()
    if mode_l not in {MODE_NORMAL, MODE_REWORK, MODE_CONTAINMENT}:
        mode_l = MODE_NORMAL
    def_tools, def_cmds = _defaults_for_mode(mode_l)
    write_paths = [
        str(p).replace("\\", "/").lstrip("/")
        for p in list(allowed_write_paths or [])
        if str(p).strip()
    ]
    read_paths = [
        str(p).replace("\\", "/").lstrip("/")
        for p in list(allowed_read_paths or [])
        if str(p).strip()
    ]
    # Global invariant (all Actions): write target ⊆ readable.
    # Prevents "can Write artifact but cannot Read it back" producer dead-ends.
    for wp in write_paths:
        if wp not in read_paths:
            read_paths.append(wp)
    source_roots = [
        str(p).replace("\\", "/").lstrip("/")
        for p in list(allowed_source_roots or [])
        if str(p).strip()
    ]
    source_files = [
        str(p).replace("\\", "/").lstrip("/")
        for p in list(allowed_source_files or [])
        if str(p).strip()
    ]
    lease = {
        "lease_id": new_lease_id(),
        "run_id": st.get("run_id") or "",
        "workflow_id": st.get("workflow_id") or "",
        "action_id": action_id,
        "actor_id": actor_id or "",
        "phase": st.get("phase") or "",
        "state_version": _state_version(st),
        "mode": mode_l,
        "status": "active",
        "allowed_tools": list(allowed_tools or def_tools),
        "allowed_commands": list(allowed_commands or def_cmds),
        "allowed_read_roots": list(allowed_read_roots or []),
        "allowed_write_roots": list(allowed_write_roots or []),
        "allowed_write_paths": write_paths,
        "allowed_read_paths": read_paths,
        "forbidden_write_paths": list(forbidden_write_paths or []),
        "forbidden_read_paths": list(forbidden_read_paths or []),
        "allowed_target_ids": list(allowed_target_ids or []),
        "allowed_source_roots": source_roots,
        "allowed_source_files": source_files,
        "issued_at": _now(),
        "revoked_at": None,
        "revoke_reason": None,
    }
    _dump(lease_path(project_root), lease)
    append_event(
        project_root,
        {
            "type": "ActionPrepared" if mode_l == MODE_NORMAL else "StateTransitioned",
            "lease_id": lease["lease_id"],
            "action_id": action_id,
            "actor_id": actor_id or "",
            "mode": mode_l,
            "lease_event": "issued",
        },
        run_id=str(st.get("run_id") or "") or None,
    )
    try:
        from ascendc_pilot.authorize.cache import bump_generation

        bump_generation()
    except Exception:  # noqa: BLE001
        pass
    return lease


def lease_allows_write_path(lease: dict[str, Any], rel_posix: str) -> dict[str, Any]:
    """Check Action-precise write paths (after workflow root containment)."""
    from ascendc_pilot.ownership import path_matches_patterns

    rel = str(rel_posix or "").replace("\\", "/").lstrip("/")
    forbid = list(lease.get("forbidden_write_paths") or [])
    if forbid and path_matches_patterns(rel, [str(x) for x in forbid]):
        return {"ok": False, "error": "ACTION_FORBIDDEN_PATH", "path": rel}
    precise = list(lease.get("allowed_write_paths") or [])
    if precise and not path_matches_patterns(rel, [str(x) for x in precise]):
        return {"ok": False, "error": "ACTION_WRITE_SCOPE_DENIED", "path": rel, "allowed": precise}
    return {"ok": True}


def _rel_from_ascendc_abs(path_s: str) -> str:
    """``…/.ascendc-pilot/<rel>`` → ``<rel>``; otherwise empty."""
    norm = str(path_s or "").replace("\\", "/")
    marker = "/.ascendc-pilot/"
    idx = norm.lower().find(marker)
    if idx < 0:
        return ""
    return norm[idx + len(marker) :].lstrip("/")


def _is_dir_prefix_of_allowed(rel: str, precise: list[str]) -> bool:
    """True when ``rel`` is a directory prefix of an allow-listed file/pattern.

    Lets subagents Glob/list ``uo/ir`` when only concrete YAML files are leased
    (ses_062d: producer blocked on parent dirs / session pack).
    """
    if not rel:
        return False
    for raw in precise:
        p = str(raw or "").replace("\\", "/").lstrip("/")
        if not p:
            continue
        if p.endswith("/**"):
            prefix = p[:-3].rstrip("/")
        else:
            prefix = p.rsplit("/", 1)[0] if "/" in p else ""
            # Also treat the file's full parent chain.
            parts = p.split("/")
            for i in range(1, len(parts)):
                parent = "/".join(parts[:i])
                if rel == parent:
                    return True
            continue
        if rel == prefix or prefix.startswith(rel + "/"):
            return True
    return False


def _under_allowed_read_roots(rel: str, roots: list[str]) -> bool:
    """Honor ``allowed_read_roots`` (absolute session dirs written at prepare)."""
    for root in roots:
        root_rel = _rel_from_ascendc_abs(str(root))
        if not root_rel:
            continue
        if rel == root_rel or rel.startswith(root_rel + "/"):
            return True
    return False


def lease_allows_read_path(lease: dict[str, Any], rel_posix: str) -> dict[str, Any]:
    """Check Action-precise read paths (forbidden deny-first, then allow-list)."""
    from ascendc_pilot.ownership import path_matches_patterns

    rel = str(rel_posix or "").replace("\\", "/").lstrip("/")
    forbid = list(lease.get("forbidden_read_paths") or [])
    if forbid and path_matches_patterns(rel, [str(x) for x in forbid]):
        return {"ok": False, "error": "ACTION_FORBIDDEN_READ_PATH", "path": rel}
    precise = list(lease.get("allowed_read_paths") or [])
    roots = list(lease.get("allowed_read_roots") or [])
    if precise or roots:
        ok = False
        if precise and path_matches_patterns(rel, [str(x) for x in precise]):
            ok = True
        elif precise and _is_dir_prefix_of_allowed(rel, [str(x) for x in precise]):
            ok = True
        elif roots and _under_allowed_read_roots(rel, [str(x) for x in roots]):
            ok = True
        if not ok:
            return {
                "ok": False,
                "error": "ACTION_READ_SCOPE_DENIED",
                "path": rel,
                "allowed": precise,
                "allowed_read_roots": roots,
            }
    return {"ok": True}


def lease_allows_source_path(lease: dict[str, Any], rel_posix: str) -> dict[str, Any]:
    """Operator-source path check (outside .ascendc-pilot).

    When lease declares ``allowed_source_roots`` / ``allowed_source_files``,
    reads must match; empty lists mean no source hard-fence (legacy allow).
    """
    from ascendc_pilot.ownership import path_matches_patterns

    rel = str(rel_posix or "").replace("\\", "/").lstrip("/")
    files = [str(x).replace("\\", "/").lstrip("/") for x in (lease.get("allowed_source_files") or [])]
    roots = [str(x).replace("\\", "/").lstrip("/") for x in (lease.get("allowed_source_roots") or [])]
    if not files and not roots:
        return {"ok": True, "unfenced": True}
    if files and path_matches_patterns(rel, files):
        return {"ok": True}
    for root in roots:
        if not root:
            continue
        if rel == root or rel.startswith(root.rstrip("/") + "/"):
            return {"ok": True}
    return {
        "ok": False,
        "error": "ACTION_SOURCE_SCOPE_DENIED",
        "path": rel,
        "allowed_source_roots": roots,
        "allowed_source_files": files[:40],
    }


def issue_lease_for_status(
    project_root: Path,
    *,
    state: dict[str, Any],
    action_id: str = "",
) -> dict[str, Any]:
    """Issue the lease that matches current workflow status (authoritative)."""
    mode = authorization_mode_for_status(str(state.get("status") or ""))
    aid = action_id or str((state.get("last_failure") or {}).get("action_id") or "") or "_lease"
    if mode == MODE_CONTAINMENT:
        aid = aid if aid and aid != "_lease" else "_containment"
    elif mode == MODE_REWORK:
        aid = aid if aid and aid != "_lease" else "_rework"
    return issue_action_lease(project_root, state=state, action_id=aid, mode=mode)


def issue_containment_lease(
    project_root: Path,
    *,
    state: dict[str, Any] | None = None,
    action_id: str = "",
    mode: str = MODE_CONTAINMENT,
) -> dict[str, Any]:
    """Backward-compatible alias — always issues containment mode."""
    return issue_action_lease(
        project_root,
        state=state,
        action_id=action_id or "_containment",
        mode=MODE_CONTAINMENT,
        allowed_tools=list(CONTAINMENT_ALLOWED_TOOLS),
        allowed_commands=list(CONTAINMENT_COMMAND_PREFIXES),
        allowed_read_roots=[],
        allowed_write_roots=[],
    )


def issue_rework_lease(
    project_root: Path,
    *,
    state: dict[str, Any] | None = None,
    action_id: str = "",
) -> dict[str, Any]:
    return issue_action_lease(
        project_root,
        state=state,
        action_id=action_id or "_rework",
        mode=MODE_REWORK,
        allowed_tools=list(REWORK_ALLOWED_TOOLS),
        allowed_commands=list(REWORK_COMMAND_PREFIXES),
    )


def revoke_active_lease(
    project_root: Path,
    *,
    reason: str = "",
    touch_active_action: bool = True,
) -> dict[str, Any]:
    """Revoke current lease if active. Returns revoke info (may be empty)."""
    import json

    path = lease_path(project_root)
    lease = _load(path)
    if not lease:
        return {"revoked": False}
    if str(lease.get("status") or "") == "revoked":
        return {"revoked": False, "lease_id": lease.get("lease_id"), "already_revoked": True}

    lease["status"] = "revoked"
    lease["revoked_at"] = _now()
    lease["revoke_reason"] = reason or "revoked"
    _dump(path, lease)

    log = agent_root(project_root) / "state" / REVOKED_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "lease_id": lease.get("lease_id"),
                    "action_id": lease.get("action_id"),
                    "revoked_at": lease.get("revoked_at"),
                    "reason": reason,
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    if touch_active_action:
        active = agent_root(project_root) / "state" / "active_action.yaml"
        if active.is_file():
            data = _load(active)
            if data:
                data["status"] = "revoked"
                data["revoked_at"] = lease["revoked_at"]
                data["revoke_reason"] = reason
                _dump(active, data)

    try:
        from ascendc_pilot.authorize.cache import bump_generation

        bump_generation()
    except Exception:  # noqa: BLE001
        pass
    return {
        "revoked": True,
        "lease_id": lease.get("lease_id"),
        "action_id": lease.get("action_id"),
        "reason": reason,
    }


def clear_lease(project_root: Path) -> None:
    """Remove lease file (used on fresh start_workflow)."""
    path = lease_path(project_root)
    if path.is_file():
        path.unlink()


def is_lease_revoked(project_root: Path, lease_id: str) -> bool:
    if not lease_id:
        return False
    current = load_lease(project_root)
    if str(current.get("lease_id") or "") == lease_id and str(current.get("status") or "") == "revoked":
        return True
    log = agent_root(project_root) / "state" / REVOKED_LOG
    if not log.is_file():
        return False
    needle = f'"lease_id": "{lease_id}"'
    needle2 = f'"lease_id":"{lease_id}"'
    text = log.read_text(encoding="utf-8")
    return needle in text or needle2 in text


def _normalize_cmd(command: str) -> str:
    """Normalize bash for allowlist matching.

    Accepts optional leading ``cd|pushd|Set-Location <dir> &&`` wrappers, then requires a
    pure acp / ``python -m ascendc_pilot`` command. Compound chains with other
    commands are not treated as acp CLI.
    """
    extracted = extract_pilot_command(command)
    if extracted:
        return extracted
    cmd = " ".join(str(command or "").strip().split())
    for sep in ("|", ">", "<", "&&", "||", ";"):
        if sep in cmd:
            cmd = cmd.split(sep, 1)[0].strip()
    return cmd


_CD_WRAPPER = re.compile(
    r'^(?:cd|pushd|Set-Location|chdir)\s+(?:"[^"]+"|\'[^\']+\'|[^\s&|;]+)\s*(?:&&|;)\s*',
    re.IGNORECASE,
)
# PowerShell / cmd / unix env prefixes before acp (ses_0662 fence bypass for limits).
_ENV_WRAPPERS = (
    re.compile(
        r"^\$env:([A-Za-z_][\w]*)\s*=\s*(?:'[^']*'|\"[^\"]*\"|[^\s;]+)\s*;\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\[System\.Environment\]::SetEnvironmentVariable\(\s*'[^']+'\s*,\s*'[^']*'"
        r"(?:\s*,\s*'[^']*')?\s*\)\s*;\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^set\s+([A-Za-z_][\w]*)\s*=\s*([^\s&]+)\s*(?:&&)\s*",
        re.IGNORECASE,
    ),
    # Unix: FOO=bar BAZ=1 acp ...
    re.compile(r"^([A-Za-z_][\w]*)=([^\s]+)\s+"),
)
_ACP_HEAD = re.compile(
    r"^(?:acp(?:\s|$)|python(?:3)?\s+-m\s+ascendc_pilot(?:\s|$))",
    re.IGNORECASE,
)


def extract_pilot_command(command: str) -> str | None:
    """Return pure acp CLI if command is only optional cd/env wrappers + acp."""
    cmd = " ".join(str(command or "").strip().split())
    if not cmd:
        return None
    while True:
        match = _CD_WRAPPER.match(cmd)
        if not match:
            break
        cmd = cmd[match.end() :].strip()
    # Strip env prefixes; keep stripping while matched (multiple --set via $env).
    progressed = True
    while progressed:
        progressed = False
        for pat in _ENV_WRAPPERS:
            match = pat.match(cmd)
            if match:
                cmd = cmd[match.end() :].strip()
                progressed = True
                break
    if any(sep in cmd for sep in ("&&", "||", ";", "|", ">", "<")):
        return None
    if not _ACP_HEAD.match(cmd):
        return None
    return cmd


def lease_allows_command(lease: dict[str, Any], command: str) -> bool:
    cmd_l = _normalize_cmd(command).lower()
    if not cmd_l:
        return False
    allowed = [str(x).lower() for x in (lease.get("allowed_commands") or [])]
    for prefix in allowed:
        p = prefix.lower().strip()
        if not p:
            continue
        if cmd_l == p or cmd_l.startswith(p + " ") or cmd_l.startswith(p + "\t"):
            return True
        if p.rstrip().endswith("uo-scope") and (
            cmd_l.startswith("acp uo-scope")
            or cmd_l.startswith("python -m ascendc_pilot uo-scope")
            or cmd_l.startswith("python3 -m ascendc_pilot uo-scope")
        ):
            return True
        if p.rstrip().endswith("run-action") and (
            " run-action " in f" {cmd_l} " or cmd_l.endswith(" run-action")
        ):
            return True
    return False


def command_matches_prefixes(command: str, prefixes: tuple[str, ...] | list[str]) -> bool:
    cmd_l = _normalize_cmd(command).lower()
    if not cmd_l:
        return False
    for prefix in prefixes:
        p = prefix.lower().strip()
        if not p:
            continue
        if cmd_l == p or cmd_l.startswith(p + " ") or cmd_l.startswith(p + "\t"):
            return True
    return False


def lease_allows_tool(lease: dict[str, Any], tool: str) -> bool:
    tool_l = (tool or "").strip().lower()
    allowed = {str(x).lower() for x in (lease.get("allowed_tools") or [])}
    return tool_l in allowed


__all__ = [
    "CONTAINMENT_ALLOWED_TOOLS",
    "CONTAINMENT_COMMAND_PREFIXES",
    "MODE_CONTAINMENT",
    "MODE_NORMAL",
    "MODE_REWORK",
    "NORMAL_ALLOWED_TOOLS",
    "REWORK_ALLOWED_TOOLS",
    "REWORK_COMMAND_PREFIXES",
    "authorization_mode_for_status",
    "clear_lease",
    "command_matches_prefixes",
    "extract_pilot_command",
    "is_lease_revoked",
    "issue_action_lease",
    "issue_containment_lease",
    "issue_lease_for_status",
    "issue_rework_lease",
    "lease_allows_command",
    "lease_allows_read_path",
    "lease_allows_source_path",
    "lease_allows_tool",
    "lease_allows_write_path",
    "lease_path",
    "load_lease",
    "revoke_active_lease",
]
