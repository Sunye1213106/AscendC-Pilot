"""Dispatch compatibility layer with deterministic repeated-failure circuit breaker."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

from . import dispatch_legacy as _legacy

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)


def _failure_fingerprint(doc: dict[str, Any], error: str) -> str:
    normalized = re.sub(r"\s+", " ", str(error or "").strip().lower())[:800]
    raw = "|".join(
        [
            str(doc.get("workflow_id") or ""),
            str(doc.get("action_id") or ""),
            normalized,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def release_dispatch_ticket(
    project_root: Path,
    ticket_id: str,
    *,
    error: str = "",
) -> dict[str, Any]:
    """Re-open once; block the second identical deterministic failure."""
    doc = _legacy.load_dispatch_ticket(project_root, ticket_id)
    if not doc:
        return {"ok": False, "error": "TICKET_NOT_FOUND", "ticket_id": ticket_id}
    if str(doc.get("status") or "") != "processing":
        return {
            "ok": False,
            "error": "TICKET_NOT_PROCESSING",
            "ticket_id": ticket_id,
            "status": doc.get("status"),
        }

    fingerprint = _failure_fingerprint(doc, error)
    previous = str(doc.get("last_failure_fingerprint") or "")
    count = int(doc.get("same_failure_count") or 0) + 1 if previous == fingerprint else 1
    doc["last_failure_fingerprint"] = fingerprint
    doc["same_failure_count"] = count
    doc["retryable_error"] = str(error or "")[:400]
    doc["failed_at"] = time.time()

    if count >= 2:
        doc["status"] = "blocked_repeat_failure"
        doc["blocked_at"] = time.time()
        doc["block_reason"] = "REPEATED_DETERMINISTIC_FAILURE"
        _legacy._write_ticket(project_root, doc)
        return {
            "ok": True,
            "ticket": doc,
            "retryable": False,
            "error": "REPEATED_DETERMINISTIC_FAILURE",
            "reason_code": "REPEATED_DETERMINISTIC_FAILURE",
            "legal_actions": ["inspect_failure", "change_input", "replace_task_plan"],
        }

    doc["status"] = "open"
    doc["reopened_at"] = time.time()
    _legacy._write_ticket(project_root, doc)
    return {"ok": True, "ticket": doc, "retryable": True}


# Legacy dispatch_result resolves this global in dispatch_legacy; route it through
# the breaker without rewriting the mature finalize/drive implementation.
_legacy.release_dispatch_ticket = release_dispatch_ticket


def dispatch_result(
    project_root: Path,
    *,
    ticket_id: str,
    action_result: dict[str, Any] | None = None,
    result_file: Path | str | None = None,
    result_text: str = "",
    slice_id: str = "",
) -> dict[str, Any]:
    out = _legacy.dispatch_result(
        project_root,
        ticket_id=ticket_id,
        action_result=action_result,
        result_file=result_file,
        result_text=result_text,
        slice_id=slice_id,
    )
    if out.get("ok"):
        return out
    ticket = _legacy.load_dispatch_ticket(project_root, ticket_id)
    if str(ticket.get("status") or "") != "blocked_repeat_failure":
        return out
    result = dict(out)
    result["stop_reason"] = "repeated_deterministic_failure"
    result["ticket_retryable"] = False
    result["reason_code"] = "REPEATED_DETERMINISTIC_FAILURE"
    result["legal_actions"] = ["inspect_failure", "change_input", "replace_task_plan"]
    step = dict(result.get("host_step") or {})
    step["kind"] = "failed"
    step["ticket_retryable"] = False
    step["reason_code"] = "REPEATED_DETERMINISTIC_FAILURE"
    step["message_zh"] = "相同 Action 已连续两次以同一确定性错误失败，已熔断；请检查失败或更改输入，不再自动重试。"
    result["host_step"] = step
    return result
