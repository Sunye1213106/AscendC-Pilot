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
        if root.name == ".understand-operator":
            candidate = root / op_name
            return candidate if candidate.is_dir() else (root if root.is_dir() else None)
        if root.parent.name == ".understand-operator":
            return root if root.is_dir() else None
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
        f"KB missing: {expected}. Run /uo-init to build .understand-operator/<op>, then tg-init.",
        ask="uo_init_required",
        payload={
            "expected_kb": expected.as_posix(),
            "hint": "tg-init defaults to <算子仓>/.understand-operator/<op>; optional --kb-root only overrides.",
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
    if str(doc.get("status") or "").strip().lower() == "confirmed":
        return doc
    raise InitGateError(
        f"tg-init not confirmed for {op_name}. Run tg-init then human-confirm before tg-plan.",
        ask="init_required",
        payload={
            "output_root": out_root.as_posix(),
            "init_status": doc.get("status") or "missing",
            "next": f"tg-init <算子仓> --op-name {op_name} --test-script-root <测试工具>",
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
        _require_audit_pass(out_root)
    doc = read_init_status(out_root)
    if not doc:
        doc = {"version": 1}
    doc["status"] = "confirmed"
    doc["confirmed_at"] = _now()
    if notes:
        doc["notes"] = notes
    write_init_status(out_root, doc)
    # Keep domain_review aligned when present.
    review_path = out_root / "realization" / "domain_review.yaml"
    if review_path.is_file():
        review = read_yaml(review_path)
        if isinstance(review, dict):
            review["status"] = "confirmed"
            review["confirmed_at"] = doc["confirmed_at"]
            write_yaml(review_path, review)
    lexicon_path = out_root / "realization" / "binding_lexicon.yaml"
    if lexicon_path.is_file():
        lexicon = read_yaml(lexicon_path)
        if isinstance(lexicon, dict):
            lexicon["locked"] = True
            write_yaml(lexicon_path, lexicon)
    return doc


def _require_audit_pass(out_root: Path) -> dict[str, Any]:
    """Require init/audit_report.yaml from tg-init-audit subagent before confirm."""
    path = Path(out_root) / "init" / "audit_report.yaml"
    if not path.is_file():
        raise InitGateError(
            "Missing init/audit_report.yaml. Open Task Follow agents/tg-init-audit.md before --confirm.",
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
    return doc


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
