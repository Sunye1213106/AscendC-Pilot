"""tg-init: legacy Understand-KB intake snapshot (used by tests / plan snapshot bootstrap).

The legacy CSV full-init flow (contract build + bind scaffolds + confirm) was
removed with that stack; the pilot's own tilingkey_full_coverage init/confirm
chain lives in ``ascendc_pilot.actions.tg_primary`` /
``testcase_agent.init_status`` instead.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hashing import semantic_snapshot_hash, stable_hash
from .io import ensure_output_dirs, output_root, read_yaml, write_json, write_yaml
from .understand import UnderstandExportError, export_testcase_contract, run_final_validation, safe_op_name, understand_root
from .validation import quality_status_from, validate_intake


class TgInitError(RuntimeError):
    def __init__(self, message: str, report: dict[str, Any] | None = None, *, ask: str = "") -> None:
        super().__init__(message)
        self.report = report or {}
        self.ask = ask


def tg_init(project_root: Path, op_name: str) -> dict[str, Any]:
    """Legacy understand intake only (used by tests / plan snapshot bootstrap)."""
    project_root = project_root.resolve()
    op_name = safe_op_name(project_root, op_name)
    uo_root = understand_root(project_root, op_name)
    out_root = output_root(project_root, op_name)
    ensure_output_dirs(out_root)

    run = {
        "version": 1,
        "command": "tg-init",
        "op_name": op_name,
        "project_root": project_root.as_posix(),
        "understand_root": uo_root.as_posix(),
        "output_root": out_root.as_posix(),
        "started_at": _now(),
        "phase": "understand_intake",
        "status": "running",
    }

    if not uo_root.exists():
        run["status"] = "fail"
        write_yaml(out_root / "run.yaml", run)
        report = {
            "status": "fail",
            "blocking_issues": [
                {
                    "code": "UNDERSTAND_ROOT_MISSING",
                    "severity": "error",
                    "path": uo_root.as_posix(),
                    "target": op_name,
                    "message": f"Understand root not found: {uo_root}",
                }
            ],
            "warnings": [],
            "info": [],
        }
        write_yaml(out_root / "intake" / "validation_report.yaml", report)
        raise TgInitError(f"Understand root not found: {uo_root}", report, ask="uo_init_required")

    try:
        export_payload = export_testcase_contract(project_root, op_name, uo_root)
        final_validation = run_final_validation(project_root, op_name, uo_root)
        if export_payload.get("intake_mode") == "built_kb_filesystem" and not final_validation.get("source_artifact_hashes"):
            from .understand import synth_final_validation

            final_validation = synth_final_validation(uo_root, export_payload)
    except Exception as exc:
        code = exc.code if isinstance(exc, UnderstandExportError) else "UNDERSTAND_EXPORT_OR_VALIDATION_FAILED"
        run["status"] = "fail"
        write_yaml(out_root / "run.yaml", run)
        report = {
            "status": "fail",
            "blocking_issues": [
                {
                    "code": code,
                    "severity": "error",
                    "path": uo_root.as_posix(),
                    "target": op_name,
                    "message": str(exc),
                }
            ],
            "warnings": [],
            "info": [],
        }
        write_yaml(out_root / "intake" / "validation_report.yaml", report)
        raise TgInitError(str(exc), report) from exc

    files = export_payload.get("files") if isinstance(export_payload.get("files"), dict) else {}
    source_hashes = final_validation.get("source_artifact_hashes") or {}
    if not source_hashes and isinstance(files.get("checks/artifact_hashes.yaml"), dict):
        source_hashes = files["checks/artifact_hashes.yaml"].get("hashes") or {}
    if not source_hashes:
        artifact_path = uo_root / "checks" / "artifact_hashes.yaml"
        if artifact_path.is_file():
            payload = read_yaml(artifact_path)
            if isinstance(payload, dict):
                source_hashes = payload.get("hashes") or {}

    report_obj = validate_intake(export_payload, final_validation)
    report = report_obj.to_dict()
    write_yaml(out_root / "intake" / "validation_report.yaml", report)

    if report_obj.status == "fail":
        run["status"] = "fail"
        run["completed_at"] = _now()
        run["validation_report"] = "intake/validation_report.yaml"
        write_yaml(out_root / "run.yaml", run)
        raise TgInitError("tg-init failed intake validation", report)

    # Drop retired UO contracts from snapshot authority after intake warning.
    if isinstance(files, dict):
        files.pop("contracts/testcase.yaml", None)

    snapshot = {
        "version": 1,
        "op_name": op_name,
        "view": "kb-export",
        "understand_root": uo_root.as_posix(),
        "contract_view": files,
        "context_slice": export_payload.get("context_slice"),
        "files": files,
        "source_artifact_hashes": dict(sorted(source_hashes.items())),
        "final_validation": final_validation,
    }
    snapshot["snapshot_hash"] = semantic_snapshot_hash(snapshot)

    quality_status = quality_status_from(files)
    meta = {
        "version": 1,
        "op_name": op_name,
        "created_at": _now(),
        "understand_root": uo_root.as_posix(),
        "understand_contract_version": None,
        "tg_contract_path": "contract/testcase.yaml",
        "source_artifact_hashes": dict(sorted(source_hashes.items())),
        "quality_status": quality_status,
        "snapshot_hash": snapshot["snapshot_hash"],
        "blocking_issues": [issue.to_dict() for issue in report_obj.blocking_issues],
        "warnings": [issue.to_dict() for issue in report_obj.warnings],
    }
    meta["meta_hash"] = stable_hash({key: value for key, value in meta.items() if key != "created_at"})

    write_json(out_root / "snapshot" / "understand_contract.json", snapshot)
    write_yaml(out_root / "snapshot" / "snapshot_meta.yaml", meta)

    run.update(
        {
            "status": "pass" if report_obj.status == "pass" else "warn",
            "completed_at": _now(),
            "snapshot": "snapshot/understand_contract.json",
            "snapshot_meta": "snapshot/snapshot_meta.yaml",
            "validation_report": "intake/validation_report.yaml",
            "next_command": "tg-plan (after tg-init binding confirmed)",
        }
    )
    write_yaml(out_root / "run.yaml", run)
    return {"run": run, "snapshot": snapshot, "snapshot_meta": meta, "validation_report": report}


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
