"""Init gate: KB presence + init.status confirmed before tg-plan."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import output_root


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
    """Resolve the exact UO product root; never invent an architecture."""
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
    except Exception as exc:
        raise InitGateError(
            "Architecture is unresolved; cannot fingerprint UO product without an exact .ascendc-pilot/<arch>/uo root.",
            ask="architecture_required",
            payload={
                "reason_code": "ARCHITECTURE_UNRESOLVED",
                "project_root": Path(project_root).expanduser().resolve().as_posix(),
                "op_name": str(op_name or ""),
            },
        ) from exc


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
        if root.name == "uo":
            parent = root.parent
            if parent.name == ".ascendc-pilot" or (
                parent.parent.name == ".ascendc-pilot" and parent.name.startswith("arch")
            ):
                if root.is_dir() and any(root.glob("*.uo")):
                    return root
                return root if root.is_dir() else None
        if root.name == ".ascendc-pilot":
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


def init_yaml_path(out_root: Path) -> Path:
    return Path(out_root) / "init.yaml"


def read_init_doc(out_root: Path) -> dict[str, Any]:
    from .products import load_init

    try:
        return load_init(out_root)
    except Exception:
        return {}


def is_init_confirmed(out_root: Path) -> bool:
    doc = read_init_doc(out_root)
    if doc.get("confirmed") is True:
        return True
    return str(doc.get("status") or "").strip().lower() == "confirmed"


def require_init_confirmed(project_root: Path, op_name: str) -> dict[str, Any]:
    out_root = output_root(project_root, op_name)
    doc = read_init_doc(out_root)
    if not is_init_confirmed(out_root):
        raise InitGateError(
            f"tg-init not confirmed for {op_name}. Run /tg-init then human-confirm before /tg-plan.",
            ask="init_required",
            payload={
                "output_root": out_root.as_posix(),
                "init_status": "missing" if not doc else "unconfirmed",
                "next": f"/uo-init then /tg-init (op={op_name}) → AskQuestion → Host `pilot_run` finalizes `human_confirm`",
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
    """Block plan/solve when UO KB changed since tg-init confirm."""
    from .isolation import kb_fingerprint_matches

    root = out_root or output_root(project_root, op_name)
    doc = status_doc if isinstance(status_doc, dict) else read_init_doc(root)
    project = Path(str(doc.get("project_root") or project_root)).expanduser().resolve()
    understand_hint = (
        Path(str(doc.get("understand_root") or "")).expanduser()
        if doc.get("understand_root")
        else None
    )
    uo_path = _fingerprint_hint(project, op_name, understand_hint=understand_hint)
    stored_digest = str(doc.get("uo_digest") or "").strip()
    if not stored_digest:
        raise InitGateError(
            "Missing uo_digest in tg/init.yaml. Re-run /tg-init.",
            ask="kb_stale_reinit",
            payload={
                "output_root": root.as_posix(),
                "understand_root": uo_path.as_posix(),
                "next": f"/tg-init (op={op_name}) → AskQuestion → Host `pilot_run` finalizes `human_confirm`",
            },
        )
    ok, detail = kb_fingerprint_matches(root, uo_path)
    if ok:
        return {"ok": True, **(detail if isinstance(detail, dict) else {"detail": detail})}
    raise InitGateError(
        "UO KB digest changed since tg-init confirm. Re-run /tg-init (do not edit $UO_ROOT from TG).",
        ask="kb_stale_reinit",
        payload={
            "output_root": root.as_posix(),
            "understand_root": uo_path.as_posix(),
            "stored_digest": stored_digest,
            "current_digest": (detail.get("current") or {}).get("digest") if isinstance(detail, dict) else "",
            "next": f"/uo-init then /tg-init (op={op_name}) → AskQuestion → Host `pilot_run` finalizes `human_confirm`",
        },
    )


def mark_init_confirmed(out_root: Path, *, notes: str = "", require_merge: bool = False, project_root: Path | None = None) -> dict[str, Any]:
    del require_merge
    from .products import dump_init, load_init, validate_init

    try:
        doc = load_init(out_root)
    except Exception as exc:
        raise InitGateError(
            "missing tg/init.yaml; cannot confirm",
            ask="init_required",
            payload={"output_root": Path(out_root).as_posix(), "error": str(exc)[:200]},
        ) from exc
    errors = validate_init(doc)
    if errors:
        raise InitGateError(
            "init.yaml invalid: " + "; ".join(errors),
            ask="init_invalid",
            payload={"errors": errors},
        )
    project = Path(str(project_root or doc.get("project_root") or ".")).expanduser().resolve()
    op = str(doc.get("op_name") or "")
    if not op or op in {"tg", "uo"}:
        op = project.name if project.name not in {".", ""} else "unknown_operator"
    from .isolation import compute_kb_fingerprint

    uo_path = _fingerprint_hint(project, op)
    fp = compute_kb_fingerprint(uo_path)
    digest = str(fp.get("digest") or "")
    if not digest:
        raise InitGateError(
            "Cannot fingerprint UO product for confirm. Need .ascendc-pilot/<arch>/uo/*.uo.",
            ask="kb_fingerprint_unavailable",
            payload={
                "output_root": Path(out_root).as_posix(),
                "fingerprint_hint": uo_path.as_posix(),
                "next": f"/uo-init (op={op}) then /tg-init → human_confirm --finalize",
            },
        )
    doc["confirmed"] = True
    doc["status"] = "confirmed"
    doc["confirmed_at"] = _now()
    doc["uo_digest"] = digest
    doc["uo_product"] = str(fp.get("uo_product") or doc.get("uo_product") or "")
    doc["project_root"] = project.as_posix()
    if notes:
        doc["notes"] = notes
    dump_init(out_root, doc)
    return doc


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
