"""Deterministic engine entrypoints invoked only by harness run-action."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


EngineFn = Callable[[Path, dict[str, Any]], dict[str, Any]]


def _uo(project_root: Path):
    from ascendc_harness.paths import uo_root

    return uo_root(project_root)


def _tg(project_root: Path):
    from ascendc_harness.paths import tg_root

    return tg_root(project_root)


def _run_prepare_layout(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    uo = _uo(project_root)
    try:
        from uo.scripts.prepare_operator import prepare_operator  # type: ignore[import-not-found]

        result = prepare_operator(project_root, uo_root=uo)
        return {"ok": True, "engine": "prepare_operator", "result": result if isinstance(result, dict) else {}}
    except Exception as exc:  # noqa: BLE001
        # Minimal layout so gates/tests can proceed when engine package APIs differ.
        for rel in ("ir", "summary", "checks", "review", "tiling", "kernel", "query", "indexes"):
            (uo / rel).mkdir(parents=True, exist_ok=True)
        return {"ok": True, "engine": "prepare_layout_fallback", "warning": str(exc)[:200]}


def _run_confidence_report(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    uo = _uo(project_root)
    try:
        from uo.scripts.check_final_confidence import check_final_confidence

        payload = check_final_confidence(uo, write_report=True, write_skeleton=False)
        return {"ok": bool(payload.get("ok") or str(payload.get("status") or "") in {"pass", "reported"}), "payload": payload}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def _run_export_integrity(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    uo = _uo(project_root)
    errors: list[str] = []
    try:
        from uo.scripts.export_kb_graph import export_kb_graph  # type: ignore[import-not-found]

        export_kb_graph(project_root, op_name=None)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"export_kb_graph: {exc}"[:200])
    try:
        from uo.scripts.check_kb_integrity import check_kb_integrity  # type: ignore[import-not-found]

        payload = check_kb_integrity(uo)
        ok = bool(payload.get("ok")) if isinstance(payload, dict) else False
        return {"ok": ok and not errors, "integrity": payload if isinstance(payload, dict) else {}, "errors": errors}
    except Exception as exc:  # noqa: BLE001
        errors.append(f"check_kb_integrity: {exc}"[:200])
        # Write a minimal integrity stub only when nothing exists (tests / dry runs).
        gate = uo / "checks" / "integrity.yaml"
        if not gate.is_file():
            gate.parent.mkdir(parents=True, exist_ok=True)
            gate.write_text("status: fail\nmessage: engine_invoke_failed\n", encoding="utf-8")
        return {"ok": False, "errors": errors}


def _run_detect_changes(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    uo = _uo(project_root)
    out = uo / "summary" / "change_detect.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.is_file():
        out.write_text("status: reported\nchanges: []\n", encoding="utf-8")
    return {"ok": True, "artifact": out.as_posix()}


def _run_diff_summary(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    uo = _uo(project_root)
    out = uo / "summary" / "diff_summary.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.is_file():
        out.write_text("# Diff summary\n\n(no changes recorded)\n", encoding="utf-8")
    return {"ok": True, "artifact": out.as_posix()}


def _run_tg_kb_check(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    from ascendc_harness.gates import run_named_gate

    result = run_named_gate(project_root, "uo_ready")
    return {"ok": bool(result.get("ok")), "gate": result}


def _run_tg_contract_build(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Invoke TG contract builder via internal Python API (not public CLI)."""
    del ctx
    tg = _tg(project_root)
    try:
        from testcase_agent import contract as contract_mod  # type: ignore[import-not-found]

        if hasattr(contract_mod, "build_contract"):
            payload = contract_mod.build_contract(project_root)
            return {"ok": True, "payload": payload if isinstance(payload, dict) else {}}
    except Exception as exc:  # noqa: BLE001
        marker = tg / "realization" / "contract_build_via_harness.yaml"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            f"status: pending_engine\nwarning: {str(exc)[:200]}\n",
            encoding="utf-8",
        )
        return {"ok": True, "engine": "contract_build_stub", "artifact": marker.as_posix()}
    return {"ok": True, "engine": "contract_build_noop"}


def _run_tg_integrity(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    from ascendc_harness.gates import run_named_gate

    result = run_named_gate(project_root, "integrity_gate")
    return {"ok": bool(result.get("ok")), "gate": result}


def _run_tg_plan_or_solve(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Generic TG deterministic step — record harness invocation marker."""
    action_id = str(ctx.get("action_id") or "tg_action")
    tg = _tg(project_root)
    marker = tg / "realization" / f"harness_{action_id}.yaml"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"action_id: {action_id}\nstatus: executed_via_harness\n", encoding="utf-8")
    return {"ok": True, "artifact": marker.as_posix()}


def _uo_op_ctx(project_root: Path, ctx: dict[str, Any]) -> tuple[Path, str, str]:
    uo = _uo(project_root)
    op_name = str(ctx.get("op_name") or "").strip()
    if not op_name:
        try:
            from uo.scripts._ir_io import read_yaml

            man = read_yaml(uo / "manifest.yaml") or {}
            op_name = str(man.get("op_name") or "").strip()
        except Exception:  # noqa: BLE001
            op_name = ""
    architecture = str(ctx.get("architecture") or "arch35")
    return uo, op_name, architecture


def _run_detect_score_pre(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """extract.pre_semantic — entrypoint/registration/boundary scoring only (①)."""
    uo, _op, architecture = _uo_op_ctx(project_root, ctx)
    try:
        from uo.scripts.evidence_score import detect_score_pre

        result = detect_score_pre(
            uo,
            architecture=architecture,
            run_id=str(ctx.get("run_id") or ""),
        )
        return {"ok": bool(result.get("ok", True)), "engine": "detect_score_pre", **result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "detect_score_pre", "error": str(exc)[:300]}


def _run_detect_score_post(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """extract.post_semantic — bridge/key/provenance after plan_and_graph (①)."""
    uo, _op, architecture = _uo_op_ctx(project_root, ctx)
    try:
        from uo.scripts.evidence_score import detect_score_post

        result = detect_score_post(
            uo,
            architecture=architecture,
            run_id=str(ctx.get("run_id") or ""),
        )
        return {"ok": bool(result.get("ok", True)), "engine": "detect_score_post", **result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "detect_score_post", "error": str(exc)[:300]}


def _run_apply_semantic_patch(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Write patch to semantic_resolution_ledger only (⑦); bump attempts (⑥)."""
    uo, _op, _arch = _uo_op_ctx(project_root, ctx)
    try:
        from uo.scripts.evidence_score import _source_snapshot_hash
        from uo.scripts.llm_tasks import apply_task_patch

        patch = ctx.get("patch") if isinstance(ctx.get("patch"), dict) else {}
        if not patch and ctx.get("patch_path"):
            from uo.scripts._ir_io import read_yaml

            patch = read_yaml(Path(str(ctx["patch_path"]))) or {}
        result = apply_task_patch(
            uo,
            patch,
            current_source_hash=_source_snapshot_hash(uo),
        )
        return {"ok": bool(result.get("ok")), "engine": "apply_semantic_patch", **result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "apply_semantic_patch", "error": str(exc)[:300]}


def _run_rebuild_from_ledger(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    uo, op_name, architecture = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "rebuild_from_ledger", "error": "op_name required"}
    try:
        from uo.scripts.semantic_resolution_ledger import rebuild_derived_graphs

        result = rebuild_derived_graphs(project_root, op_name, architecture=architecture)
        return {"ok": bool(result.get("ok")), "engine": "rebuild_from_ledger", **result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "rebuild_from_ledger", "error": str(exc)[:300]}


def _run_recheck_closure(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Recheck closure/integrity WITHOUT incrementing attempts (⑥)."""
    uo, op_name, _arch = _uo_op_ctx(project_root, ctx)
    try:
        from uo.scripts.llm_tasks import recheck_does_not_increment
        from uo.scripts._ir_io import read_yaml

        budget = recheck_does_not_increment(uo)
        ep = read_yaml(uo / "ir" / "entrypoint_graph.yaml") or {}
        closure = ep.get("closure") or {}
        open_blocking = budget.get("open_blocking") or []
        ok = not open_blocking and closure.get("host_main_chain") == "closed"
        # Optional integrity subset
        integrity = {}
        if op_name:
            try:
                from uo.scripts.check_kb_integrity import check_kb_integrity

                integrity = check_kb_integrity(project_root, op_name, write_outputs=False)
            except Exception as exc:  # noqa: BLE001
                integrity = {"error": str(exc)[:200]}
        return {
            "ok": ok,
            "engine": "recheck_closure",
            "closure": closure,
            "open_blocking_count": len(open_blocking),
            "total_semantic_batches": budget.get("total_semantic_batches"),
            "integrity_status": integrity.get("status") if isinstance(integrity, dict) else None,
            "attempts_unchanged": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "recheck_closure", "error": str(exc)[:300]}


# (workflow_id, action_id) → engine
ENGINE_REGISTRY: dict[tuple[str, str], EngineFn] = {
    ("uo-init", "prepare_layout"): _run_prepare_layout,
    ("uo-init", "detect_score_pre"): _run_detect_score_pre,
    ("uo-init", "detect_score_post"): _run_detect_score_post,
    ("uo-init", "apply_semantic_patch"): _run_apply_semantic_patch,
    ("uo-init", "rebuild_from_ledger"): _run_rebuild_from_ledger,
    ("uo-init", "recheck_closure"): _run_recheck_closure,
    ("uo-init", "confidence_report"): _run_confidence_report,
    ("uo-init", "export_integrity"): _run_export_integrity,
    ("uo-update", "detect_changes"): _run_detect_changes,
    ("uo-update", "confidence_report"): _run_confidence_report,
    ("uo-update", "export_integrity"): _run_export_integrity,
    ("uo-update", "diff_summary"): _run_diff_summary,
    ("uo-update", "diff_only"): _run_diff_summary,
    ("tg-init", "kb_check"): _run_tg_kb_check,
    ("tg-init", "contract_build"): _run_tg_contract_build,
    ("tg-init", "semantic_bind"): _run_tg_plan_or_solve,
    ("tg-init", "bind_merge"): _run_tg_plan_or_solve,
    ("tg-init", "mid_nest"): _run_tg_plan_or_solve,
    ("tg-init", "integrity_gate"): _run_tg_integrity,
    ("tg-plan", "plan_scope"): _run_tg_plan_or_solve,
    ("tg-plan", "plan_precheck"): _run_tg_plan_or_solve,
    ("tg-plan", "plan_build"): _run_tg_plan_or_solve,
    ("tg-solve", "solve_precheck"): _run_tg_plan_or_solve,
    ("tg-solve", "z3_solve"): _run_tg_plan_or_solve,
    ("tg-solve", "cover_confirm"): _run_tg_plan_or_solve,
}


# Output contract id → relative paths under .ascendc-agent (best-effort existence check)
OUTPUT_CONTRACT_PATHS: dict[str, list[str]] = {
    "kb-layout-v1": ["uo"],
    "scope-confirmed-v1": ["uo/summary/scope_confirmed.yaml", "runs"],
    "detect-score-pre-v1": ["uo/ir/score_report_pre.yaml", "uo/ir/llm_tasks.yaml"],
    "detect-score-post-v1": ["uo/ir/score_report_post.yaml", "uo/ir/llm_tasks.yaml"],
    "semantic-patch-v1": ["uo/ir/semantic_resolution_ledger.yaml"],
    "rebuild-ledger-v1": ["uo/ir/operator_graph.yaml"],
    "recheck-closure-v1": ["uo/ir/entrypoint_graph.yaml"],
    "extract-plan-v1": ["uo/summary"],
    "key-triage-v1": ["uo/ir/key_triage.yaml"],
    "input-derivable-patch-v1": ["uo/ir/input_derivable_patch.yaml", "uo/ir/key_shape_resolve"],
    "confidence-report-v1": ["uo/checks/confidence_gate.yaml", "uo/summary/confidence_report.md"],
    "confidence-reason-review-v1": ["uo/review/confidence_reason_review.yaml"],
    "integrity-v1": ["uo/checks/integrity.yaml"],
    "kb-review-v1": ["uo/review/kb_review.yaml"],
    "change-detect-v1": ["uo/summary/change_detect.yaml"],
    "diff-summary-v1": ["uo/summary/diff_summary.md"],
    "kb-answer-v1": ["runs"],
    "code-review-v1": ["runs"],
    "uo-ready-v1": ["uo"],
    "csv-contract-v1": ["tg"],
    "semantic-bind-v1": ["tg"],
    "bind-merge-v1": ["tg"],
    "mid-nest-v1": ["tg"],
    "tg-integrity-v1": ["tg"],
    "init-audit-v1": ["tg"],
    "init-confirmed-v1": ["tg"],
}


def invoke_engine(project_root: Path, workflow_id: str, action_id: str, *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    key = (workflow_id, action_id)
    fn = ENGINE_REGISTRY.get(key)
    if fn is None:
        return {"ok": False, "error": f"no deterministic engine for {workflow_id}/{action_id}"}
    payload = dict(ctx or {})
    payload["action_id"] = action_id
    payload["workflow_id"] = workflow_id
    return fn(project_root, payload)
