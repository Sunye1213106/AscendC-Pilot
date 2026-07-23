"""Run receipts, event log, and progress helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_harness.paths import ensure_agent_layout, runs_root


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump(path: Path, data: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML required")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _load_state(project_root: Path) -> dict[str, Any]:
    from ascendc_harness.state import load_state

    return load_state(project_root)


def run_dir(project_root: Path, run_id: str | None = None) -> Path:
    ensure_agent_layout(project_root)
    rid = run_id or str(_load_state(project_root).get("run_id") or "NO_RUN")
    path = runs_root(project_root) / rid
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_event(project_root: Path, event: dict[str, Any], *, run_id: str | None = None) -> None:
    path = run_dir(project_root, run_id) / "events.jsonl"
    row = dict(event)
    row.setdefault("at", _now())
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def file_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def issue_receipt(
    project_root: Path,
    *,
    actor_type: str,
    actor_id: str,
    action_id: str,
    workflow_spec_hash: str = "",
    input_hashes: dict[str, str] | None = None,
    output_hashes: dict[str, str] | None = None,
    checker_result: dict[str, Any] | None = None,
    identity: str = "",
    artifact: str = "",
) -> Path:
    """Harness-issued receipt only — agents must not forge this file."""
    state = _load_state(project_root)
    run_id = str(state.get("run_id") or "NO_RUN")
    identity = identity or f"{run_id}:{action_id}:{actor_id}"
    safe = identity.replace(":", "_").replace("/", "_")
    path = run_dir(project_root, run_id) / "subagents" / f"{safe}.yaml"
    payload = {
        "identity": identity,
        "run_id": run_id,
        "workflow_id": state.get("workflow_id"),
        "phase": state.get("phase"),
        "actor_type": actor_type,
        "actor_id": actor_id,
        "agent": actor_id,  # compat with older has_subagent_receipt
        "action_id": action_id,
        "workflow_spec_hash": workflow_spec_hash,
        "input_hashes": dict(input_hashes or {}),
        "output_hashes": dict(output_hashes or {}),
        "checker_result": dict(checker_result or {}),
        "artifact": artifact,
        "issued_by": "harness",
        "recorded_at": _now(),
    }
    _dump(path, payload)
    append_event(
        project_root,
        {"type": "receipt_issued", "identity": identity, "actor_id": actor_id, "action_id": action_id},
        run_id=run_id,
    )
    return path


def write_subagent_receipt(
    project_root: Path,
    *,
    identity: str,
    agent: str,
    artifact: str,
    actor_type: str = "producer",
    action_id: str = "",
    input_hashes: dict[str, str] | None = None,
    output_hashes: dict[str, str] | None = None,
    checker_result: dict[str, Any] | None = None,
) -> Path:
    """Compat wrapper — always routes through issue_receipt."""
    return issue_receipt(
        project_root,
        actor_type=actor_type,
        actor_id=agent,
        action_id=action_id or "subagent",
        input_hashes=input_hashes,
        output_hashes=output_hashes,
        checker_result=checker_result,
        identity=identity,
        artifact=artifact,
    )


def has_subagent_receipt(
    project_root: Path,
    *,
    agent: str | None = None,
    identity_prefix: str = "",
    require_harness_issued: bool = True,
) -> bool:
    state = _load_state(project_root)
    run_id = str(state.get("run_id") or "")
    if not run_id:
        return False
    base = runs_root(project_root) / run_id / "subagents"
    if not base.is_dir():
        return False
    for path in base.glob("*.yaml"):
        data = _load(path)
        if require_harness_issued and str(data.get("issued_by") or "") != "harness":
            # Accept legacy receipts that lack issued_by only when hashes present
            if not data.get("output_hashes") and not data.get("input_hashes"):
                continue
        if agent and str(data.get("agent") or data.get("actor_id") or "") != agent:
            continue
        if identity_prefix and not str(data.get("identity") or "").startswith(identity_prefix):
            continue
        return True
    return False


def semantic_progress_fingerprint(state: dict[str, Any]) -> dict[str, Any]:
    """Semantic sets only — file hash jitter is not progress."""
    open_ids = sorted(str(it.get("id") or "") for it in (state.get("open_items") or []) if it.get("id"))
    failed = sorted(
        {
            str(g.get("id") or g.get("gate") or "")
            for g in (state.get("failed_gates") or [])
            if isinstance(g, dict) and not g.get("ok", True)
        }
    )
    findings = sorted(str(x) for x in (state.get("error_finding_ids") or []))
    return {
        "open_obligation_ids": open_ids,
        "failed_gate_ids": failed,
        "error_finding_ids": findings,
        "status": state.get("status"),
        "phase": state.get("phase"),
    }


def fingerprint_improved(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """True if semantic debt decreased or closed into human/blocked/failed."""
    if after.get("status") in {"human_required", "blocked", "failed", "passed"} and after.get("status") != before.get(
        "status"
    ):
        return True
    b_open = set(before.get("open_obligation_ids") or [])
    a_open = set(after.get("open_obligation_ids") or [])
    if a_open < b_open:
        return True
    b_fail = set(before.get("failed_gate_ids") or [])
    a_fail = set(after.get("failed_gate_ids") or [])
    if a_fail < b_fail:
        return True
    b_find = set(before.get("error_finding_ids") or [])
    a_find = set(after.get("error_finding_ids") or [])
    if a_find < b_find:
        return True
    return False


# Re-export for older imports
def no_progress_exceeded(project_root: Path, *, limit: int = 3) -> bool:
    from ascendc_harness.state import no_progress_exceeded as _n

    return _n(project_root, limit=limit)


__all__ = [
    "append_event",
    "file_sha256",
    "fingerprint_improved",
    "has_subagent_receipt",
    "issue_receipt",
    "no_progress_exceeded",
    "run_dir",
    "semantic_progress_fingerprint",
    "write_subagent_receipt",
]
