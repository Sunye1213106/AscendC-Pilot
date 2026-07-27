"""Fast paths for expensive UO deterministic actions.

The module is intentionally outside the core UO engine so it can reject provable
no-op rebuilds before ``build_layered_kb`` is imported, and keep closure rechecks
validation-only. Any uncertain rebuild condition delegates to the canonical engine.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

EngineFallback = Callable[..., dict[str, Any]]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _write_yaml_if_changed(path: Path, payload: dict[str, Any]) -> bool:
    import yaml

    rendered = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == rendered:
                return False
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True


def _stat_fingerprint(paths: list[Path], *, run_id: str) -> str:
    rows: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            st = path.stat()
            rows.append((path.name, int(st.st_size), int(st.st_mtime_ns)))
        except OSError:
            rows.append((path.name, -1, -1))
    raw = json.dumps({"run_id": run_id, "files": rows}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _uo_context(project_root: Path, ctx: dict[str, Any]) -> tuple[Path, str, str]:
    from ascendc_pilot.paths import uo_root

    uo = uo_root(project_root)
    manifest = _read_yaml(uo / "manifest.yaml")
    op_name = str(ctx.get("op_name") or manifest.get("op_name") or project_root.name).strip()
    architecture = str(ctx.get("architecture") or manifest.get("architecture") or "arch35").strip()
    return uo, op_name, architecture


def _fast_rebuild_if_safe(
    project_root: Path,
    ctx: dict[str, Any],
    *,
    fallback: EngineFallback,
    workflow_id: str,
    action_id: str,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    uo, _op_name, architecture = _uo_context(project_root, ctx)
    run_id = str(ctx.get("run_id") or "").strip()
    if not run_id:
        return fallback(project_root, workflow_id, action_id, ctx=ctx)

    try:
        from uo.scripts.evidence_score import _source_snapshot_hash
        from uo.scripts.llm_tasks import compute_semantic_stats
        from uo.scripts.semantic_resolution_ledger import should_skip_layered_rebuild

        snapshot = str(_source_snapshot_hash(uo, run_id=run_id) or "")
        if not snapshot:
            return fallback(project_root, workflow_id, action_id, ctx=ctx)
        skip = should_skip_layered_rebuild(
            uo,
            architecture=architecture,
            source_snapshot=snapshot,
            current_run_id=run_id,
        )
        stats = compute_semantic_stats(uo, current_run_id=run_id)
    except Exception:  # noqa: BLE001
        return fallback(project_root, workflow_id, action_id, ctx=ctx)

    if not bool(skip.get("skip")) or int(stats.get("unconsumed_patch_count") or 0) != 0:
        return fallback(project_root, workflow_id, action_id, ctx=ctx)

    ir = uo / "ir"
    entrypoint = _read_yaml(ir / "entrypoint_graph.yaml")
    operator_graph = _read_yaml(ir / "operator_graph.yaml")
    closure = entrypoint.get("closure") if isinstance(entrypoint.get("closure"), dict) else {}
    blocking = int(stats.get("blocking_gap_count") or 0)
    host_closed = closure.get("host_main_chain") == "closed"
    kernel_closed = closure.get("kernel_main_chain") == "closed"
    has_open_problem = blocking > 0 or not host_closed or not kernel_closed
    elapsed = int((time.perf_counter() - t0) * 1000)
    receipt = {
        "version": 1,
        "status": "skipped_zero_delta",
        "run_id": run_id,
        "source_snapshot_hash": snapshot,
        "rebuild_input_fingerprint": (
            skip.get("rebuild_input_fingerprint") or {}
        ).get("fingerprint"),
        "materializable_delta_count": int(skip.get("materializable_delta_count") or 0),
        "unconsumed_patch_count": 0,
        "timing_ms": {"preflight": elapsed, "total": elapsed},
    }
    _write_yaml_if_changed(ir / "rebuild_fastpath.yaml", receipt)
    return {
        "ok": True,
        "engine": "rebuild_from_ledger",
        "fast_path": "zero_delta_preflight",
        "source_snapshot_hash": snapshot,
        "node_count": len(operator_graph.get("nodes") or []),
        "edge_count": len(operator_graph.get("edges") or []),
        "closure": closure,
        "materialized_patch_count": 0,
        "materializable_delta_count": 0,
        "unconsumed_patch_count": 0,
        "build_layered_kb_invoked": False,
        "large_yaml_reexported": False,
        "rebuild_skipped": True,
        "layers_rebuilt": [],
        "layer_rebuild_mode": "noop",
        "blocking_before": blocking,
        "blocking_after": blocking,
        "semantic_progress": not has_open_problem,
        "NO_SEMANTIC_PROGRESS": has_open_problem,
        "timing_ms": receipt["timing_ms"],
        **stats,
    }


def _fast_recheck_closure(
    project_root: Path,
    ctx: dict[str, Any],
    *,
    fallback: EngineFallback,
    workflow_id: str,
    action_id: str,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    uo, op_name, _architecture = _uo_context(project_root, ctx)
    run_id = str(ctx.get("run_id") or "").strip()
    if not run_id:
        return fallback(project_root, workflow_id, action_id, ctx=ctx)

    ir = uo / "ir"
    watched = [
        ir / "entrypoint_graph.yaml",
        ir / "llm_tasks.yaml",
        ir / "semantic_resolution_ledger.yaml",
        ir / "semantic_apply_report.yaml",
        ir / "semantic_task_triage.yaml",
    ]
    input_fp = _stat_fingerprint(watched, run_id=run_id)
    summary_path = ir / "closure_summary.yaml"
    previous = _read_yaml(summary_path)
    previous_result = previous.get("result") if isinstance(previous.get("result"), dict) else {}

    if previous.get("input_fingerprint") == input_fp and previous_result.get("ok") is True:
        out = dict(previous_result)
        out["cache_hit"] = True
        out["timing_ms"] = {
            "fingerprint": int((time.perf_counter() - t0) * 1000),
            "total": int((time.perf_counter() - t0) * 1000),
        }
        return out

    if previous.get("input_fingerprint") == input_fp and previous_result.get("ok") is False:
        out = dict(previous_result)
        out.update(
            {
                "ok": False,
                "engine": "recheck_closure",
                "error": "NO_PROGRESS_RECHECK",
                "cache_hit": True,
                "attempts_unchanged": True,
            }
        )
        reason_codes = list(out.get("reason_codes") or [])
        if "NO_PROGRESS_RECHECK" not in reason_codes:
            reason_codes.append("NO_PROGRESS_RECHECK")
        out["reason_codes"] = reason_codes
        out["timing_ms"] = {
            "fingerprint": int((time.perf_counter() - t0) * 1000),
            "total": int((time.perf_counter() - t0) * 1000),
        }
        return out

    try:
        from ascendc_pilot.recovery import recoveries_for_closure_gaps
        from ascendc_pilot.state import load_state
        from uo.scripts.llm_tasks import compute_semantic_stats

        entrypoint = _read_yaml(ir / "entrypoint_graph.yaml")
        closure = entrypoint.get("closure") if isinstance(entrypoint.get("closure"), dict) else {}
        stats = compute_semantic_stats(uo, current_run_id=run_id)
        blocking = int(stats.get("blocking_gap_count") or 0)
        unconsumed = int(stats.get("unconsumed_patch_count") or 0)
        host_closed = closure.get("host_main_chain") == "closed"
        kernel_closed = closure.get("kernel_main_chain") == "closed"
        triage = _read_yaml(ir / "semantic_task_triage.yaml")
        triage_stats = triage.get("stats") if isinstance(triage.get("stats"), dict) else {}
        post_provisional = int(triage_stats.get("post_semantic_provisional_count") or 0)
        route_none = int(triage_stats.get("blocking_route_none_count") or 0)
        ok = (
            blocking == 0
            and unconsumed == 0
            and host_closed
            and kernel_closed
            and post_provisional == 0
            and route_none == 0
        )
        state = load_state(project_root) or {}
        routed = recoveries_for_closure_gaps(
            host_closed=host_closed,
            kernel_closed=kernel_closed,
            blocking_gap_count=blocking + post_provisional + route_none,
            unconsumed_patch_count=unconsumed,
            no_progress=False,
            workflow_id=str(state.get("workflow_id") or workflow_id or "uo-init"),
            current_phase=str(state.get("phase") or ctx.get("phase") or "extract"),
        )
    except Exception:  # noqa: BLE001
        return fallback(project_root, workflow_id, action_id, ctx=ctx)

    integrity_doc = _read_yaml(uo / "checks" / "integrity.yaml")
    elapsed = int((time.perf_counter() - t0) * 1000)
    out: dict[str, Any] = {
        "ok": ok,
        "engine": "recheck_closure",
        "fast_path": "closure_only",
        "cache_hit": False,
        "closure": closure,
        "open_blocking_count": blocking,
        "blocking_gap_count": blocking,
        "unconsumed_patch_count": unconsumed,
        "post_semantic_provisional_count": post_provisional,
        "blocking_route_none_count": route_none,
        "integrity_status": integrity_doc.get("status") or "deferred_to_export_integrity",
        "integrity_recomputed": False,
        "attempts_unchanged": True,
        "fingerprint": input_fp,
        "timing_ms": {"total": elapsed},
        **stats,
    }
    if not ok:
        out["recovery_actions"] = list(routed.get("recovery_actions") or [])
        out["recoveries"] = list(routed.get("recoveries") or [])
        out["reason_codes"] = list(routed.get("reason_codes") or [])

    _write_yaml_if_changed(
        summary_path,
        {
            "version": 1,
            "op_name": op_name,
            "run_id": run_id,
            "input_fingerprint": input_fp,
            "integrity_policy": "read_existing_only; full check runs in export_integrity",
            "result": out,
        },
    )
    return out


def invoke_fast_uo_engine(
    project_root: Path,
    workflow_id: str,
    action_id: str,
    *,
    ctx: dict[str, Any] | None,
    fallback: EngineFallback,
) -> dict[str, Any]:
    """Route only proven-safe UO fast paths; delegate every uncertain case."""
    payload = dict(ctx or {})
    if workflow_id == "uo-init" and action_id == "rebuild_from_ledger":
        return _fast_rebuild_if_safe(
            Path(project_root),
            payload,
            fallback=fallback,
            workflow_id=workflow_id,
            action_id=action_id,
        )
    if workflow_id == "uo-init" and action_id == "recheck_closure":
        return _fast_recheck_closure(
            Path(project_root),
            payload,
            fallback=fallback,
            workflow_id=workflow_id,
            action_id=action_id,
        )
    return fallback(project_root, workflow_id, action_id, ctx=payload)
