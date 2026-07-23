"""Run receipts, event log, and progress helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_harness.paths import ensure_agent_layout, runs_root, state_root


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


def hmac_key_path(project_root: Path) -> Path:
    return state_root(project_root) / "harness_hmac.key"


def get_or_create_hmac_key(project_root: Path) -> bytes:
    """Load or create per-project HMAC key under private harness state."""
    ensure_agent_layout(project_root)
    path = hmac_key_path(project_root)
    if path.is_file():
        return path.read_bytes()
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def _canonical_receipt_bytes(payload: dict[str, Any]) -> bytes:
    body = {k: v for k, v in payload.items() if k not in {"signature", "_path"}}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def sign_receipt_payload(project_root: Path, payload: dict[str, Any]) -> str:
    key = get_or_create_hmac_key(project_root)
    return hmac.new(key, _canonical_receipt_bytes(payload), hashlib.sha256).hexdigest()


def verify_receipt_signature(project_root: Path, payload: dict[str, Any]) -> bool:
    sig = str(payload.get("signature") or "")
    if not sig:
        return False
    expected = sign_receipt_payload(project_root, payload)
    return hmac.compare_digest(sig, expected)


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
    nonce: str = "",
    _internal: bool = False,
) -> Path:
    """Issue an HMAC-signed receipt. Only callable from harness run-action finalize.

    External callers must finalize through the action runtime; receipts are private.
    """
    if not _internal:
        raise RuntimeError(
            "issue_receipt is private; use `harness run-action <action_id> --finalize`"
        )
    state = _load_state(project_root)
    run_id = str(state.get("run_id") or "NO_RUN")
    identity = identity or f"{run_id}:{action_id}:{actor_id}"
    safe = identity.replace(":", "_").replace("/", "_")
    path = run_dir(project_root, run_id) / "subagents" / f"{safe}.yaml"
    checker = dict(checker_result or {})
    payload = {
        "identity": identity,
        "run_id": run_id,
        "workflow_id": state.get("workflow_id"),
        "phase": state.get("phase"),
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action_id": action_id,
        "workflow_spec_hash": workflow_spec_hash,
        "input_hashes": dict(input_hashes or {}),
        "output_hashes": dict(output_hashes or {}),
        "checker_result": checker,
        "nonce": nonce or "",
        "artifact": artifact,
        "issued_by": "harness",
        "recorded_at": _now(),
    }
    payload["signature"] = sign_receipt_payload(project_root, payload)
    _dump(path, payload)
    append_event(
        project_root,
        {"type": "receipt_issued", "identity": identity, "actor_id": actor_id, "action_id": action_id},
        run_id=run_id,
    )
    return path


def verify_receipt(
    project_root: Path,
    *,
    actor_id: str = "",
    actor_type: str = "",
    action_id: str = "",
    identity_prefix: str = "",
    expected_input_hashes: dict[str, str] | None = None,
    expected_output_hashes: dict[str, str] | None = None,
    require_harness_issued: bool = True,
    require_hashes: bool = True,
    require_action_id: bool = True,
    require_spec_hash: bool = True,
    require_checker_result: bool = False,
    require_signature: bool = True,
    require_checker_ok: bool = False,
) -> dict[str, Any]:
    """Strictly verify a Harness-issued receipt for the current run.

    Checks: HMAC signature, run_id, actor, action_id, input/output hashes,
    checker_result, workflow_spec_hash, issued_by=harness.
    File existence alone is not enough.
    """
    state = _load_state(project_root)
    run_id = str(state.get("run_id") or "")
    if not run_id:
        return {"ok": False, "reason_code": "NO_RUN", "message": "no active run_id"}

    base = runs_root(project_root) / run_id / "subagents"
    if not base.is_dir():
        return {"ok": False, "reason_code": "NO_RECEIPTS_DIR", "message": "subagents receipt dir missing"}

    expected_wf_hash = ""
    if require_spec_hash:
        try:
            from ascendc_harness.spec_hashes import workflow_spec_hash

            wid = str(state.get("workflow_id") or "")
            expected_wf_hash = workflow_spec_hash(wid) if wid else workflow_spec_hash()
        except Exception:  # noqa: BLE001
            expected_wf_hash = ""

    candidates: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.yaml")):
        data = _load(path)
        if not data:
            continue
        data["_path"] = path.as_posix()
        candidates.append(data)

    if not candidates:
        return {"ok": False, "reason_code": "NO_RECEIPT", "message": "no receipt files"}

    errors: list[str] = []
    for data in candidates:
        if require_harness_issued and str(data.get("issued_by") or "") != "harness":
            errors.append(f"{data.get('_path')}: issued_by!=harness")
            continue
        if require_signature and not verify_receipt_signature(project_root, data):
            errors.append(f"{data.get('_path')}: invalid or missing HMAC signature")
            continue
        if str(data.get("run_id") or "") != run_id:
            errors.append(f"{data.get('_path')}: run_id mismatch")
            continue
        rid_actor = str(data.get("actor_id") or data.get("agent") or "")
        if actor_id and rid_actor != actor_id:
            continue
        if actor_type and str(data.get("actor_type") or "") != actor_type:
            continue
        if identity_prefix and not str(data.get("identity") or "").startswith(identity_prefix):
            continue
        rid_action = str(data.get("action_id") or "")
        if action_id and rid_action != action_id:
            continue
        if require_action_id and not rid_action:
            errors.append(f"{data.get('_path')}: action_id missing")
            continue

        in_h = data.get("input_hashes") if isinstance(data.get("input_hashes"), dict) else {}
        out_h = data.get("output_hashes") if isinstance(data.get("output_hashes"), dict) else {}
        if require_hashes and not in_h and not out_h:
            errors.append(f"{data.get('_path')}: input_hashes/output_hashes empty")
            continue
        if expected_input_hashes:
            mismatch = False
            for k, v in expected_input_hashes.items():
                if str(in_h.get(k) or "") != str(v):
                    errors.append(f"{data.get('_path')}: input_hash {k} mismatch")
                    mismatch = True
                    break
            if mismatch:
                continue
        if expected_output_hashes:
            mismatch = False
            for k, v in expected_output_hashes.items():
                if str(out_h.get(k) or "") != str(v):
                    errors.append(f"{data.get('_path')}: output_hash {k} mismatch")
                    mismatch = True
                    break
            if mismatch:
                continue

        if require_spec_hash:
            got = str(data.get("workflow_spec_hash") or "")
            if not got:
                errors.append(f"{data.get('_path')}: workflow_spec_hash missing")
                continue
            if expected_wf_hash and got != expected_wf_hash:
                errors.append(f"{data.get('_path')}: workflow_spec_hash mismatch")
                continue

        checker = data.get("checker_result")
        if require_checker_result:
            if not isinstance(checker, dict) or not checker:
                errors.append(f"{data.get('_path')}: checker_result missing")
                continue
        if require_checker_ok:
            if not isinstance(checker, dict) or not checker.get("ok"):
                errors.append(f"{data.get('_path')}: checker_result.ok != true")
                continue

        return {
            "ok": True,
            "receipt": {k: v for k, v in data.items() if k != "_path"},
            "path": data.get("_path"),
            "run_id": run_id,
            "actor_id": rid_actor,
            "action_id": rid_action,
            "workflow_spec_hash": data.get("workflow_spec_hash"),
        }

    return {
        "ok": False,
        "reason_code": "RECEIPT_VERIFY_FAILED",
        "message": "no receipt passed strict verification",
        "errors": errors[:12],
        "run_id": run_id,
    }


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
    "get_or_create_hmac_key",
    "issue_receipt",
    "no_progress_exceeded",
    "run_dir",
    "semantic_progress_fingerprint",
    "sign_receipt_payload",
    "verify_receipt",
    "verify_receipt_signature",
]
