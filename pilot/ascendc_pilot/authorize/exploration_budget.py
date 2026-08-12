# -*- coding: utf-8 -*-
"""Exploration budget + duplicate suppression for uo-query / kb_lookup."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

DEFAULT_LIMITS = {
    "semantic": 6,
    "source": 2,
    "repo": 2,
    "total": 10,
    "hard_total": 12,
}

SOFT_REASON = "BUDGET_NEAR_LIMIT"
HARD_REASON = "EXPLORATION_BUDGET_EXHAUSTED"
DUP_REASON = "DUPLICATE_EXPLORATION"

_UO_QUERY_RE = re.compile(r"\buo-query\b", re.I)
_RO_SEARCH_RE = re.compile(r"\bro-search\b", re.I)


def budget_path(project_root: Path, *, run_id: str, action_id: str = "kb_lookup") -> Path:
    from ascendc_pilot.paths import agent_root, discover_arch
    from ascendc_pilot.state import load_state

    state = load_state(project_root) or {}
    arch = str(state.get("architecture") or "").strip()
    if not arch:
        try:
            arch = discover_arch(project_root)
        except Exception:  # noqa: BLE001
            arch = "arch35"
    root = agent_root(project_root, arch)
    return root / f"runs/{run_id}/actions/{action_id}/exploration_budget.yaml"


def init_budget(
    project_root: Path,
    *,
    run_id: str,
    action_id: str = "kb_lookup",
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    limits = dict(DEFAULT_LIMITS if limits is None else {**DEFAULT_LIMITS, **limits})
    body = {
        "schema": "uo-exploration-budget/v1",
        "run_id": run_id,
        "action_id": action_id,
        "limits": limits,
        "counts": {"semantic": 0, "source": 0, "repo": 0, "total": 0},
        "seen_semantic": [],
        "seen_spans": [],
        "warnings": [],
        "exhausted": False,
    }
    path = budget_path(project_root, run_id=run_id, action_id=action_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if yaml is not None:
        path.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return body


def load_budget(project_root: Path, *, run_id: str, action_id: str = "kb_lookup") -> dict[str, Any] | None:
    path = budget_path(project_root, run_id=run_id, action_id=action_id)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    return data if isinstance(data, dict) else None


def save_budget(project_root: Path, body: dict[str, Any], *, run_id: str, action_id: str = "kb_lookup") -> None:
    path = budget_path(project_root, run_id=run_id, action_id=action_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if yaml is not None:
        path.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


def classify_tool(tool: str, command: str = "", path: str = "") -> str | None:
    """Return budget bucket: semantic | repo | source | None (uncounted)."""
    tool_l = (tool or "").strip().lower()
    cmd = command or ""
    if tool_l in {"bash", "shell", "terminal"}:
        if _UO_QUERY_RE.search(cmd):
            return "semantic"
        if _RO_SEARCH_RE.search(cmd):
            return "repo"
        return None
    if tool_l in {"grep", "glob"}:
        return "repo"
    if tool_l in {"read"}:
        norm = (path or "").replace("\\", "/").lower()
        if "/.ascendc-pilot/" in norm or norm.endswith(".uo"):
            return None
        if any(seg in norm for seg in ("/op_host/", "/op_kernel/", "/op_graph/", "/common/")):
            return "source"
        if norm.endswith((".cpp", ".h", ".hpp", ".cc", ".cu")):
            return "source"
        return None
    return None


def _semantic_key(command: str) -> str:
    # Normalize whitespace; drop --project path noise for duplicate detection.
    cmd = re.sub(r"\s+", " ", (command or "").strip())
    cmd = re.sub(r"--project\s+\S+", "--project <P>", cmd, flags=re.I)
    return hashlib.sha256(cmd.encode("utf-8")).hexdigest()[:16]


def _span_key(path: str, command: str = "") -> str:
    """Identity for one source window, not for the whole source file."""
    norm = (path or "").replace("\\", "/").lstrip("./")
    range_hint = re.sub(r"\s+", "", str(command or "").strip().lower())
    raw = f"{norm}|{range_hint}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def check_and_record(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
    tool: str,
    command: str = "",
    path: str = "",
) -> dict[str, Any]:
    """Update budget; return allow/deny verdict fragment for authorize.

    Per-bucket and total limits are *soft*: crossing them warns the Agent to
    converge but does not turn into a hidden hard stop. ``hard_total`` is the
    single hard ceiling; the call that reaches it is allowed, and the next
    counted exploration call is denied.
    """
    body = load_budget(project_root, run_id=run_id, action_id=action_id)
    if body is None:
        body = init_budget(project_root, run_id=run_id, action_id=action_id)
    bucket = classify_tool(tool, command, path)
    if bucket is None:
        return {"ok": True, "skipped": True, "budget": body}

    limits = dict(body.get("limits") or DEFAULT_LIMITS)
    counts = dict(body.get("counts") or {})
    warnings = list(body.get("warnings") or [])
    seen_sem = list(body.get("seen_semantic") or [])
    seen_spans = list(body.get("seen_spans") or [])
    hard_total = int(limits.get("hard_total") or 12)

    if body.get("exhausted") or int(counts.get("total") or 0) >= hard_total:
        body["exhausted"] = True
        save_budget(project_root, body, run_id=run_id, action_id=action_id)
        return {
            "ok": False,
            "decision": "deny",
            "reason_code": HARD_REASON,
            "message_zh": "探索预算硬顶耗尽：请立即输出 ANSWERED|PARTIAL|UNKNOWN 并停止",
            "budget": body,
        }

    # Duplicate suppression.
    if bucket == "semantic":
        key = _semantic_key(command)
        if key in seen_sem:
            warnings.append({"reason_code": DUP_REASON, "bucket": bucket, "key": key})
            body["warnings"] = warnings[-20:]
            save_budget(project_root, body, run_id=run_id, action_id=action_id)
            return {
                "ok": False,
                "decision": "deny",
                "reason_code": DUP_REASON,
                "message_zh": "重复 semantic 查询已抑制；请换 hop 或 STOP",
                "budget": body,
            }
        seen_sem.append(key)
        body["seen_semantic"] = seen_sem[-64:]
    if bucket == "source":
        # Older Host adapters expose only a file path for Read.  Without a
        # range hint we cannot distinguish line 100 from line 800, so fail open
        # on duplicate suppression rather than incorrectly banning the second
        # window. Range-aware Hosts pass offset/limit in ``command`` and get
        # exact window deduplication.
        range_hint = str(command or "").strip()
        if range_hint:
            key = _span_key(path, range_hint)
            if key in seen_spans:
                warnings.append({"reason_code": DUP_REASON, "bucket": bucket, "key": key})
                body["warnings"] = warnings[-20:]
                save_budget(project_root, body, run_id=run_id, action_id=action_id)
                return {
                    "ok": False,
                    "decision": "deny",
                    "reason_code": DUP_REASON,
                    "message_zh": "同一源码 span 重复 Read 已抑制",
                    "budget": body,
                }
            seen_spans.append(key)
            body["seen_spans"] = seen_spans[-64:]

    counts[bucket] = int(counts.get(bucket) or 0) + 1
    counts["total"] = int(counts.get("total") or 0) + 1
    body["counts"] = counts

    soft_hit = (
        counts.get(bucket, 0) >= int(limits.get(bucket) or 0)
        or counts["total"] >= int(limits.get("total") or 10)
    )
    if soft_hit:
        warnings.append(
            {
                "reason_code": SOFT_REASON,
                "bucket": bucket,
                "counts": dict(counts),
            }
        )
        body["warnings"] = warnings[-20:]
    if counts["total"] >= hard_total:
        # This call is allowed. The next counted tool is denied.
        body["exhausted"] = True

    save_budget(project_root, body, run_id=run_id, action_id=action_id)
    out: dict[str, Any] = {"ok": True, "budget": body, "bucket": bucket}
    if soft_hit or counts["total"] >= max(1, int(limits.get("total") or 10) - 1):
        out["warning"] = SOFT_REASON
        out["message_zh"] = (
            "接近/超过探索软预算，只有会改变结论的 material gap 才继续；否则立即收束答案"
        )
    if counts["total"] >= hard_total:
        out["hard_limit_reached"] = True
        out["message_zh"] = "本次为最后一次允许的探索调用；现在必须收束答案"
    return out
