"""TG init gate compatibility layer with architecture-safe fingerprinting."""

from __future__ import annotations

from pathlib import Path

from . import init_status_legacy as _legacy

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)


def _fingerprint_hint(project_root: Path, op_name: str, *, understand_hint: Path | None = None) -> Path:
    """Resolve an existing UO product root; never invent an architecture."""
    if understand_hint is not None:
        hint = Path(understand_hint).expanduser()
        if ".ascendc-pilot" in hint.parts:
            return hint
    product_dir = _legacy._product_uo_root(project_root, op_name=op_name)
    if product_dir is not None:
        return product_dir
    try:
        from ascendc_pilot.paths import uo_product_root

        return uo_product_root(project_root)
    except Exception as exc:  # noqa: BLE001
        raise _legacy.InitGateError(
            "Architecture is unresolved; cannot fingerprint UO product without an exact .ascendc-pilot/<arch>/uo root.",
            ask="architecture_required",
            payload={
                "reason_code": "ARCHITECTURE_UNRESOLVED",
                "project_root": Path(project_root).expanduser().resolve().as_posix(),
                "op_name": str(op_name or ""),
            },
        ) from exc


# Legacy functions resolve this name in their module globals. Patch that single
# dependency so all confirm/freshness paths share the no-default rule.
_legacy._fingerprint_hint = _fingerprint_hint
