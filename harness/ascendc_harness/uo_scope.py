"""Harness-wrapped UO scope confirmation steps (no direct domain CLI)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _resolve_op_name(project: Path, op_name: str) -> str:
    name = str(op_name or "").strip()
    if name:
        return name
    # Prefer directory name of operator package
    return project.name


def run_uo_scope(
    project: Path,
    step: str,
    *,
    op_name: str = "",
    architecture: str = "arch35",
    decision: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Run one deterministic scope step under Harness control."""
    project = Path(project).expanduser().resolve()
    step_l = str(step or "").strip().lower().replace("_", "-")
    arch = str(architecture or "arch35").strip() or "arch35"
    resolved_op = _resolve_op_name(project, op_name)

    if step_l in {"scan", "macro-scan", "macro_scope_scan"}:
        from uo.scripts.macro_scope_scan import main as scan_main

        argv = [str(project), "--architecture", arch, "--op-name", resolved_op]
        code = int(scan_main(argv) or 0)
        return {
            "ok": code == 0,
            "step": "scan",
            "exit_code": code,
            "architecture": arch,
            "op_name": resolved_op,
        }

    if step_l in {"checkpoint", "review", "review-checkpoint"}:
        from uo.scripts.review_checkpoint import main as review_main

        if not decision:
            return {
                "ok": False,
                "step": "checkpoint",
                "error": "decision_required",
                "message_zh": "需要 --decision continue|revise|stop|manual_supplement",
            }
        argv = [
            str(project),
            "--gate",
            "macro_scope",
            "--decision",
            decision,
            "--op-name",
            resolved_op,
        ]
        if notes:
            argv.extend(["--notes", notes])
        code = int(review_main(argv) or 0)
        return {
            "ok": code == 0,
            "step": "checkpoint",
            "exit_code": code,
            "decision": decision,
            "op_name": resolved_op,
        }

    if step_l in {"build-evidence", "build_evidence", "extract-build-evidence"}:
        from uo.scripts.extract_build_evidence import main as build_main

        argv = [str(project), "--op-name", resolved_op]
        code = int(build_main(argv) or 0)
        return {"ok": code == 0, "step": "build-evidence", "exit_code": code, "op_name": resolved_op}

    if step_l in {"closure", "source-closure", "source_closure"}:
        from uo.scripts.source_closure import main as closure_main

        argv = [str(project), "--op-name", resolved_op, "--architecture", arch]
        code = int(closure_main(argv) or 0)
        return {"ok": code == 0, "step": "closure", "exit_code": code, "op_name": resolved_op}

    if step_l in {"stage", "stage-cbm", "stage_cbm_scope"}:
        from uo.scripts.stage_cbm_scope import main as stage_main

        argv = [str(project), "--op-name", resolved_op]
        code = int(stage_main(argv) or 0)
        return {"ok": code == 0, "step": "stage", "exit_code": code, "op_name": resolved_op}

    if step_l in {"finalize", "finalize-scope", "finalize_scope"}:
        from uo.scripts.finalize_scope import main as finalize_main

        argv = [str(project), "--op-name", resolved_op]
        code = int(finalize_main(argv) or 0)
        return {"ok": code == 0, "step": "finalize", "exit_code": code, "op_name": resolved_op}

    return {
        "ok": False,
        "error": "unknown_step",
        "message_zh": (
            "未知 step；可用: scan | checkpoint | build-evidence | closure | stage | finalize"
        ),
        "step": step,
    }


def print_result(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1
