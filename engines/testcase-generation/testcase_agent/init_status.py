"""Init gate: KB presence + init.status confirmed before tg-plan."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import output_root, read_yaml, write_yaml


def _uo_root(project_root: Path, op_name: str, *, arch: str | None = None) -> Path:
    del op_name
    try:
        from ascendc_pilot.paths import uo_root

        return uo_root(project_root, arch=arch)
    except Exception:
        arch_name = (arch or "").strip()
        if not arch_name:
            raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
        return Path(project_root).expanduser().resolve() / ".ascendc-pilot" / arch_name / "uo"


class InitGateError(RuntimeError):
    def __init__(self, message: str, *, ask: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.ask = ask
        self.payload = payload or {}


def _product_uo_root(project_root: Path, *, op_name: str = "", architecture: str = "") -> Path | None:
    """Return the formal product dir (``.ascendc-pilot/<arch>/uo``) when a ``.uo`` exists."""
    try:
        from testcase_agent import product_uo

        product = product_uo.product(project_root, op_name=op_name, architecture=architecture)
    except Exception:
        return None
    if product is None or not product.is_file() or product.suffix != ".uo":
        return None
    return product.parent


def _fingerprint_hint(project_root: Path, op_name: str, *, understand_hint: Path | None = None) -> Path:
    """Build a path that still contains ``.ascendc-pilot`` even without an arch UO tree.

    ``compute_kb_fingerprint`` treats its argument as a project/arch hint; the
    formal ``.uo`` product is the authority whenever one exists.
    """
    if understand_hint is not None:
        hint = Path(understand_hint).expanduser()
        if ".ascendc-pilot" in hint.parts:
            return hint
    product_dir = _product_uo_root(project_root, op_name=op_name)
    if product_dir is not None:
        return product_dir
    try:
        from ascendc_pilot.paths import uo_product_root

        return uo_product_root(project_root)
    except Exception:
        return Path(project_root).expanduser().resolve() / ".ascendc-pilot" / "arch35" / "uo"


def kb_exists(project_root: Path, op_name: str, kb_root: Path | None = None) -> Path | None:
    """Return understand root if present, else None.

    Product-only layouts are valid: a finalized ``.uo`` under
    ``.ascendc-pilot/<arch>/uo/`` is sufficient KB presence even when the
    retired YAML/DB export tree is absent.
    """
    if kb_root is not None:
        root = kb_root.expanduser().resolve()
        if root.suffix == ".uo" and root.is_file():
            return root.parent
        # Arch-scoped (canonical) or legacy top-level ``.ascendc-pilot/uo``.
        if root.name == "uo":
            parent = root.parent
            if parent.name == ".ascendc-pilot" or (
                parent.parent.name == ".ascendc-pilot" and parent.name.startswith("arch")
            ):
                if root.is_dir() and any(root.glob("*.uo")):
                    return root
                return root if root.is_dir() else None
        if root.name == ".ascendc-pilot":
            # Prefer arch-scoped product dirs; fall back to legacy top-level.
            for child in sorted(root.iterdir()) if root.is_dir() else []:
                if child.is_dir() and child.name.startswith("arch"):
                    candidate = child / "uo"
                    if candidate.is_dir() and any(candidate.glob("*.uo")):
                        return candidate
            candidate = root / "uo"
            if candidate.is_dir() and any(candidate.glob("*.uo")):
                return candidate
            return candidate if candidate.is_dir() else None
        if root.is_dir():
            return root
        return None
    product_dir = _product_uo_root(project_root, op_name=op_name)
    if product_dir is not None:
        return product_dir
    uo = _uo_root(project_root, op_name)
    return uo if uo.is_dir() else None


def require_kb(project_root: Path, op_name: str, kb_root: Path | None = None) -> Path:
    found = kb_exists(project_root, op_name, kb_root=kb_root)
    if found is not None:
        return found
    try:
        from ascendc_pilot.paths import uo_product_root

        expected = uo_product_root(project_root)
    except Exception:
        expected = Path(project_root).expanduser().resolve() / ".ascendc-pilot" / "<arch>" / "uo"
    raise InitGateError(
        f"KB missing: {expected}. Run /uo-init to build .ascendc-pilot/<arch>/uo/*.uo, then tg-init.",
        ask="uo_init_required",
        payload={
            "expected_kb": expected.as_posix(),
            "hint": "tg-init defaults to <算子仓>/.ascendc-pilot/<arch>/uo/*.uo; optional --kb-root only overrides.",
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
                "next": (
                    f"/uo-init then /tg-init (op={op_name}) → init_audit → "
                    "AskQuestion → acp run-action human_confirm --finalize"
                ),
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
    understand_hint = (
        Path(str(doc.get("understand_root") or "")).expanduser()
        if doc.get("understand_root")
        else None
    )
    uo_path = _fingerprint_hint(project_root, op_name, understand_hint=understand_hint)
    stored = read_kb_fingerprint(root)
    if not stored.get("digest"):
        # Legacy confirms without fingerprint: require re-confirm once.
        raise InitGateError(
            "Missing init/kb_fingerprint.yaml. Re-run tg-init --confirm after current gates.",
            ask="kb_stale_reinit",
            payload={
                "output_root": root.as_posix(),
                "understand_root": uo_path.as_posix(),
                "next": (
                    f"/tg-init (op={op_name}) → AskQuestion → "
                    "acp run-action human_confirm --finalize"
                ),
            },
        )
    ok, detail = kb_fingerprint_matches(root, uo_path)
    if ok:
        return {"ok": True, **(detail if isinstance(detail, dict) else {"detail": detail})}
    raise InitGateError(
        "UO KB fingerprint changed since tg-init confirm. Re-run /tg-init (do not edit $UO_ROOT from TG).",
        ask="kb_stale_reinit",
        payload={
            "output_root": root.as_posix(),
            "understand_root": uo_path.as_posix(),
            "stored_digest": (detail.get("stored") or {}).get("digest"),
            "current_digest": (detail.get("current") or {}).get("digest"),
            "next": (
                f"/uo-init then /tg-init (op={op_name}) → AskQuestion → "
                "acp run-action human_confirm --finalize"
            ),
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
            "acp run-action auto (drain tg-init deterministic phases)",
            "init_audit engine → init/audit_report.yaml (TILINGKEY_AUDIT_CHECKLIST_IDS)",
            "AskQuestion: confirm | rework | stop",
            "acp run-action human_confirm --finalize",
            "Then /tg-plan",
        ],
    }
    write_init_status(out_root, doc)
    return doc


def mark_init_confirmed(out_root: Path, *, notes: str = "", require_merge: bool = False) -> dict[str, Any]:
    del require_merge  # legacy CSV merge/domain-symmetry/closure gate was removed; kept for call-site compat.
    require_audit_pass(out_root, checklist="tilingkey")
    doc = read_init_status(out_root)
    if not doc:
        doc = {"version": 1}
    doc["status"] = "confirmed"
    doc["confirmed_at"] = _now()
    if notes:
        doc["notes"] = notes

    # Fingerprint the formal .uo product into OUT_ROOT only (hard isolation).
    # Must succeed even when the retired arch-scoped UO YAML/DB tree is absent.
    from .isolation import write_kb_fingerprint

    project = Path(str(doc.get("project_root") or ".")).expanduser().resolve()
    op = str(doc.get("op_name") or "")
    if not op or op in {"tg", "uo"}:
        # out_root is .ascendc-pilot/tg — never treat directory name as op_name
        op = project.name if project.name not in {".", ""} else "unknown_operator"
    understand_hint = (
        Path(str(doc.get("understand_root") or "")).expanduser()
        if doc.get("understand_root")
        else None
    )
    uo_path = _fingerprint_hint(project, op, understand_hint=understand_hint)
    fp = write_kb_fingerprint(out_root, uo_path)
    digest = str(fp.get("digest") or "")
    if not digest:
        raise InitGateError(
            "Cannot fingerprint UO product for confirm. Need .ascendc-pilot/<arch>/uo/*.uo "
            "(or a legacy top-level / arch UO export). Refusing to mark confirmed without a lock.",
            ask="kb_fingerprint_unavailable",
            payload={
                "output_root": out_root.as_posix(),
                "fingerprint_hint": uo_path.as_posix(),
                "next": f"/uo-init (op={op}) then /tg-init → human_confirm --finalize",
            },
        )
    doc["kb_fingerprint_digest"] = digest
    doc["kb_fingerprint"] = "init/kb_fingerprint.yaml"
    if fp.get("uo_product"):
        doc["uo_product"] = str(fp.get("uo_product"))

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
    return doc


def require_audit_pass(
    out_root: Path,
    *,
    checklist: str = "tilingkey",
) -> dict[str, Any]:
    """Require init/audit_report.yaml from the init_audit engine before confirm."""
    from .resolve_policy import TILINGKEY_AUDIT_CHECKLIST_IDS

    # Legacy CSV checklist removed; only tilingkey ids are accepted.
    del checklist  # call-site compat; always tilingkey
    required = TILINGKEY_AUDIT_CHECKLIST_IDS

    path = Path(out_root) / "init" / "audit_report.yaml"
    if not path.is_file():
        raise InitGateError(
            "Missing init/audit_report.yaml. Re-run /tg-init init_audit (deterministic engine) before --confirm.",
            ask="audit_required",
            payload={"expected": path.as_posix(), "next": "init_audit engine → write init/audit_report.yaml"},
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
            "init_audit MUST cover the mode checklist.",
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
