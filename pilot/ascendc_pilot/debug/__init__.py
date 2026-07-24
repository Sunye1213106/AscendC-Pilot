"""Debug mode: capture tool failures, long non-logical thoughts, export sessions."""

from __future__ import annotations

import json
import os
import re
import shutil
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
    return {"ok": True, "enabled": enabled, "scope": scope, "path": path.as_posix(), "config": cfg}


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
    transcript_hint: str = "",
) -> dict[str, Any]:
    """Bundle run state + anomalies + optional transcript into debug/exports/."""
    root = resolve_project_root(project_root)
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

    transcript_copied = _try_copy_transcript(
        export_dir,
        session_id=session_id,
        transcript_hint=transcript_hint,
    )
    if transcript_copied:
        copied.append(transcript_copied)

    anomalies = list_anomalies(root, limit=100)
    md = _render_export_md(
        root=root,
        state=st,
        reason=reason,
        subagent=subagent,
        anomalies=anomalies,
        copied=copied,
    )
    (export_dir / "DEBUG_REPORT.md").write_text(md, encoding="utf-8")
    meta = {
        "ok": True,
        "reason": reason,
        "subagent": subagent,
        "export_dir": export_dir.as_posix(),
        "run_id": run_id,
        "copied": copied,
        "anomaly_count": len(anomalies),
        "at": _now(),
    }
    _dump_yaml(export_dir / "export_meta.yaml", meta)
    _dump_yaml(_project_debug_dir(root) / "latest_export.yaml", meta)
    return meta


def _try_copy_transcript(
    export_dir: Path,
    *,
    session_id: str = "",
    transcript_hint: str = "",
) -> str:
    candidates: list[Path] = []
    if transcript_hint:
        candidates.append(Path(transcript_hint))
    cwd = Path.cwd()
    if session_id:
        candidates.extend(cwd.glob(f"session*{session_id}*.md"))
        candidates.extend(cwd.glob(f"*{session_id}*.md"))
    candidates.extend(
        sorted(cwd.glob("session-ses_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    )
    home_proj = Path.home() / ".cursor" / "projects"
    if home_proj.is_dir():
        for proj in home_proj.iterdir():
            tr = proj / "agent-transcripts"
            if tr.is_dir():
                files = sorted(tr.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
                candidates.extend(files[:2])

    for src in candidates:
        try:
            if not src.is_file():
                continue
            if src.stat().st_size > 80_000_000:
                continue
            dst = export_dir / f"transcript_{src.name}"
            shutil.copy2(src, dst)
            return dst.name
        except Exception:  # noqa: BLE001
            continue
    return ""


def _render_export_md(
    *,
    root: Path,
    state: dict[str, Any],
    reason: str,
    subagent: str,
    anomalies: list[dict[str, Any]],
    copied: list[str],
) -> str:
    lines = [
        f"# AscendC Debug Export ({reason})",
        "",
        f"- project: `{root.as_posix()}`",
        f"- run_id: `{state.get('run_id')}`",
        f"- phase/status: `{state.get('phase')}` / `{state.get('status')}`",
        f"- subagent: `{subagent or '-'}`",
        f"- exported_at: `{_now()}`",
        "",
        "## Copied artifacts",
        "",
    ]
    for c in copied:
        lines.append(f"- `{c}`")
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
        if cfg.get("auto_export_on_subagent_stop", True):
            meta = export_session_bundle(
                root,
                reason="subagent_stop",
                subagent=sub,
                session_id=str(payload.get("session_id") or ""),
            )
            out["export"] = meta
            out["followup_message"] = (
                f"[ascendc-debug] 子代理 `{sub or '?'}` 已结束；"
                f"会话已导出到 `{meta.get('export_dir')}`。"
                f"异常数={meta.get('anomaly_count', 0)}。"
                f"请按 Bundle 继续（通常是 `acp run-action <action_id> --finalize`），"
                f"不要复述 METHOD。"
            )

    elif event in {"sessionEnd", "session_end", "stop"}:
        if cfg.get("auto_export_on_session_end", True):
            meta = export_session_bundle(
                root,
                reason="session_end",
                session_id=str(payload.get("session_id") or ""),
            )
            out["export"] = meta

    return out
