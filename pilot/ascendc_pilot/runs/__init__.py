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

from ascendc_pilot.paths import AGENT_DIR, STATE_SUBDIR, ensure_agent_layout, runs_root


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
    from ascendc_pilot.state import load_state

    return load_state(project_root)


def hmac_key_path(project_root: Path) -> Path:
    """Arch-neutral HMAC key: ``.ascendc-pilot/control/pilot_hmac.key``.

    Intake receipts (architecture / project / resume) are signed before any
    ``<arch>/`` tree exists. The key must not live under arch-scoped ``state/``.
    """
    from ascendc_pilot.active_run import control_root

    return control_root(project_root) / "pilot_hmac.key"


def get_or_create_hmac_key(project_root: Path) -> bytes:
    """Load or create per-project HMAC key on the arch-neutral control plane."""
    path = hmac_key_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return path.read_bytes()
    root = Path(project_root).expanduser().resolve() / AGENT_DIR
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name == "control":
                continue
            legacy = child / STATE_SUBDIR / "pilot_hmac.key"
            if legacy.is_file():
                data = legacy.read_bytes()
                if data:
                    path.write_bytes(data)
                    try:
                        path.chmod(0o600)
                    except OSError:
                        pass
                    return data
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


def receipts_dir(project_root: Path, run_id: str | None = None) -> Path:
    """Run-scoped receipts (gate proofs), not long-lived TG/CE products."""
    path = run_dir(project_root, run_id) / "receipts"
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


def _sha256_json(value: Any) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def slim_checker_result_for_receipt(checker_result: dict[str, Any] | None) -> dict[str, Any]:
    """Keep receipt checker_result small: ok + summaries/hashes, never full engine blobs.

    Full engine/apply payloads belong in session artifacts / IR; embedding them in
    HMAC-signed receipts makes every ``acp next`` verify path O(blob size).
    """
    raw = dict(checker_result or {})
    if not raw:
        return {}

    def _gate_row(g: Any) -> dict[str, Any]:
        if not isinstance(g, dict):
            return {"ok": bool(g)}
        return {
            "id": str(g.get("id") or g.get("gate") or g.get("name") or ""),
            "ok": bool(g.get("ok", True)),
            "error": str(g.get("error") or g.get("reason_code") or "")[:120],
        }

    gates_in = raw.get("gates")
    gates_out: list[dict[str, Any]] = []
    if isinstance(gates_in, list):
        gates_out = [_gate_row(g) for g in gates_in[:32]]

    contract = raw.get("output_contract") if isinstance(raw.get("output_contract"), dict) else {}
    engine = raw.get("engine") if isinstance(raw.get("engine"), dict) else {}
    apply = raw.get("apply") if isinstance(raw.get("apply"), dict) else {}
    identity_injection = (
        raw.get("identity_injection") if isinstance(raw.get("identity_injection"), dict) else {}
    )
    producer_identity = (
        raw.get("producer_identity") if isinstance(raw.get("producer_identity"), dict) else {}
    )
    target_violation = (
        raw.get("target_violation") if isinstance(raw.get("target_violation"), dict) else {}
    )

    engine_summary: dict[str, Any] = {}
    if engine:
        engine_summary = {
            "ok": bool(engine.get("ok", True)),
            "engine": str(engine.get("engine") or ""),
            "checkpoint": str(engine.get("checkpoint") or ""),
            "payload_sha256": _sha256_json(engine),
        }
        for key in ("tasks", "closed_pre_tasks", "triage", "report"):
            if key in engine:
                engine_summary[f"{key}_sha256"] = _sha256_json(engine.get(key))

    apply_summary: dict[str, Any] = {}
    if apply:
        apply_summary = {
            "ok": bool(apply.get("ok", True)),
            "payload_sha256": _sha256_json(apply),
        }

    return {
        "ok": bool(raw.get("ok")),
        "schema": "receipt_checker_v1",
        "full_checker_sha256": _sha256_json(raw),
        "producer_identity": {
            "ok": bool(producer_identity.get("ok", True)),
            "error": str(producer_identity.get("error") or "")[:120],
        }
        if producer_identity
        else {},
        "identity_injection": {
            "ok": bool(identity_injection.get("ok", True)),
            "skipped": bool(identity_injection.get("skipped", False)),
            "error": str(identity_injection.get("error") or "")[:120],
        }
        if identity_injection
        else {},
        "gates": gates_out,
        "output_contract": {
            "ok": bool(contract.get("ok", True)),
            "skipped": bool(contract.get("skipped", False)),
            "error": str(contract.get("error") or "")[:120],
            "contract_id": str(contract.get("contract_id") or ""),
        }
        if contract
        else {},
        "engine": engine_summary,
        "apply": apply_summary,
        "target_violation": {
            "ok": bool(target_violation.get("ok", True)) if target_violation else True,
            "error": str(target_violation.get("error") or "")[:120],
        }
        if target_violation
        else {},
    }


def _receipt_paths_for_action(base: Path, action_id: str = "") -> list[Path]:
    """Prefer filename filter when action_id known (identity = run:action:actor).

    When ``action_id`` is set and no filename matches, return empty — never fall
    back to scanning every receipt (that made ``acp next`` O(all fat receipts)
    for each incomplete pipeline step).
    """
    if not base.is_dir():
        return []
    aid = str(action_id or "").strip()
    if aid:
        # Filename is `{run}_{action}_{actor}.yaml` after ':' → '_'
        return sorted({*base.glob(f"*_{aid}_*.yaml"), *base.glob(f"*_{aid}.yaml")})
    return sorted(base.glob("*.yaml"))


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
    """Issue an HMAC-signed receipt. Only callable from acp run-action finalize.

    External callers must finalize through the action runtime; receipts are private.
    ``checker_result`` is always slimmed before signing (full blobs stay in session/IR).
    """
    if not _internal:
        raise RuntimeError(
            "issue_receipt is private; Host `pilot_run` holds finalize"
        )
    state = _load_state(project_root)
    run_id = str(state.get("run_id") or "NO_RUN")
    identity = identity or f"{run_id}:{action_id}:{actor_id}"
    safe = identity.replace(":", "_").replace("/", "_")
    path = run_dir(project_root, run_id) / "subagents" / f"{safe}.yaml"
    checker = slim_checker_result_for_receipt(
        checker_result if isinstance(checker_result, dict) else {}
    )
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
        "issued_by": "pilot",
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


def _maybe_compact_bloated_receipt(
    project_root: Path, path: Path, data: dict[str, Any]
) -> dict[str, Any]:
    """Rewrite legacy fat receipts to slim checker_result + resign (once).

    Old finalize embedded full engine.report into HMAC receipts (~100KB–1MB),
    making every subsequent verify dominate ``acp next``. Compaction preserves
    identity/hashes and re-signs with the project HMAC key.
    """
    checker = data.get("checker_result")
    if not isinstance(checker, dict) or checker.get("schema") == "receipt_checker_v1":
        return data
    try:
        approx = len(json.dumps(checker, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        approx = 0
    if approx < 8192:
        return data
    slim = slim_checker_result_for_receipt(checker)
    payload = {k: v for k, v in data.items() if k not in {"signature", "_path"}}
    payload["checker_result"] = slim
    payload["signature"] = sign_receipt_payload(project_root, payload)
    try:
        _dump(path, payload)
    except Exception:  # noqa: BLE001
        return data
    payload["_path"] = data.get("_path") or path.as_posix()
    return payload


_VERIFY_RESULT_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def invalidate_action_receipts(
    project_root: Path, *, action_id: str, run_id: str = ""
) -> int:
    """Drop signed receipts for an action so the pipeline can re-run that step."""
    state = _load_state(project_root)
    rid = str(run_id or state.get("run_id") or "").strip()
    aid = str(action_id or "").strip()
    if not rid or not aid:
        return 0
    base = runs_root(project_root) / rid / "subagents"
    dropped = 0
    for path in _receipt_paths_for_action(base, aid):
        try:
            path.unlink()
            dropped += 1
        except OSError:
            continue
    dead = [
        key
        for key in list(_VERIFY_RESULT_CACHE)
        if len(key) >= 3 and str(key[1]) == rid and str(key[2]) == aid
    ]
    for key in dead:
        _VERIFY_RESULT_CACHE.pop(key, None)
    return dropped


def _verify_cache_key(
    project_root: Path,
    *,
    run_id: str,
    action_id: str,
    path: Path,
    actor_id: str,
    require_checker_ok: bool,
    require_spec_hash: bool,
) -> tuple[Any, ...] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (
        str(Path(project_root).resolve()),
        run_id,
        action_id,
        actor_id,
        require_checker_ok,
        require_spec_hash,
        int(st.st_mtime_ns),
        int(st.st_size),
    )


def verify_receipt(
    project_root: Path,
    *,
    actor_id: str = "",
    actor_type: str = "",
    action_id: str = "",
    identity_prefix: str = "",
    expected_input_hashes: dict[str, str] | None = None,
    expected_output_hashes: dict[str, str] | None = None,
    require_pilot_issued: bool = True,
    require_hashes: bool = True,
    require_action_id: bool = True,
    require_spec_hash: bool = True,
    require_checker_result: bool = False,
    require_signature: bool = True,
    require_checker_ok: bool = False,
) -> dict[str, Any]:
    """Strictly verify a Pilot-issued receipt for the current run.

    Checks: HMAC signature, run_id, actor, action_id, input/output hashes,
    checker_result, workflow_spec_hash, issued_by=acp.
    File existence alone is not enough.

    Performance: when ``action_id`` is set, only matching receipt files are loaded;
    missing action_id never scans siblings; cheap identity filters run before HMAC;
    successful verifies are cached by (path mtime/size) within the process.
    """
    state = _load_state(project_root)
    run_id = str(state.get("run_id") or "")
    if not run_id:
        return {"ok": False, "reason_code": "NO_RUN", "message": "no active run_id"}

    base = runs_root(project_root) / run_id / "subagents"
    if not base.is_dir():
        return {"ok": False, "reason_code": "NO_RECEIPTS_DIR", "message": "subagents receipt dir missing"}

    # Fast path: single matching receipt + no hash overrides → process cache
    can_cache = (
        bool(action_id)
        and not expected_input_hashes
        and not expected_output_hashes
        and not identity_prefix
        and not actor_type
        and require_pilot_issued
        and require_hashes
        and require_action_id
        and require_signature
    )
    paths = _receipt_paths_for_action(base, action_id)
    if not paths:
        return {"ok": False, "reason_code": "NO_RECEIPT", "message": "no receipt files"}

    if can_cache and len(paths) == 1:
        ck = _verify_cache_key(
            project_root,
            run_id=run_id,
            action_id=action_id,
            path=paths[0],
            actor_id=actor_id,
            require_checker_ok=require_checker_ok,
            require_spec_hash=require_spec_hash,
        )
        if ck is not None and ck in _VERIFY_RESULT_CACHE:
            return dict(_VERIFY_RESULT_CACHE[ck])

    expected_wf_hash = ""
    if require_spec_hash:
        try:
            from ascendc_pilot.spec_hashes import workflow_spec_hash

            wid = str(state.get("workflow_id") or "")
            expected_wf_hash = workflow_spec_hash(wid) if wid else workflow_spec_hash()
        except Exception:  # noqa: BLE001
            expected_wf_hash = ""

    errors: list[str] = []
    for path in paths:
        data = _load(path)
        if not data:
            continue
        data["_path"] = path.as_posix()

        # Cheap filters BEFORE HMAC (legacy receipts can be hundreds of KB).
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
        if require_pilot_issued and str(data.get("issued_by") or "") != "pilot":
            errors.append(f"{data.get('_path')}: issued_by!=acp")
            continue

        if require_signature and not verify_receipt_signature(project_root, data):
            errors.append(f"{data.get('_path')}: invalid or missing HMAC signature")
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

        # Migrate bloated legacy receipts after they pass verify (rewrite+resign once).
        data = _maybe_compact_bloated_receipt(project_root, path, data)
        rid_actor = str(data.get("actor_id") or data.get("agent") or rid_actor)
        rid_action = str(data.get("action_id") or rid_action)

        result = {
            "ok": True,
            "receipt": {k: v for k, v in data.items() if k != "_path"},
            "path": data.get("_path"),
            "run_id": run_id,
            "actor_id": rid_actor,
            "action_id": rid_action,
            "workflow_spec_hash": data.get("workflow_spec_hash"),
        }
        if can_cache:
            ck = _verify_cache_key(
                project_root,
                run_id=run_id,
                action_id=rid_action,
                path=path,
                actor_id=actor_id,
                require_checker_ok=require_checker_ok,
                require_spec_hash=require_spec_hash,
            )
            if ck is not None:
                _VERIFY_RESULT_CACHE[ck] = dict(result)
        return result

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
    from ascendc_pilot.state import no_progress_exceeded as _n

    return _n(project_root, limit=limit)


__all__ = [
    "append_event",
    "file_sha256",
    "fingerprint_improved",
    "get_or_create_hmac_key",
    "issue_receipt",
    "invalidate_action_receipts",
    "no_progress_exceeded",
    "run_dir",
    "semantic_progress_fingerprint",
    "sign_receipt_payload",
    "slim_checker_result_for_receipt",
    "verify_receipt",
    "verify_receipt_signature",
]
