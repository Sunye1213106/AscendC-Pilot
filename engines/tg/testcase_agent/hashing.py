from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def semantic_snapshot_hash(snapshot: dict[str, Any]) -> str:
    semantic = {
        "op_name": snapshot.get("op_name"),
        "view": snapshot.get("view"),
        "contract_view": snapshot.get("contract_view"),
        "context_slice": snapshot.get("context_slice"),
        "files": snapshot.get("files"),
        "source_artifact_hashes": snapshot.get("source_artifact_hashes"),
    }
    return stable_hash(semantic)


def semantic_plan_hash(
    snapshot_hash: str | None,
    obligations: list[dict[str, Any]],
    matrix: dict[str, Any],
    unresolved: dict[str, Any],
    planning_context: dict[str, Any] | None = None,
) -> str:
    return stable_hash(
        {
            "snapshot_hash": snapshot_hash,
            "planning_context": _without_hashes(planning_context or {}),
            "obligations": obligations,
            "matrix": _without_hashes(matrix),
            "unresolved": _without_hashes(unresolved),
        }
    )


def _without_hashes(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_hashes(child)
            for key, child in value.items()
            if key not in {"version", "snapshot_hash", "plan_hash", "created_at", "started_at", "completed_at", "approved_at"}
        }
    if isinstance(value, list):
        return [_without_hashes(child) for child in value]
    return value
