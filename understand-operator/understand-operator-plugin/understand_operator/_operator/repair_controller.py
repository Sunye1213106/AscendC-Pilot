from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from understand_operator._operator.run_context import phase0_context
from understand_operator._operator.spec import spec_bundle_hash

MAX_ATTEMPTS = 3


def read_repair_state(uo_root: Path, run_id: str, repair_key: str) -> dict[str, Any]:
    return _read(uo_root / "runs" / run_id / "repairs" / f"{_safe_key(repair_key)}.yaml")


def record_repair_attempt(
    uo_root: Path,
    run_id: str,
    repair_key: str,
    task_id: str,
    owner: str,
    target: dict[str, Any],
    candidate_path: str,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    path = uo_root / "runs" / run_id / "repairs" / f"{_safe_key(repair_key)}.yaml"
    state = _read(path)
    previous_errors = [item for item in state.get("previous_errors") or [] if isinstance(item, dict)]
    existing_attempt = int(state.get("attempt") or 0)
    attempt = min(existing_attempt + 1, MAX_ATTEMPTS)
    previous_errors.extend(_compact_errors(errors))
    status = "exhausted" if attempt >= MAX_ATTEMPTS else "retrying"
    payload = {
        "version": 1,
        "artifact": {"type": "runs.repair_state", "schema_version": 1, "owner": "repair-controller"},
        "snapshot": _snapshot(uo_root, run_id),
        "repair_key": repair_key,
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
            "repair_key": repair_key,
            "attempt": attempt,
            "max_attempts": MAX_ATTEMPTS,
            "last_error": previous_errors[-1] if previous_errors else {},
            "error_codes": sorted({str(item.get("code")) for item in previous_errors if item.get("code")}),
            "candidate_path": candidate_path,
        }
    return {}


def mark_repair_completed(
    uo_root: Path,
    run_id: str,
    repair_key: str,
    task_id: str,
    owner: str,
    target: dict[str, Any],
    candidate_path: str,
) -> dict[str, Any]:
    path = uo_root / "runs" / run_id / "repairs" / f"{_safe_key(repair_key)}.yaml"
    state = _read(path)
    previous_errors = [item for item in state.get("previous_errors") or [] if isinstance(item, dict)]
    attempt = int(state.get("attempt") or 0)
    payload = {
        "version": 1,
        "artifact": {"type": "runs.repair_state", "schema_version": 1, "owner": "repair-controller"},
        "snapshot": _snapshot(uo_root, run_id),
        "repair_key": repair_key,
        "task_id": task_id,
        "owner": owner,
        "target": target,
        "candidate_path": candidate_path,
        "attempt": max(attempt, 1),
        "max_attempts": MAX_ATTEMPTS,
        "previous_errors": previous_errors,
        "status": "completed",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return payload


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


def _safe_key(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value) or "unknown_key"


def _snapshot(uo_root: Path, run_id: str) -> dict[str, str]:
    context = phase0_context(uo_root, run_id)
    return {
        "run_id": run_id,
        "source_snapshot_id": str(context.get("source_snapshot_id") or "SOURCE_UNKNOWN"),
        "source_revision": str(context.get("source_revision") or "unknown"),
        "spec_bundle_hash": spec_bundle_hash(),
    }


def repair_key_for_batch(run_id: str, owner: str, target: dict[str, Any], items: list[dict[str, Any]], relations: list[dict[str, Any]]) -> str:
    target_path = str(target.get("path") or "")
    item_local_ids = sorted(str(item.get("local_id")) for item in items if isinstance(item, dict) and item.get("local_id"))
    relation_local_ids = sorted(str(rel.get("local_id")) for rel in relations if isinstance(rel, dict) and rel.get("local_id"))
    material = "\0".join([run_id, owner, target_path, ",".join(item_local_ids), ",".join(relation_local_ids)])
    return "REPAIR_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16].upper()
