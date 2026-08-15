"""Last-exclusive pointer under ``.ascendc-pilot/control/active_run.yaml``.

This is a discover_arch / host-context fallback for *which* architecture was
last written by an exclusive product-family lock. It is **not** the mutex:
parallel families use ``control/product_locks.yaml``; sessions bind a ``.uo``
digest in ``control/session_bindings.yaml``.

Resolution consumers (``discover_arch``, ``host-context``) still prefer this
pointer after explicit ``--architecture`` / env override.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ascendc_pilot.paths import AGENT_DIR, STATE_SUBDIR

ACTIVE_RUN_SCHEMA = "pilot-active-run/v1"


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def control_root(project_root: Path | str) -> Path:
    return Path(project_root).expanduser().resolve() / AGENT_DIR / "control"


def active_run_path(project_root: Path | str) -> Path:
    return control_root(project_root) / "active_run.yaml"


def read_active_run(project_root: Path | str) -> dict[str, Any] | None:
    path = active_run_path(project_root)
    if not path.is_file():
        return None
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(doc, dict):
        return None
    arch = str(doc.get("architecture") or "").strip()
    if not arch:
        return None
    return doc


def active_architecture(project_root: Path | str) -> str | None:
    """Return architecture from a valid active_run pointer, else None.

    Validity requires the pointed ``workflow.yaml`` to still exist so a stale
    pointer cannot silently redirect to a wiped arch tree.
    """
    doc = read_active_run(project_root)
    if not doc:
        return None
    arch = str(doc.get("architecture") or "").strip()
    if not arch:
        return None
    root = Path(project_root).expanduser().resolve()
    wf = root / AGENT_DIR / arch / STATE_SUBDIR / "workflow.yaml"
    if not wf.is_file():
        return None
    return arch


def write_active_run(
    project_root: Path | str,
    *,
    architecture: str,
    run_id: str = "",
    workflow_id: str = "",
    status: str = "",
) -> dict[str, Any]:
    """Persist the arch-neutral active-run pointer (fail-closed on empty arch)."""
    arch = str(architecture or "").strip()
    if not arch:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
    root = Path(project_root).expanduser().resolve()
    ctrl = control_root(root)
    ctrl.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema": ACTIVE_RUN_SCHEMA,
        "architecture": arch,
        "run_id": str(run_id or "").strip(),
        "workflow_id": str(workflow_id or "").strip(),
        "status": str(status or "").strip(),
        "state_path": f"{arch}/{STATE_SUBDIR}/workflow.yaml",
        "updated_at": _now(),
    }
    import yaml

    path = active_run_path(root)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return payload


def clear_active_run(project_root: Path | str) -> None:
    path = active_run_path(project_root)
    if path.is_file():
        path.unlink()
