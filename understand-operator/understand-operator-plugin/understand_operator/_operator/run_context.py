from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    if yaml is None or not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def active_run_id(uo_root: Path) -> str:
    manifest = read_yaml_mapping(uo_root / "manifest.yaml")
    run_id = manifest.get("current_run_id")
    if not isinstance(run_id, str) or not run_id.startswith("UO_RUN_") or run_id == "UO_RUN_PENDING":
        raise RuntimeError(f"manifest.yaml.current_run_id is not active in {uo_root}")
    return run_id


def phase0_dir(uo_root: Path, run_id: str | None = None) -> Path:
    return uo_root / "runs" / (run_id or active_run_id(uo_root)) / "phase0"


def phase0_context(uo_root: Path, run_id: str | None = None) -> dict[str, Any]:
    data = read_yaml_mapping(phase0_dir(uo_root, run_id) / "context.yaml")
    for item in data.get("items") or []:
        if isinstance(item, dict) and isinstance(item.get("data"), dict):
            return item["data"]
    manifest = read_yaml_mapping(uo_root / "manifest.yaml")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return {
        "source_revision": source.get("revision") or "unknown",
        "source_snapshot_id": source.get("snapshot_id") or "SOURCE_PHASE0",
    }
