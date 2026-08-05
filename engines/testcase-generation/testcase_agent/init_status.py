"""Init gate: KB presence + init.status confirmed before tg-plan."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import output_root, read_yaml, write_yaml
from .understand import understand_root


class InitGateError(RuntimeError):
    def __init__(self, message: str, *, ask: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.ask = ask
        self.payload = payload or {}


def kb_exists(project_root: Path, op_name: str, kb_root: Path | None = None) -> Path | None:
    """Return understand root if present, else None."""
    if kb_root is not None:
        root = kb_root.expanduser().resolve()
        # New layout
        if root.name == "uo" and root.parent.name == ".ascendc-pilot":
            return root if root.is_dir() else None
        if root.name == ".ascendc-pilot":
            candidate = root / "uo"
            return candidate if candidate.is_dir() else None
        if root.is_dir():
            return root
        return None
    uo = understand_root(project_root, op_name)
    return uo if uo.is_dir() else None


def require_kb(project_root: Path, op_name: str, kb_root: Path | None = None) -> Path:
    found = kb_exists(project_root, op_name, kb_root=kb_root)
    if found is not None:
        return found
    expected = understand_root(project_root, op_name)
    raise InitGateError(
        f"KB missing: {expected}. Run /uo-init to build .ascendc-pilot/uo, then tg-init.",
        ask="uo_init_required",
        payload={
            "expected_kb": expected.as_posix(),
            "hint": "tg-init defaults to <算子仓>/.ascendc-pilot/uo; optional --kb-root only overrides.",
            "next": f"uo-init <算子仓> --op-name {op_name}",
        },
    )


def init_status_path(out_root: Path) -> Path:
    return out_root / "init" / "status.yaml"


def read_init_status(out_root: Path) -> dict[str, Any]:
    path = init_status_path(out_root)
    if not path.is_file():
        return {}
    data = read_yaml(path)
    return data if isinstance(data, dict) else {}


def write_init_status(out_root: Path, payload: dict[str, Any]) -> Path:
    path = init_status_path(out_root)
    write_yaml(path, payload)
    return path


def is_init_confirmed(out_root: Path) -> bool:
    status = str(read_init_status(out_root).get("status") or "").strip().lower()
    return status == "confirmed"


def require_init_confirmed(project_root: Path, op_name: str) -> dict[str, Any]:
    out_root = output_root(project_root, op_name)
    doc = read_init_status(out_root)
    if str(doc.get("status") or "").strip().lower() != "confirmed":
        raise InitGateError(
            f"tg-init not confirmed for {op_name}. Run tg-init then human-confirm before tg-plan.",
            ask="init_required",
            payload={
                "output_root": out_root.as_posix(),
                "init_status": doc.get("status") or "missing",
                "next": f"tg-init <算子仓> --op-name {op_name} --test-script-root <测试工具>",
            },
        )
    require_kb_fingerprint_fresh(project_root, op_name, out_root=out_root, status_doc=doc)
    return doc


def require_kb_fingerprint_fresh(
    project_root: Path,
    op_name: str,
    *,
    out_root: Path | None = None,
    status_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Block plan/solve when UO KB changed since tg-init --confirm."""
    from .isolation import kb_fingerprint_matches, read_kb_fingerprint

    root = out_root or output_root(project_root, op_name)
    doc = status_doc if isinstance(status_doc, dict) else read_init_status(root)
    uo_path = Path(str(doc.get("understand_root") or "")).expanduser() if doc.get("understand_root") else understand_root(
        project_root, op_name
    )
    if not uo_path.is_dir():
        uo_path = understand_root(project_root, op_name)
    stored = read_kb_fingerprint(root)
    if not stored.get("digest"):
        # Legacy confirms without fingerprint: require re-confirm once.
        raise InitGateError(
            "Missing init/kb_fingerprint.yaml. Re-run tg-init --confirm after current gates.",
            ask="kb_stale_reinit",
            payload={
                "output_root": root.as_posix(),
                "understand_root": uo_path.as_posix(),
                "next": f"tg-init <算子仓> --op-name {op_name} --confirm",
            },
        )
    ok, detail = kb_fingerprint_matches(root, uo_path)
    if ok:
        return detail
    raise InitGateError(
        "UO KB fingerprint changed since tg-init confirm. Re-run /tg-init (do not edit $UO_ROOT from TG).",
        ask="kb_stale_reinit",
        payload={
            "output_root": root.as_posix(),
            "understand_root": uo_path.as_posix(),
            "stored_digest": (detail.get("stored") or {}).get("digest"),
            "current_digest": (detail.get("current") or {}).get("digest"),
            "next": f"tg-init <算子仓> --op-name {op_name} --test-script-root <测试工具> then --confirm",
        },
    )


def mark_init_pending(
    out_root: Path,
    *,
    op_name: str,
    project_root: Path,
    understand_root_path: Path,
    artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    doc = {
        "version": 1,
        "op_name": op_name,
        "status": "pending_confirm",
        "project_root": project_root.as_posix(),
        "understand_root": understand_root_path.as_posix(),
        "updated_at": _now(),
        "artifacts": artifacts or {},
        "next": [
            "Task Follow uo-query per needs_binding KEY → uo_query_resolve/",
            "tg-init --merge-uo-resolve (lexicon + domain symmetry)",
            "Task tg-init-audit → init/audit_report.yaml (pass required)",
            "tg-init --confirm",
            "Then tg-plan",
        ],
    }
    write_init_status(out_root, doc)
    return doc


def mark_init_confirmed(out_root: Path, *, notes: str = "", require_merge: bool = True) -> dict[str, Any]:
    if require_merge:
        from .resolve_policy import require_full_csv_closure
        from .uo_resolve_merge import UoMergeError, require_domain_symmetry, require_merge_pass

        try:
            require_merge_pass(out_root)
            require_domain_symmetry(out_root)
        except UoMergeError as exc:
            raise InitGateError(str(exc), ask=exc.ask, payload=exc.report) from exc
        closure = require_full_csv_closure(out_root)
        if str(closure.get("status") or "").lower() != "pass":
            raise InitGateError(
                "CSV closure verify failed. Nested uo-query Tasks on open mid-symbols, then --merge-uo-resolve.",
                ask=str(closure.get("ask") or "shape_closure_incomplete"),
                payload=closure,
            )
        require_audit_pass(out_root)
    else:
        # Full tilingkey mode: still require referee audit, but not CSV merge/closure.
        require_audit_pass(out_root, checklist="tilingkey")
    doc = read_init_status(out_root)
    if not doc:
        doc = {"version": 1}
    doc["status"] = "confirmed"
    doc["confirmed_at"] = _now()
    if notes:
        doc["notes"] = notes

    # Fingerprint UO KB into OUT_ROOT only (hard isolation).
    from .isolation import write_kb_fingerprint

    uo_path = Path(str(doc.get("understand_root") or "")).expanduser()
    if not uo_path.is_dir():
        project = Path(str(doc.get("project_root") or ".")).expanduser()
        op = str(doc.get("op_name") or "")
        if not op or op in {"tg", "uo"}:
            # out_root is .ascendc-pilot/tg — never treat directory name as op_name
            op = project.name if project.name not in {".", ""} else "unknown_operator"
        uo_path = understand_root(project, op)
    if uo_path.is_dir():
        fp = write_kb_fingerprint(out_root, uo_path)
        doc["kb_fingerprint_digest"] = fp.get("digest")
        doc["kb_fingerprint"] = "init/kb_fingerprint.yaml"

    write_init_status(out_root, doc)
    # Align domain_review only when no pending columns (never forge confirmed over open review).
    review_path = out_root / "realization" / "domain_review.yaml"
    if review_path.is_file():
        review = read_yaml(review_path)
        if isinstance(review, dict):
            pending = [c for c in (review.get("pending_columns") or []) if c]
            status = str(review.get("status") or "").lower()
            if pending and status not in {"confirmed", "human", "llm_confirmed"}:
                raise InitGateError(
                    f"domain_review still has {len(pending)} pending_columns; "
                    "AskQuestion lock domains before --confirm (do not forge confirmed).",
                    ask="domain_review_required",
                    payload={"pending_columns": pending[:20]},
                )
            if status not in {"confirmed", "human", "llm_confirmed"}:
                review["status"] = "confirmed"
                review["confirmed_at"] = doc["confirmed_at"]
                write_yaml(review_path, review)
    lexicon_path = out_root / "realization" / "binding_lexicon.yaml"
    if lexicon_path.is_file():
        lexicon = read_yaml(lexicon_path)
        if isinstance(lexicon, dict):
            # Document-level lock only after item-level binds exist; do not fake item locks.
            lexicon["locked"] = True
            write_yaml(lexicon_path, lexicon)
    return doc


def require_audit_pass(
    out_root: Path,
    *,
    checklist: str = "csv",
) -> dict[str, Any]:
    """Require init/audit_report.yaml from tg-init-audit subagent before confirm."""
    from .resolve_policy import AUDIT_CHECKLIST_IDS, TILINGKEY_AUDIT_CHECKLIST_IDS

    required = (
        TILINGKEY_AUDIT_CHECKLIST_IDS
        if checklist in {"tilingkey", "tilingkey_full_coverage", "full"}
        else AUDIT_CHECKLIST_IDS
    )

    path = Path(out_root) / "init" / "audit_report.yaml"
    if not path.is_file():
        raise InitGateError(
            "Missing init/audit_report.yaml. Open Task Follow agents/tg-init-audit (composed) before --confirm.",
            ask="audit_required",
            payload={"expected": path.as_posix(), "next": "Task tg-init-audit → write init/audit_report.yaml"},
        )
    doc = read_yaml(path)
    if not isinstance(doc, dict):
        raise InitGateError("init/audit_report.yaml invalid", ask="audit_required")
    if str(doc.get("status") or "").strip().lower() != "pass":
        blockers = doc.get("blockers") or []
        raise InitGateError(
            f"init audit status={doc.get('status')!r}; blockers={blockers}. Fix then re-audit; do not --confirm.",
            ask="audit_failed",
            payload={"audit_report": path.as_posix(), "blockers": blockers},
        )
    checks = doc.get("checks") if isinstance(doc.get("checks"), list) else []
    seen = {
        str(c.get("id") or "")
        for c in checks
        if isinstance(c, dict) and c.get("id")
    }
    missing_ids = [cid for cid in required if cid not in seen]
    if missing_ids:
        raise InitGateError(
            f"init/audit_report.yaml missing checklist ids: {missing_ids[:12]}. "
            "tg-init-audit MUST cover the mode checklist.",
            ask="audit_incomplete",
            payload={"missing_ids": missing_ids, "checklist": checklist},
        )
    failed_checks = [
        str(c.get("id"))
        for c in checks
        if isinstance(c, dict) and str(c.get("status") or "").lower() == "fail"
    ]
    if failed_checks:
        raise InitGateError(
            f"init audit has failing checks: {failed_checks}. Fix then re-audit; do not --confirm.",
            ask="audit_failed",
            payload={"failed_checks": failed_checks},
        )
    return doc


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
