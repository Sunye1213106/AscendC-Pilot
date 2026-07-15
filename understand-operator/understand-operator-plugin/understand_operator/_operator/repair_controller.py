from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

MAX_ATTEMPTS = 3


def record_repair_attempt(uo_root: Path, run_id: str, task_id: str, owner: str, target: dict[str, Any], candidate_path: str, errors: list[dict[str, Any]]) -> dict[str, Any]:
    path = uo_root / "runs" / run_id / "repairs" / f"{_safe_task_id(task_id)}.yaml"
    state = _read(path)
    previous_errors = [item for item in state.get("previous_errors") or [] if isinstance(item, dict)]
    attempt = int(state.get("attempt") or 0) + 1
    previous_errors.extend(_compact_errors(errors))
    status = "exhausted" if attempt >= MAX_ATTEMPTS else "retrying"
    payload = {
        "version": 1,
        "task_id": task_id,
        "owner": owner,
        "target": target,
        "candidate_path": candidate_path,
        "attempt": attempt,
        "max_attempts": MAX_ATTEMPTS,
        "previous_errors": previous_errors,
        "status": status,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    if status == "exhausted":
        return {
            "code": "CANDIDATE_REPAIR_EXHAUSTED",
            "message": "candidate repair attempts exhausted",
            "target": target,
            "task_id": task_id,
            "attempt": attempt,
            "max_attempts": MAX_ATTEMPTS,
            "last_error": previous_errors[-1] if previous_errors else {},
            "error_codes": sorted({str(item.get("code")) for item in previous_errors if item.get("code")}),
            "candidate_path": candidate_path,
        }
    return {}


def _compact_errors(errors: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for error in errors:
        result.append({key: str(error.get(key) or "") for key in ("code", "field", "message", "target") if error.get(key) not in (None, "")})
    return result


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _safe_task_id(task_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in task_id) or "unknown_task"
