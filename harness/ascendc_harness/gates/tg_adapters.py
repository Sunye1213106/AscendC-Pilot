"""TG gate adapters — wrap testcase_agent validators; never invent shallow file checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_harness.paths import tg_root, uo_root


def _load(path: Path) -> Any:
    if yaml is None or not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _op_name(project_root: Path) -> str:
    """Best-effort op name for TG APIs that still require it."""
    uo = uo_root(project_root)
    man = _load(uo / "manifest.yaml")
    if isinstance(man, dict) and man.get("op_name"):
        return str(man["op_name"])
    tg = tg_root(project_root)
    for rel in ("init/status.yaml", "realization/status.yaml"):
        doc = _load(tg / rel)
        if isinstance(doc, dict) and doc.get("op_name"):
            return str(doc["op_name"])
    return project_root.name


def _wrap_exc(gate: str, fn: Any) -> dict[str, Any]:
    try:
        payload = fn()
        if isinstance(payload, dict) and "status" in payload and "ok" not in payload:
            ok = str(payload.get("status") or "").lower() in {"pass", "passed", "ok", "confirmed"}
            return {"gate": gate, "ok": ok, "detail": payload, "message": "ok" if ok else f"{gate} status={payload.get('status')!r}"}
        if isinstance(payload, dict) and "ok" in payload:
            return {"gate": gate, **payload} if payload.get("gate") else {"gate": gate, "ok": bool(payload.get("ok")), "detail": payload}
        return {"gate": gate, "ok": True, "detail": payload if isinstance(payload, dict) else {"result": payload}, "message": "ok"}
    except Exception as exc:  # noqa: BLE001 — domain engines raise typed errors
        ask = getattr(exc, "ask", "") or ""
        payload = getattr(exc, "payload", None) or {}
        return {
            "gate": gate,
            "ok": False,
            "ask": ask,
            "detail": payload if isinstance(payload, dict) else {},
            "message": str(exc)[:400],
        }


def gate_merge_pass(project_root: Path) -> dict[str, Any]:
    out = tg_root(project_root)

    def _run() -> Any:
        from testcase_agent.uo_resolve_merge import require_merge_pass

        return require_merge_pass(out)

    return _wrap_exc("merge_pass", _run)


def gate_domain_symmetry(project_root: Path) -> dict[str, Any]:
    out = tg_root(project_root)

    def _run() -> Any:
        from testcase_agent.uo_resolve_merge import require_domain_symmetry

        return require_domain_symmetry(out)

    return _wrap_exc("domain_symmetry", _run)


def gate_csv_closure(project_root: Path) -> dict[str, Any]:
    out = tg_root(project_root)

    def _run() -> Any:
        from testcase_agent.resolve_policy import require_full_csv_closure

        return require_full_csv_closure(out)

    result = _wrap_exc("csv_closure", _run)
    detail = result.get("detail") if isinstance(result.get("detail"), dict) else {}
    if detail and "status" in detail:
        ok = str(detail.get("status") or "").lower() in {"pass", "passed", "ok"}
        result["ok"] = ok
        result["message"] = "ok" if ok else f"csv_closure status={detail.get('status')!r}"
    return result


def gate_audit_pass(project_root: Path) -> dict[str, Any]:
    out = tg_root(project_root)
    doc = _load(out / "init" / "audit_report.yaml") or {}
    if not isinstance(doc, dict) or not doc:
        return {"gate": "audit_pass", "ok": False, "message": "init/audit_report.yaml missing"}
    status = str(doc.get("status") or "").lower()
    ok = status in {"pass", "passed", "ok"}
    # Prefer engine private checklist when available
    try:
        from testcase_agent.init_status import AUDIT_CHECKLIST_IDS  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        try:
            from testcase_agent.resolve_policy import AUDIT_CHECKLIST_IDS
        except Exception:  # noqa: BLE001
            AUDIT_CHECKLIST_IDS = ()  # type: ignore[misc, assignment]
    checked = doc.get("checked_ids") or doc.get("checklist") or []
    if AUDIT_CHECKLIST_IDS and isinstance(checked, list) and checked:
        missing = [x for x in AUDIT_CHECKLIST_IDS if x not in checked]
        if missing:
            ok = False
    return {
        "gate": "audit_pass",
        "ok": ok,
        "status": status,
        "message": "ok" if ok else f"audit status={status!r}",
    }


def gate_kb_fingerprint_fresh(project_root: Path, *, op_name: str | None = None) -> dict[str, Any]:
    name = op_name or _op_name(project_root)
    out = tg_root(project_root)

    def _run() -> Any:
        from testcase_agent.init_status import require_kb_fingerprint_fresh

        return require_kb_fingerprint_fresh(project_root, name, out_root=out)

    return _wrap_exc("kb_fingerprint_fresh", _run)


def gate_kb_fingerprint_matches(project_root: Path) -> dict[str, Any]:
    out = tg_root(project_root)
    uo = uo_root(project_root)

    def _run() -> Any:
        from testcase_agent.isolation import kb_fingerprint_matches

        matched, detail = kb_fingerprint_matches(out, uo)
        return {"ok": bool(matched), "matched": matched, **(detail if isinstance(detail, dict) else {"detail": detail})}

    return _wrap_exc("kb_fingerprint", _run)


def gate_init_confirmed(project_root: Path, *, op_name: str | None = None) -> dict[str, Any]:
    name = op_name or _op_name(project_root)

    def _run() -> Any:
        from testcase_agent.init_status import require_init_confirmed

        return require_init_confirmed(project_root, name)

    return _wrap_exc("init_confirmed", _run)


def gate_plan_approved(project_root: Path, *, level: str = "") -> dict[str, Any]:
    """Read plan/levels/<L>/human_supplement.yaml — not plan/status.yaml."""
    out = tg_root(project_root)
    try:
        from testcase_agent.io import resolve_plan_dir

        plan_dir = resolve_plan_dir(out, level)
    except Exception as exc:  # noqa: BLE001
        # Fallback: scan levels/*/human_supplement.yaml
        levels = sorted((out / "plan" / "levels").glob("*/human_supplement.yaml")) if (out / "plan" / "levels").is_dir() else []
        if not levels:
            return {
                "gate": "plan_approved",
                "ok": False,
                "message": f"plan level unresolved: {exc}",
            }
        plan_dir = levels[-1].parent

    supplement = _load(plan_dir / "human_supplement.yaml") or {}
    unresolved = _load(plan_dir / "unresolved.yaml") or {}
    if not isinstance(supplement, dict):
        supplement = {}
    if not isinstance(unresolved, dict):
        unresolved = {}

    status = str(supplement.get("status") or "").lower()
    decision = str(supplement.get("decision") or "").lower()
    approved = status in {"approved", "pass", "ok"} or decision in {"approve", "approved"}
    allow = unresolved.get("allow_solve")
    if allow is False:
        approved = False
    has_hash = bool(supplement.get("approved_snapshot_hash") or supplement.get("approved_plan_hash"))
    if approved and not has_hash:
        # Soft warn: approve without hash is incomplete for solve
        pass
    return {
        "gate": "plan_approved",
        "ok": bool(approved and allow is not False),
        "status": status or decision,
        "allow_solve": allow,
        "plan_dir": plan_dir.as_posix(),
        "message": (
            "ok"
            if approved and allow is not False
            else f"plan not approved (status={status!r}, decision={decision!r}, allow_solve={allow!r})"
        ),
    }


def gate_allow_solve(project_root: Path, *, level: str = "") -> dict[str, Any]:
    out = tg_root(project_root)
    try:
        from testcase_agent.io import resolve_plan_dir

        plan_dir = resolve_plan_dir(out, level)
    except Exception as exc:  # noqa: BLE001
        return {"gate": "allow_solve", "ok": False, "message": str(exc)[:300]}
    unresolved = _load(plan_dir / "unresolved.yaml") or {}
    allow = unresolved.get("allow_solve") if isinstance(unresolved, dict) else None
    ok = allow is True
    return {
        "gate": "allow_solve",
        "ok": ok,
        "allow_solve": allow,
        "reason": (unresolved or {}).get("allow_solve_reason") if isinstance(unresolved, dict) else "",
        "message": "ok" if ok else f"allow_solve={allow!r}",
    }


def gate_solve_terminal(project_root: Path) -> dict[str, Any]:
    out = tg_root(project_root)
    for rel in (
        "solve/status.yaml",
        "solve/latest/status.yaml",
        "realization/solve_status.yaml",
    ):
        doc = _load(out / rel)
        if isinstance(doc, dict) and doc:
            status = str(doc.get("status") or "").lower()
            ok = status in {"pass", "passed", "ok", "done", "complete", "completed"}
            return {
                "gate": "solve_terminal",
                "ok": ok,
                "status": status,
                "path": (out / rel).as_posix(),
                "message": "ok" if ok else f"solve status={status!r}",
            }
    return {"gate": "solve_terminal", "ok": False, "message": "solve status artifact missing"}
