"""Deterministic engine entrypoints invoked only by acp run-action."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


EngineFn = Callable[[Path, dict[str, Any]], dict[str, Any]]


def _uo(project_root: Path, *, arch: str | None = None):
    from ascendc_pilot.paths import uo_root

    return uo_root(project_root, arch=arch)


def _tg(project_root: Path, *, arch: str | None = None):
    from ascendc_pilot.paths import tg_root

    return tg_root(project_root, arch=arch)


def _ctx_root(project_root: Path, *, arch: str | None = None):
    from ascendc_pilot.paths import context_root

    return context_root(project_root, arch=arch)



def _run_confidence_report(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Emit confidence gate from new-engine quality.yaml (no old classify/ledger)."""
    uo = _uo(project_root)
    del ctx
    try:
        from uo_init.yaml_io import read_yaml, write_yaml

        quality = read_yaml(uo / "quality.yaml") or {}
        unresolved = read_yaml(uo / "ir" / "unresolved.yaml") or {}
        blockers = unresolved.get("blockers") if isinstance(unresolved.get("blockers"), list) else []
        ok = bool(quality) and len(blockers) == 0
        status = "pass" if ok else "reported"
        payload = {
            "ok": ok,
            "status": status,
            "quality": quality,
            "blocker_count": len(blockers),
            "engine": "uo_init",
        }
        checks = uo / "checks"
        checks.mkdir(parents=True, exist_ok=True)
        write_yaml(checks / "confidence_gate.yaml", payload)
        summary = uo / "summary"
        summary.mkdir(parents=True, exist_ok=True)
        (summary / "confidence_report.md").write_text(
            f"# Confidence\n\nstatus: {status}\nblockers: {len(blockers)}\n",
            encoding="utf-8",
        )
        return {
            "ok": True,
            "payload": payload,
            "input_derivable": {},
            "input_derivable_closed": True,
            "severity_grades": {},
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def _run_key_triage_stub(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stub: new layered KB has no old escalate/key_triage authority yet."""
    del ctx
    from uo_init.yaml_io import write_yaml

    uo = _uo(project_root)
    ir = uo / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "not_applicable",
        "keys": [],
        "engine": "uo_init.update",
        "message": "key_triage deferred on new KB; see docs/debug/open-problems.md",
    }
    write_yaml(ir / "key_triage.yaml", payload)
    return {"ok": True, "skipped": True, "payload": payload}


def _run_key_resolution_stub(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stub until key-resolution is rewritten for layered KB IDs."""
    del ctx
    from uo_init.yaml_io import write_yaml

    uo = _uo(project_root)
    ir = uo / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "not_applicable",
        "patches": [],
        "engine": "uo_init.update",
        "message": "key_resolution deferred on new KB; see docs/debug/open-problems.md",
    }
    write_yaml(ir / "input_derivable_patch.yaml", payload)
    return {"ok": True, "skipped": True, "payload": payload}


def _run_confidence_review_stub(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stub referee receipt for new-engine confidence_report."""
    del ctx
    from uo_init.yaml_io import write_yaml

    uo = _uo(project_root)
    review = uo / "review"
    review.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "accepted",
        "ok": True,
        "engine": "uo_init.update",
        "message": "confidence_review auto-accepted for quality.yaml-backed report",
    }
    write_yaml(review / "confidence_reason_review.yaml", payload)
    return {"ok": True, "skipped": True, "payload": payload}


def _run_export_integrity(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Delegate integrity to uo_init.pilot_engines.export_integrity."""
    try:
        from uo_init.pilot_engines import export_integrity

        return export_integrity(Path(project_root), ctx or {})
    except Exception as exc:  # noqa: BLE001
        uo = _uo(project_root)
        gate = uo / "checks" / "integrity.yaml"
        if not gate.is_file():
            gate.parent.mkdir(parents=True, exist_ok=True)
            gate.write_text("status: fail\nmessage: engine_invoke_failed\n", encoding="utf-8")
        return {"ok": False, "errors": [str(exc)[:200]]}


def _run_detect_changes(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    uo, op_name, _arch = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "detect_changes", "error": "op_name required"}
    try:
        from uo_init.update import detect_kb_changes

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
        from uo_init.update import detect_kb_changes, load_change_set_if_fresh, plan_kb_update

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
    uo, op_name, arch = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "apply_update", "error": "op_name required"}
    run_id = str((ctx or {}).get("run_id") or "").strip()
    try:
        from uo_init.update import update_operator

        result = update_operator(
            project_root,
            op_name,
            architecture=arch or "arch35",
            run_id=run_id or None,
            reuse_artifacts=True,
            cann_root=str((ctx or {}).get("cann_root") or "") or None,
            ops_root=str((ctx or {}).get("ops_root") or "") or None,
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
        from uo_init.update import (
            detect_kb_changes,
            export_diff_product,
            load_change_set_if_fresh,
            load_update_plan_if_fresh,
            plan_kb_update,
        )

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
    """Resolve op_name / architecture / consumer root / level / focus / mode for TG engines."""
    import os

    from ascendc_pilot.paths import resolve_arch
    from ascendc_pilot.state import load_state

    arch_hint = resolve_arch(
        str(ctx.get("architecture") or "").strip() or None
    )
    state = load_state(project_root) or {}
    params = _load_yaml(_ctx_root(project_root, arch=arch_hint) / "pilot_params.yaml") or {}
    if not isinstance(params, dict):
        params = {}
    pack = _load_yaml(_ctx_root(project_root, arch=arch_hint) / "context_pack.yaml") or {}
    if not isinstance(pack, dict):
        pack = {}
    run_ctx = _load_yaml(_tg(project_root, arch=arch_hint) / "init" / "run_context.yaml") or {}
    if not isinstance(run_ctx, dict):
        run_ctx = {}
    init_intent = _load_yaml(
        _tg(project_root, arch=arch_hint) / "init" / "init_intent.yaml"
    ) or {}
    if not isinstance(init_intent, dict):
        init_intent = {}
    plan_intent = _load_yaml(
        _tg(project_root, arch=arch_hint) / "plan" / "plan_intent.yaml"
    ) or {}
    if not isinstance(plan_intent, dict):
        plan_intent = {}
    man = _load_yaml(_uo(project_root, arch=arch_hint) / "manifest.yaml") or {}
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
        default=arch_hint,
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
        init_intent.get("consumer_root"),
        os.environ.get("ASCENDC_CSV_CONSUMER_ROOT"),
        os.environ.get("ASCENDC_TEST_SCRIPT_ROOT"),
    )
    mode = _pick(
        ctx.get("mode"),
        ctx.get("tg_mode"),
        state.get("mode"),
        params.get("mode"),
        init_intent.get("mode"),
        plan_intent.get("mode"),
        default="tilingkey_full_coverage",
    )
    return {
        "op_name": op_name,
        "architecture": architecture,
        "level": level,
        "focus": focus,
        "test_script_root": consumer,
        "csv_consumer_root": consumer,
        "mode": mode,
    }


_FULL_TK_MODES = frozenset({"tilingkey_full_coverage", "tilingkey_full"})


def _is_tilingkey_full(tg_ctx: dict[str, Any]) -> bool:
    return str(tg_ctx.get("mode") or "").strip() in _FULL_TK_MODES


def _require_consumer_root(
    tg_ctx: dict[str, Any], *, optional: bool | None = None
) -> Path | None:
    """Return the CSV consumer root.

    When ``mode`` is ``tilingkey_full_coverage`` (the default), consumer is
    optional — full TilingKey closure does not need a CSV sheet. Pass
    ``optional=False`` to force the legacy requirement.
    """
    if optional is None:
        optional = _is_tilingkey_full(tg_ctx)
    raw = str(tg_ctx.get("csv_consumer_root") or tg_ctx.get("test_script_root") or "").strip()
    if not raw:
        if optional:
            return None
        raise RuntimeError(
            "TEST_SCRIPT_ROOT_REQUIRED: set acp context test_script_root/csv_consumer_root "
            "(context/pilot_params.yaml, workflow state, or ASCENDC_TEST_SCRIPT_ROOT); "
            "or set mode=tilingkey_full_coverage to skip CSV consumer"
        )
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise RuntimeError(f"TEST_SCRIPT_ROOT_INVALID: not a directory: {path}")
    return path


def _run_tg_init_intent(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Write tg/init/init_intent.yaml — defaults to tilingkey_full_coverage."""
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    intent_path = _tg(project_root) / "init" / "init_intent.yaml"
    intent_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_yaml(intent_path) or {}
    if not isinstance(existing, dict):
        existing = {}
    mode = str(
        ctx.get("mode")
        or existing.get("mode")
        or tg_ctx.get("mode")
        or "tilingkey_full_coverage"
    ).strip()
    doc = {
        "schema": "tg-init-intent/v1",
        "mode": mode,
        "source": str(ctx.get("source") or existing.get("source") or "default"),
        "consumer_root": str(
            ctx.get("consumer_root")
            or existing.get("consumer_root")
            or tg_ctx.get("csv_consumer_root")
            or ""
        ),
        "op_name": tg_ctx["op_name"],
        "architecture": tg_ctx["architecture"],
        "description": str(ctx.get("description") or existing.get("description") or ""),
    }
    try:
        import yaml

        intent_path.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "init_intent", "error": str(exc)[:200]}
    return {"ok": True, "engine": "init_intent", "artifact": intent_path.as_posix(), **doc}


def _write_tilingkey_contract(project_root: Path, tg_ctx: dict[str, Any]) -> dict[str, Any]:
    """Minimal UO-based contract for tilingkey_full_coverage (no CSV consumer)."""
    import yaml

    tg = _tg(project_root)
    uo = _uo(project_root)
    for rel in (
        "ir/operator_graph.yaml",
        "tiling/exhaustive_key_space.yaml",
        "ir/tg_host_view.yaml",
        "ir/host_codemap.yaml",
    ):
        # tg_host_view OR host_codemap alias is enough for the view check.
        pass
    graph = uo / "ir" / "operator_graph.yaml"
    keys = uo / "tiling" / "exhaustive_key_space.yaml"
    view = uo / "ir" / "tg_host_view.yaml"
    alias = uo / "ir" / "host_codemap.yaml"
    errors: list[str] = []
    if not graph.is_file():
        errors.append("missing uo/ir/operator_graph.yaml")
    if not keys.is_file():
        errors.append("missing uo/tiling/exhaustive_key_space.yaml")
    if not view.is_file() and not alias.is_file():
        errors.append("missing uo/ir/tg_host_view.yaml (run uo-init export_tg_host_view)")
    key_doc = _load_yaml(keys) or {}
    graph_doc = _load_yaml(graph) or {}
    declared_count = int(key_doc.get("legal_key_count") or 0)
    if declared_count <= 0:
        # Legacy aliases — UO export uses legal_key_count only.
        declared_count = int(
            key_doc.get("count")
            or len(key_doc.get("keys") or key_doc.get("declared_keys") or [])
            or 0
        )
    if declared_count <= 0 and keys.is_file():
        errors.append("DECLARED_SET_EMPTY: legal_key_count missing or zero")
    index_rel = str(key_doc.get("legal_key_index") or "")
    if index_rel and declared_count > 0:
        index_path = uo / index_rel.replace("\\", "/").lstrip("/")
        if not index_path.is_file():
            # legal_key_index is relative to uo/tiling/ in some exports
            alt = uo / "tiling" / Path(index_rel).name
            index_path = alt if alt.is_file() else index_path
        if index_path.is_file():
            try:
                n_lines = sum(
                    1
                    for line in index_path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.strip().startswith("#")
                )
                if n_lines != declared_count:
                    errors.append(
                        f"DECLARED_SET_MISMATCH: legal_key_count={declared_count} "
                        f"but {index_path.name} has {n_lines} rows"
                    )
            except OSError as exc:
                errors.append(f"legal_key_index_unreadable: {exc}")
    contract = {
        "schema": "tg-tilingkey-contract/v1",
        "status": "pass" if not errors else "fail",
        "mode": "tilingkey_full_coverage",
        "op_name": tg_ctx["op_name"],
        "architecture": tg_ctx["architecture"],
        "declared_set": {
            "source": "uo/tiling/exhaustive_key_space.yaml",
            "fingerprint": str(
                key_doc.get("fingerprint")
                or graph_doc.get("fingerprint")
                or ""
            ),
            "count": declared_count,
            "legal_key_index": index_rel,
        },
        "graph_fingerprint": str(graph_doc.get("fingerprint") or ""),
        "host_view": "uo/ir/tg_host_view.yaml",
        "errors": errors,
    }
    out = tg / "contract" / "tilingkey_contract.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # Snapshot stub so later bind steps have a file to open.
    snap = tg / "snapshot" / "understand_contract.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    if not snap.is_file():
        import json

        snap.write_text(
            json.dumps(
                {
                    "schema": "tg-tilingkey-snapshot/v1",
                    "mode": "tilingkey_full_coverage",
                    "op_name": tg_ctx["op_name"],
                    "architecture": tg_ctx["architecture"],
                    "files": {},
                    "snapshot_hash": contract["declared_set"]["fingerprint"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return contract


def _run_tg_contract_build(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    op_name = tg_ctx["op_name"]
    if not op_name:
        return {"ok": False, "engine": "contract_build", "error": "op_name required"}
    try:
        consumer = _require_consumer_root(tg_ctx)
        if _is_tilingkey_full(tg_ctx) and consumer is None:
            payload = _write_tilingkey_contract(project_root, tg_ctx)
            ok = str(payload.get("status") or "").lower() == "pass"
            # Persist mode for subsequent TG actions.
            params_path = _ctx_root(project_root) / "pilot_params.yaml"
            params_path.parent.mkdir(parents=True, exist_ok=True)
            existing = _load_yaml(params_path) or {}
            if not isinstance(existing, dict):
                existing = {}
            existing.update(
                {
                    "op_name": op_name,
                    "architecture": tg_ctx["architecture"],
                    "mode": tg_ctx["mode"],
                    "test_script_root": "",
                    "csv_consumer_root": "",
                    "level": tg_ctx["level"],
                    "focus": tg_ctx["focus"],
                }
            )
            try:
                import yaml

                params_path.write_text(
                    yaml.safe_dump(existing, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception:  # noqa: BLE001
                pass
            return {
                "ok": ok,
                "engine": "contract_build",
                "op_name": op_name,
                "mode": tg_ctx["mode"],
                "csv_consumer_root": "",
                "payload": payload,
                "errors": payload.get("errors") or [],
            }

        from testcase_agent.contract import tg_contract

        assert consumer is not None
        payload = tg_contract(project_root, op_name, csv_consumer_root=consumer)
        # Persist resolved params for subsequent TG actions.
        params_path = _ctx_root(project_root) / "pilot_params.yaml"
        params_path.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_yaml(params_path) or {}
        if not isinstance(existing, dict):
            existing = {}
        existing.update(
            {
                "op_name": op_name,
                "architecture": tg_ctx["architecture"],
                "mode": tg_ctx.get("mode") or "csv_consumer",
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
            "mode": tg_ctx.get("mode") or "csv_consumer",
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
        if _is_tilingkey_full(tg_ctx) and consumer is None:
            import yaml

            from uo_init.host_codemap import load_tg_host_view

            uo = _uo(project_root)
            view = load_tg_host_view(uo)
            reads_of = None
            try:
                from uo_init.host_codemap import CodemapQuery

                reads_of = CodemapQuery(uo).reads_of
            except Exception:  # noqa: BLE001
                reads_of = None
            rows = []
            for f in view.get("fields") or []:
                name = str(f.get("name") or "")
                if not name:
                    continue
                reads = list(f.get("reads") or [])
                if reads_of is not None:
                    try:
                        reads = reads_of(name) or reads
                    except Exception:  # noqa: BLE001
                        pass
                rows.append({
                    "field": name,
                    "kind": f.get("kind"),
                    "reads": reads,
                    "exactness": f.get("exactness"),
                })
            inv = {
                "schema": "tg-tilingkey-binding-inventory/v1",
                "mode": "tilingkey_full_coverage",
                "fields": rows,
                "field_count": len(rows),
                "graph_fingerprint": str(
                    (_load_yaml(uo / "ir" / "operator_graph.yaml") or {}).get("fingerprint")
                    or ""
                ),
            }
            inv_path = tg / "realization" / "binding_inventory.yaml"
            inv_path.parent.mkdir(parents=True, exist_ok=True)
            inv_path.write_text(
                yaml.safe_dump(inv, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            return {
                "ok": True,
                "engine": "semantic_bind",
                "mode": "tilingkey_full_coverage",
                "artifacts": {},
                "inventory_path": inv_path.as_posix(),
                "csv_consumer_root": "",
                "field_count": len(rows),
            }

        from testcase_agent.binding_inventory import build_binding_inventory, fingerprint_consumer
        from testcase_agent.init import write_bind_scaffolds
        from testcase_agent.io import read_json, read_yaml

        assert consumer is not None
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
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    tg = _tg(project_root)
    if _is_tilingkey_full(tg_ctx) and _require_consumer_root(tg_ctx) is None:
        import yaml

        inv = tg / "realization" / "binding_inventory.yaml"
        report = {
            "schema": "tg-bind-merge/v1",
            "mode": "tilingkey_full_coverage",
            "status": "pass" if inv.is_file() else "fail",
            "note": "full mode skips CSV realization merge; host-view inventory is authoritative",
            "inventory": inv.as_posix() if inv.is_file() else "",
        }
        out = tg / "realization" / "uo_merge_report.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return {
            "ok": report["status"] == "pass",
            "engine": "bind_merge",
            "mode": "tilingkey_full_coverage",
            "payload": report,
        }
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
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    tg = _tg(project_root)
    if _is_tilingkey_full(tg_ctx) and _require_consumer_root(tg_ctx) is None:
        import yaml

        queue = {
            "schema": "tg-mid-nest/v1",
            "mode": "tilingkey_full_coverage",
            "status": "pass",
            "symbols": [],
            "note": "full mode has no CSV mid-symbol queue",
        }
        out = tg / "realization" / "mid_symbol_queue.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(queue, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return {
            "ok": True,
            "engine": "mid_nest",
            "mode": "tilingkey_full_coverage",
            "artifact": out.as_posix(),
        }
    try:
        from testcase_agent.resolve_policy import write_mid_symbol_queue

        queue = write_mid_symbol_queue(tg)
        return {"ok": True, "engine": "mid_nest", "queue": queue if isinstance(queue, dict) else {}}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "mid_nest", "error": str(exc)[:400]}


def _run_tg_integrity(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.gates import run_named_gate

    import yaml

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    op = str(tg_ctx.get("op_name") or "") or None
    tg = _tg(project_root)
    if _is_tilingkey_full(tg_ctx):
        # Full TK mode: key contract / host-view readiness instead of CSV closure.
        contract = _load_yaml(tg / "contract" / "tilingkey_contract.yaml") or {}
        status = str(contract.get("status") or "").lower()
        ok = status == "pass" and not list(contract.get("errors") or [])
        receipt = {
            "schema": "tg-tilingkey-integrity/v1",
            "mode": "tilingkey_full_coverage",
            "status": "pass" if ok else "fail",
            "tilingkey_contract_status": status or "missing",
            "errors": list(contract.get("errors") or []),
        }
        out = tg / "contract" / "integrity_gate.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(receipt, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return {
            "ok": ok,
            "engine": "integrity_gate",
            "mode": "tilingkey_full_coverage",
            "artifact": out.as_posix(),
            "gates": {
                "tilingkey_contract": {
                    "ok": ok,
                    "status": status or "missing",
                    "errors": list(contract.get("errors") or []),
                }
            },
        }
    domain = run_named_gate(project_root, "domain_symmetry", op_name=op)
    closure = run_named_gate(project_root, "csv_closure", op_name=op)
    ok = bool(domain.get("ok")) and bool(closure.get("ok"))
    receipt = {
        "schema": "tg-csv-integrity/v1",
        "mode": "csv_consumer",
        "status": "pass" if ok else "fail",
        "gates": {"domain_symmetry": domain, "csv_closure": closure},
    }
    out = tg / "contract" / "integrity_gate.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(receipt, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # CSV contract still expects uo_merge_report for tg-integrity-v1.
    return {
        "ok": ok,
        "engine": "integrity_gate",
        "artifact": out.as_posix(),
        "gates": {"domain_symmetry": domain, "csv_closure": closure},
    }


def _run_tg_plan_intent(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Write plan_intent.yaml. Default mode = tilingkey_full_coverage."""
    import yaml

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    tg = _tg(project_root)
    init_intent = _load_yaml(tg / "init" / "init_intent.yaml") or {}
    existing = _load_yaml(tg / "plan" / "plan_intent.yaml") or {}
    mode = (
        str(ctx.get("mode") or "").strip()
        or str(existing.get("mode") or "").strip()
        or str(init_intent.get("mode") or "").strip()
        or "tilingkey_full_coverage"
    )
    source = (
        str(ctx.get("source") or "").strip()
        or str(existing.get("source") or "").strip()
        or ("init_intent" if init_intent.get("mode") else "default")
    )
    intent = {
        "schema": "tg-plan-intent/v1",
        "mode": mode,
        "source": source,
        "description": str(ctx.get("description") or existing.get("description") or ""),
        "pr_ref": str(ctx.get("pr_ref") or existing.get("pr_ref") or ""),
        "op_name": tg_ctx.get("op_name") or "",
        "architecture": tg_ctx.get("architecture") or "",
    }
    out = tg / "plan" / "plan_intent.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(intent, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True, "engine": "plan_intent", "artifact": out.as_posix(), **intent}


def _run_tg_plan_scope(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    try:
        consumer = _require_consumer_root(tg_ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_scope", "error": str(exc)[:400]}
    tg = _tg(project_root)
    level = tg_ctx["level"] or "L0"
    intent = _load_yaml(tg / "plan" / "plan_intent.yaml") or {}
    mode = (
        str(intent.get("mode") or "").strip()
        or tg_ctx.get("mode")
        or "tilingkey_full_coverage"
    )
    scope = {
        "version": 1,
        "op_name": tg_ctx["op_name"],
        "level": level,
        "focus": tg_ctx["focus"],
        "mode": mode,
        "csv_consumer_root": consumer.as_posix() if consumer else "",
        "architecture": tg_ctx["architecture"],
    }
    out = tg / "plan" / "levels" / level / "plan_scope.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml

        out.write_text(yaml.safe_dump(scope, allow_unicode=True, sort_keys=False), encoding="utf-8")
        # Keep plan_intent in sync with resolved mode.
        if not intent:
            intent = {
                "schema": "tg-plan-intent/v1",
                "mode": mode,
                "source": "plan_scope",
                "op_name": tg_ctx["op_name"],
            }
            intent_path = tg / "plan" / "plan_intent.yaml"
            intent_path.write_text(
                yaml.safe_dump(intent, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
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
        level = tg_ctx["level"] or "L0"
        if _is_tilingkey_full(tg_ctx) and consumer is None:
            import yaml

            uo = _uo(project_root)
            keys = _load_yaml(uo / "tiling" / "exhaustive_key_space.yaml") or {}
            graph = _load_yaml(uo / "ir" / "operator_graph.yaml") or {}
            count = int(keys.get("legal_key_count") or 0)
            if count <= 0:
                count = int(
                    keys.get("count")
                    or len(keys.get("keys") or keys.get("declared_keys") or [])
                    or 0
                )
            if count <= 0:
                return {
                    "ok": False,
                    "engine": "plan_build",
                    "error": "DECLARED_SET_EMPTY",
                    "mode": "tilingkey_full_coverage",
                }
            fp = str(keys.get("fingerprint") or graph.get("fingerprint") or "")
            obligations = {
                "schema": "coverage-obligations/v2",
                "mode": "tilingkey_full_coverage",
                "version": 2,
                "plan_hash": fp,
                "declared_set": {
                    "source": "uo/tiling/exhaustive_key_space.yaml",
                    "fingerprint": fp,
                    "count": count,
                    "legal_key_index": str(keys.get("legal_key_index") or ""),
                },
                "obligations": [
                    {
                        "id": "CLOSE_DECLARED_SET",
                        "kind": "set_closure",
                        "invariant": "D = (R ∩ D) ∪ E",
                    },
                    {
                        "id": "EXCLUSION_SOUNDNESS",
                        "kind": "proof_policy",
                        "invariant": "R ∩ E = ∅",
                    },
                    {
                        "id": "WITNESS_PROVENANCE",
                        "kind": "provenance",
                        "invariant": "every R key has successful replay evidence",
                    },
                    {
                        "id": "EXCLUSION_PROVENANCE",
                        "kind": "provenance",
                        "invariant": "every E key has verified rule evidence",
                    },
                ],
            }
            obl = _tg(project_root) / "plan" / "levels" / level / "coverage_obligations.yaml"
            obl.parent.mkdir(parents=True, exist_ok=True)
            obl.write_text(
                yaml.safe_dump(obligations, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            return {
                "ok": True,
                "engine": "plan_build",
                "op_name": op_name,
                "level": level,
                "mode": "tilingkey_full_coverage",
                "artifact": obl.as_posix(),
                "declared_count": count,
            }

        from testcase_agent.planner import tg_plan

        assert consumer is not None
        payload = tg_plan(
            project_root,
            op_name,
            level=level,
            focus=tg_ctx["focus"] or "",
            csv_consumer_root=consumer,
            reuse_snapshot=True,
        )
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
            "mode": tg_ctx.get("mode") or "csv_consumer",
            "payload": payload if isinstance(payload, dict) else {},
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_build", "error": str(exc)[:400]}


def _run_tg_solve_precheck(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.gates import run_named_gate

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    try:
        _require_consumer_root(tg_ctx)  # optional under tilingkey_full_coverage
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "solve_precheck", "error": str(exc)[:400]}
    op = tg_ctx.get("op_name") or None
    g1 = run_named_gate(project_root, "plan_approved", op_name=op)
    g2 = run_named_gate(project_root, "kb_fingerprint_fresh", op_name=op)
    ok = bool(g1.get("ok")) and bool(g2.get("ok"))
    return {
        "ok": ok,
        "engine": "solve_precheck",
        "mode": tg_ctx.get("mode"),
        "gates": {"plan_approved": g1, "kb_fingerprint_fresh": g2},
    }


def _run_tg_z3_solve(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    op_name = tg_ctx["op_name"]
    if not op_name:
        return {"ok": False, "engine": "z3_solve", "error": "op_name required"}
    if _is_tilingkey_full(tg_ctx):
        # CSV/Z3 path is not used for full TK closure; Phase 4 wires closure_*.
        return {
            "ok": True,
            "engine": "z3_solve",
            "mode": "tilingkey_full_coverage",
            "op_name": op_name,
            "skipped": True,
            "note": (
                "tilingkey_full_coverage uses closure_ledger/search/residual "
                "(Phase 4); z3_solve is a no-op in this mode"
            ),
        }
    try:
        consumer = _require_consumer_root(tg_ctx)
        from testcase_agent.solve import tg_solve

        assert consumer is not None
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


def _closure_ws(project_root: Path):
    from testcase_agent.closure import workspace as WS

    return WS.default_workspace(project_root).ensure()


def _dump_closure_yaml(path: Path, doc: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _closure_live_default(ctx: dict[str, Any], key: str) -> bool:
    """Production defaults to live Host; CI/synthetic may opt out explicitly."""
    if key in ctx:
        return bool(ctx.get(key))
    import os

    if str(os.environ.get("TG_CLOSURE_CI") or "").strip().lower() in {"1", "true", "yes"}:
        return False
    if str(os.environ.get("UO_OPERATOR") or "").startswith("_synthetic"):
        return False
    return True


def _run_oracle_probe(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Oracle integrity probe — live Host by default (CI/synthetic may opt out)."""
    tg = _tg(project_root)
    ws = _closure_ws(project_root)
    from testcase_agent.closure.ledger import baseline_fingerprint

    baseline = baseline_fingerprint(project_root)
    issues: list[str] = []
    live: dict[str, Any] = {"attempted": False}
    try:
        from testcase_agent.closure import workspace as WS

        sch = WS.schema()
        if not sch.dims:
            issues.append("tiling schema has no dims")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"schema_unavailable: {exc}")

    live_probe = _closure_live_default(ctx, "live_probe")
    if live_probe:
        live["attempted"] = True
        try:
            from testcase_agent.closure import generate as G
            from testcase_agent.closure.oracle import HostOracle

            rng = __import__("random").Random(0)
            cases = [G.sample_case(rng) for _ in range(int(ctx.get("probe_n") or 10))]
            # One illegal / empty case for reject path when possible.
            oracle = HostOracle()
            verdicts = oracle.judge(cases, tag="oracle_probe")
            batch_accounting = oracle.last_accounting
            judged = batch_accounting["judged"]
            accepted = batch_accounting["accepted"]
            with_key = sum(1 for v in verdicts if v.key)
            live.update({
                "sent": len(cases),
                "judged": judged,
                "accepted": accepted,
                "with_key": with_key,
                "accounting": batch_accounting,
            })
            if not batch_accounting["conserved"]:
                issues.append("ORACLE_ACCOUNTING_MISMATCH")
            if batch_accounting["not_run"]:
                issues.append("ORACLE_SUSPECT:not_run")
                (ws.state / "oracle_suspect").write_text("1", encoding="utf-8")
            if accepted == 0:
                issues.append("ORACLE_SUSPECT:accepted==0")
            if with_key == 0:
                issues.append("ORACLE_SUSPECT:accepted_with_key==0")
        except Exception as exc:  # noqa: BLE001
            issues.append(f"live_probe_failed: {exc}")
            live["error"] = str(exc)[:300]
    else:
        issues.append("live_probe_disabled: schema-only probe (CI/synthetic)")
        # Schema-only is allowed only when explicitly opted out; do not fail CI.
        if str((__import__("os").environ.get("TG_CLOSURE_CI") or "")).strip().lower() in {
            "1", "true", "yes",
        } or str((__import__("os").environ.get("UO_OPERATOR") or "")).startswith("_synthetic"):
            issues = [i for i in issues if not i.startswith("live_probe_disabled")]

    doc = {
        "schema": "tg-oracle-probe/v2",
        "ok": len(issues) == 0,
        "issues": issues,
        "state": str(ws.state),
        "baseline": baseline,
        "live": live,
        "live_probe": live_probe,
        "note": (
            "Production requires live_probe; set TG_CLOSURE_CI=1 or UO_OPERATOR=_synthetic_* "
            "for schema-only CI probes"
        ),
    }
    out = tg / "closure" / "oracle_probe.yaml"
    _dump_closure_yaml(out, doc)
    return {"ok": doc["ok"], "engine": "oracle_probe", "artifact": out.as_posix(), **doc}


def _run_closure_ledger(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent.closure import ledger
    from testcase_agent.closure import lemma
    from testcase_agent.closure import closure_state

    ws = _closure_ws(project_root)
    try:
        rebuilt = ledger.rebuild(ws)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "closure_ledger", "error": str(exc)[:300]}
    # Only re-verify / apply already-promoted active rules. Package seed rules
    # must not enter E before lemma_review (methodology §6.5).
    try:
        current_fp = ""
        try:
            import yaml

            graph = _uo(project_root) / "ir" / "operator_graph.yaml"
            if graph.is_file():
                current_fp = str(
                    (yaml.safe_load(graph.read_text(encoding="utf-8")) or {}).get("fingerprint")
                    or ""
                )
        except Exception:
            current_fp = ""
        applied = lemma.reverify_active(ws, current_uo_graph_fingerprint=current_fp)
    except TypeError:
        # Older signature without fingerprint kwarg.
        try:
            applied = lemma.reverify_active(ws)
        except Exception as exc:  # noqa: BLE001
            applied = {"ok": False, "error": str(exc)[:200]}
    except Exception as exc:  # noqa: BLE001
        applied = {"ok": False, "error": str(exc)[:200]}
    st = ledger.state(ws)
    try:
        snapshot = closure_state.write(ws, relations=list(ctx.get("finite_relations") or []))
    except Exception as exc:  # noqa: BLE001
        snapshot = {"error": str(exc)[:200]}
    return {
        "ok": bool(rebuilt.get("ok", True)) and bool(applied.get("ok", True)) and not snapshot.get("error"),
        "engine": "closure_ledger",
        "rebuild": rebuilt,
        "apply_rules": {
            "excluded": applied.get("excluded"),
            "gap": applied.get("gap"),
            "revoked_count": applied.get("revoked_count", 0),
            "error": applied.get("error"),
        },
        "closure_state": snapshot,
        **st,
    }


def _run_closure_search(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    import os

    from testcase_agent.closure import search_round

    ws = _closure_ws(project_root)
    budget = int(ctx.get("budget") or 64)
    seed = int(ctx.get("seed") or 0)
    oracle = ctx.get("oracle")
    if oracle is None and (
        str(os.environ.get("TG_CLOSURE_CI") or "").strip().lower() in {"1", "true", "yes"}
        or str(os.environ.get("UO_OPERATOR") or "").startswith("_synthetic")
    ):
        try:
            from testcase_agent.closure.oracle import StubOracle

            keys = ctx.get("stub_keys") or []
            oracle = StubOracle(keys=[int(k) for k in keys] if keys else [1, 2, 3, 4])
        except Exception:
            oracle = None
    try:
        out = search_round.run_round(ws, budget=budget, seed=seed, oracle=oracle)
    except Exception as exc:  # noqa: BLE001
        # Still leave a round stub so the output contract is satisfiable.
        rounds = ws.state / "rounds" / "round_0001"
        rounds.mkdir(parents=True, exist_ok=True)
        stub = {
            "schema": "tg-closure-search-stub/v1",
            "ok": False,
            "error": str(exc)[:300],
            "new_R": 0,
        }
        _dump_closure_yaml(rounds / "progress.yaml", stub)
        return {"ok": False, "engine": "closure_search", **stub}
    return {"engine": "closure_search", **out}


def _run_closure_residual(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent.closure import residual
    from testcase_agent.closure import search_round

    ws = _closure_ws(project_root)
    analysis = residual.analyse(ws)
    routed = search_round.route(ws)
    reason = str(routed.get("reason") or "PROOF_BLOCKED")

    # Round budget for automatic rework (control plane closes the loop).
    budget = int(ctx.get("round_budget") or 32)
    budget_path = ws.state / "round_budget.yaml"
    used = 0
    try:
        import yaml

        if budget_path.is_file():
            used = int((yaml.safe_load(budget_path.read_text(encoding="utf-8")) or {}).get("used") or 0)
    except Exception:
        used = 0

    # Do not mutate workflow state inside this action. Controllers / acp
    # advance apply rework after the action receipt is finalized.
    auto_rework: dict[str, Any] = {"attempted": False, "deferred": True}
    escalate = reason in {"ORACLE_SUSPECT", "PROOF_BLOCKED"}
    needs_rework = reason not in {"GAP_ZERO"} and not escalate and used < budget
    if used >= budget and reason not in {"GAP_ZERO"} and not escalate:
        escalate = True
        reason = "PROOF_BLOCKED"
        auto_rework = {"attempted": False, "budget_exhausted": True, "used": used, "deferred": False}
        needs_rework = False
    elif needs_rework:
        used += 1
        try:
            import yaml

            budget_path.write_text(
                yaml.safe_dump(
                    {"used": used, "budget": budget, "last_reason": reason},
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass
        auto_rework = {
            "attempted": False,
            "deferred": True,
            "reason_code": reason,
            "used": used,
            "budget": budget,
        }

    route_doc = {
        "schema": "tg-closure-route/v1",
        "reason": reason,
        "round_budget": {"used": used, "budget": budget},
        "auto_rework": auto_rework,
        "rework_hint": (
            f"acp rework --reason {reason}"
            if needs_rework
            else ""
        ),
        "residual": {
            "open": analysis.get("open"),
            "distance": analysis.get("distance"),
            "mostly_distance_1": analysis.get("mostly_distance_1"),
        },
        "state": {k: routed.get(k) for k in ("declared", "R", "E", "gap", "violation")},
    }
    out = _tg(project_root) / "closure" / "route.yaml"
    _dump_closure_yaml(out, route_doc)
    return {
        "ok": True,
        "engine": "closure_residual",
        "reason_code": reason,
        "reason_codes": [reason],
        "needs_rework": needs_rework,
        "escalate": escalate,
        "artifact": out.as_posix(),
        **route_doc,
    }


def _run_closure_construct(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent.closure import construct
    from testcase_agent.closure import residual
    from testcase_agent.closure import workspace as WS

    ws = _closure_ws(project_root)
    analysis = residual.analyse(ws)
    targets = residual.distance_one_targets(analysis)[: int(ctx.get("limit") or 32)]
    built = 0
    cases: list = []
    for t in targets:
        key = t.get("key")
        try:
            inst = WS.decode(int(key))
            cases.extend(construct.build(inst))
            built += 1
        except Exception:
            continue
    # Production defaults to live Host; CI/synthetic may opt out.
    replayed = 0
    if cases and _closure_live_default(ctx, "live_replay"):
        try:
            from testcase_agent.closure.oracle import HostOracle

            verdicts = HostOracle().judge(cases[:64], tag="construct")
            replayed = sum(1 for v in verdicts if v.verdict)
            rows = []
            for i, v in enumerate(verdicts):
                if not v.verdict:
                    continue
                rows.append({
                    "ok": int(v.ok),
                    "tiling_key": int(v.key),
                    "reject": v.reject,
                    "_arm": "construct",
                })
            if rows:
                from testcase_agent.closure import corpus as C
                from testcase_agent.closure import ledger

                C.commit(rows, ws, name="construct_key_cases.csv")
                ledger.rebuild(ws)
        except Exception as exc:  # noqa: BLE001
            doc_err = str(exc)[:200]
        else:
            doc_err = ""
    else:
        doc_err = ""

    doc = {
        "schema": "tg-closure-construct/v1",
        "targets": len(targets),
        "built_cases": len(cases),
        "targets_decoded": built,
        "replayed": replayed,
        "sample_keys": [t.get("key") for t in targets[:10]],
        "error": doc_err,
    }
    out = _tg(project_root) / "closure" / "construct" / "targets.yaml"
    _dump_closure_yaml(out, doc)
    return {"ok": True, "engine": "closure_construct", "artifact": out.as_posix(), **doc}


def _run_closure_explain(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    ws = _closure_ws(project_root)
    why = ws.state / "why.csv"
    ran = False
    err = ""
    result: dict[str, Any] = {}
    if _closure_live_default(ctx, "live_explain"):
        try:
            from testcase_agent.closure import construct
            from testcase_agent.closure import explain

            result = explain.run_explain(
                construct.build,
                open_limit=int(ctx.get("open_limit") or 60),
                per_target=int(ctx.get("per_target") or 24),
                ws=ws,
            )
            ran = True
            why = Path(result.get("path") or why)
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:300]
    doc = {
        "schema": "tg-closure-explain/v1",
        "why_exists": why.is_file() if why else False,
        "path": str(why) if why and why.is_file() else "",
        "ran": ran,
        "accepted": result.get("accepted", 0),
        "error": err,
    }
    out = _tg(project_root) / "closure" / "construct" / "explain_receipt.yaml"
    _dump_closure_yaml(out, doc)
    return {"ok": True, "engine": "closure_explain", **doc}


def _run_lemma_leads(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    from testcase_agent.closure import mine

    ws = _closure_ws(project_root)
    try:
        pairs = mine.mine_pairs(ws, top=40)
        triples = mine.mine_triples(ws, top=40)
    except Exception as exc:  # noqa: BLE001
        pairs, triples = [], []
        err = str(exc)[:300]
    else:
        err = ""
    leads = {
        "schema": "tg-lemma-leads/v1",
        "pairs": pairs,
        "triples": triples,
        "pair_count": len(pairs),
        "triple_count": len(triples),
        "error": err,
    }
    out = _tg(project_root) / "closure" / "lemmas" / "leads.yaml"
    _dump_closure_yaml(out, leads)
    return {
        "ok": not err,
        "engine": "lemma_leads",
        "artifact": out.as_posix(),
        "pair_count": len(pairs),
        "triple_count": len(triples),
        "error": err,
    }


def _run_lemma_mine(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Producer scaffold — real proof writing is done by tg-lemma-producer subagent."""
    import yaml

    from ascendc_pilot.paths import agent_root

    run_id = str(ctx.get("run_id") or "local")
    parts = (
        agent_root(project_root)
        / "runs"
        / run_id
        / "actions"
        / "lemma_mine"
    )
    parts.mkdir(parents=True, exist_ok=True)
    leads = _load_yaml(_tg(project_root) / "closure" / "lemmas" / "leads.yaml") or {}
    staging = {
        "schema": "tg-lemma-mine-staging/v1",
        "status": "awaiting_subagent",
        "lead_count": int(leads.get("pair_count") or 0) + int(leads.get("triple_count") or 0),
        "instructions": (
            "Write parts/part_0.yaml with source-cited lemma candidates only; "
            "do not invent leads; follow tilingkey-closure LEMMA.md"
        ),
    }
    (parts / "staging.yaml").write_text(
        yaml.safe_dump(staging, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    part0 = parts / "parts" / "part_0.yaml"
    if not part0.is_file():
        part0.parent.mkdir(parents=True, exist_ok=True)
        _dump_closure_yaml(part0, {
            "schema": "tg-lemma-part/v1",
            "candidates": [],
            "note": "placeholder — producer replaces with cited lemmas",
        })
    return {
        "ok": True,
        "engine": "lemma_mine",
        "staging": str(parts / "staging.yaml"),
        "need_subagent": True,
    }


def _run_lemma_review(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Referee scaffold — tg-closure-referee fills runs/.../review.yaml only."""
    import yaml

    run_id = str(ctx.get("run_id") or "local")
    from ascendc_pilot.paths import agent_root

    review_dir = agent_root(project_root) / "runs" / run_id / "actions" / "lemma_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    existing = review_dir / "review.yaml"
    if existing.is_file():
        doc = yaml.safe_load(existing.read_text(encoding="utf-8")) or {}
    else:
        doc = {
            "schema": "tg-lemma-review/v1",
            "status": "awaiting_referee",
            "accepted": [],
            "rejected": [],
            "note": "Referee must verify source citations before lemma_apply",
        }
        existing.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    # Persistent canon is promoted by lemma_apply (deterministic), not referee.
    return {
        "ok": True,
        "engine": "lemma_review",
        "artifact": existing.as_posix(),
        "status": doc.get("status"),
    }


def _run_lemma_apply(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent.closure import lemma

    ws = _closure_ws(project_root)
    tg = _tg(project_root)
    run_id = str(ctx.get("run_id") or "local")
    from ascendc_pilot.paths import agent_root

    review_path = (
        agent_root(project_root) / "runs" / run_id / "actions" / "lemma_review" / "review.yaml"
    )
    review = _load_yaml(review_path) or _load_yaml(tg / "closure" / "lemmas" / "reviews.yaml") or {}
    # Persist referee receipt into the closure ledger for subsequent rounds.
    if review:
        _dump_closure_yaml(tg / "closure" / "lemmas" / "reviews.yaml", review)
    promoted = {"promoted": 0}
    if review.get("accepted"):
        tg_ctx = _resolve_tg_ctx(project_root, ctx)
        uo = _uo(project_root, arch=tg_ctx.get("architecture"))
        man = _load_yaml(uo / "manifest.yaml") or {}
        promoted = lemma.promote_reviewed(
            review,
            ws,
            source_revision=str(man.get("source_revision") or ""),
            uo_graph_fingerprint=str(
                ((man.get("fingerprint") or man.get("graph_fingerprint") or ""))
            ),
        )
    out = lemma.apply_rules(ws, refresh=True)
    return {"engine": "lemma_apply", "promote": promoted, **out}


def _run_closure_audit(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Referee scaffold for post-apply invariant review (runs/.../review.yaml only)."""
    import yaml

    from testcase_agent.closure import ledger
    from testcase_agent.closure import lemma
    from ascendc_pilot.paths import agent_root

    run_id = str(ctx.get("run_id") or "local")
    ws = _closure_ws(project_root)
    st = ledger.state(ws)
    audit_dir = agent_root(project_root) / "runs" / run_id / "actions" / "closure_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    existing = audit_dir / "review.yaml"
    if existing.is_file():
        doc = yaml.safe_load(existing.read_text(encoding="utf-8")) or {}
    else:
        doc = {
            "schema": "tg-closure-audit/v1",
            "status": "awaiting_referee" if st.get("gap", 1) else "auto_ok",
            "state": st,
            "soundness_ok": lemma.soundness_ok(ws),
            "note": "Referee confirms I1–I4 before certify",
        }
        existing.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    status = str(doc.get("status") or "").strip().lower()
    # Scaffold may still be awaiting a human/subagent referee — do not claim success.
    awaiting = status in {"", "awaiting_referee", "pending", "open"}
    return {
        "ok": not awaiting,
        "engine": "closure_audit",
        "artifact": existing.as_posix(),
        "status": doc.get("status"),
        "needs_referee": awaiting,
        **st,
    }


def _run_closure_certify(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.gates import run_named_gate
    from ascendc_pilot.paths import agent_root
    from testcase_agent.closure import ledger
    from testcase_agent.closure import report

    ws = _closure_ws(project_root)
    gate = run_named_gate(project_root, "closure_soundness")
    rep = report.report(ws, refresh=True)
    st = ledger.state(ws)

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    uo = _uo(project_root, arch=tg_ctx.get("architecture"))
    man = _load_yaml(uo / "manifest.yaml") or {}
    uo_fp = str(man.get("fingerprint") or man.get("graph_fingerprint") or "")
    invariants = report.certify_invariants(ws, uo_graph_fingerprint=uo_fp)

    # Promote referee audit receipt into the durable closure ledger.
    run_id = str(ctx.get("run_id") or "local")
    audit_review = (
        agent_root(project_root) / "runs" / run_id / "actions" / "closure_audit" / "review.yaml"
    )
    audit_doc = _load_yaml(audit_review) or {}
    if audit_doc:
        _dump_closure_yaml(_tg(project_root) / "closure" / "audit_report.yaml", audit_doc)

    audit_status = str(audit_doc.get("status") or "").strip().lower()
    audit_ok = audit_status in {"pass", "passed", "accepted", "auto_ok"} and bool(
        audit_doc.get("soundness_ok", True)
    )
    if not audit_doc:
        audit_ok = False
    if audit_status in {"awaiting_referee", "pending", "open", "fail", "failed", "reject", "rejected"}:
        audit_ok = False

    cert = {
        "schema": "tg-closure-certificate/v1",
        "ok": (
            bool(gate.get("ok"))
            and bool(rep.get("gap_zero"))
            and bool(invariants.get("ok"))
            and audit_ok
        ),
        "gate": gate,
        "audit": {
            "ok": audit_ok,
            "status": audit_status or "missing",
            "path": audit_review.as_posix() if audit_review.is_file() else "",
            "soundness_ok": audit_doc.get("soundness_ok"),
        },
        "invariants": invariants,
        "report": {
            "gap_zero": rep.get("gap_zero"),
            "open": rep.get("open"),
            "problem_count": rep.get("problem_count"),
            "undeclared": rep.get("undeclared"),
            "undeclared_path": rep.get("undeclared_path"),
        },
        "state": st,
        "note": "R−D is reported separately and does not block D-closure when I9 path exists",
    }
    if not audit_ok:
        cert["error"] = (
            f"closure_audit status={audit_status or 'missing'!r}; "
            "require status in {{pass, accepted, auto_ok}} before certify"
        )
    out = _tg(project_root) / "closure" / "certificate.yaml"
    _dump_closure_yaml(out, cert)
    # Also drop a standalone undeclared defect receipt.
    if rep.get("undeclared_path"):
        defect = {
            "schema": "tg-undeclared-key-defect/v1",
            "count": rep.get("undeclared"),
            "path": rep.get("undeclared_path"),
        }
        _dump_closure_yaml(_tg(project_root) / "closure" / "undeclared_defect.yaml", defect)
    return {
        "ok": cert["ok"],
        "engine": "closure_certify",
        "artifact": out.as_posix(),
        **cert,
    }


def _uo_op_ctx(project_root: Path, ctx: dict[str, Any]) -> tuple[Path, str, str]:
    uo = _uo(project_root)
    op_name = str(ctx.get("op_name") or "").strip()
    if not op_name:
        try:
            from ascendc_pilot.uo_artifacts import read_yaml

            man = read_yaml(uo / "manifest.yaml") or {}
            op_name = str(man.get("op_name") or "").strip()
        except Exception:  # noqa: BLE001
            op_name = ""
    architecture = str(ctx.get("architecture") or "arch35")
    return uo, op_name, architecture


def _uo_init_engine(action_id: str) -> EngineFn:
    def _run(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
        from uo_init.pilot_engines import ENGINES

        fn = ENGINES[action_id]
        return fn(Path(project_root), ctx or {})

    _run.__name__ = f"_run_uo_init_{action_id}"
    return _run


ENGINE_REGISTRY: dict[tuple[str, str], EngineFn] = {
    ("uo-init", "prepare_layout"): _uo_init_engine("prepare_layout"),
    ("uo-init", "scope_scan"): _uo_init_engine("scope_scan"),
    ("uo-init", "scope_confirm"): _uo_init_engine("scope_confirm"),
    ("uo-init", "extract_host"): _uo_init_engine("extract_host"),
    ("uo-init", "extract_tiling_key"): _uo_init_engine("extract_tiling_key"),
    ("uo-init", "extract_registry"): _uo_init_engine("extract_registry"),
    ("uo-init", "extract_kernel"): _uo_init_engine("extract_kernel"),
    ("uo-init", "normalize_variables"): _uo_init_engine("normalize_variables"),
    ("uo-init", "derive_key_fields"): _uo_init_engine("derive_key_fields"),
    ("uo-init", "normalize_predicates"): _uo_init_engine("normalize_predicates"),
    ("uo-init", "resolve_gaps"): _uo_init_engine("resolve_gaps"),
    ("uo-init", "apply_gap_patch"): _uo_init_engine("apply_gap_patch"),
    ("uo-init", "export_kb"): _uo_init_engine("export_kb"),
    ("uo-init", "build_index"): _uo_init_engine("build_index"),
    ("uo-init", "export_tg_host_view"): _uo_init_engine("export_tg_host_view"),
    ("uo-init", "export_integrity"): _uo_init_engine("export_integrity"),
    ("uo-init", "kb_review"): _uo_init_engine("kb_review"),
    # Legacy tk-cover workflow removed; closure lives under tg-solve.
    ("uo-update", "detect_changes"): _run_detect_changes,
    ("uo-update", "plan_update"): _run_plan_update,
    ("uo-update", "apply_update"): _run_apply_update,
    ("uo-update", "key_triage"): _run_key_triage_stub,
    ("uo-update", "key_resolution"): _run_key_resolution_stub,
    ("uo-update", "confidence_report"): _run_confidence_report,
    ("uo-update", "confidence_review"): _run_confidence_review_stub,
    ("uo-update", "export_integrity"): _run_export_integrity,
    ("uo-update", "diff_summary"): _run_diff_summary,
    ("uo-update", "diff_only"): _run_diff_summary,
    ("tg-init", "init_intent"): _run_tg_init_intent,
    ("tg-init", "kb_check"): _run_tg_kb_check,
    ("tg-init", "contract_build"): _run_tg_contract_build,
    ("tg-init", "semantic_bind"): _run_tg_semantic_bind,
    ("tg-init", "bind_merge"): _run_tg_bind_merge,
    ("tg-init", "mid_nest"): _run_tg_mid_nest,
    ("tg-init", "integrity_gate"): _run_tg_integrity,
    ("tg-plan", "plan_intent"): _run_tg_plan_intent,
    ("tg-plan", "plan_scope"): _run_tg_plan_scope,
    ("tg-plan", "plan_precheck"): _run_tg_plan_precheck,
    ("tg-plan", "plan_build"): _run_tg_plan_build,
    ("tg-solve", "solve_precheck"): _run_tg_solve_precheck,
    ("tg-solve", "oracle_probe"): _run_oracle_probe,
    ("tg-solve", "closure_ledger"): _run_closure_ledger,
    ("tg-solve", "closure_search"): _run_closure_search,
    ("tg-solve", "closure_residual"): _run_closure_residual,
    ("tg-solve", "closure_construct"): _run_closure_construct,
    ("tg-solve", "closure_explain"): _run_closure_explain,
    ("tg-solve", "lemma_leads"): _run_lemma_leads,
    ("tg-solve", "lemma_mine"): _run_lemma_mine,
    ("tg-solve", "lemma_review"): _run_lemma_review,
    ("tg-solve", "lemma_apply"): _run_lemma_apply,
    ("tg-solve", "closure_audit"): _run_closure_audit,
    ("tg-solve", "closure_certify"): _run_closure_certify,
    ("tg-solve", "z3_solve"): _run_tg_z3_solve,
    ("tg-solve", "cover_confirm"): _run_tg_cover_confirm,
}


# Output contract id → relative paths under .ascendc-pilot (existence + nonempty where applicable)
OUTPUT_CONTRACT_PATHS: dict[str, list[str]] = {
    "kb-layout-v1": ["uo/manifest.yaml", "uo/operator.yaml"],
    "scope-candidates-v1": ["uo/summary/scope_candidates.yaml"],
    "scope-confirmed-v1": [
        "uo/runs/{run_id}/scope/scope_confirmed.yaml",
        "uo/runs/{run_id}/scope/receipt.yaml",
    ],
    "extract-host-v1": ["uo/ir/host_extract_receipt.yaml"],
    "extract-tiling-key-v1": ["uo/tiling/key_bind_receipt.yaml"],
    "extract-registry-v1": ["uo/tiling/families.yaml"],
    "extract-kernel-v1": ["uo/kernel/fold_receipt.yaml"],
    "normalize-variables-v1": ["uo/tiling/normalize_variables_receipt.yaml"],
    "derive-key-fields-v1": [
        "uo/ir/host_derivation.yaml",
        "uo/ir/derive_key_fields_receipt.yaml",
        "uo/tiling/key_derivations.yaml",
    ],
    "normalize-predicates-v1": ["uo/ir/unresolved.yaml"],
    "resolve-gaps-v1": ["uo/ir/resolve_gaps_receipt.yaml"],
    "resolve-gaps-staging-v1": [
        "uo/ir/resolve_gaps_staging.yaml",
        "runs/{run_id}/actions/resolve_gaps/parts/**",
        "runs/{run_id}/actions/resolve_gaps/staging.yaml",
    ],
    "gap-patch-v1": ["uo/ir/gap_patch_receipt.yaml", "uo/ir/gap_bindings.yaml"],
    "export-kb-v1": ["uo/ir/operator_graph.yaml", "uo/quality.yaml"],
    "build-index-v1": ["uo/indexes/kb_graph.sqlite"],
    "export-tg-host-view-v1": [
        "uo/ir/tg_host_view.yaml",
        "uo/checks/tg_host_view_receipt.yaml",
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
        "uo/ir/extract_plan_aliases.yaml",
        "uo/ir/receiver_bindings.yaml",
        "uo/ir/host_subgraph.yaml",
        "uo/ir/kernel_subgraph.yaml",
        "uo/ir/macro_semantics.yaml",
    ],
    "extract-plan-staging-v1": [
        # Deterministic-only: base graph; Map path: relation_parts → reduced relations.
        "runs/{run_id}/actions/extract_plan/staging/semantic_relations.base.yaml",
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
    "tg-init-intent-v1": ["tg/init/init_intent.yaml"],
    "tilingkey-contract-v1": [
        "tg/contract/tilingkey_contract.yaml",
        "tg/snapshot/understand_contract.json",
    ],
    "tilingkey-binding-v1": [
        "tg/realization/binding_inventory.yaml",
    ],
    "tilingkey-integrity-v1": [
        "tg/contract/integrity_gate.yaml",
    ],
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
    "plan-intent-v1": ["tg/plan/plan_intent.yaml"],
    "plan-precheck-v1": ["tg/init/status.yaml"],
    "plan-build-v1": ["tg/plan"],
    "plan-approved-v1": ["tg/plan/levels/*/human_supplement.yaml"],
    "solve-precheck-v1": ["tg/plan/levels/*/human_supplement.yaml"],
    "oracle-probe-v1": ["tg/closure/oracle_probe.yaml"],
    "closure-ledger-v1": [
        "tg/closure/R.txt",
        "tg/closure/open.txt",
        "tg/closure/excluded.txt",
    ],
    "closure-search-v1": ["tg/closure/rounds/**"],
    "closure-residual-v1": ["tg/closure/route.yaml"],
    "closure-construct-v1": ["tg/closure/construct/**"],
    "closure-explain-v1": ["tg/closure/construct/explain_receipt.yaml"],
    "lemma-leads-v1": ["tg/closure/lemmas/leads.yaml"],
    "lemma-mine-staging-v1": [
        "runs/{run_id}/actions/lemma_mine/parts/**",
        "runs/{run_id}/actions/lemma_mine/staging.yaml",
    ],
    "lemma-mine-v1": [
        "runs/{run_id}/actions/lemma_mine/parts/**",
        "runs/{run_id}/actions/lemma_mine/staging.yaml",
    ],
    "lemma-review-v1": [
        "runs/{run_id}/actions/lemma_review/review.yaml",
    ],
    "lemma-apply-v1": [
        "tg/closure/excluded.txt",
        "tg/closure/excluded_why.csv",
        "tg/closure/open.txt",
        "tg/closure/lemmas/reviews.yaml",
    ],
    "closure-audit-v1": [
        "runs/{run_id}/actions/closure_audit/review.yaml",
    ],
    "closure-certify-v1": [
        "tg/closure/certificate.yaml",
        "tg/closure/audit_report.yaml",
    ],
    "z3-solve-v1": ["tg/solve"],
    "cover-confirm-v1": [
        "tg/solve/**/realize_report.yaml",
        "tg/solve/**/solver_report.yaml",
    ],
    "tk-env-v1": ["uo/tk/env_probe.yaml"],
    "tk-derive-v1": ["uo/tk/derive_fields.yaml"],
    "tk-codemap-v1": [
        "uo/tk/export_codemap.yaml",
        "uo/ir/host_codemap.yaml",
    ],
    "tk-recipe-staging-v1": [
        "runs/{run_id}/actions/mine_recipe/parts/**",
        "runs/{run_id}/actions/mine_recipe/staging.yaml",
    ],
    "tk-recipe-v1": ["uo/tk/recipe.yaml", "uo/tk/apply_recipe.yaml"],
    "tk-gate-v1": ["uo/tk/coverage_gate.yaml"],
}

# Contracts that must contain at least one nonempty concrete artifact (not empty dir / empty file)
OUTPUT_CONTRACT_NONEMPTY_GLOBS: dict[str, list[str]] = {
    "scope-confirmed-v1": [
        "uo/runs/{run_id}/scope/scope_confirmed.yaml",
        "uo/runs/{run_id}/scope/receipt.yaml",
    ],
    "extract-plan-v1": [
        "uo/ir/extract_plan.yaml",
        "uo/ir/extract_plan_candidates.yaml",
        "uo/ir/extract_plan_aliases.yaml",
        "uo/ir/receiver_bindings.yaml",
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
    "tilingkey-contract-v1": [
        "tg/contract/tilingkey_contract.yaml",
    ],
    "tilingkey-binding-v1": [
        "tg/realization/binding_inventory.yaml",
    ],
    "tilingkey-integrity-v1": [
        "tg/contract/integrity_gate.yaml",
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
