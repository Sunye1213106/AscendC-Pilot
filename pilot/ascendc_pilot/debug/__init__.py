"""Debug mode: capture tool failures, long non-logical thoughts, export sessions."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# Meta / process-debate markers (ZH+EN) — high density ⇒ non-logical thrash.
_META_PATTERNS = (
    re.compile(r"让我想想"),
    re.compile(r"要不要"),
    re.compile(r"严格来说"),
    re.compile(r"纠结"),
    re.compile(r"是否应该"),
    re.compile(r"我需要先"),
    re.compile(r"不过[，,]?可能"),
    re.compile(r"实际上[，,]?规则"),
    re.compile(r"todowrite", re.I),
    re.compile(r"merge\s*[:=]?\s*(true|false)", re.I),
    re.compile(r"should I", re.I),
    re.compile(r"let me think", re.I),
    re.compile(r"wait[,，]", re.I),
    re.compile(r"on the other hand", re.I),
    re.compile(r"but (actually|strictly|technically)", re.I),
)

_DEFAULTS = {
    "enabled": False,
    "thought_char_limit": 2500,
    "thought_meta_hits_min": 4,
    "auto_export_on_subagent_stop": True,
    "auto_export_on_session_end": True,
}


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _global_debug_path() -> Path:
    return Path.home() / ".config" / "ascendc-pilot" / "debug.yaml"


def _project_debug_dir(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / ".ascendc-pilot" / "debug"


def _debug_session_path(project_root: Path) -> Path:
    return _project_debug_dir(project_root) / "debug_session.yaml"


def _children_registry_path(project_root: Path) -> Path:
    return _project_debug_dir(project_root) / "children_registry.yaml"


def _tool_events_path(project_root: Path) -> Path:
    return _project_debug_dir(project_root) / "tool_events.jsonl"


def _new_debug_session_id() -> str:
    return f"dbg_{uuid.uuid4().hex[:12]}"


def _new_registration_id() -> str:
    return f"reg_{uuid.uuid4().hex[:12]}"


def _parse_ts(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:  # noqa: BLE001
        return None


def load_debug_session(project_root: Path | None = None) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    return _load_yaml(_debug_session_path(root))


def _save_debug_session(project_root: Path, data: dict[str, Any]) -> None:
    _dump_yaml(_debug_session_path(project_root), data)


def _load_children_registry(project_root: Path) -> dict[str, Any]:
    data = _load_yaml(_children_registry_path(project_root))
    if not isinstance(data.get("children"), list):
        data["children"] = []
    return data


def _save_children_registry(project_root: Path, data: dict[str, Any]) -> None:
    _dump_yaml(_children_registry_path(project_root), data)


def _append_tool_event(project_root: Path, entry: dict[str, Any]) -> None:
    path = _tool_events_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def list_tool_events(project_root: Path | None = None, *, limit: int = 5000) -> list[dict[str, Any]]:
    path = _tool_events_path(resolve_project_root(project_root))
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return rows[-limit:]


def _ir_path_hint(path_s: str) -> bool:
    p = path_s.replace("\\", "/").lower()
    return "/ir/" in p or p.endswith(".ir.yaml") or "/.ascendc-pilot/ir/" in p


def _cbm_tool_name(tool: str) -> bool:
    t = tool.lower()
    return any(
        x in t
        for x in (
            "codebase",
            "search_graph",
            "query_graph",
            "trace_path",
            "get_architecture",
            "index_repository",
        )
    )


def audit_stats_from_tool_events(events: list[dict[str, Any]]) -> dict[str, int]:
    stats = {
        "source_files_read": 0,
        "ir_files_read": 0,
        "cbm_queries": 0,
        "grep_queries": 0,
        "tool_call_count": 0,
        "tool_failures": 0,
        "written_artifacts": 0,
    }
    for ev in events:
        if not isinstance(ev, dict):
            continue
        stats["tool_call_count"] += 1
        tool = str(ev.get("tool") or "").lower()
        path_s = str(ev.get("path") or ev.get("file") or "")
        failed = bool(ev.get("failed")) or str(ev.get("outcome") or "") == "failure"
        if failed:
            stats["tool_failures"] += 1
        if tool in {"read", "glob", "list"}:
            if _ir_path_hint(path_s):
                stats["ir_files_read"] += 1
            elif path_s:
                stats["source_files_read"] += 1
        elif tool == "grep" or tool == "search":
            stats["grep_queries"] += 1
        elif _cbm_tool_name(tool):
            stats["cbm_queries"] += 1
        elif tool in {"write", "edit", "apply_patch", "strreplace", "patch"} and path_s:
            stats["written_artifacts"] += 1
    return stats


def record_tool_event(
    project_root: Path | None,
    *,
    tool: str,
    parent_session_id: str = "",
    child_session_id: str = "",
    action_id: str = "",
    actor_id: str = "",
    path: str = "",
    pattern: str = "",
    failed: bool = False,
    outcome: str = "success",
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    if not is_enabled(root):
        return {"ok": False, "skipped": True, "reason": "debug_disabled"}
    ds = load_debug_session(root)
    entry = {
        "at": _now(),
        "tool": tool,
        "parent_session_id": normalize_session_id(parent_session_id) or ds.get("parent_session_id") or "",
        "child_session_id": normalize_session_id(child_session_id),
        "action_id": action_id,
        "actor_id": actor_id,
        "path": path[:500],
        "pattern": pattern[:500],
        "failed": bool(failed),
        "outcome": outcome,
        "project_root": root.as_posix(),
        "run_id": str(ds.get("run_id") or ""),
        "detail": detail or {},
    }
    _append_tool_event(root, entry)
    return {"ok": True, "entry": entry}


def register_child(
    project_root: Path | None,
    *,
    parent_session_id: str,
    child_session_id: str = "",
    workflow_id: str = "",
    run_id: str = "",
    phase: str = "",
    action_id: str = "",
    actor_id: str = "",
    started_at: str = "",
    task_prompt_path: str = "",
    task_prompt_text: str = "",
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    if not is_enabled(root):
        return {"ok": False, "skipped": True, "reason": "debug_disabled"}
    ds = load_debug_session(root)
    parent = normalize_session_id(parent_session_id)
    child = normalize_session_id(child_session_id)
    if child and not _SESSION_ID_RE.search(child):
        child = ""
    reg = _load_children_registry(root)
    prompt_text = task_prompt_text
    if not prompt_text and task_prompt_path:
        p = Path(task_prompt_path)
        if p.is_file():
            prompt_text = p.read_text(encoding="utf-8", errors="replace")
    row: dict[str, Any] = {
        "registration_id": _new_registration_id(),
        "parent_session_id": parent,
        "child_session_id": child,
        "workflow_id": workflow_id or str(ds.get("workflow_id") or ""),
        "run_id": run_id or str(ds.get("run_id") or ""),
        "phase": phase,
        "action_id": action_id,
        "actor_id": actor_id,
        "started_at": started_at or _now(),
        "task_prompt_path": task_prompt_path,
        "task_prompt_text": prompt_text[:50_000],
        "exported": False,
        "export_dir": "",
    }
    reg["children"].append(row)
    _save_children_registry(root, reg)
    if parent and not ds.get("parent_session_id"):
        ds["parent_session_id"] = parent
        _save_debug_session(root, ds)
    return {"ok": True, "registration": row}


def patch_child_session_id(
    project_root: Path | None,
    *,
    child_session_id: str,
    parent_session_id: str = "",
    action_id: str = "",
    registration_id: str = "",
) -> dict[str, Any]:
    """Set child_session_id from Task tool return only (caller must pass parsed id)."""
    root = resolve_project_root(project_root)
    child = normalize_session_id(child_session_id)
    if not child:
        return {"ok": False, "error": "missing_child_session_id"}
    reg = _load_children_registry(root)
    parent = normalize_session_id(parent_session_id)
    target: dict[str, Any] | None = None
    if registration_id:
        for row in reg["children"]:
            if row.get("registration_id") == registration_id:
                target = row
                break
    if target is None:
        candidates = [
            r
            for r in reg["children"]
            if not normalize_session_id(str(r.get("child_session_id") or ""))
            and (not parent or normalize_session_id(str(r.get("parent_session_id") or "")) == parent)
            and (not action_id or str(r.get("action_id") or "") == action_id)
        ]
        if candidates:
            target = sorted(candidates, key=lambda r: str(r.get("started_at") or ""))[-1]
    if target is None:
        return {"ok": False, "error": "no_pending_registration"}
    target["child_session_id"] = child
    target["patched_at"] = _now()
    _save_children_registry(root, reg)
    return {"ok": True, "registration": target}


def get_child_registration(project_root: Path | None, child_session_id: str) -> dict[str, Any] | None:
    root = resolve_project_root(project_root)
    child = normalize_session_id(child_session_id)
    if not child:
        return None
    for row in _load_children_registry(root).get("children") or []:
        if normalize_session_id(str(row.get("child_session_id") or "")) == child:
            return row
    return None


def is_registered_child(project_root: Path | None, session_id: str) -> bool:
    return get_child_registration(project_root, session_id) is not None


def _child_export_eligible(row: dict[str, Any], ds: dict[str, Any], root: Path) -> tuple[bool, str]:
    if not ds.get("debug_session_id"):
        return False, "no_debug_session"
    parent = normalize_session_id(str(row.get("parent_session_id") or ""))
    ds_parent = normalize_session_id(str(ds.get("parent_session_id") or ""))
    if ds_parent and parent != ds_parent:
        return False, "parent_session_mismatch"
    if str(row.get("run_id") or "") != str(ds.get("run_id") or ""):
        return False, "run_id_mismatch"
    if str(ds.get("project_root") or "") != root.as_posix():
        return False, "project_root_mismatch"
    started = _parse_ts(str(row.get("started_at") or ""))
    enabled = _parse_ts(str(ds.get("enabled_at") or ""))
    if started and enabled and started < enabled:
        return False, "started_before_debug_enabled"
    child = normalize_session_id(str(row.get("child_session_id") or ""))
    if not child:
        return False, "child_session_id_missing"
    return True, ""


def _export_stamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")


def _copy_exact_child_transcript(project_root: Path, child_session_id: str, dest: Path) -> dict[str, Any]:
    sid = normalize_session_id(child_session_id)
    if not sid:
        return {
            "transcript_status": "unavailable",
            "reason": "missing_child_session_id",
            "ok": False,
        }
    hits = _find_session_files(sid, _transcript_search_roots(project_root))
    if not hits:
        return {
            "transcript_status": "unavailable",
            "reason": f"no transcript file for {sid}",
            "ok": False,
        }
    hits_sorted = sorted(
        hits,
        key=lambda p: (0 if p.suffix.lower() == ".md" else 1, p.name.lower(), str(p)),
    )
    src = hits_sorted[0]
    try:
        if src.suffix.lower() == ".jsonl":
            dest.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        else:
            shutil.copy2(src, dest)
        return {
            "transcript_status": "ok",
            "source": src.as_posix(),
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "transcript_status": "unavailable",
            "reason": f"copy_failed:{exc}",
            "ok": False,
        }


def export_child_session(
    project_root: Path | None = None,
    *,
    child_session_id: str,
    reason: str = "manual",
    subagent: str = "",
    force: bool = False,
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    if not is_enabled(root) and not force:
        return {"ok": False, "skipped": True, "reason": "debug_disabled"}
    ds = load_debug_session(root)
    row = get_child_registration(root, child_session_id)
    if not row:
        return {"ok": False, "error": "child_not_registered", "child_session_id": child_session_id}
    ok, why = _child_export_eligible(row, ds, root)
    if not ok and not force:
        return {"ok": False, "skipped": True, "reason": why, "child_session_id": child_session_id}

    from ascendc_pilot.state import load_state

    st = load_state(root) or {}
    child = normalize_session_id(child_session_id)
    action_id = str(row.get("action_id") or "action")
    stamp = _export_stamp()
    export_dir = (
        _project_debug_dir(root) / "exports" / f"{stamp}_{action_id}_{child}"
    )
    export_dir.mkdir(parents=True, exist_ok=True)

    events = [
        e
        for e in list_tool_events(root)
        if normalize_session_id(str(e.get("child_session_id") or "")) == child
        or (
            not e.get("child_session_id")
            and normalize_session_id(str(e.get("parent_session_id") or ""))
            == normalize_session_id(str(row.get("parent_session_id") or ""))
            and str(e.get("action_id") or "") == action_id
        )
    ]
    audit = audit_stats_from_tool_events(events)

    prompt_path = export_dir / "prompt.md"
    prompt_body = str(row.get("task_prompt_text") or "").strip()
    if not prompt_body:
        prompt_body = "_no task prompt captured_\n"
    prompt_path.write_text(prompt_body, encoding="utf-8")

    transcript_dest = export_dir / "transcript.md"
    transcript_info = _copy_exact_child_transcript(root, child, transcript_dest)
    if not transcript_info.get("ok"):
        if transcript_dest.is_file():
            transcript_dest.unlink(missing_ok=True)
        transcript_info.setdefault("transcript_status", "unavailable")

    tool_events_file = export_dir / "tool_events.jsonl"
    with tool_events_file.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")

    failures = [e for e in events if e.get("failed") or str(e.get("outcome") or "") == "failure"]
    tool_failures_file = export_dir / "tool_failures.jsonl"
    with tool_failures_file.open("w", encoding="utf-8") as fh:
        for ev in failures:
            fh.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")

    result_md = export_dir / "result.md"
    result_md.write_text(
        f"# Child result\n\n- child_session_id: `{child}`\n- reason: `{reason}`\n",
        encoding="utf-8",
    )

    metadata = {
        "debug_session_id": ds.get("debug_session_id"),
        "parent_session_id": row.get("parent_session_id"),
        "child_session_id": child,
        "project_root": root.as_posix(),
        "workflow_id": row.get("workflow_id") or st.get("workflow_id"),
        "run_id": row.get("run_id") or st.get("run_id"),
        "phase": row.get("phase") or st.get("phase"),
        "action_id": action_id,
        "actor_id": row.get("actor_id"),
        "started_at": row.get("started_at"),
        "enabled_at": ds.get("enabled_at"),
        "exported_at": _now(),
        "reason": reason,
        "subagent": subagent,
        "transcript_status": transcript_info.get("transcript_status"),
        "transcript_reason": transcript_info.get("reason", ""),
        "audit": audit,
    }
    _dump_yaml(export_dir / "metadata.yaml", metadata)

    manifest = {
        "files": sorted(p.name for p in export_dir.iterdir() if p.is_file()),
        "export_dir": export_dir.as_posix(),
    }
    _dump_yaml(export_dir / "artifact_manifest.yaml", manifest)

    anomalies = list_anomalies(root, limit=100)
    md = _render_child_export_md(
        root=root,
        state=st,
        reason=reason,
        subagent=subagent,
        row=row,
        metadata=metadata,
        anomalies=anomalies,
        audit=audit,
    )
    (export_dir / "DEBUG_REPORT.md").write_text(md, encoding="utf-8")

    row["exported"] = True
    row["export_dir"] = export_dir.as_posix()
    row["exported_at"] = _now()
    reg = _load_children_registry(root)
    for i, r in enumerate(reg.get("children") or []):
        if normalize_session_id(str(r.get("child_session_id") or "")) == child:
            reg["children"][i] = row
            break
    _save_children_registry(root, reg)

    meta = {
        "ok": True,
        "reason": reason,
        "child_session_id": child,
        "parent_session_id": row.get("parent_session_id"),
        "export_dir": export_dir.as_posix(),
        "transcript": transcript_info,
        "audit": audit,
        "at": _now(),
    }
    _dump_yaml(_project_debug_dir(root) / "latest_export.yaml", meta)
    return meta


def _render_child_export_md(
    *,
    root: Path,
    state: dict[str, Any],
    reason: str,
    subagent: str,
    row: dict[str, Any],
    metadata: dict[str, Any],
    anomalies: list[dict[str, Any]],
    audit: dict[str, int],
) -> str:
    ts = metadata.get("transcript_status") or "unknown"
    treason = metadata.get("transcript_reason") or ""
    lines = [
        f"# AscendC Debug Child Export ({reason})",
        "",
        f"- project: `{root.as_posix()}`",
        f"- run_id: `{metadata.get('run_id')}`",
        f"- action_id: `{row.get('action_id')}`",
        f"- child_session_id: `{row.get('child_session_id')}`",
        f"- parent_session_id: `{row.get('parent_session_id')}`",
        f"- subagent: `{subagent or row.get('actor_id') or '-'}`",
        f"- transcript_status: `{ts}`",
        f"- transcript_reason: `{treason or '-'}`",
        f"- exported_at: `{metadata.get('exported_at')}`",
        "",
        "## Audit (tool events only)",
        "",
    ]
    for k, v in audit.items():
        lines.append(f"- {k}: {v}")
    lines.extend(["", "## Anomalies (parent session, recent)", ""])
    if not anomalies:
        lines.append("_none_")
    else:
        for a in anomalies[-20:]:
            lines.append(f"- **{a.get('kind')}** @ {a.get('at')}: {a.get('summary')}")
    lines.append("")
    return "\n".join(lines) + "\n"


def finalize_parent_index(
    project_root: Path | None = None,
    *,
    parent_session_id: str = "",
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    if not is_enabled(root):
        return {"ok": False, "skipped": True, "reason": "debug_disabled"}
    ds = load_debug_session(root)
    parent = normalize_session_id(parent_session_id) or normalize_session_id(str(ds.get("parent_session_id") or ""))
    reg = _load_children_registry(root)
    bundles: list[dict[str, Any]] = []
    for row in reg.get("children") or []:
        if normalize_session_id(str(row.get("parent_session_id") or "")) != parent:
            continue
        ok, _ = _child_export_eligible(row, ds, root)
        if not ok or not row.get("exported"):
            continue
        bundles.append(
            {
                "child_session_id": row.get("child_session_id"),
                "action_id": row.get("action_id"),
                "export_dir": row.get("export_dir"),
                "started_at": row.get("started_at"),
                "exported_at": row.get("exported_at"),
            }
        )
    bundles.sort(key=lambda b: str(b.get("started_at") or ""))
    summary = {
        "debug_session_id": ds.get("debug_session_id"),
        "parent_session_id": parent,
        "project_root": root.as_posix(),
        "workflow_id": ds.get("workflow_id"),
        "run_id": ds.get("run_id"),
        "enabled_at": ds.get("enabled_at"),
        "finalized_at": _now(),
        "child_count": len(bundles),
    }
    dbg_dir = _project_debug_dir(root)
    _dump_yaml(dbg_dir / "parent_session_summary.yaml", summary)
    _dump_yaml(
        dbg_dir / "children_index.yaml",
        {"parent_session_id": parent, "children": bundles},
    )
    return {"ok": True, "summary": summary, "children": bundles}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        if yaml is None:
            return json.loads(path.read_text(encoding="utf-8"))
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if yaml is None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def resolve_project_root(explicit: Path | str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = (os.environ.get("ASCENDC_PROJECT_ROOT") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    cache = Path.home() / ".config" / "opencode" / "ascendc-last-project"
    if cache.is_file():
        root = cache.read_text(encoding="utf-8").strip()
        if root and Path(root).is_dir():
            return Path(root).resolve()
    return Path.cwd().resolve()


def load_config(project_root: Path | None = None) -> dict[str, Any]:
    cfg = dict(_DEFAULTS)
    g = _load_yaml(_global_debug_path())
    cfg.update({k: v for k, v in g.items() if k in _DEFAULTS or k in {"notes"}})
    root = resolve_project_root(project_root)
    local = _load_yaml(_project_debug_dir(root) / "config.yaml")
    cfg.update({k: v for k, v in local.items() if k in _DEFAULTS or k in {"notes"}})
    env = (os.environ.get("ASCENDC_DEBUG") or "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        cfg["enabled"] = True
    elif env in {"0", "false", "no", "off"}:
        cfg["enabled"] = False
    cfg["project_root"] = root.as_posix()
    return cfg


def is_enabled(project_root: Path | None = None) -> bool:
    return bool(load_config(project_root).get("enabled"))


def set_enabled(
    project_root: Path | None,
    enabled: bool,
    *,
    scope: str = "project",
    parent_session_id: str = "",
    **overrides: Any,
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    cfg = load_config(root)
    cfg["enabled"] = bool(enabled)
    cfg["updated_at"] = _now()
    for k, v in overrides.items():
        if k in _DEFAULTS:
            cfg[k] = v
    if scope == "global":
        path = _global_debug_path()
    else:
        path = _project_debug_dir(root) / "config.yaml"
    keep = {k: cfg[k] for k in list(_DEFAULTS) + ["updated_at", "notes"] if k in cfg}
    _dump_yaml(path, keep)
    session_meta: dict[str, Any] | None = None
    if enabled and scope != "global":
        from ascendc_pilot.state import load_state

        st = load_state(root) or {}
        enabled_at = _now()
        session_meta = {
            "debug_session_id": _new_debug_session_id(),
            "parent_session_id": normalize_session_id(parent_session_id),
            "project_root": root.as_posix(),
            "workflow_id": str(st.get("workflow_id") or ""),
            "run_id": str(st.get("run_id") or ""),
            "enabled_at": enabled_at,
        }
        _save_debug_session(root, session_meta)
    return {
        "ok": True,
        "enabled": enabled,
        "scope": scope,
        "path": path.as_posix(),
        "config": cfg,
        "debug_session": session_meta,
    }


def anomalies_path(project_root: Path | None = None) -> Path:
    root = resolve_project_root(project_root)
    return _project_debug_dir(root) / "anomalies.jsonl"


def append_anomaly(
    project_root: Path | None,
    *,
    kind: str,
    summary: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    if not is_enabled(root):
        return {"ok": False, "skipped": True, "reason": "debug_disabled"}
    entry = {
        "at": _now(),
        "kind": kind,
        "summary": summary[:500],
        "detail": detail or {},
        "project_root": root.as_posix(),
    }
    path = anomalies_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    return {"ok": True, "path": path.as_posix(), "entry": entry}


def analyze_thought(text: str, *, char_limit: int = 2500, meta_hits_min: int = 4) -> dict[str, Any]:
    """Return anomaly descriptor if thought looks long + non-logical thrash."""
    raw = str(text or "")
    hits = [p.pattern for p in _META_PATTERNS if p.search(raw)]
    long = len(raw) >= int(char_limit)
    meta_heavy = len(hits) >= int(meta_hits_min)
    density = (len(hits) / max(len(raw), 1)) * 1000
    flagged = long and (meta_heavy or density >= 1.2)
    return {
        "flagged": flagged,
        "char_len": len(raw),
        "meta_hits": hits,
        "meta_count": len(hits),
        "density_per_1k": round(density, 3),
        "long": long,
        "meta_heavy": meta_heavy,
    }


def classify_tool_output_failure(
    *,
    tool: str = "",
    error: str = "",
    exit_code: int | None = None,
    output_text: str = "",
) -> dict[str, Any]:
    """Strict failure classifier — avoid mistaking successful Read/bash bodies for errors.

    Real failures:
    - non-zero exit_code
    - SchemaError / invalid arguments
    - authorize deny / blocked harness messages
    - JSON payload with top-level ``"ok": false`` (acp responses)
    """
    tool_l = str(tool or "").lower()
    err = str(error or "")
    text = str(output_text or "") or err
    reasons: list[str] = []

    if exit_code is not None and int(exit_code) != 0:
        reasons.append(f"exit_code={exit_code}")

    if re.search(r"SchemaError|invalid arguments|Missing key", text, re.I):
        reasons.append("schema_error")

    if re.search(
        r"\[ascendc-pilot\]\s*blocked|HARNESS_ACTION_NOT_AUTHORIZED|PRIMARY_PROTECTED_WRITE|"
        r"decision[\"']?\s*:\s*[\"']deny",
        text,
        re.I,
    ):
        reasons.append("harness_deny")

    # Prefer structured acp JSON: look for "ok": false near the start of an object.
    # Do NOT treat the word "error"/"fail" inside successful file contents as failure.
    json_ok_false = False
    for m in re.finditer(r"\{[^{}]{0,4000}\}", text):
        chunk = m.group(0)
        if re.search(r'"ok"\s*:\s*false', chunk):
            json_ok_false = True
            break
    if not json_ok_false and re.search(r'"ok"\s*:\s*false', text):
        # Large truncated JSON — still count if ok:false appears before any ok:true
        first_false = text.find('"ok": false')
        if first_false < 0:
            first_false = text.find('"ok":false')
        first_true = text.find('"ok": true')
        if first_true < 0:
            first_true = text.find('"ok":true')
        if first_false >= 0 and (first_true < 0 or first_false < first_true):
            json_ok_false = True
    if json_ok_false:
        reasons.append("json_ok_false")

    # Explicit error-only envelopes (not Read file dumps)
    if re.search(r"^(Error|ERROR|Exception|Traceback)\b", err.strip()):
        reasons.append("error_envelope")

    # Successful Read tool dumps look like <path>…</path><type>file</type><content>…
    looks_like_read_dump = bool(
        re.search(r"<path>.*</path>\s*<type>\s*file\s*</type>", text, re.I | re.S)
        or (tool_l == "read" and text.lstrip().startswith("<path>"))
    )
    if looks_like_read_dump and not reasons:
        return {"is_failure": False, "reasons": [], "skipped": "read_success_dump"}

    # Successful acp with ok:true and no ok:false
    if re.search(r'"ok"\s*:\s*true', text) and not json_ok_false and not reasons:
        return {"is_failure": False, "reasons": [], "skipped": "json_ok_true"}

    is_failure = bool(reasons)
    return {
        "is_failure": is_failure,
        "reasons": reasons,
        "skipped": "" if is_failure else "no_failure_signal",
    }


def record_tool_failure(
    project_root: Path | None,
    *,
    tool: str,
    error: str,
    args: dict[str, Any] | None = None,
    agent: str = "",
    action_id: str = "",
    exit_code: int | None = None,
    require_real_failure: bool = True,
) -> dict[str, Any]:
    if require_real_failure:
        verdict = classify_tool_output_failure(
            tool=tool, error=error, exit_code=exit_code, output_text=error
        )
        if not verdict.get("is_failure"):
            return {
                "ok": True,
                "skipped": True,
                "reason": "not_a_real_failure",
                "classify": verdict,
            }
    return append_anomaly(
        project_root,
        kind="tool_failure",
        summary=f"{tool} failed: {str(error)[:200]}",
        detail={
            "tool": tool,
            "error": str(error)[:2000],
            "args": _safe_args(args),
            "agent": agent,
            "action_id": action_id,
            "exit_code": exit_code,
        },
    )


def record_long_thought(
    project_root: Path | None,
    text: str,
    *,
    agent: str = "",
) -> dict[str, Any]:
    cfg = load_config(project_root)
    analysis = analyze_thought(
        text,
        char_limit=int(cfg.get("thought_char_limit") or 2500),
        meta_hits_min=int(cfg.get("thought_meta_hits_min") or 4),
    )
    if not analysis["flagged"]:
        return {"ok": True, "flagged": False, "analysis": analysis}
    return append_anomaly(
        project_root,
        kind="long_nonlogical_thought",
        summary=(
            f"thought {analysis['char_len']} chars, meta_hits={analysis['meta_count']} "
            f"({', '.join(analysis['meta_hits'][:4])})"
        ),
        detail={"analysis": analysis, "excerpt": text[:800], "agent": agent},
    )


def _safe_args(args: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in list(args.items())[:20]:
        s = str(v)
        out[str(k)] = s[:500] + ("…" if len(s) > 500 else "")
    return out


def list_anomalies(project_root: Path | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    path = anomalies_path(project_root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return rows[-limit:]


def export_session_bundle(
    project_root: Path | None = None,
    *,
    reason: str = "manual",
    subagent: str = "",
    session_id: str = "",
    parent_session_id: str = "",
    transcript_hint: str = "",
) -> dict[str, Any]:
    """Legacy/manual export — routes to child bundle when session_id is a registered child."""
    root = resolve_project_root(project_root)
    sid = normalize_session_id(session_id)
    if sid and is_registered_child(root, sid):
        return export_child_session(
            root,
            child_session_id=sid,
            reason=reason,
            subagent=subagent,
        )
    return _export_legacy_session_bundle(
        root,
        reason=reason,
        subagent=subagent,
        session_id=session_id,
        parent_session_id=parent_session_id,
        transcript_hint=transcript_hint,
    )


def _export_legacy_session_bundle(
    project_root: Path,
    *,
    reason: str = "manual",
    subagent: str = "",
    session_id: str = "",
    parent_session_id: str = "",
    transcript_hint: str = "",
) -> dict[str, Any]:
    """Bundle run state + anomalies + optional transcript into debug/exports/ (non-child)."""
    root = project_root
    from ascendc_pilot.paths import agent_root, runs_root
    from ascendc_pilot.state import load_state

    st = load_state(root) or {}
    run_id = str(st.get("run_id") or "NO_RUN")
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    export_dir = _project_debug_dir(root) / "exports" / f"{stamp}_{run_id}_{reason}"
    export_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for rel in (
        "state/workflow.yaml",
        "state/active_action.yaml",
        "debug/config.yaml",
        "debug/anomalies.jsonl",
    ):
        src = agent_root(root) / rel
        if src.is_file():
            dst = export_dir / rel.replace("/", "_")
            shutil.copy2(src, dst)
            copied.append(dst.name)

    rdir = runs_root(root) / run_id
    if rdir.is_dir():
        for name in ("events.jsonl", "observations.jsonl"):
            src = rdir / name
            if src.is_file():
                shutil.copy2(src, export_dir / name)
                copied.append(name)
        for folder in ("observations", "actions"):
            src = rdir / folder
            if src.is_dir():
                dest = export_dir / folder
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.copytree(src, dest)
                copied.append(f"{folder}/")

    transcript_info = _try_copy_transcripts(
        export_dir,
        project_root=root,
        session_id=session_id,
        parent_session_id=parent_session_id,
        transcript_hint=transcript_hint,
        reason=reason,
    )
    copied.extend(transcript_info.get("copied") or [])

    anomalies = list_anomalies(root, limit=100)
    md = _render_export_md(
        root=root,
        state=st,
        reason=reason,
        subagent=subagent,
        anomalies=anomalies,
        copied=copied,
        session_id=session_id,
        parent_session_id=parent_session_id,
        transcript_note=str(transcript_info.get("note") or ""),
    )
    (export_dir / "DEBUG_REPORT.md").write_text(md, encoding="utf-8")
    meta = {
        "ok": True,
        "reason": reason,
        "subagent": subagent,
        "session_id": session_id or "",
        "parent_session_id": parent_session_id or "",
        "export_dir": export_dir.as_posix(),
        "run_id": run_id,
        "copied": copied,
        "transcript": transcript_info,
        "anomaly_count": len(anomalies),
        "at": _now(),
    }
    _dump_yaml(export_dir / "export_meta.yaml", meta)
    _dump_yaml(_project_debug_dir(root) / "latest_export.yaml", meta)
    return meta


_SESSION_ID_RE = re.compile(r"(ses_[A-Za-z0-9]+)")
_TASK_ID_ATTR_RE = re.compile(r"""<task\s+[^>]*\bid=["'](ses_[A-Za-z0-9]+)["']""", re.I)


def normalize_session_id(raw: str) -> str:
    """Return bare ses_* id from raw / path / filename."""
    text = str(raw or "").strip()
    if not text:
        return ""
    m = _SESSION_ID_RE.search(text.replace("\\", "/"))
    return m.group(1) if m else ""


def extract_task_session_id_from_text(text: str) -> str:
    """Parse OpenCode Task tool output for `<task id="ses_…">`."""
    m = _TASK_ID_ATTR_RE.search(str(text or ""))
    return m.group(1) if m else ""


def _transcript_search_roots(project_root: Path) -> list[Path]:
    roots: list[Path] = []
    for p in (project_root, Path.cwd()):
        try:
            roots.append(p.resolve())
        except Exception:  # noqa: BLE001
            roots.append(p)
    # Workspace often holds session-ses_*.md above the operator package.
    try:
        cur = project_root.resolve()
        for _ in range(5):
            if cur.parent == cur:
                break
            cur = cur.parent
            roots.append(cur)
    except Exception:  # noqa: BLE001
        pass
    # de-dupe preserving order
    out: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        if r.is_dir():
            out.append(r)
    return out


def _find_session_files(session_id: str, search_roots: list[Path]) -> list[Path]:
    sid = normalize_session_id(session_id)
    if not sid:
        return []
    found: list[Path] = []
    seen: set[str] = set()
    patterns = (
        f"session-{sid}.md",
        f"session-{sid}*.md",
        f"*{sid}*.md",
    )
    for root in search_roots:
        for pat in patterns:
            for hit in root.glob(pat):
                if not hit.is_file():
                    continue
                key = str(hit.resolve()) if hit.exists() else str(hit)
                if key in seen:
                    continue
                # Require id token in name to avoid unrelated *ses_* substring hits.
                if sid not in hit.name:
                    continue
                seen.add(key)
                found.append(hit)
    # Cursor agent transcripts: only paths that contain the session id.
    home_proj = Path.home() / ".cursor" / "projects"
    if home_proj.is_dir():
        for proj in home_proj.iterdir():
            tr = proj / "agent-transcripts"
            if not tr.is_dir():
                continue
            for hit in tr.rglob("*.jsonl"):
                path_s = str(hit).replace("\\", "/")
                if sid not in path_s and sid not in hit.name:
                    continue
                key = str(hit.resolve()) if hit.exists() else str(hit)
                if key in seen:
                    continue
                seen.add(key)
                found.append(hit)
    return found


def _try_copy_transcripts(
    export_dir: Path,
    *,
    project_root: Path,
    session_id: str = "",
    parent_session_id: str = "",
    transcript_hint: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """Copy only explicitly identified transcripts — never fish cwd for unrelated sessions."""
    copied: list[str] = []
    missing: list[str] = []
    search_roots = _transcript_search_roots(project_root)

    def _copy_one(src: Path, label: str) -> bool:
        try:
            if not src.is_file():
                return False
            if src.stat().st_size > 80_000_000:
                return False
            dst_name = f"transcript_{label}_{src.name}" if label else f"transcript_{src.name}"
            # Keep stable short name when label empty / already unique.
            if not label:
                dst_name = f"transcript_{src.name}"
            dst = export_dir / dst_name
            shutil.copy2(src, dst)
            copied.append(dst.name)
            return True
        except Exception:  # noqa: BLE001
            return False

    if transcript_hint:
        hint = Path(transcript_hint)
        if not _copy_one(hint, "hint"):
            missing.append(f"hint:{transcript_hint}")

    child = normalize_session_id(session_id)
    parent = normalize_session_id(parent_session_id)
    # Avoid duplicating when ids collide.
    ids: list[tuple[str, str]] = []
    if child:
        ids.append(("subagent", child))
    if parent and parent != child:
        ids.append(("host", parent))

    if not ids and not transcript_hint:
        note = (
            "no transcript copied: require --session-id / --parent-session-id / --transcript "
            "(refuses cwd mtime fishing of unrelated session-ses_*.md)"
        )
        return {"copied": copied, "missing": missing, "note": note, "ok": False}

    for label, sid in ids:
        hits = _find_session_files(sid, search_roots)
        if not hits:
            missing.append(sid)
            continue
        # Prefer markdown session export over jsonl when both exist.
        hits_sorted = sorted(
            hits,
            key=lambda p: (0 if p.suffix.lower() == ".md" else 1, p.name.lower(), str(p)),
        )
        _copy_one(hits_sorted[0], label)

    note = ""
    if missing and not copied:
        note = f"transcript not found for: {', '.join(missing)}"
    elif missing:
        note = f"partial: missing {', '.join(missing)}"
    elif copied:
        note = "ok"
    return {
        "copied": copied,
        "missing": missing,
        "note": note,
        "ok": bool(copied),
        "session_id": child,
        "parent_session_id": parent,
        "reason": reason,
    }


def _render_export_md(
    *,
    root: Path,
    state: dict[str, Any],
    reason: str,
    subagent: str,
    anomalies: list[dict[str, Any]],
    copied: list[str],
    session_id: str = "",
    parent_session_id: str = "",
    transcript_note: str = "",
) -> str:
    lines = [
        f"# AscendC Debug Export ({reason})",
        "",
        f"- project: `{root.as_posix()}`",
        f"- run_id: `{state.get('run_id')}`",
        f"- phase/status: `{state.get('phase')}` / `{state.get('status')}`",
        f"- subagent: `{subagent or '-'}`",
        f"- session_id: `{session_id or '-'}`",
        f"- parent_session_id: `{parent_session_id or '-'}`",
        f"- transcript: `{transcript_note or '-'}`",
        f"- exported_at: `{_now()}`",
        "",
        "## Copied artifacts",
        "",
    ]
    for c in copied:
        lines.append(f"- `{c}`")
    if not any(str(c).startswith("transcript_") for c in copied):
        lines.append("- _(no transcript — pass session id; will not fish unrelated sessions)_")
    lines.extend(["", "## Anomalies (recent)", ""])
    if not anomalies:
        lines.append("_none_")
    else:
        for a in anomalies[-30:]:
            lines.append(f"- **{a.get('kind')}** @ {a.get('at')}: {a.get('summary')}")
    tool_fails = [a for a in anomalies if a.get("kind") == "tool_failure"]
    thoughts = [a for a in anomalies if a.get("kind") == "long_nonlogical_thought"]
    lines.extend(
        [
            "",
            "## Counts",
            "",
            f"- tool_failure: {len(tool_fails)}",
            f"- long_nonlogical_thought: {len(thoughts)}",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def hook_handle(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Entry for Cursor/OpenCode hooks. Always fail-open (never block)."""
    root = resolve_project_root(payload.get("project_root") or payload.get("cwd"))
    cfg = load_config(root)
    if not cfg.get("enabled"):
        return {"ok": True, "skipped": True}

    out: dict[str, Any] = {"ok": True, "event": event}

    if event in {"postToolUseFailure", "tool_failure"}:
        tool = str(payload.get("tool_name") or payload.get("tool") or "unknown")
        err = str(
            payload.get("error_message")
            or payload.get("error")
            or payload.get("message")
            or "tool failed"
        )
        rec = record_tool_failure(
            root,
            tool=tool,
            error=err,
            args=payload.get("tool_input") or payload.get("args") or {},
            agent=str(payload.get("agent") or ""),
            action_id=str(payload.get("action_id") or ""),
            # Cursor/OpenCode failure events are already authoritative failures.
            require_real_failure=False,
        )
        out["recorded"] = rec
        if rec.get("ok"):
            msg = f"[ascendc-debug] captured tool_failure: {tool}"
            out["agent_message"] = msg
            out["additional_context"] = msg

    elif event in {"afterAgentThought", "agent_thought"}:
        text = str(payload.get("text") or payload.get("thought") or payload.get("content") or "")
        rec = record_long_thought(root, text, agent=str(payload.get("agent") or ""))
        out["recorded"] = rec
        if rec.get("ok") and rec.get("entry"):
            out["additional_context"] = (
                "[ascendc-debug] long non-logical thought captured — "
                "prefer acting over debating control-plane rules."
            )

    elif event in {"subagentStop", "subagent_stop"}:
        sub = str(
            payload.get("subagent_type")
            or payload.get("subagent")
            or payload.get("agent")
            or ""
        )
        child_sid = str(
            payload.get("session_id")
            or payload.get("task_session_id")
            or payload.get("child_session_id")
            or ""
        )
        parent_sid = str(
            payload.get("parent_session_id")
            or payload.get("host_session_id")
            or ""
        )
        if cfg.get("auto_export_on_subagent_stop", True):
            child_norm = normalize_session_id(child_sid)
            if child_norm:
                patch_child_session_id(
                    root,
                    child_session_id=child_norm,
                    parent_session_id=parent_sid,
                    action_id=str(payload.get("action_id") or ""),
                )
                meta = export_child_session(
                    root,
                    child_session_id=child_norm,
                    reason="subagent_stop",
                    subagent=sub,
                )
            else:
                meta = {"ok": False, "skipped": True, "reason": "missing_child_session_id"}
            out["export"] = meta
            if meta.get("ok"):
                out["followup_message"] = (
                    f"[ascendc-debug] 子代理 `{sub or '?'}` 已结束；"
                    f"会话已导出到 `{meta.get('export_dir')}`。"
                    f"请按 Bundle 继续（通常是 `acp run-action <action_id> --finalize`），"
                    f"不要复述 METHOD。"
                )

    elif event in {"sessionEnd", "session_end", "stop"}:
        if cfg.get("auto_export_on_session_end", True):
            meta = finalize_parent_index(
                root,
                parent_session_id=str(
                    payload.get("parent_session_id")
                    or payload.get("session_id")
                    or payload.get("host_session_id")
                    or ""
                ),
            )
            out["export"] = meta

    return out
