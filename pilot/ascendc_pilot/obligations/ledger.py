"""Persistent Obligation Ledger with monotonic state transitions.

States: open → candidate → verified  |  open → blocked
Verified can only be written by the harness (recorded gate pass / settle).
Untrusted domain status strings are never sufficient to create VERIFIED state.
Illegal transitions require an explicit ``reverted_by`` record.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.paths import state_root

LEDGER_FILENAME = "obligation_ledger.yaml"
LEDGER_VERSION = 1

# Monotonic forward edges. Anything else needs explicit revert metadata.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"candidate", "verified", "blocked"}),
    "candidate": frozenset({"verified", "blocked"}),
    "blocked": frozenset({"open", "candidate"}),  # unblock → resume
    "verified": frozenset(),  # terminal unless explicit revert
}

LEDGER_STATUSES = frozenset({"open", "candidate", "verified", "blocked"})


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ledger_path(project_root: Path) -> Path:
    return state_root(project_root) / LEDGER_FILENAME


def _empty_ledger(workflow_id: str = "") -> dict[str, Any]:
    return {
        "version": LEDGER_VERSION,
        "workflow_id": workflow_id,
        "updated_at": _now(),
        "items": {},
        "history": [],
    }


def load_ledger(project_root: Path) -> dict[str, Any]:
    path = ledger_path(project_root)
    if yaml is None or not path.is_file():
        return _empty_ledger()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return _empty_ledger()
    data.setdefault("version", LEDGER_VERSION)
    data.setdefault("items", {})
    data.setdefault("history", [])
    if not isinstance(data["items"], dict):
        data["items"] = {}
    if not isinstance(data["history"], list):
        data["history"] = []
    return data


def save_ledger(project_root: Path, ledger: dict[str, Any]) -> Path:
    path = ledger_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = _now()
    if yaml is not None:
        path.write_text(
            yaml.safe_dump(ledger, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return path


def _normalize_ledger_status(raw: str) -> str:
    s = (raw or "open").strip().lower()
    aliases = {
        "unresolved": "open",
        "pending": "open",
        "in_progress": "candidate",
        "ready_for_llm": "candidate",
        "resolved": "verified",
        "pass": "verified",
        "passed": "verified",
        "accepted": "verified",
        "ok": "verified",
        "closed": "verified",
        "done": "verified",
        "failed": "blocked",
        "error": "blocked",
        "": "open",
    }
    if s in LEDGER_STATUSES:
        return s
    return aliases.get(s, "open" if s not in LEDGER_STATUSES else s)


def can_transition(from_status: str, to_status: str) -> bool:
    a = _normalize_ledger_status(from_status)
    b = _normalize_ledger_status(to_status)
    if a == b:
        return True
    return b in ALLOWED_TRANSITIONS.get(a, frozenset())


def _verification_evidence_matches_gate(
    settled_by_gate: str | None,
    evidence: list[dict[str, Any]] | None,
) -> bool:
    """A verified row must carry evidence bound to the gate that settled it."""
    gate = str(settled_by_gate or "").strip()
    if not gate:
        return False
    for ev in evidence or []:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("gate_id") or "").strip() != gate:
            continue
        if ev.get("receipt_path") or ev.get("run_id") or ev.get("artifact_sha256"):
            return True
    return False


def _append_history(
    ledger: dict[str, Any],
    *,
    oid: str,
    from_status: str,
    to_status: str,
    reason: str,
    evidence: list[dict[str, Any]] | None = None,
    reverted_by: str | None = None,
) -> None:
    hist = list(ledger.get("history") or [])
    entry: dict[str, Any] = {
        "at": _now(),
        "id": oid,
        "from": from_status,
        "to": to_status,
        "reason": reason,
    }
    if evidence:
        entry["evidence"] = evidence
    if reverted_by:
        entry["reverted_by"] = reverted_by
    hist.append(entry)
    # Cap history to keep YAML small.
    ledger["history"] = hist[-500:]


def upsert_item(
    ledger: dict[str, Any],
    *,
    oid: str,
    status: str,
    kind: str = "static",
    label_zh: str = "",
    settled_by_gate: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
    reason: str = "sync",
    allow_revert: bool = False,
    reverted_by: str | None = None,
    verified_by_harness: bool = False,
) -> dict[str, Any]:
    """Insert or transition one ledger item.

    ``verified_by_harness`` is intentionally explicit. A caller that merely
    observed a domain status such as ``pass``/``done``/``resolved`` cannot
    settle the persistent ledger. VERIFIED additionally requires gate-bound
    evidence; otherwise the request is downgraded to ``candidate``.
    """
    items = ledger.setdefault("items", {})
    assert isinstance(items, dict)
    target = _normalize_ledger_status(status)
    if target == "verified" and not (
        verified_by_harness and _verification_evidence_matches_gate(settled_by_gate, evidence)
    ):
        target = "candidate"
        reason = f"unverified_claim:{reason}"
        settled_by_gate = None
    prev = items.get(oid)
    if not isinstance(prev, dict):
        row = {
            "id": oid,
            "kind": kind,
            "label_zh": label_zh or oid,
            "status": target,
            "settled_by_gate": settled_by_gate,
            "evidence": list(evidence or []) if target == "verified" else [],
            "updated_at": _now(),
        }
        items[oid] = row
        _append_history(
            ledger,
            oid=oid,
            from_status="(new)",
            to_status=target,
            reason=reason,
            evidence=evidence if target == "verified" else None,
        )
        return row

    from_status = _normalize_ledger_status(str(prev.get("status") or "open"))
    if from_status == target:
        # Refresh metadata without a transition. Do not attach verification
        # metadata to non-verified rows.
        if target == "verified" and settled_by_gate:
            prev["settled_by_gate"] = settled_by_gate
        if target == "verified" and evidence:
            prev["evidence"] = list(evidence)
        if label_zh:
            prev["label_zh"] = label_zh
        prev["updated_at"] = _now()
        return prev

    if not can_transition(from_status, target):
        if not allow_revert:
            # Keep previous status; record refused transition.
            _append_history(
                ledger,
                oid=oid,
                from_status=from_status,
                to_status=target,
                reason=f"refused:{reason}",
                evidence=evidence if target == "verified" else None,
            )
            return prev
        # Explicit revert path (e.g. gate rolled back).
        prev["status"] = target
        prev["reverted_by"] = reverted_by or reason
        prev["updated_at"] = _now()
        if target == "verified" and settled_by_gate is not None:
            prev["settled_by_gate"] = settled_by_gate
        elif target != "verified":
            prev["settled_by_gate"] = None
        if target == "verified" and evidence:
            prev["evidence"] = list(evidence)
        elif target != "verified":
            prev["evidence"] = []
        _append_history(
            ledger,
            oid=oid,
            from_status=from_status,
            to_status=target,
            reason=reason,
            evidence=evidence if target == "verified" else None,
            reverted_by=prev["reverted_by"],
        )
        return prev

    prev["status"] = target
    prev["updated_at"] = _now()
    if target == "verified" and settled_by_gate is not None:
        prev["settled_by_gate"] = settled_by_gate
    elif target != "verified":
        prev["settled_by_gate"] = None
    if target == "verified" and evidence:
        # Append evidence pointers (dedupe by receipt_path+gate_id+run_id).
        existing = list(prev.get("evidence") or [])
        seen = {
            (str(e.get("receipt_path") or ""), str(e.get("gate_id") or ""), str(e.get("run_id") or ""))
            for e in existing
            if isinstance(e, dict)
        }
        for e in evidence:
            if not isinstance(e, dict):
                continue
            key = (str(e.get("receipt_path") or ""), str(e.get("gate_id") or ""), str(e.get("run_id") or ""))
            if key not in seen:
                existing.append(e)
                seen.add(key)
        prev["evidence"] = existing
    elif target != "verified":
        prev["evidence"] = []
    if label_zh:
        prev["label_zh"] = label_zh
    _append_history(
        ledger,
        oid=oid,
        from_status=from_status,
        to_status=target,
        reason=reason,
        evidence=evidence if target == "verified" else None,
    )
    return prev


def map_collect_status_to_ledger(status: str) -> str:
    """Map collect_obligations statuses onto ledger vocabulary."""
    return _normalize_ledger_status(status)


def sync_from_collected(
    project_root: Path,
    workflow_id: str,
    collected: list[dict[str, Any]],
    *,
    run_id: str = "",
) -> dict[str, Any]:
    """Merge freshly collected obligations into the persistent ledger.

    A collected row may request VERIFIED only when it names a gate that is
    already present in Pilot ``passed_gates``. Other closed-looking domain
    statuses are retained as ``candidate`` until a verifier/gate settles them.
    If a previously settling gate disappears, the row is explicitly reverted.
    """
    from ascendc_pilot.state import load_state

    ledger = load_ledger(project_root)
    prev_wid = str(ledger.get("workflow_id") or "").strip()
    ledger["workflow_id"] = workflow_id
    derived_ids = {str(row.get("id") or "") for row in collected if row.get("id")}
    if prev_wid and prev_wid != workflow_id:
        items = ledger.get("items") or {}
        if isinstance(items, dict):
            for oid in list(items):
                if oid in derived_ids:
                    continue
                prev = items.pop(oid)
                st = ""
                if isinstance(prev, dict):
                    st = str(prev.get("status") or "")
                ledger.setdefault("history", []).append(
                    {
                        "at": _now(),
                        "id": oid,
                        "from": st or "(item)",
                        "to": "(dropped)",
                        "reason": "workflow_switch",
                    }
                )
    state = load_state(project_root) if project_root else {}
    passed_gates = set(state.get("passed_gates") or []) if isinstance(state, dict) else set()

    for row in collected:
        oid = str(row.get("id") or "")
        if not oid:
            continue
        status = map_collect_status_to_ledger(str(row.get("status") or "open"))
        gate = str(row.get("settled_by_gate") or "").strip()
        harness_verified = bool(status == "verified" and gate and gate in passed_gates)
        if status == "verified" and not harness_verified:
            status = "candidate"
        evidence: list[dict[str, Any]] = []
        if harness_verified:
            evidence.append(
                {
                    "gate_id": gate,
                    "run_id": run_id or str((state or {}).get("run_id") or ""),
                    "receipt_path": "",  # filled by callers when known
                }
            )

        prev = (ledger.get("items") or {}).get(oid)
        if isinstance(prev, dict) and _normalize_ledger_status(str(prev.get("status"))) == "verified":
            # Revert only if settling gate is no longer in passed_gates.
            settle = str(prev.get("settled_by_gate") or gate or "")
            if settle and settle not in passed_gates and status != "verified":
                upsert_item(
                    ledger,
                    oid=oid,
                    status=status,
                    kind=str(row.get("kind") or "static"),
                    label_zh=str(row.get("label_zh") or oid),
                    settled_by_gate=gate or None,
                    evidence=evidence or None,
                    reason="gate_absent_revert",
                    allow_revert=True,
                    reverted_by=f"gate:{settle}",
                )
            # else keep verified
            continue

        upsert_item(
            ledger,
            oid=oid,
            status=status,
            kind=str(row.get("kind") or "static"),
            label_zh=str(row.get("label_zh") or oid),
            settled_by_gate=gate or None,
            evidence=evidence or None,
            reason="collect_sync",
            verified_by_harness=harness_verified,
        )

    save_ledger(project_root, ledger)
    return ledger


def view_as_collect_items(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Project ledger items into the collect_obligations row shape."""
    # Map ledger status back to CLOSED_OBLIGATION vocabulary for open checks.
    status_out = {
        "open": "open",
        "candidate": "in_progress",
        "verified": "verified",
        "blocked": "blocked",
    }
    out: list[dict[str, Any]] = []
    items = ledger.get("items") or {}
    if not isinstance(items, dict):
        return out
    for oid, row in items.items():
        if not isinstance(row, dict):
            continue
        st = _normalize_ledger_status(str(row.get("status") or "open"))
        out.append(
            {
                "id": oid,
                "kind": row.get("kind") or "static",
                "label_zh": row.get("label_zh") or oid,
                "status": status_out.get(st, st),
                "settled_by_gate": row.get("settled_by_gate"),
                "evidence": list(row.get("evidence") or []),
                "ledger_status": st,
            }
        )
    return out


def validate_ledger(ledger: dict[str, Any]) -> list[str]:
    """Return human-readable errors for CI / check script."""
    errors: list[str] = []
    if int(ledger.get("version") or 0) != LEDGER_VERSION:
        errors.append(f"unexpected version {ledger.get('version')}")
    items = ledger.get("items") or {}
    if not isinstance(items, dict):
        errors.append("items must be a mapping")
        return errors
    for oid, row in items.items():
        if not isinstance(row, dict):
            errors.append(f"{oid}: item not a mapping")
            continue
        st = str(row.get("status") or "")
        if st not in LEDGER_STATUSES:
            errors.append(f"{oid}: invalid status {st!r}")
        evidence = list(row.get("evidence") or [])
        for ev in evidence:
            if not isinstance(ev, dict):
                errors.append(f"{oid}: evidence entry not a mapping")
        if st == "verified":
            gate = str(row.get("settled_by_gate") or "").strip()
            if not gate:
                errors.append(f"{oid}: verified item lacks settled_by_gate")
            if not _verification_evidence_matches_gate(gate, evidence):
                errors.append(f"{oid}: verified item lacks gate-bound evidence")
    # History transitions must be legal or marked reverted/refused.
    for i, h in enumerate(ledger.get("history") or []):
        if not isinstance(h, dict):
            errors.append(f"history[{i}]: not a mapping")
            continue
        fr, to = str(h.get("from") or ""), str(h.get("to") or "")
        reason = str(h.get("reason") or "")
        if fr == "(new)" or reason.startswith("refused:") or reason.startswith("unverified_claim:"):
            continue
        if h.get("reverted_by"):
            continue
        if fr in LEDGER_STATUSES and to in LEDGER_STATUSES and not can_transition(fr, to):
            errors.append(f"history[{i}]: illegal transition {fr}->{to} without reverted_by")
    return errors
