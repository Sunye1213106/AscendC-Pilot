from __future__ import annotations

from pathlib import Path
from typing import Any

from uo._operator.spec import spec_bundle_hash

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


def is_active_run_id(run_id: Any) -> bool:
    """True for a real session run id (Pilot ``RUN_*`` or legacy ``UO_RUN_*``).

    Pending placeholders (``*_PENDING``) are never active. One ACP session/task
    uses exactly one run id; Pilot state.run_id is the authority when bound.
    """
    if not isinstance(run_id, str):
        return False
    value = run_id.strip()
    if not value or value.endswith("_PENDING"):
        return False
    return value.startswith("RUN_") or value.startswith("UO_RUN_")


def active_run_id(uo_root: Path) -> str:
    manifest = read_yaml_mapping(uo_root / "manifest.yaml")
    run_id = manifest.get("current_run_id")
    if not is_active_run_id(run_id):
        raise RuntimeError(f"manifest.yaml.current_run_id is not active in {uo_root}")
    return str(run_id).strip()


def scope_dir(uo_root: Path, run_id: str | None = None) -> Path:
    """Canonical write path: runs/<id>/scope/."""
    rid = run_id or active_run_id(uo_root)
    return uo_root / "runs" / rid / "scope"


def resolve_scope_dir(uo_root: Path, run_id: str | None = None) -> Path:
    """Read current run scope path."""
    modern = scope_dir(uo_root, run_id)
    return modern


def scope_context(uo_root: Path, run_id: str | None = None) -> dict[str, Any]:
    data = read_yaml_mapping(resolve_scope_dir(uo_root, run_id) / "context.yaml")
    if any(
        key in data
        for key in (
            "project_root",
            "op_name",
            "script_dir",
            "run_id",
            "source_revision",
            "source_snapshot_id",
            "spec_bundle_hash",
        )
    ):
        return data
    for item in data.get("items") or []:
        if isinstance(item, dict) and isinstance(item.get("data"), dict):
            return item["data"]
    manifest = read_yaml_mapping(uo_root / "manifest.yaml")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return {
        "source_revision": source.get("revision") or "unknown",
        "source_snapshot_id": source.get("snapshot_id") or "SOURCE_UNKNOWN",
        "spec_bundle_hash": spec_bundle_hash(),
    }


def scope_snapshot(uo_root: Path, run_id: str) -> dict[str, str]:
    context = scope_context(uo_root, run_id)
    return {
        "run_id": run_id,
        "source_snapshot_id": str(context.get("source_snapshot_id") or "SOURCE_UNKNOWN"),
        "source_revision": str(context.get("source_revision") or "unknown"),
        "spec_bundle_hash": str(context.get("spec_bundle_hash") or spec_bundle_hash()),
    }


def scope_receipt(uo_root: Path, run_id: str | None = None) -> dict[str, Any]:
    return read_yaml_mapping(resolve_scope_dir(uo_root, run_id) / "receipt.yaml")


def source_root_for_operator(operator_root: Path, uo_root: Path, run_id: str | None = None) -> Path:
    """Return the scope-confirmed SOURCE_ROOT, falling back to OPERATOR_ROOT."""
    receipt = scope_receipt(uo_root, run_id)
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
        return CandidateRunCheckResult(
            False,
            current,
            f"candidate task.run_id {candidate_run_id!r} does not match current run {current!r}",
        )
    receipt = resolve_scope_dir(uo_root, current) / "receipt.yaml"
    if not receipt.exists():
        return CandidateRunCheckResult(
            False, current, f"Scope confirmation receipt missing for current run {current}"
        )
    return CandidateRunCheckResult(True, current, "")


class CandidateRunCheckResult:
    def __init__(self, ok: bool, current_run_id: str, message: str) -> None:
        self.ok = ok
        self.current_run_id = current_run_id
        self.message = message
