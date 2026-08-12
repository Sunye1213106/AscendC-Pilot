"""Static + dynamic obligations normalized from domain artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.paths import tg_root, uo_root
from ascendc_pilot.workflows import get_workflow
from ascendc_pilot.workflows.specs import CLOSED_OBLIGATION_STATUSES, STATIC_OBLIGATION_GATE_MAP

# Statuses that keep an obligation in the open set (must not complete while present).
_OPEN_STATUSES = frozenset(
    {
        "open",
        "unresolved",
        "pending",
        "in_progress",
        "failed",
        "error",
        "ready_for_llm",
        "blocked",
        "",
    }
)

# Acceptable closed aliases from domain YAMLs (normalized to CLOSED set).
_CLOSED_ALIASES = {
    "closed": "resolved",
    "done": "resolved",
    "pass": "verified",
    "passed": "verified",
    "accepted": "verified",
    "ok": "verified",
}


def _load(path: Path) -> Any:
    if yaml is None or not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _normalize_status(raw: str) -> str:
    s = (raw or "open").strip().lower()
    if s in CLOSED_OBLIGATION_STATUSES:
        return s
    if s in _CLOSED_ALIASES:
        return _CLOSED_ALIASES[s]
    return s if s else "open"


def _is_closed(status: str) -> bool:
    return _normalize_status(status) in CLOSED_OBLIGATION_STATUSES


def _gate_passed(project_root: Path, gate_id: str) -> bool:
    """Settle static obligations from ``passed_gates``, with live gate fallback.

    Prefer the harness ledger. If a settling gate was never recorded (older
    prepare without ``scope_receipt`` on the Action/phase gate list), re-check
    the live gate so machine-validated receipts can still close obligations.
    Live fallback does **not** write ``passed_gates`` (complete/advance/finalize
    remain the writers).
    """
    try:
        from ascendc_pilot.state import load_state

        state = load_state(project_root)
        passed = state.get("passed_gates") or []
        if isinstance(passed, list) and gate_id in passed:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        from ascendc_pilot.gates import run_named_gate

        live = run_named_gate(project_root, gate_id)
        return bool(live.get("ok"))
    except Exception:  # noqa: BLE001
        return False


def _settle_static(project_root: Path, row: dict[str, Any]) -> dict[str, Any]:
    oid = str(row["id"])
    gate_id = STATIC_OBLIGATION_GATE_MAP.get(oid, "")
    label = str(row.get("label_zh") or oid)
    if gate_id and _gate_passed(project_root, gate_id):
        return {
            "id": oid,
            "kind": "static",
            "label_zh": label,
            "status": "verified",
            "settled_by_gate": gate_id,
        }
    return {
        "id": oid,
        "kind": "static",
        "label_zh": label,
        "status": "open",
        "settled_by_gate": gate_id or None,
    }


def _items_from_yaml(path: Path) -> list[dict[str, Any]]:
    doc = _load(path)
    out: list[dict[str, Any]] = []
    if not isinstance(doc, dict):
        return out
    items = (
        doc.get("items")
        or doc.get("gaps")
        or doc.get("open")
        or doc.get("obligations")
        or doc.get("uncovered_obligations")
        or []
    )
    if not isinstance(items, list):
        return out
    for it in items:
        if isinstance(it, str):
            out.append(
                {
                    "id": it,
                    "source": path.as_posix(),
                    "kind": "dynamic",
                    "status": "open",
                    "label_zh": it[:120],
                }
            )
            continue
        if not isinstance(it, dict):
            continue
        status = _normalize_status(str(it.get("status") or it.get("state") or "open"))
        kid = str(it.get("id") or it.get("key") or it.get("target") or it.get("obligation_id") or "")
        if not kid:
            continue
        out.append(
            {
                "id": kid,
                "source": path.as_posix(),
                "kind": "dynamic",
                "status": status,
                "label_zh": str(it.get("reason") or it.get("message") or kid)[:120],
            }
        )
    return out


def _collect_obligations_derived(project_root: Path, workflow_id: str) -> list[dict[str, Any]]:
    """Legacy derivation from gates + domain YAML (no ledger I/O)."""
    meta = get_workflow(workflow_id)
    out: list[dict[str, Any]] = []

    for row in meta.get("static_obligations") or []:
        if isinstance(row, dict) and row.get("id"):
            out.append(_settle_static(project_root, row))

    uo = uo_root(project_root)
    tg = tg_root(project_root)
    for rel in meta.get("dynamic_obligation_sources") or []:
        rel_s = str(rel)
        bases = [uo, tg, project_root / ".ascendc-pilot"]
        matched: list[Path] = []
        if "**" in rel_s:
            for base in bases:
                matched.extend(base.glob(rel_s))
        else:
            for base in bases:
                candidate = base / rel_s
                if candidate.is_file():
                    matched.append(candidate)
        for path in matched:
            out.extend(_items_from_yaml(path))

    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for row in out:
        kid = str(row.get("id") or "")
        if not kid or kid in seen:
            continue
        seen.add(kid)
        uniq.append(row)
    return uniq


def collect_obligations(project_root: Path, workflow_id: str) -> list[dict[str, Any]]:
    """Return all obligations with settled status. Open ones must block complete.

    Ledger-first: sync derived items into ``obligation_ledger.yaml``, then
    project ledger rows. On ledger failure, fall back to pure derivation so
    existing callers keep working.
    """
    derived = _collect_obligations_derived(project_root, workflow_id)
    try:
        from ascendc_pilot.obligations.ledger import sync_from_collected, view_as_collect_items
        from ascendc_pilot.state import load_state

        state = load_state(project_root)
        run_id = str(state.get("run_id") or "") if isinstance(state, dict) else ""
        ledger = sync_from_collected(
            project_root, workflow_id, derived, run_id=run_id
        )
        projected = view_as_collect_items(ledger)
        if not projected:
            return derived
        # Preserve any brand-new derived ids that race ahead of ledger write.
        seen = {str(r.get("id") or "") for r in projected}
        for row in derived:
            kid = str(row.get("id") or "")
            if kid and kid not in seen:
                projected.append(row)
        return projected
    except Exception:  # noqa: BLE001 — never break complete_workflow on ledger bugs
        return derived


def open_obligations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Obligations that still block completion (not in CLOSED terminal set)."""
    result: list[dict[str, Any]] = []
    for it in items:
        status = _normalize_status(str(it.get("status") or "open"))
        if status not in CLOSED_OBLIGATION_STATUSES:
            result.append({**it, "status": status if status in _OPEN_STATUSES else "open"})
    return result


def obligation_id_set(items: list[dict[str, Any]]) -> set[str]:
    """IDs of still-open obligations (for entropy / progress fingerprints)."""
    return {str(it.get("id") or "") for it in open_obligations(items) if it.get("id")}


def all_obligations_closed(items: list[dict[str, Any]]) -> bool:
    return len(open_obligations(items)) == 0
