"""tg-init: KB intake + CSV contract + bind scaffolds (binding lives here, not a separate command)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hashing import semantic_snapshot_hash, stable_hash
from .init_status import (
    InitGateError,
    mark_init_confirmed,
    mark_init_pending,
    require_kb,
)
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


def tg_init_full(
    project_root: Path,
    op_name: str,
    *,
    test_script_root: Path | None = None,
    kb_root: Path | None = None,
    lexicon_seed: Path | None = None,
    confirm: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    """Intake + contract + bind scaffolds. confirm=True locks init.status=confirmed."""
    project_root = project_root.resolve()
    op_name = safe_op_name(project_root, op_name)
    out_root = output_root(project_root, op_name)
    ensure_output_dirs(out_root)
    (out_root / "init").mkdir(parents=True, exist_ok=True)
    (out_root / "bind").mkdir(parents=True, exist_ok=True)

    if confirm and not test_script_root:
        # Allow confirm-only after prior init wrote pending status.
        if (out_root / "init" / "status.yaml").is_file():
            try:
                status = mark_init_confirmed(out_root, notes=notes)
            except InitGateError as exc:
                raise TgInitError(str(exc), ask=exc.ask) from exc
            return {
                "status": "confirmed",
                "op_name": op_name,
                "project_root": project_root.as_posix(),
                "output_root": out_root.as_posix(),
                "init": status,
                "next": "tg-plan <算子仓> --op-name <op>  # default L0,L1 whole-operator; optional --level L2 --topic <scope>",
            }

    try:
        uo_root = require_kb(project_root, op_name, kb_root=kb_root)
    except InitGateError as exc:
        raise TgInitError(str(exc), ask=exc.ask) from exc

    write_yaml(
        out_root / "init" / "run_context.yaml",
        {
            "version": 1,
            "op_name": op_name,
            "project_root": project_root.as_posix(),
            "understand_root": uo_root.as_posix(),
            "test_script_root": test_script_root.resolve().as_posix() if test_script_root else "",
            "started_at": _now(),
        },
    )

    intake = tg_init(project_root, op_name)
    contract_result: dict[str, Any] | None = None
    if test_script_root is None:
        raise TgInitError(
            "TEST_SCRIPT_ROOT_REQUIRED: tg-init needs --test-script-root <测试工具> "
            "(or --confirm after a prior pending init).",
            ask="missing_init_inputs",
        )

    try:
        from .contract import TgContractError, tg_contract

        contract_result = tg_contract(
            project_root,
            op_name,
            csv_consumer_root=test_script_root,
            reuse_snapshot=True,
            lexicon_seed=lexicon_seed,
        )
    except TgContractError as exc:
        raise TgInitError(str(exc)) from exc

    artifacts = write_bind_scaffolds(out_root, intake["snapshot"], contract_result)
    status_doc = mark_init_pending(
        out_root,
        op_name=op_name,
        project_root=project_root,
        understand_root_path=uo_root,
        artifacts=artifacts,
    )

    if confirm:
        try:
            status_doc = mark_init_confirmed(out_root, notes=notes)
        except InitGateError as exc:
            raise TgInitError(str(exc), ask=exc.ask) from exc

    return {
        "status": status_doc.get("status"),
        "op_name": op_name,
        "project_root": project_root.as_posix(),
        "output_root": out_root.as_posix(),
        "understand_root": uo_root.as_posix(),
        "snapshot_hash": intake["snapshot"].get("snapshot_hash"),
        "contract": {
            "status": (contract_result or {}).get("status"),
            "csv_variables": len(((contract_result or {}).get("realization_map") or {}).get("csv_variables") or []),
            "binding_gaps": (contract_result or {}).get("binding_gaps") or [],
            "domain_review_status": (contract_result or {}).get("domain_review_status"),
        },
        "artifacts": artifacts,
        "init": status_doc,
        "ask": "confirm_init" if status_doc.get("status") != "confirmed" else "",
        "next": (
            "tg-plan …"
            if status_doc.get("status") == "confirmed"
            else [
                "PARENT: Task Follow uo-query per needs_binding_keys → --merge-uo-resolve → --verify-csv-closure",
                "AskQuestion 仅域锁定 → tg-init-audit → tg-init --confirm → tg-plan",
            ]
        ),
    }


def write_bind_scaffolds(
    out_root: Path,
    snapshot: dict[str, Any],
    contract_result: dict[str, Any] | None,
) -> dict[str, str]:
    """Script-side bind seeds for LLM completion under bind/ + realization/."""
    bind_dir = out_root / "bind"
    bind_dir.mkdir(parents=True, exist_ok=True)
    realization = out_root / "realization"
    rmap = (contract_result or {}).get("realization_map") if isinstance(contract_result, dict) else None
    if not isinstance(rmap, dict) and (realization / "realization_map.yaml").is_file():
        loaded = read_yaml(realization / "realization_map.yaml")
        rmap = loaded if isinstance(loaded, dict) else {}
    rmap = rmap if isinstance(rmap, dict) else {}

    csv_vars = []
    for item in rmap.get("csv_variables") or []:
        if isinstance(item, dict):
            csv_vars.append(
                {
                    "id": item.get("id") or item.get("name") or item.get("field"),
                    "aliases": item.get("aliases") or [],
                    "domain": item.get("domain") or item.get("values") or {},
                    "role": item.get("role") or "free",
                    "importance": item.get("importance") or "normal",
                    "notes": "",
                }
            )
        elif item:
            csv_vars.append({"id": str(item), "aliases": [], "domain": {}, "role": "free", "importance": "normal", "notes": ""})

    csv_path = bind_dir / "csv_variables.yaml"
    if not csv_path.is_file():
        write_yaml(
            csv_path,
            {
                "version": 1,
                "status": "seed",
                "source": "harness contract_build realization_map",
                "variables": csv_vars,
                "hint": "LLM: refine domains / aliases / importance; consumer-side only without uo-query",
            },
        )

    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    key_cards = []
    for rel, payload in sorted(files.items()):
        if not str(rel).startswith("tiling/key_cards/"):
            continue
        if not isinstance(payload, dict):
            continue
        key_id = str(payload.get("id") or Path(rel).stem)
        key_cards.append(
            {
                "key_id": key_id,
                "shape_expr": payload.get("shape_expr") or "",
                "shape_determined": [],
                "csv_bindings": [],
                "confidence": "unknown",
                "needs_uo_query": True,
            }
        )

    key_shape_path = bind_dir / "key_shape_conditions.yaml"
    if not key_shape_path.is_file():
        write_yaml(
            key_shape_path,
            {
                "version": 1,
                "status": "seed",
                "keys": key_cards,
                "hint": "LLM: fill shape_expr / shape_determined via Task Follow uo-query when uncertain",
            },
        )

    code_csv_path = bind_dir / "code_csv_correspondence.yaml"
    if not code_csv_path.is_file():
        write_yaml(
            code_csv_path,
            {
                "version": 1,
                "status": "seed",
                "mappings": [],
                "hint": "LLM: map Host/Kernel symbols ↔ CSV columns (operator semantics → uo-query)",
            },
        )

    shape_det_path = bind_dir / "shape_determined.yaml"
    if not shape_det_path.is_file():
        write_yaml(
            shape_det_path,
            {
                "version": 1,
                "status": "seed",
                "variables": [],
                "hint": "Mark vars derived from KEY/shape so plan does not dump them as not-CSV-realizable free covers",
            },
        )

    uo_dir = realization / "uo_query_resolve"
    uo_dir.mkdir(parents=True, exist_ok=True)
    template = uo_dir / "_BATCH_TEMPLATE.yaml"
    if not template.is_file():
        write_yaml(
            template,
            {
                "version": 1,
                "batch_id": "example_related_keys",
                "keys": ["KEY_A", "KEY_B"],
                "task": "Follow uo-query/SKILL.md; batch related keys; write per-KEY yaml beside this file",
                "parent_rule": "Parent must NOT loop uo_kb_query CLI; open Task subagents (cap ~8)",
            },
        )

    return {
        "csv_variables": "bind/csv_variables.yaml",
        "key_shape_conditions": "bind/key_shape_conditions.yaml",
        "code_csv_correspondence": "bind/code_csv_correspondence.yaml",
        "shape_determined": "bind/shape_determined.yaml",
        "binding_lexicon": "realization/binding_lexicon.yaml",
        "domain_review": "realization/domain_review.yaml",
        "uo_query_resolve": "realization/uo_query_resolve/",
        "init_status": "init/status.yaml",
        "run_context": "init/run_context.yaml",
    }


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
