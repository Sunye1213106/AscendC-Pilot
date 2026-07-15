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
    if any(key in data for key in ("project_root", "op_name", "script_dir", "run_id", "source_revision", "source_snapshot_id", "spec_bundle_hash")):
        return data
    for item in data.get("items") or []:
        if isinstance(item, dict) and isinstance(item.get("data"), dict):
            return item["data"]
    manifest = read_yaml_mapping(uo_root / "manifest.yaml")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return {
        "source_revision": source.get("revision") or "unknown",
        "source_snapshot_id": source.get("snapshot_id") or "SOURCE_PHASE0",
    }


def phase0_receipt(uo_root: Path, run_id: str | None = None) -> dict[str, Any]:
    return read_yaml_mapping(phase0_dir(uo_root, run_id) / "receipt.yaml")


def source_root_for_operator(operator_root: Path, uo_root: Path, run_id: str | None = None) -> Path:
    """Return the Phase 0 frozen SOURCE_ROOT, falling back to OPERATOR_ROOT.

    Candidate paths are interpreted relative to SOURCE_ROOT, while UO_ROOT stays
    under OPERATOR_ROOT/.understand-operator/<op_name>.
    """
    receipt = phase0_receipt(uo_root, run_id)
    source = receipt.get("source") if isinstance(receipt.get("source"), dict) else {}
    raw_root = source.get("root")
    if isinstance(raw_root, str) and raw_root:
        return Path(raw_root).resolve()
    manifest = read_yaml_mapping(uo_root / "manifest.yaml")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    raw_root = source.get("root")
    if isinstance(raw_root, str) and raw_root:
        return Path(raw_root).resolve()
    return operator_root.resolve()


def assert_candidate_run_current(uo_root: Path, candidate_run_id: str) -> CandidateRunCheckResult:
    manifest = read_yaml_mapping(uo_root / "manifest.yaml")
    current = manifest.get("current_run_id")
    if not isinstance(current, str) or not current:
        return CandidateRunCheckResult(False, "", "manifest.yaml.current_run_id is missing")
    if candidate_run_id != current:
        return CandidateRunCheckResult(False, current, f"candidate task.run_id {candidate_run_id!r} does not match current run {current!r}")
    receipt = phase0_dir(uo_root, current) / "receipt.yaml"
    if not receipt.exists():
        return CandidateRunCheckResult(False, current, f"Phase 0 receipt missing for current run {current}")
    return CandidateRunCheckResult(True, current, "")


class CandidateRunCheckResult:
    def __init__(self, ok: bool, current_run_id: str, message: str) -> None:
        self.ok = ok
        self.current_run_id = current_run_id
        self.message = message
