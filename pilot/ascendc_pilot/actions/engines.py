"""Deterministic engine entrypoints invoked only by acp run-action."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


EngineFn = Callable[[Path, dict[str, Any]], dict[str, Any]]


def _uo(project_root: Path):
    from ascendc_pilot.paths import uo_root

    return uo_root(project_root)


def _tg(project_root: Path):
    from ascendc_pilot.paths import tg_root

    return tg_root(project_root)


def _run_prepare_layout(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    project_root = Path(project_root).expanduser().resolve()
    uo = _uo(project_root)
    raw_op = str((ctx or {}).get("op_name") or "").strip()
    op_name = raw_op or project_root.name
    run_id = str((ctx or {}).get("run_id") or "").strip()
    if not run_id:
        return {
            "ok": False,
            "engine": "prepare_layout",
            "error": "run_id_required",
            "op_name": op_name,
            "message_zh": "prepare_layout 需要 Pilot state.run_id（一次会话一个 run id）",
        }
    try:
        from uo.scripts.prepare_operator import main as prepare_main

        argv = [str(project_root), "--op-name", op_name, "--run-id", run_id]
        code = int(prepare_main(argv) or 0)
        manifest = uo / "manifest.yaml"
        # prepare_operator exit codes:
        #   0 = ok
        #   2 = uo-init skill missing (hard)
        #   3 = plugin/skill hash drift (soft; stubs already written)
        if code == 2:
            return {
                "ok": False,
                "engine": "prepare_operator",
                "exit_code": code,
                "error": "uo-init skill missing — reinstall with install.ps1/install.sh",
                "op_name": op_name,
                "run_id": run_id,
                "message_zh": "缺少已安装的 uo-init skill，请重新执行 install",
            }
        if not manifest.is_file():
            return {
                "ok": False,
                "engine": "prepare_operator",
                "exit_code": code,
                "error": "manifest.yaml missing after prepare_operator",
                "op_name": op_name,
                "run_id": run_id,
            }
        scope_dir = uo / "runs" / run_id / "scope"
        if not scope_dir.is_dir():
            return {
                "ok": False,
                "engine": "prepare_operator",
                "exit_code": code,
                "error": "run_id_layout_mismatch",
                "op_name": op_name,
                "run_id": run_id,
                "message_zh": f"UO 未写入 runs/{run_id}/scope（run id 未与 Pilot 对齐）",
            }
        return {
            "ok": True,
            "engine": "prepare_operator",
            "exit_code": code,
            "op_name": op_name,
            "run_id": run_id,
            "manifest": manifest.as_posix(),
            "warning": "installed_skill_version_mismatch" if code == 3 else "",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "engine": "prepare_layout",
            "error": str(exc)[:400],
            "op_name": op_name,
            "run_id": run_id,
            "message_zh": "prepare_layout 失败；禁止空目录 fallback 假通过",
        }

def _run_confidence_report(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    uo = _uo(project_root)
    run_id = str((ctx or {}).get("run_id") or "")
    try:
        # Re-consume key_resolution patches into Host→KEY product before confidence.
        from uo.scripts.classify_input_derivable import classify_and_write
        from uo.scripts.check_final_confidence import check_final_confidence
        from uo.scripts.semantic_severity import grade_summary, input_derivable_closure

        id_payload = classify_and_write(uo)
        payload = check_final_confidence(uo, write_report=True, write_skeleton=False)
        closure = input_derivable_closure(uo)
        grades = grade_summary(uo, current_run_id=run_id)
        return {
            "ok": bool(payload.get("ok") or str(payload.get("status") or "") in {"pass", "reported"}),
            "payload": payload,
            "input_derivable": id_payload.get("stats") if isinstance(id_payload, dict) else {},
            "input_derivable_closed": closure,
            "severity_grades": grades,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def _run_export_integrity(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    uo = _uo(project_root)
    errors: list[str] = []
    try:
        from uo.scripts.publish_kb_products import publish_kb_products  # type: ignore[import-not-found]
        from uo.scripts._ir_io import read_yaml

        man = read_yaml(uo / "manifest.yaml") or {}
        op_name = str(man.get("op_name") or project_root.name).strip()
        payload = publish_kb_products(
            project_root,
            op_name,
            write=True,
            include_testcase_contract=True,
            include_integrity=True,
        )
        ok = bool(payload.get("ok", True))
        integrity = payload.get("integrity") if isinstance(payload.get("integrity"), dict) else {}
        if not ok:
            errors.append("publish_kb_products failed")
        return {
            "ok": ok and not errors,
            "integrity": integrity,
            "publish": payload,
            "errors": errors,
        }
    except Exception as exc:  # noqa: BLE001
        errors.append(f"publish_kb_products: {exc}"[:200])
        gate = uo / "checks" / "integrity.yaml"
        if not gate.is_file():
            gate.parent.mkdir(parents=True, exist_ok=True)
            gate.write_text("status: fail\nmessage: engine_invoke_failed\n", encoding="utf-8")
        return {"ok": False, "errors": errors}


def _run_detect_changes(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    uo, op_name, _arch = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "detect_changes", "error": "op_name required"}
    try:
        from uo.scripts.detect_kb_changes import detect_kb_changes

        payload = detect_kb_changes(project_root, op_name, write=True)
        out = uo / "diff" / "change_set.yaml"
        return {
            "ok": out.is_file(),
            "engine": "detect_changes",
            "artifact": out.as_posix() if out.is_file() else "",
            "scoped_change_count": payload.get("scoped_change_count"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "detect_changes", "error": str(exc)[:300]}


def _run_plan_update(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    uo, op_name, _arch = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "plan_update", "error": "op_name required"}
    try:
        from uo.scripts.detect_kb_changes import detect_kb_changes
        from uo.scripts.plan_kb_update import plan_kb_update
        from uo.scripts.update_artifact_io import load_change_set_if_fresh

        change_set = load_change_set_if_fresh(uo, repo_root=project_root)
        reused = change_set is not None
        if change_set is None:
            change_set = detect_kb_changes(project_root, op_name, write=True)
        plan_kb_update(project_root, op_name, change_set=change_set, write=True)
        out = uo / "summary" / "update_plan.yaml"
        return {
            "ok": out.is_file(),
            "engine": "plan_update",
            "artifact": out.as_posix() if out.is_file() else "",
            "change_set_reused": reused,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_update", "error": str(exc)[:300]}


def _run_apply_update(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    uo, op_name, _arch = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "apply_update", "error": "op_name required"}
    run_id = str((ctx or {}).get("run_id") or "").strip()
    try:
        from uo.scripts.update_operator import update_operator

        result = update_operator(
            project_root,
            op_name,
            run_id=run_id or None,
            reuse_artifacts=True,
            run_gates=False,
        )
        status = str((result or {}).get("status") or "")
        receipt_ok = any((uo / "runs").glob("*/update/receipt.yaml")) if (uo / "runs").is_dir() else False
        diff_ok = (uo / "diff" / "index.yaml").is_file() and (uo / "diff" / "change_set.yaml").is_file()
        eng_ok = status in {"pass", "blocked", "noop"} or status == "pass"
        if status == "fail":
            eng_ok = False
        return {
            "ok": eng_ok and (diff_ok or status == "blocked"),
            "engine": "apply_update",
            "receipt_present": receipt_ok,
            "diff_present": diff_ok,
            "publish_deferred": bool((result or {}).get("publish_deferred")),
            "run_id": (result.get("run_id") if isinstance(result, dict) else None) or run_id,
            "result_keys": list(result.keys())[:12] if isinstance(result, dict) else [],
            "status": status,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "apply_update", "error": str(exc)[:300]}


def _run_diff_summary(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Emit canonical diff/ product from existing change_set/update_plan when fresh."""
    uo, op_name, _arch = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "diff_summary", "error": "op_name required"}
    try:
        from uo.scripts.detect_kb_changes import detect_kb_changes
        from uo.scripts.export_diff_product import export_diff_product
        from uo.scripts.plan_kb_update import plan_kb_update
        from uo.scripts.update_artifact_io import load_change_set_if_fresh, load_update_plan_if_fresh

        change_set = load_change_set_if_fresh(uo, repo_root=project_root)
        plan = load_update_plan_if_fresh(uo, change_set=change_set) if change_set else None
        reused = change_set is not None and plan is not None
        if change_set is None:
            change_set = detect_kb_changes(project_root, op_name, write=True)
        if plan is None:
            plan = plan_kb_update(project_root, op_name, change_set=change_set, write=True)
        product = export_diff_product(
            project_root,
            op_name,
            change_set=change_set,
            update_plan=plan,
            write=True,
        )
        return {"ok": True, "engine": "diff_summary", "product": product, "artifacts_reused": reused}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "diff_summary", "error": str(exc)[:300]}


def _run_tg_kb_check(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.gates import run_named_gate

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

    from ascendc_pilot.state import load_state

    state = load_state(project_root) or {}
    params = _load_yaml(project_root / ".ascendc-pilot" / "context" / "pilot_params.yaml") or {}
    if not isinstance(params, dict):
        params = {}
    pack = _load_yaml(project_root / ".ascendc-pilot" / "context" / "context_pack.yaml") or {}
    if not isinstance(pack, dict):
        pack = {}
    run_ctx = _load_yaml(project_root / ".ascendc-pilot" / "tg" / "init" / "run_context.yaml") or {}
    if not isinstance(run_ctx, dict):
        run_ctx = {}
    man = _load_yaml(project_root / ".ascendc-pilot" / "uo" / "manifest.yaml") or {}
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
            "TEST_SCRIPT_ROOT_REQUIRED: set acp context test_script_root/csv_consumer_root "
            "(context/pilot_params.yaml, workflow state, or ASCENDC_TEST_SCRIPT_ROOT)"
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
        params_path = project_root / ".ascendc-pilot" / "context" / "pilot_params.yaml"
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
        lexicon = read_yaml(tg / "realization" / "binding_lexicon.yaml") or {}
        if not lexicon:
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
    from ascendc_pilot.gates import run_named_gate

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
    from ascendc_pilot.gates import run_named_gate

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
    from ascendc_pilot.gates import run_named_gate

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
        from ascendc_pilot.gates.tg_adapters import _latest_solve_root

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
    from ascendc_pilot.gates import run_named_gate

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
    """extract.pre_semantic — materialize entrypoint graph, then score (①).

    ``ir/entrypoint_graph.yaml`` is produced here (entrypoints layer), not by scope.
    Gate ``detect_score_pre`` requires that file after this engine runs.
    """
    uo, op_name, architecture = _uo_op_ctx(project_root, ctx)
    if not op_name:
        op_name = project_root.name
    try:
        from uo.scripts.build_layered_kb import build_layered_kb
        from uo.scripts.evidence_score import detect_score_pre

        layered = build_layered_kb(
            project_root,
            op_name,
            architecture=architecture,
            layers={"entrypoints"},
            allow_empty_plan=True,
            mode="structural",
        )
        ep_path = uo / "ir" / "entrypoint_graph.yaml"
        if not ep_path.is_file():
            return {
                "ok": False,
                "engine": "detect_score_pre",
                "error": "entrypoint_graph.yaml not written by entrypoints layer",
            }
        boundary_path = uo / "ir" / "operator_boundary.yaml"
        if not boundary_path.is_file():
            try:
                from uo.scripts.extract_operator_boundary import extract_operator_boundary

                extract_operator_boundary(project_root, op_name, architecture=architecture)
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "engine": "detect_score_pre",
                    "error": f"operator_boundary missing and extract failed: {exc}"[:300],
                }
        if not boundary_path.is_file():
            return {
                "ok": False,
                "engine": "detect_score_pre",
                "error": "operator_boundary.yaml missing after entrypoints layer",
            }
        result = detect_score_pre(
            uo,
            architecture=architecture,
            run_id=str(ctx.get("run_id") or ""),
        )
        ep = layered.get("entrypoint_graph") if isinstance(layered, dict) else {}
        nodes = (ep or {}).get("nodes") if isinstance(ep, dict) else []
        return {
            "ok": bool(result.get("ok", True)),
            "engine": "detect_score_pre",
            "entrypoint_node_count": len(nodes or []),
            "has_operator_boundary": (uo / "ir" / "operator_boundary.yaml").is_file(),
            **result,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "detect_score_pre", "error": str(exc)[:300]}


def _run_extract_plan(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """extract.plan_and_graph prepare/finalize helper.

    Prepare path (no plan yet): write ``extract_plan_candidates.yaml`` via propose.
    Finalize path (plan present): validate plan then build host/kernel/tilingkey/bridge.
    """
    uo, op_name, architecture = _uo_op_ctx(project_root, ctx)
    if not op_name:
        op_name = project_root.name
    mode = str(ctx.get("extract_plan_mode") or "").strip().lower()
    plan_path = uo / "ir" / "extract_plan.yaml"
    try:
        from uo.scripts.apply_extract_plan import apply_extract_plan
        from uo.scripts.build_layered_kb import build_layered_kb
        from uo.scripts.propose_extract_plan import propose_extract_plan

        if mode == "finalize" or (not mode and plan_path.is_file()):
            applied = apply_extract_plan(project_root, op_name, check_only=False)
            if not applied.get("ok"):
                return {
                    "ok": False,
                    "engine": "extract_plan",
                    "phase": "apply",
                    "error": "extract_plan validation failed",
                    "apply": applied,
                }
            layered = build_layered_kb(
                project_root,
                op_name,
                architecture=architecture,
                layers={"entrypoints", "host", "kernel", "tilingkey", "bridge"},
                allow_empty_plan=False,
                mode="structural",
            )
            stats = (layered or {}).get("stats") if isinstance(layered, dict) else {}
            return {
                "ok": True,
                "engine": "extract_plan",
                "phase": "build",
                "apply": applied,
                "has_host": (uo / "ir" / "host_subgraph.yaml").is_file(),
                "has_kernel": (uo / "ir" / "kernel_subgraph.yaml").is_file(),
                "has_macro_semantics": (uo / "ir" / "macro_semantics.yaml").is_file(),
                "stats": stats,
                "macro_materialization": (stats or {}).get("macro_materialization") or {},
                "timing_ms": (stats or {}).get("timing_ms") or {},
            }

        # Prepare: candidates only (LLM confirms → extract_plan.yaml)
        from uo.scripts._ir_io import read_yaml, write_yaml
        from ascendc_pilot.runs import file_sha256
        from uo.scripts.extract_plan_io import (
            build_extract_plan_candidates_summary,
            scan_candidates_section_lines,
        )
        from uo.scripts.ir_summary import count_file_lines

        cand_path = uo / "ir" / "extract_plan_candidates.yaml"
        sha_side = uo / "ir" / "extract_plan_candidates.sha256"
        force_propose = str(ctx.get("extract_plan_force_propose") or "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        reused = False
        candidates: dict[str, Any] | Any = None
        candidates_sha256 = ""

        # Rework after checker fail: keep candidates + sha (ses_0625 churn fix).
        if not force_propose and cand_path.is_file() and sha_side.is_file():
            should_reuse = plan_path.is_file()
            if not should_reuse:
                try:
                    from ascendc_pilot.state import load_state

                    st = str((load_state(project_root) or {}).get("status") or "")
                    should_reuse = st in {"rework_required", "human_required"}
                except Exception:  # noqa: BLE001
                    should_reuse = False
            if should_reuse:
                loaded = read_yaml(cand_path)
                if isinstance(loaded, dict):
                    candidates = loaded
                    candidates_sha256 = sha_side.read_text(encoding="utf-8").strip()
                    reused = bool(candidates_sha256)

        if not reused:
            candidates = propose_extract_plan(project_root, op_name, architecture=architecture)
            write_yaml(cand_path, candidates if isinstance(candidates, dict) else {"ok": False})
            candidates_sha256 = file_sha256(cand_path) or ""
            if candidates_sha256:
                sha_side.write_text(candidates_sha256 + "\n", encoding="utf-8")

        summary_path = uo / "ir" / "extract_plan_candidates.summary.yaml"
        if isinstance(candidates, dict):
            section_lines = scan_candidates_section_lines(cand_path)
            line_count = count_file_lines(cand_path)
            write_yaml(
                summary_path,
                build_extract_plan_candidates_summary(
                    candidates,
                    candidates_sha256=candidates_sha256,
                    section_lines=section_lines,
                    candidates_line_count=line_count,
                    candidates_path=cand_path,
                ),
            )
        status = str((candidates or {}).get("status") or "").lower() if isinstance(candidates, dict) else ""
        if status in {"blocked", "fail", "failed"} or (
            isinstance(candidates, dict) and candidates.get("ok") is False
        ):
            recovery = (candidates or {}).get("recovery") if isinstance(candidates, dict) else None
            recovery_cli = ""
            if isinstance(candidates, dict):
                recovery_cli = str(candidates.get("recovery_cli") or "")
                if not recovery_cli and isinstance(recovery, dict):
                    recovery_cli = str(recovery.get("cli") or "")
            return {
                "ok": False,
                "engine": "extract_plan",
                "phase": "propose",
                "error": "propose_extract_plan blocked",
                "propose": candidates,
                "candidates_path": cand_path.as_posix(),
                "candidates_sha256": candidates_sha256,
                "reused_candidates": reused,
                "recovery_cli": recovery_cli,
                "message_zh": (
                    str((recovery or {}).get("message_zh") or "propose_extract_plan 被候选预算拦住")
                    if isinstance(recovery, dict)
                    else "propose_extract_plan 被候选预算拦住"
                ),
            }
        raised = (candidates or {}).get("limits_auto_raised") if isinstance(candidates, dict) else None
        return {
            "ok": True,
            "engine": "extract_plan",
            "phase": "propose",
            "candidates_path": cand_path.as_posix(),
            "candidates_sha256": candidates_sha256,
            "reused_candidates": reused,
            "propose_status": status or "ok",
            "limits_auto_raised": raised or {},
            "limits_persisted": str((candidates or {}).get("limits_persisted") or "")
            if isinstance(candidates, dict)
            else "",
            "message_zh": (
                "rework：已复用既有 extract_plan_candidates（未 re-propose，避免 sha churn）"
                if reused
                else (
                    "已自动抬高 extract 候选预算并写入 pilot_params"
                    if raised
                    else "extract_plan candidates 已就绪"
                )
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "extract_plan", "error": str(exc)[:400]}


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
    """Apply producer patches (or auto mark_missing) into ledger; bump attempts (⑥)."""
    uo, _op, _arch = _uo_op_ctx(project_root, ctx)
    try:
        from uo.scripts._ir_io import read_yaml
        from uo.scripts.evidence_score import _source_snapshot_hash
        from uo.scripts.llm_tasks import apply_patches_batch, resolve_patches_for_apply

        run_id = str(ctx.get("run_id") or "").strip()
        if not run_id:
            return {
                "ok": False,
                "engine": "apply_semantic_patch",
                "error": "SEMANTIC_DOCUMENT_RUN_ID_MISSING",
                "message": "ctx.run_id required",
            }
        workflow_id = str(ctx.get("workflow_id") or "uo-init")
        phase = str(ctx.get("phase") or "")
        actor_id = str(ctx.get("actor_id") or "uo-semantic-resolve")
        role_id = str(ctx.get("role_id") or "producer")
        action_session_id = str(ctx.get("action_session_id") or "")
        lease_id = str(ctx.get("lease_id") or "")

        # Prefer explicit ctx.patch / patch_path; else ir/semantic_patches.yaml; else auto.
        patches_doc: dict[str, Any] | None = None
        single = ctx.get("patch") if isinstance(ctx.get("patch"), dict) else None
        if single and single.get("task_id"):
            patches_doc = {"patches": [single]}
        elif ctx.get("patch_path"):
            patches_doc = read_yaml(Path(str(ctx["patch_path"]))) or {}
        else:
            patches_path = uo / "ir" / "semantic_patches.yaml"
            if patches_path.is_file():
                patches_doc = read_yaml(patches_path) or {}

        resolved = resolve_patches_for_apply(
            uo,
            current_run_id=run_id,
            patches_doc=patches_doc,
            workflow_id=workflow_id,
        )
        if not resolved.get("ok"):
            out = {"ok": False, "engine": "apply_semantic_patch", **resolved}
            if resolved.get("error") == "SEMANTIC_PATCHES_REQUIRED":
                out["recovery_actions"] = ["adjudicate_llm_tasks", "apply_semantic_patch"]
            return out
        patches = list(resolved.get("patches") or [])
        if resolved.get("skipped") or not patches:
            # Ensure ledger artifact exists for output contract even when nothing to apply.
            ledger = uo / "ir" / "semantic_resolution_ledger.yaml"
            if not ledger.is_file():
                from uo.scripts.semantic_resolution_ledger import save_ledger

                save_ledger(
                    uo,
                    {
                        "version": 1,
                        "artifact_identity": {"run_id": run_id, "workflow_id": workflow_id},
                        "semantic_patches": [],
                        "note": "empty_skip",
                    },
                )
            return {
                "ok": True,
                "engine": "apply_semantic_patch",
                "skipped": True,
                "reason": resolved.get("reason") or "no_patches",
                "source": resolved.get("source"),
            }
        result = apply_patches_batch(
            uo,
            patches,
            current_run_id=run_id,
            current_source_hash=_source_snapshot_hash(uo, run_id=run_id),
            workflow_id=workflow_id,
            phase=phase,
            control_action_id=str(ctx.get("action_id") or "apply_semantic_patch"),
            actor_id=actor_id,
            role_id=role_id,
            action_session_id=action_session_id,
            lease_id=lease_id,
        )
        from uo.scripts.llm_tasks import compute_semantic_stats

        stats = compute_semantic_stats(uo, current_run_id=run_id)
        return {
            "ok": bool(result.get("ok")),
            "engine": "apply_semantic_patch",
            "source": resolved.get("source"),
            **result,
            **stats,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "apply_semantic_patch", "error": str(exc)[:300]}


def _run_rebuild_from_ledger(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    uo, op_name, architecture = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "rebuild_from_ledger", "error": "op_name required"}
    try:
        from uo.scripts.semantic_resolution_ledger import rebuild_derived_graphs

        run_id = str(ctx.get("run_id") or "").strip()
        result = rebuild_derived_graphs(
            project_root,
            op_name,
            architecture=architecture,
            run_id=run_id,
        )
        from uo.scripts.llm_tasks import compute_semantic_stats

        stats = compute_semantic_stats(uo, current_run_id=run_id) if uo and run_id else {}
        out = {"ok": bool(result.get("ok")), "engine": "rebuild_from_ledger", **result, **stats}
        # Surface progress / skip contract for Host observation.
        if result.get("NO_SEMANTIC_PROGRESS"):
            out["recovery_reason"] = "NO_SEMANTIC_PROGRESS"
        if result.get("macro_materialization"):
            out["macro_materialization"] = result.get("macro_materialization")
        return out
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "rebuild_from_ledger", "error": str(exc)[:300]}


def _run_apply_scope_expansion(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Audit LLM scope expansion requests and update confirmed scope."""
    uo, op_name, arch = _uo_op_ctx(project_root, ctx)
    try:
        from uo.scripts.scope_expansion import apply_scope_expansion

        result = apply_scope_expansion(
            project_root,
            op_name,
            uo_root=uo,
            architecture=arch or "arch35",
        )
        out = {"ok": bool(result.get("ok")), "engine": "apply_scope_expansion", **result}
        if result.get("ok") and result.get("new_files"):
            out["recovery_actions"] = ["detect_score_post", "rebuild_from_ledger"]
            out["next_actions"] = ["detect_score_post"]
        elif result.get("status") == "human_required":
            out["human_required"] = True
        return out
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "apply_scope_expansion", "error": str(exc)[:300]}


def _run_recheck_closure(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Recheck closure/integrity WITHOUT incrementing attempts (⑥)."""
    uo, op_name, _arch = _uo_op_ctx(project_root, ctx)
    try:
        import hashlib
        import json

        from ascendc_pilot.recovery import recoveries_for_closure_gaps
        from uo.scripts.evidence_score import _source_snapshot_hash
        from uo.scripts.llm_tasks import (
            blocking_gap_tasks,
            compute_semantic_stats,
            recheck_does_not_increment,
        )
        from uo.scripts._ir_io import read_yaml, write_yaml
        from uo.scripts.semantic_resolution_ledger import load_ledger

        run_id = str(ctx.get("run_id") or "").strip()
        if not run_id:
            return {
                "ok": False,
                "engine": "recheck_closure",
                "error": "SEMANTIC_DOCUMENT_RUN_ID_MISSING",
            }

        budget = recheck_does_not_increment(uo, current_run_id=run_id)
        ep = read_yaml(uo / "ir" / "entrypoint_graph.yaml") or {}
        closure = ep.get("closure") or {}
        stats = compute_semantic_stats(uo, current_run_id=run_id)
        gap_tasks = blocking_gap_tasks(uo, current_run_id=run_id)
        blocking_gap_count = int(stats.get("blocking_gap_count") or budget.get("blocking_gap_count") or 0)
        unconsumed = int(stats.get("unconsumed_patch_count") or 0)
        host_closed = closure.get("host_main_chain") == "closed"
        kernel_closed = closure.get("kernel_main_chain") == "closed"
        ok = blocking_gap_count == 0 and unconsumed == 0 and host_closed and kernel_closed

        snap = _source_snapshot_hash(uo, run_id=run_id)
        ledger_doc = load_ledger(uo)
        current_ledger_ids = [
            str(p.get("task_id") or "")
            for p in (ledger_doc.get("semantic_patches") or [])
            if isinstance(p, dict) and str(p.get("run_id") or "") == run_id
        ]
        current_task_ids = [
            str(t.get("task_id") or "")
            for t in (budget.get("tasks") or [])
            if isinstance(t, dict)
        ]
        effective_types = sorted(
            {
                str(t.get("effective_task_type") or t.get("type") or "")
                for t in gap_tasks
                if isinstance(t, dict)
            }
        )
        boundary = read_yaml(uo / "ir" / "operator_boundary.yaml") or {}
        scope_receipt = read_yaml(uo / "ir" / "scope_expansion_receipt.yaml") or {}
        fp_payload = {
            "run_id": run_id,
            "source_snapshot_hash": snap,
            "current_run_task_ids": sorted(current_task_ids),
            "current_run_ledger_ids": sorted(current_ledger_ids),
            "host_closure": closure.get("host_main_chain"),
            "kernel_closure": closure.get("kernel_main_chain"),
            "blocking_gap_count": blocking_gap_count,
            "unconsumed_patch_count": unconsumed,
            "effective_task_types": effective_types,
            "boundary_input_count": len(boundary.get("inputs") or []),
            "boundary_output_count": len(boundary.get("outputs") or []),
            "scope_expansion_rounds": int(scope_receipt.get("rounds") or 0),
            "patch_ids": sorted(current_ledger_ids),
        }
        fingerprint = hashlib.sha256(json.dumps(fp_payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        fp_path = uo / "ir" / "recheck_fingerprint.yaml"
        prev = read_yaml(fp_path) or {}
        prev_fp = str(prev.get("fingerprint") or "")
        no_progress = bool(prev_fp and prev_fp == fingerprint and not ok)

        from ascendc_pilot.state import load_state

        st = load_state(project_root) or {}
        current_phase = str(st.get("phase") or ctx.get("phase") or "extract")
        wid = str(st.get("workflow_id") or ctx.get("workflow_id") or "uo-init")
        routed = recoveries_for_closure_gaps(
            host_closed=host_closed,
            kernel_closed=kernel_closed,
            blocking_gap_count=blocking_gap_count,
            unconsumed_patch_count=unconsumed,
            no_progress=no_progress,
            workflow_id=wid,
            current_phase=current_phase,
            blocking_tasks=gap_tasks,
        )
        recovery_actions = list(routed.get("recovery_actions") or [])
        recoveries = list(routed.get("recoveries") or [])

        if no_progress:
            write_yaml(fp_path, {"fingerprint": fingerprint, "payload": fp_payload})
            return {
                "ok": False,
                "engine": "recheck_closure",
                "error": "NO_PROGRESS_RECHECK",
                "human_required": True,
                "deadlock_diagnosis": routed.get("deadlock_diagnosis") or ["deadlock_no_progress"],
                "closure": closure,
                "blocking_gap_count": blocking_gap_count,
                "unconsumed_patch_count": unconsumed,
                "recovery_actions": recovery_actions,
                "recoveries": recoveries,
                "reason_codes": routed.get("reason_codes") or ["NO_PROGRESS_RECHECK"],
                "fingerprint": fingerprint,
                "attempts_unchanged": True,
                **stats,
            }
        write_yaml(fp_path, {"fingerprint": fingerprint, "payload": fp_payload})

        out = {
            "ok": ok,
            "engine": "recheck_closure",
            "closure": closure,
            "open_blocking_count": len(budget.get("open_blocking") or []),
            "blocking_gap_count": blocking_gap_count,
            "unconsumed_patch_count": unconsumed,
            "total_semantic_batches": budget.get("total_semantic_batches"),
            "integrity_status": "deferred_to_export_integrity",
            "integrity_recomputed": False,
            "attempts_unchanged": True,
            "fingerprint": fingerprint,
            **stats,
        }
        if not ok:
            out["recovery_actions"] = recovery_actions
            out["recoveries"] = recoveries
            out["reason_codes"] = routed.get("reason_codes") or []
        return out
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "recheck_closure", "error": str(exc)[:300]}


# (workflow_id, action_id) → engine
ENGINE_REGISTRY: dict[tuple[str, str], EngineFn] = {
    ("uo-init", "prepare_layout"): _run_prepare_layout,
    ("uo-init", "detect_score_pre"): _run_detect_score_pre,
    ("uo-init", "extract_plan"): _run_extract_plan,
    ("uo-init", "detect_score_post"): _run_detect_score_post,
    ("uo-init", "apply_semantic_patch"): _run_apply_semantic_patch,
    ("uo-init", "apply_scope_expansion"): _run_apply_scope_expansion,
    ("uo-init", "rebuild_from_ledger"): _run_rebuild_from_ledger,
    ("uo-init", "recheck_closure"): _run_recheck_closure,
    ("uo-init", "confidence_report"): _run_confidence_report,
    ("uo-init", "export_integrity"): _run_export_integrity,
    ("uo-update", "detect_changes"): _run_detect_changes,
    ("uo-update", "plan_update"): _run_plan_update,
    ("uo-update", "apply_update"): _run_apply_update,
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


# Output contract id → relative paths under .ascendc-pilot (existence + nonempty where applicable)
OUTPUT_CONTRACT_PATHS: dict[str, list[str]] = {
    "kb-layout-v1": ["uo/manifest.yaml"],
    # Canonical run-scoped artifacts (never uo/summary/ — summary is human export only)
    "scope-confirmed-v1": [
        "uo/runs/{run_id}/scope/scope_confirmed.yaml",
        "uo/runs/{run_id}/scope/receipt.yaml",
        "uo/cbm/index_meta.json",
    ],
    "detect-score-pre-v1": [
        "uo/ir/entrypoint_graph.yaml",
        "uo/ir/operator_boundary.yaml",
        "uo/ir/score_report_pre.yaml",
        "uo/ir/llm_tasks.yaml",
    ],
    "detect-score-post-v1": [
        "uo/ir/score_report_post.yaml",
        "uo/ir/llm_tasks.yaml",
        "uo/ir/semantic_task_triage.yaml",
    ],
    "semantic-patches-v1": ["uo/ir/semantic_patches.yaml"],
    "semantic-patch-v1": ["uo/ir/semantic_resolution_ledger.yaml"],
    "scope-expansion-v1": ["uo/ir/scope_expansion_receipt.yaml"],
    "rebuild-ledger-v1": ["uo/ir/entrypoint_graph.yaml", "uo/ir/operator_graph.yaml"],
    # Recheck is validation-only; required state under inspection
    "recheck-closure-v1": ["uo/ir/entrypoint_graph.yaml", "uo/ir/llm_tasks.yaml"],
    "extract-plan-v1": [
        "uo/ir/extract_plan.yaml",
        "uo/ir/extract_plan_candidates.yaml",
        "uo/ir/host_subgraph.yaml",
        "uo/ir/kernel_subgraph.yaml",
        "uo/ir/macro_semantics.yaml",
    ],
    "key-triage-v1": ["uo/ir/key_triage.yaml"],
    # Shape staging is optional; patch is the producer contract
    "input-derivable-patch-v1": ["uo/ir/input_derivable_patch.yaml"],
    "confidence-report-v1": ["uo/checks/confidence_gate.yaml", "uo/summary/confidence_report.md"],
    "confidence-reason-review-v1": ["uo/review/confidence_reason_review.yaml"],
    "integrity-v1": ["uo/checks/integrity.yaml"],
    "kb-review-v1": ["uo/review/kb_product_review.yaml"],
    "change-detect-v1": ["uo/diff/change_set.yaml"],
    "update-plan-v1": ["uo/summary/update_plan.yaml"],
    "update-apply-v1": [
        "uo/runs/{run_id}/update/receipt.yaml",
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
    ],
    "diff-summary-v1": [
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
        "uo/diff/impact.yaml",
        "uo/diff/unresolved.yaml",
    ],
    # kb-answer / uo-ready: readiness precondition (existing KB), not answer/write payload.
    "kb-answer-v1": ["uo/manifest.yaml", "uo/checks/integrity.yaml"],
    "code-review-v1": [
        "ce/review/index.yaml",
        "ce/review/functional_report.yaml",
        "ce/review/bug_report.yaml",
    ],
    "uo-ready-v1": ["uo/manifest.yaml", "uo/checks/integrity.yaml"],
    "csv-contract-v1": [
        "tg/snapshot/understand_contract.json",
        "tg/realization/realization_map.yaml",
        "tg/realization/binding_inventory.yaml",
        "tg/realization/llm_bind_prompt_bundle.yaml",
        "tg/realization/binding_gaps.yaml",
        "tg/realization/unresolved.yaml",
    ],
    "semantic-bind-v1": [
        "tg/realization/binding_inventory.yaml",
        "tg/realization/semantic_bind_apply.yaml",
        "tg/realization/binding_lexicon.yaml",
        "tg/realization/unresolved.yaml",
    ],
    "semantic-bind-patch-v1": [
        "tg/realization/semantic_bind_patch.yaml",
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
    "init-audit-v1": ["tg/init/audit_report.yaml"],
    "init-confirmed-v1": ["tg/init/status.yaml"],
    "plan-scope-v1": ["tg/plan/levels/*/plan_scope.yaml"],
    "plan-precheck-v1": ["tg/init/status.yaml"],
    "plan-build-v1": ["tg/plan"],
    "plan-approved-v1": ["tg/plan/levels/*/human_supplement.yaml"],
    "solve-precheck-v1": ["tg/plan/levels/*/human_supplement.yaml"],
    "z3-solve-v1": ["tg/solve"],
    "cover-confirm-v1": [
        "tg/solve/**/realize_report.yaml",
        "tg/solve/**/solver_report.yaml",
    ],
}

# Contracts that must contain at least one nonempty concrete artifact (not empty dir / empty file)
OUTPUT_CONTRACT_NONEMPTY_GLOBS: dict[str, list[str]] = {
    "scope-confirmed-v1": [
        "uo/runs/{run_id}/scope/scope_confirmed.yaml",
        "uo/runs/{run_id}/scope/receipt.yaml",
        "uo/cbm/index_meta.json",
    ],
    "extract-plan-v1": [
        "uo/ir/extract_plan.yaml",
        "uo/ir/extract_plan_candidates.yaml",
        "uo/ir/host_subgraph.yaml",
        "uo/ir/kernel_subgraph.yaml",
    ],
    "change-detect-v1": [
        "uo/diff/change_set.yaml",
    ],
    "update-plan-v1": [
        "uo/summary/update_plan.yaml",
    ],
    "update-apply-v1": [
        "uo/runs/{run_id}/update/receipt.yaml",
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
    ],
    "diff-summary-v1": [
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
        "uo/diff/impact.yaml",
        "uo/diff/unresolved.yaml",
    ],
    "kb-review-v1": [
        "uo/review/kb_product_review.yaml",
    ],
    "code-review-v1": [
        "ce/review/index.yaml",
        "ce/review/functional_report.yaml",
        "ce/review/bug_report.yaml",
    ],
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
    "semantic-bind-v1": [
        "tg/realization/semantic_bind_apply.yaml",
        "tg/realization/binding_inventory.yaml",
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
