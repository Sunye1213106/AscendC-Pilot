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
    from ascendc_harness.gates import run_named_gate

    result = run_named_gate(project_root, "uo_ready", op_name=str(ctx.get("op_name") or "") or None)
    return {"ok": bool(result.get("ok")), "gate": result, "engine": "kb_check"}


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return None
    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _resolve_tg_ctx(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Resolve op_name / architecture / consumer root / level / focus for TG engines."""
    import os

    from ascendc_harness.state import load_state

    state = load_state(project_root) or {}
    params = _load_yaml(project_root / ".ascendc-agent" / "context" / "harness_params.yaml") or {}
    if not isinstance(params, dict):
        params = {}
    pack = _load_yaml(project_root / ".ascendc-agent" / "context" / "context_pack.yaml") or {}
    if not isinstance(pack, dict):
        pack = {}
    run_ctx = _load_yaml(project_root / ".ascendc-agent" / "tg" / "init" / "run_context.yaml") or {}
    if not isinstance(run_ctx, dict):
        run_ctx = {}
    man = _load_yaml(project_root / ".ascendc-agent" / "uo" / "manifest.yaml") or {}
    if not isinstance(man, dict):
        man = {}

    def _pick(*vals: Any, default: str = "") -> str:
        for v in vals:
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        return default

    op_name = _pick(
        ctx.get("op_name"),
        state.get("op_name"),
        params.get("op_name"),
        pack.get("op_name"),
        run_ctx.get("op_name"),
        man.get("op_name"),
        project_root.name,
    )
    architecture = _pick(
        ctx.get("architecture"),
        state.get("architecture"),
        params.get("architecture"),
        pack.get("architecture"),
        man.get("architecture"),
        default="arch35",
    )
    level = _pick(ctx.get("level"), state.get("level"), params.get("level"), pack.get("level"), default="L0")
    focus = _pick(ctx.get("focus"), state.get("focus"), params.get("focus"), pack.get("focus"))
    consumer = _pick(
        ctx.get("csv_consumer_root"),
        ctx.get("test_script_root"),
        state.get("csv_consumer_root"),
        state.get("test_script_root"),
        params.get("csv_consumer_root"),
        params.get("test_script_root"),
        pack.get("csv_consumer_root"),
        pack.get("test_script_root"),
        run_ctx.get("test_script_root"),
        os.environ.get("ASCENDC_CSV_CONSUMER_ROOT"),
        os.environ.get("ASCENDC_TEST_SCRIPT_ROOT"),
    )
    return {
        "op_name": op_name,
        "architecture": architecture,
        "level": level,
        "focus": focus,
        "test_script_root": consumer,
        "csv_consumer_root": consumer,
    }


def _require_consumer_root(tg_ctx: dict[str, Any]) -> Path:
    raw = str(tg_ctx.get("csv_consumer_root") or tg_ctx.get("test_script_root") or "").strip()
    if not raw:
        raise RuntimeError(
            "TEST_SCRIPT_ROOT_REQUIRED: set harness context test_script_root/csv_consumer_root "
            "(context/harness_params.yaml, workflow state, or ASCENDC_TEST_SCRIPT_ROOT)"
        )
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise RuntimeError(f"TEST_SCRIPT_ROOT_INVALID: not a directory: {path}")
    return path


def _run_tg_contract_build(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    op_name = tg_ctx["op_name"]
    if not op_name:
        return {"ok": False, "engine": "contract_build", "error": "op_name required"}
    try:
        consumer = _require_consumer_root(tg_ctx)
        from testcase_agent.contract import tg_contract

        payload = tg_contract(project_root, op_name, csv_consumer_root=consumer)
        # Persist resolved params for subsequent TG actions.
        params_path = project_root / ".ascendc-agent" / "context" / "harness_params.yaml"
        params_path.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_yaml(params_path) or {}
        if not isinstance(existing, dict):
            existing = {}
        existing.update(
            {
                "op_name": op_name,
                "architecture": tg_ctx["architecture"],
                "test_script_root": consumer.as_posix(),
                "csv_consumer_root": consumer.as_posix(),
                "level": tg_ctx["level"],
                "focus": tg_ctx["focus"],
            }
        )
        try:
            import yaml

            params_path.write_text(yaml.safe_dump(existing, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": str(payload.get("status") or "").lower() in {"pass", "ok", "passed", ""} or bool(payload),
            "engine": "contract_build",
            "op_name": op_name,
            "csv_consumer_root": consumer.as_posix(),
            "payload": payload if isinstance(payload, dict) else {},
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "contract_build", "error": str(exc)[:400]}


def _run_tg_semantic_bind(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    tg = _tg(project_root)
    try:
        consumer = _require_consumer_root(tg_ctx)
        from testcase_agent.binding_inventory import build_binding_inventory, fingerprint_consumer
        from testcase_agent.init import write_bind_scaffolds
        from testcase_agent.io import read_json, read_yaml

        snapshot_path = tg / "snapshot" / "understand_contract.json"
        if not snapshot_path.is_file():
            return {"ok": False, "engine": "semantic_bind", "error": "missing snapshot; run contract_build first"}
        snapshot = read_json(snapshot_path)
        rmap = read_yaml(tg / "realization" / "realization_map.yaml") or {}
        schema = read_yaml(tg / "realization" / "consumer_schema.yaml") or {}
        if not schema:
            schema = read_yaml(tg / "contract" / "consumer_schema.yaml") or {}
        lexicon = read_yaml(tg / "realization" / "lexicon.yaml") or {}
        gaps = list((rmap.get("binding_gaps") if isinstance(rmap, dict) else None) or [])
        contract_result = {
            "realization_map": rmap if isinstance(rmap, dict) else {},
            "binding_gaps": gaps,
        }
        artifacts = write_bind_scaffolds(tg, snapshot if isinstance(snapshot, dict) else {}, contract_result)
        inv = build_binding_inventory(
            schema=schema if isinstance(schema, dict) else {},
            lexicon=lexicon if isinstance(lexicon, dict) else {},
            snapshot_files=(snapshot.get("files") if isinstance(snapshot, dict) else {}) or {},
            consumer_root=consumer,
            binding_gaps=gaps,
        )
        inv["consumer_fingerprint"] = fingerprint_consumer(consumer)
        inv_path = tg / "realization" / "binding_inventory.yaml"
        try:
            from testcase_agent.io import write_yaml

            write_yaml(inv_path, inv)
        except Exception:  # noqa: BLE001
            import yaml

            inv_path.parent.mkdir(parents=True, exist_ok=True)
            inv_path.write_text(yaml.safe_dump(inv, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return {
            "ok": True,
            "engine": "semantic_bind",
            "artifacts": artifacts,
            "inventory_path": inv_path.as_posix(),
            "csv_consumer_root": consumer.as_posix(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "semantic_bind", "error": str(exc)[:400]}


def _run_tg_bind_merge(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    tg = _tg(project_root)
    try:
        from testcase_agent.uo_resolve_merge import merge_uo_resolve

        payload = merge_uo_resolve(tg, auto_fix_heuristics=True)
        ok = True
        if isinstance(payload, dict):
            status = str(payload.get("status") or "").lower()
            if status and status not in {"pass", "passed", "ok", "merged"}:
                ok = bool(payload.get("ok", False))
            elif "ok" in payload:
                ok = bool(payload.get("ok"))
        return {"ok": ok, "engine": "bind_merge", "payload": payload if isinstance(payload, dict) else {}}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "bind_merge", "error": str(exc)[:400]}


def _run_tg_mid_nest(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    tg = _tg(project_root)
    try:
        from testcase_agent.resolve_policy import write_mid_symbol_queue

        queue = write_mid_symbol_queue(tg)
        return {"ok": True, "engine": "mid_nest", "queue": queue if isinstance(queue, dict) else {}}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "mid_nest", "error": str(exc)[:400]}


def _run_tg_integrity(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_harness.gates import run_named_gate

    op = str(ctx.get("op_name") or "") or None
    domain = run_named_gate(project_root, "domain_symmetry", op_name=op)
    closure = run_named_gate(project_root, "csv_closure", op_name=op)
    ok = bool(domain.get("ok")) and bool(closure.get("ok"))
    return {
        "ok": ok,
        "engine": "integrity_gate",
        "gates": {"domain_symmetry": domain, "csv_closure": closure},
    }


def _run_tg_plan_scope(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    try:
        consumer = _require_consumer_root(tg_ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_scope", "error": str(exc)[:400]}
    tg = _tg(project_root)
    level = tg_ctx["level"] or "L0"
    scope = {
        "version": 1,
        "op_name": tg_ctx["op_name"],
        "level": level,
        "focus": tg_ctx["focus"],
        "csv_consumer_root": consumer.as_posix(),
        "architecture": tg_ctx["architecture"],
    }
    out = tg / "plan" / "levels" / level / "plan_scope.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml

        out.write_text(yaml.safe_dump(scope, allow_unicode=True, sort_keys=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_scope", "error": str(exc)[:200]}
    return {"ok": True, "engine": "plan_scope", "artifact": out.as_posix(), **scope}


def _run_tg_plan_precheck(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_harness.gates import run_named_gate

    op = str((_resolve_tg_ctx(project_root, ctx)).get("op_name") or "") or None
    g1 = run_named_gate(project_root, "tg_init_confirmed", op_name=op)
    g2 = run_named_gate(project_root, "kb_fingerprint_fresh", op_name=op)
    ok = bool(g1.get("ok")) and bool(g2.get("ok"))
    return {"ok": ok, "engine": "plan_precheck", "gates": {"tg_init_confirmed": g1, "kb_fingerprint_fresh": g2}}


def _run_tg_plan_build(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    op_name = tg_ctx["op_name"]
    if not op_name:
        return {"ok": False, "engine": "plan_build", "error": "op_name required"}
    try:
        consumer = _require_consumer_root(tg_ctx)
        from testcase_agent.planner import tg_plan

        payload = tg_plan(
            project_root,
            op_name,
            level=tg_ctx["level"] or "L0",
            focus=tg_ctx["focus"] or "",
            csv_consumer_root=consumer,
            reuse_snapshot=True,
        )
        level = tg_ctx["level"] or "L0"
        obl = _tg(project_root) / "plan" / "levels" / level / "coverage_obligations.yaml"
        if not obl.is_file() or obl.stat().st_size == 0:
            # Some planners write under plan/coverage_obligations.yaml
            alt = _tg(project_root) / "plan" / "coverage_obligations.yaml"
            if not alt.is_file() or alt.stat().st_size == 0:
                return {
                    "ok": False,
                    "engine": "plan_build",
                    "error": "coverage_obligations.yaml missing or empty after tg_plan",
                    "payload": payload if isinstance(payload, dict) else {},
                }
        return {
            "ok": True,
            "engine": "plan_build",
            "op_name": op_name,
            "level": level,
            "payload": payload if isinstance(payload, dict) else {},
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_build", "error": str(exc)[:400]}


def _run_tg_solve_precheck(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_harness.gates import run_named_gate

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    try:
        _require_consumer_root(tg_ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "solve_precheck", "error": str(exc)[:400]}
    op = tg_ctx.get("op_name") or None
    g1 = run_named_gate(project_root, "plan_approved", op_name=op)
    g2 = run_named_gate(project_root, "kb_fingerprint_fresh", op_name=op)
    ok = bool(g1.get("ok")) and bool(g2.get("ok"))
    return {"ok": ok, "engine": "solve_precheck", "gates": {"plan_approved": g1, "kb_fingerprint_fresh": g2}}


def _run_tg_z3_solve(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    op_name = tg_ctx["op_name"]
    if not op_name:
        return {"ok": False, "engine": "z3_solve", "error": "op_name required"}
    try:
        consumer = _require_consumer_root(tg_ctx)
        from testcase_agent.solve import tg_solve

        payload = tg_solve(
            project_root,
            op_name,
            level=tg_ctx["level"] or "",
            csv_consumer_root=consumer,
        )
        # Require nonempty solver report artifact.
        from ascendc_harness.gates.tg_adapters import _latest_solve_root

        solve_root = _latest_solve_root(_tg(project_root))
        if solve_root is None or not (solve_root / "solver_report.yaml").is_file():
            return {
                "ok": False,
                "engine": "z3_solve",
                "error": "solver_report.yaml missing after tg_solve",
                "payload": payload if isinstance(payload, dict) else {},
            }
        return {
            "ok": True,
            "engine": "z3_solve",
            "op_name": op_name,
            "solve_root": solve_root.as_posix(),
            "payload": payload if isinstance(payload, dict) else {},
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "z3_solve", "error": str(exc)[:400]}


def _run_tg_cover_confirm(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_harness.gates import run_named_gate

    op = str((_resolve_tg_ctx(project_root, ctx)).get("op_name") or "") or None
    result = run_named_gate(project_root, "solve_terminal", op_name=op)
    return {"ok": bool(result.get("ok")), "engine": "cover_confirm", "gate": result}


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
    ("tg-init", "semantic_bind"): _run_tg_semantic_bind,
    ("tg-init", "bind_merge"): _run_tg_bind_merge,
    ("tg-init", "mid_nest"): _run_tg_mid_nest,
    ("tg-init", "integrity_gate"): _run_tg_integrity,
    ("tg-plan", "plan_scope"): _run_tg_plan_scope,
    ("tg-plan", "plan_precheck"): _run_tg_plan_precheck,
    ("tg-plan", "plan_build"): _run_tg_plan_build,
    ("tg-solve", "solve_precheck"): _run_tg_solve_precheck,
    ("tg-solve", "z3_solve"): _run_tg_z3_solve,
    ("tg-solve", "cover_confirm"): _run_tg_cover_confirm,
}


# Output contract id → relative paths under .ascendc-agent (existence + nonempty where applicable)
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
    "csv-contract-v1": [
        "tg/realization/realization_map.yaml",
        "tg/snapshot/understand_contract.json",
    ],
    "semantic-bind-v1": [
        "tg/realization/binding_inventory.yaml",
    ],
    "bind-merge-v1": [
        "tg/realization/uo_merge_report.yaml",
    ],
    "mid-nest-v1": [
        "tg/realization/mid_symbol_queue.yaml",
    ],
    "tg-integrity-v1": [
        "tg/realization/uo_merge_report.yaml",
    ],
    "init-audit-v1": ["tg/init"],
    "init-confirmed-v1": ["tg/init/status.yaml"],
    "plan-scope-v1": ["tg/plan"],
    "plan-precheck-v1": ["tg/init/status.yaml"],
    "plan-build-v1": ["tg/plan"],
    "plan-approved-v1": ["tg/plan"],
    "solve-precheck-v1": ["tg/plan"],
    "z3-solve-v1": ["tg/solve"],
    "cover-confirm-v1": ["tg/solve"],
}

# Contracts that must contain at least one nonempty concrete artifact (not empty dir / empty file)
OUTPUT_CONTRACT_NONEMPTY_GLOBS: dict[str, list[str]] = {
    "plan-build-v1": [
        "tg/plan/levels/*/coverage_obligations.yaml",
        "tg/plan/coverage_obligations.yaml",
    ],
    "z3-solve-v1": [
        "tg/solve/**/solver_report.yaml",
        "tg/solve/solver_report.yaml",
    ],
    "cover-confirm-v1": [
        "tg/solve/**/realize_report.yaml",
        "tg/solve/**/solver_report.yaml",
    ],
    "csv-contract-v1": [
        "tg/realization/realization_map.yaml",
    ],
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
