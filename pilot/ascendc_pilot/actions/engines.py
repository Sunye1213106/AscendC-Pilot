"""Deterministic engine entrypoints invoked only by acp run-action."""

from __future__ import annotations

import os
import time
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
            architecture=arch,
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
    """Require CodeMap ``.uo`` with TG view blobs (D / host_view / graph)."""
    import yaml

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    ready = _ensure_uo_tg_views(project_root, tg_ctx)
    ok = bool(ready.get("ok")) and int(ready.get("legal_key_count") or 0) > 0
    receipt = {
        "schema": "tg-uo-ready/v1",
        "ok": ok,
        "mode": str(tg_ctx.get("mode") or "tilingkey_full_coverage"),
        "op_name": str(tg_ctx.get("op_name") or ""),
        "architecture": str(tg_ctx.get("architecture") or ""),
        "uo_product": str(ready.get("path") or ""),
        "legal_key_count": int(ready.get("legal_key_count") or 0),
        "error": "" if ok else str(ready.get("error") or "UO TG views not ready"),
    }
    out = _tg(project_root) / "init" / "uo_ready.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(receipt, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {
        "ok": ok,
        "engine": "kb_check",
        "mode": receipt["mode"],
        "gate": {
            "gate": "uo_ready",
            "ok": ok,
            "message": "ok" if ok else receipt["error"],
            "detail": ready,
        },
        "uo": ready,
        "receipt_path": out.as_posix(),
    }


def _ensure_uo_tg_views(project_root: Path, tg_ctx: dict[str, Any]) -> dict[str, Any]:
    """Locate ``.uo`` and ensure TPL/D + host/graph view_blobs exist."""
    try:
        from uo_init.tg_projection import ensure_tg_views

        return ensure_tg_views(
            project_root,
            op_name=str(tg_ctx.get("op_name") or ""),
            architecture=str(tg_ctx.get("architecture") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:400]}


def _load_uo_tg_doc(project_root: Path, tg_ctx: dict[str, Any], name: str) -> dict[str, Any]:
    """Load a TG view exclusively from the CodeMap ``.uo`` view_blob."""
    try:
        from uo_init.store.reader import find_uo_product, load_view_blob

        product = find_uo_product(
            project_root,
            op_name=str(tg_ctx.get("op_name") or ""),
            architecture=str(tg_ctx.get("architecture") or ""),
        )
        if product is None or product.suffix != ".uo":
            return {}
        blob = load_view_blob(product, name)
        return blob if isinstance(blob, dict) else {}
    except Exception:
        return {}


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

    arch_explicit = str(ctx.get("architecture") or "").strip() or None
    try:
        arch_hint = resolve_arch(arch_explicit)
    except ValueError as exc:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE") from exc
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
    if not architecture:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
    level = _pick(ctx.get("level"), state.get("level"), params.get("level"), pack.get("level"), default="L0")
    focus = _pick(ctx.get("focus"), state.get("focus"), params.get("focus"), pack.get("focus"))
    test_script_root = _pick(
        ctx.get("test_script_root"),
        state.get("test_script_root"),
        params.get("test_script_root"),
        pack.get("test_script_root"),
        run_ctx.get("test_script_root"),
        os.environ.get("ASCENDC_TEST_SCRIPT_ROOT"),
        init_intent.get("consumer_root"),
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
        "test_script_root": test_script_root,
        "mode": mode,
    }


_FULL_TK_MODES = frozenset({"tilingkey_full_coverage", "tilingkey_full"})


def _is_tilingkey_full(tg_ctx: dict[str, Any]) -> bool:
    return str(tg_ctx.get("mode") or "").strip() in _FULL_TK_MODES


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
            or tg_ctx.get("test_script_root")
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
    """Build tilingkey contract from CodeMap ``.uo`` view_blobs only."""
    import yaml

    tg = _tg(project_root)
    errors: list[str] = []
    ready = _ensure_uo_tg_views(project_root, tg_ctx)
    if not ready.get("ok"):
        errors.append(str(ready.get("error") or "uo_tg_views_unavailable"))
    graph_doc = _load_uo_tg_doc(project_root, tg_ctx, "ir/operator_graph.yaml")
    key_doc = _load_uo_tg_doc(project_root, tg_ctx, "tiling/exhaustive_key_space.yaml")
    view_doc = _load_uo_tg_doc(project_root, tg_ctx, "ir/tg_host_view.yaml")
    if not graph_doc:
        errors.append("missing view_blob ir/operator_graph.yaml in .uo")
    if not key_doc:
        errors.append("missing view_blob tiling/exhaustive_key_space.yaml in .uo")
    if not view_doc:
        errors.append("missing view_blob ir/tg_host_view.yaml in .uo")
    declared_count = int(key_doc.get("legal_key_count") or 0)
    if declared_count <= 0:
        declared_count = int(ready.get("legal_key_count") or 0)
    if declared_count <= 0:
        errors.append("DECLARED_SET_EMPTY: legal_key_count missing or zero")
    index_rel = str(key_doc.get("legal_key_index") or "tiling/legal_key_index.jsonl")
    try:
        from uo_init.tg_projection import legal_key_rows
        from uo_init.store.reader import find_uo_product

        product = find_uo_product(
            project_root,
            op_name=str(tg_ctx.get("op_name") or ""),
            architecture=str(tg_ctx.get("architecture") or ""),
        )
        if product is not None and declared_count > 0:
            n_rows = len(legal_key_rows(product))
            if n_rows and n_rows != declared_count:
                errors.append(
                    f"DECLARED_SET_MISMATCH: legal_key_count={declared_count} "
                    f"but legal_key_index has {n_rows} rows"
                )
    except Exception:
        pass
    contract = {
        "schema": "tg-tilingkey-contract/v1",
        "status": "pass" if not errors else "fail",
        "mode": "tilingkey_full_coverage",
        "op_name": tg_ctx["op_name"],
        "architecture": tg_ctx["architecture"],
        "declared_set": {
            "source": "uo:tiling/exhaustive_key_space.yaml",
            "fingerprint": str(
                key_doc.get("fingerprint")
                or graph_doc.get("fingerprint")
                or ready.get("graph_fingerprint")
                or ""
            ),
            "count": declared_count,
            "legal_key_index": index_rel,
        },
        "graph_fingerprint": str(
            graph_doc.get("fingerprint") or ready.get("graph_fingerprint") or ""
        ),
        "host_view": "uo:ir/tg_host_view.yaml",
        "uo_product": str(ready.get("path") or ""),
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
        if _is_tilingkey_full(tg_ctx):
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
                "payload": payload,
                "errors": payload.get("errors") or [],
            }
        return {
            "ok": False,
            "engine": "contract_build",
            "error": "legacy CSV contract path removed; use tilingkey_full_coverage",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "contract_build", "error": str(exc)[:400]}


def _run_tg_semantic_bind(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    tg = _tg(project_root)
    try:
        if _is_tilingkey_full(tg_ctx):
            import yaml

            _ensure_uo_tg_views(project_root, tg_ctx)
            view = _load_uo_tg_doc(project_root, tg_ctx, "ir/tg_host_view.yaml")
            graph_doc = _load_uo_tg_doc(project_root, tg_ctx, "ir/operator_graph.yaml")
            if not view:
                return {
                    "ok": False,
                    "engine": "semantic_bind",
                    "error": "missing view_blob ir/tg_host_view.yaml in .uo",
                }
            rows = []
            for f in view.get("fields") or []:
                name = str(f.get("name") or "")
                if not name:
                    continue
                reads = list(f.get("reads") or [])
                rows.append({
                    "field": name,
                    "kind": f.get("kind"),
                    "tiling_key": f.get("tiling_key"),
                    "reads": reads,
                    "exactness": f.get("exactness"),
                    "entity_id": f.get("entity_id"),
                    "packing": list(f.get("packing") or []),
                })
            # Also bind declared key dims when host fields are sparse.
            for dim, meta in (view.get("declared_keys") or {}).items():
                if any(r.get("field") == dim or r.get("tiling_key") == dim for r in rows):
                    continue
                rows.append({
                    "field": str(dim),
                    "kind": "key_dim",
                    "tiling_key": str(dim),
                    "reads": [],
                    "exactness": "",
                    "packing": list((meta or {}).get("packing") or []),
                })
            inv = {
                "schema": "tg-tilingkey-binding-inventory/v1",
                "mode": "tilingkey_full_coverage",
                "fields": rows,
                "field_count": len(rows),
                "graph_fingerprint": str(
                    graph_doc.get("fingerprint")
                    or (view.get("source") or {}).get("graph_fingerprint")
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
                "field_count": len(rows),
            }

        return {
            "ok": False,
            "engine": "semantic_bind",
            "error": "legacy CSV bind path removed; use tilingkey_full_coverage",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "semantic_bind", "error": str(exc)[:400]}




def _run_tg_integrity(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    import yaml

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    tg = _tg(project_root)
    _ = tg_ctx
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
        level = tg_ctx["level"] or "L0"
        if _is_tilingkey_full(tg_ctx):
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
            text = yaml.safe_dump(obligations, allow_unicode=True, sort_keys=False)
            obl = _tg(project_root) / "plan" / "levels" / level / "coverage_obligations.yaml"
            obl.parent.mkdir(parents=True, exist_ok=True)
            obl.write_text(text, encoding="utf-8")
            # plan-build-v1 also requires the root alias used by ownership/contracts.
            root_obl = _tg(project_root) / "plan" / "coverage_obligations.yaml"
            root_obl.parent.mkdir(parents=True, exist_ok=True)
            root_obl.write_text(text, encoding="utf-8")
            unresolved = {
                "schema": "tg-unresolved/v1",
                "status": "ready_for_manual_review",
                "allow_solve": True,
                "allow_solve_reason": "tilingkey_full_coverage T=D approved for closure",
                "blocking_hard_obligations": [],
                "contract_gaps": [],
                "plan_hash": fp,
            }
            unresolved_path = obl.parent / "unresolved.yaml"
            unresolved_path.write_text(
                yaml.safe_dump(unresolved, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            return {
                "ok": True,
                "engine": "plan_build",
                "op_name": op_name,
                "level": level,
                "mode": "tilingkey_full_coverage",
                "artifact": obl.as_posix(),
                "root_artifact": root_obl.as_posix(),
                "unresolved": unresolved_path.as_posix(),
                "declared_count": count,
            }

        return {
            "ok": False,
            "engine": "plan_build",
            "error": "legacy CSV plan path removed; use tilingkey_full_coverage",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_build", "error": str(exc)[:400]}


def _run_tg_solve_precheck(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.gates import run_named_gate

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
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
    selfcheck_doc: dict[str, Any] = {}
    if live_probe:
        live["attempted"] = True
        try:
            from testcase_agent.closure import generate as G
            from testcase_agent.closure import oracle as O
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
                O.write_oracle_suspect(ws, "ORACLE_SUSPECT:not_run")
            if accepted == 0:
                issues.append("ORACLE_SUSPECT:accepted==0")
            if with_key == 0:
                issues.append("ORACLE_SUSPECT:accepted_with_key==0")

            # Strengthened selfcheck: DONE count, wide CSV, driver config, singleton dims.
            done_count = batch_accounting.get("judged")
            log_text = str(ctx.get("driver_log") or live.get("driver_log") or "")
            if log_text:
                done_count = O.count_done_marks(log_text)
            wide = ctx.get("wide_csv")
            if not wide:
                # Best-effort: newest key_cases CSV under artifacts.
                try:
                    cands = sorted(ws.artifacts.glob("*key_cases*.csv"), key=lambda p: p.stat().st_mtime)
                    wide = str(cands[-1]) if cands else None
                except Exception:
                    wide = None
            driver_doc = None
            try:
                from replay.package_data import resolve_adapter_file, package_file, load_yaml
                import yaml as _yaml

                man = resolve_adapter_file("operator.yaml") or package_file("operator.yaml")
                if man.is_file():
                    driver_doc = _yaml.safe_load(man.read_text(encoding="utf-8")) or {}
                proto = load_yaml("log_protocol.yaml", refresh=True)
                if proto:
                    driver_doc = {**(driver_doc or {}), **proto}
            except Exception:
                pass
            corpus_rows: list[dict[str, Any]] = []
            try:
                from testcase_agent.closure import corpus as C

                df = C.load(ws)
                if df is not None and not df.empty:
                    corpus_rows = df.to_dict(orient="records")
            except Exception:
                corpus_rows = []
            dim_names: list[str] = []
            try:
                dim_names = list(WS.dim_names())
            except Exception:
                dim_names = []
            selfcheck_doc = O.selfcheck(
                sent=len(cases),
                done_count=int(done_count) if done_count is not None else None,
                wide_csv=wide,
                driver_doc=driver_doc,
                corpus_rows=corpus_rows,
                dims=dim_names,
                ws=ws,
            )
            issues.extend(selfcheck_doc.get("issues") or [])
            live["selfcheck_warnings"] = list(selfcheck_doc.get("warnings") or [])
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
        # Still run offline selfcheck pieces when artifacts exist.
        try:
            from testcase_agent.closure import oracle as O

            wide = ctx.get("wide_csv")
            selfcheck_doc = O.selfcheck(
                sent=ctx.get("sent"),
                done_count=ctx.get("done_count"),
                wide_csv=wide,
                driver_doc=ctx.get("driver_doc"),
                corpus_rows=ctx.get("corpus_rows"),
                dims=ctx.get("dims"),
                ws=ws,
            )
            # Offline mismatches still raise suspect, but CI schema-only may ignore.
            if selfcheck_doc.get("issues") and not (
                str((__import__("os").environ.get("TG_CLOSURE_CI") or "")).strip().lower()
                in {"1", "true", "yes"}
            ):
                issues.extend(selfcheck_doc["issues"])
            live["selfcheck_warnings"] = list(selfcheck_doc.get("warnings") or [])
        except Exception:
            pass

    doc = {
        "schema": "tg-oracle-probe/v3",
        "ok": len(issues) == 0,
        "issues": issues,
        "state": str(ws.state),
        "baseline": baseline,
        "live": live,
        "live_probe": live_probe,
        "selfcheck": selfcheck_doc,
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
        "growth_match": routed.get("growth_match"),
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
        "target_hit_rate": routed.get("target_hit_rate"),
        "rewrite_share": routed.get("rewrite_share"),
        "refuse_share": routed.get("refuse_share"),
        "round_growth": routed.get("round_growth") or {},
        "lemma_trigger": routed.get("lemma_trigger"),
        "construct_trigger": routed.get("construct_trigger"),
    }
    out = _tg(project_root) / "closure" / "route.yaml"
    _dump_closure_yaml(out, route_doc)

    new_r = None
    new_declared_r = None
    rounds_dir = ws.state / "rounds"
    if rounds_dir.is_dir():
        rounds = sorted(rounds_dir.glob("round_*"))
        if rounds:
            latest_prog = rounds[-1] / "progress.yaml"
            if latest_prog.is_file():
                try:
                    import yaml

                    prog_doc = yaml.safe_load(latest_prog.read_text(encoding="utf-8")) or {}
                    new_r = prog_doc.get("new_R")
                    new_declared_r = prog_doc.get("new_declared_R", new_r)
                except Exception:
                    new_r = None

    round_analysis = {
        "schema": "tg-closure-round-analysis/v1",
        "blame": analysis.get("blame"),
        "distance_histogram": analysis.get("distance"),
        "mostly_distance_1": analysis.get("mostly_distance_1"),
        "open_patterns": analysis.get("open_patterns"),
        "pattern_dims": analysis.get("pattern_dims"),
        "r_witness_values": analysis.get("r_witness_values"),
        "reason": reason,
        "growth_match": routed.get("growth_match"),
        "state": route_doc["state"],
        "target_hit_rate": routed.get("target_hit_rate"),
        "rewrite_share": routed.get("rewrite_share"),
        "refuse_share": routed.get("refuse_share"),
        "round_growth": routed.get("round_growth") or {},
        "lemma_trigger": routed.get("lemma_trigger"),
        "construct_trigger": routed.get("construct_trigger"),
        "new_R": new_r,
        "new_declared_R": new_declared_r,
        "timestamp": time.time(),
        "note": (
            "Analyse after every replay round. expected→lemma on rejects; "
            "unexpected→directed construct from discovered R + source."
        ),
    }
    analysis_out = _tg(project_root) / "closure" / "round_analysis.yaml"
    _dump_closure_yaml(analysis_out, round_analysis)
    stamp_path = ws.state / "round_analysis.stamp"
    stamp_path.write_text(str(round_analysis["timestamp"]), encoding="utf-8")

    return {
        "ok": True,
        "engine": "closure_residual",
        "reason_code": reason,
        "reason_codes": [reason],
        "needs_rework": needs_rework,
        "escalate": escalate,
        "artifact": out.as_posix(),
        "round_analysis": analysis_out.as_posix(),
        **route_doc,
    }


def _run_closure_construct(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent.closure import construct
    from testcase_agent.closure import residual
    from testcase_agent.closure import workspace as WS

    ws = _closure_ws(project_root)
    skip_gate = bool(ctx.get("skip_analysis_gate")) or os.environ.get("TG_SKIP_ANALYSIS_GATE") == "1"
    analysis_path = _tg(project_root) / "closure" / "round_analysis.yaml"
    stamp_path = ws.state / "round_analysis.stamp"
    if not skip_gate:
        if not analysis_path.is_file() or not stamp_path.is_file():
            return {
                "ok": False,
                "engine": "closure_construct",
                "reason": "ANALYSIS_REQUIRED",
                "error": "Host/residual round_analysis required before construct",
            }
        try:
            import yaml

            analysis_doc = yaml.safe_load(analysis_path.read_text(encoding="utf-8")) or {}
            analysis_ts = float(analysis_doc.get("timestamp") or 0)
            corpus_mtime = 0.0
            for pattern in ("*key_cases*.csv", "rounds/**/*key_cases*.csv"):
                for csv_path in ws.artifacts.glob(pattern):
                    if csv_path.is_file():
                        corpus_mtime = max(corpus_mtime, csv_path.stat().st_mtime)
            if corpus_mtime > analysis_ts + 1:
                return {
                    "ok": False,
                    "engine": "closure_construct",
                    "reason": "ANALYSIS_REQUIRED",
                    "error": "Host corpus newer than round_analysis; rerun residual",
                }
        except Exception:
            pass

    analysis = residual.analyse(ws)
    targets = residual.distance_one_targets(analysis)[: int(ctx.get("limit") or 32)]
    built = 0
    cases: list = []
    traces: list[dict[str, Any]] = []
    path_counts: dict[str, int] = {"hook": 0, "codemap": 0, "hints": 0, "empty": 0}
    for t in targets:
        key = t.get("key")
        try:
            inst = WS.decode(int(key))
            spelled, meta = construct.build_with_meta(inst)
            path = str(meta.get("path") or construct.last_build_path() or "empty")
            path_counts[path] = path_counts.get(path, 0) + 1
            codemap_traces = construct.last_traces()
            cases.extend(spelled)
            built += 1
            traces.append(
                {
                    "key": int(key),
                    "differing_dims": t.get("differing_dims"),
                    "spelled": len(spelled),
                    "path": path,
                    "codemap": codemap_traces,
                }
            )
        except Exception as exc:  # noqa: BLE001
            traces.append({"key": key, "error": str(exc)[:200]})
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

    trace_with_codemap = sum(1 for x in traces if x.get("codemap"))
    trace_coverage = (trace_with_codemap / len(traces)) if traces else 0.0
    warnings: list[str] = []
    # trace_coverage cannot detect hook dominance: the hook path also emits
    # CodeMap traces, so it sits at 1.0 even when nothing was CodeMap-directed.
    codemap_share = (path_counts.get("codemap", 0) / built) if built else 0.0
    hook_share = (path_counts.get("hook", 0) / built) if built else 0.0
    if trace_coverage < 0.2 and built > 0:
        warnings.append("codemap_trace_low")
    if built > 0 and codemap_share < 0.5:
        warnings.append(
            f"construct_hook_dominated:codemap_share={codemap_share:.2f}"
        )
    construct_issues: list[str] = []
    if built > 0 and hook_share >= 1.0:
        # A hook may implement knobs but must not replace the CodeMap path.
        construct_issues.append(
            "construct_bypassed_codemap: every target came from the "
            "operator hook; CodeMap-directed construction produced nothing"
        )

    doc = {
        "schema": "tg-closure-construct/v1",
        "targets": len(targets),
        "built_cases": len(cases),
        "targets_decoded": built,
        "replayed": replayed,
        "sample_keys": [t.get("key") for t in targets[:10]],
        "error": doc_err,
        "codemap_directed": any(bool(x.get("codemap")) for x in traces),
        "trace_coverage": round(trace_coverage, 4),
        "path_counts": path_counts,
        "codemap_share": round(codemap_share, 4),
        "warnings": warnings,
        "issues": construct_issues,
    }
    out = _tg(project_root) / "closure" / "construct" / "targets.yaml"
    _dump_closure_yaml(out, doc)
    trace_path = _tg(project_root) / "closure" / "construct" / "trace.yaml"
    _dump_closure_yaml(
        trace_path,
        {"schema": "tg-closure-construct-trace/v1", "traces": traces[:64]},
    )
    ok = not construct_issues or bool(ctx.get("allow_hook_only"))
    return {
        "ok": ok,
        "engine": "closure_construct",
        "artifact": out.as_posix(),
        "trace": trace_path.as_posix(),
        "reason": "" if ok else "CODEMAP_PATH_REQUIRED",
        **doc,
    }


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
            return {
                "ok": True,
                "engine": "closure_explain",
                "evidence": "none",
                "why_exists": why.is_file() if why else False,
                "path": "",
                "ran": False,
                "accepted": 0,
                "error": err,
            }
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
    from testcase_agent.closure import observations as OBS

    ws = _closure_ws(project_root)
    try:
        leads = OBS.build_leads(ws, top=40)
        err = str(leads.get("error") or "")
    except Exception as exc:  # noqa: BLE001
        leads = {
            "schema": "tg-lemma-leads/v1",
            "source": "oracle_observation",
            "observation_count": 0,
            "lead_count": 0,
            "leads": [],
            "pairs": [],
            "triples": [],
            "pair_count": 0,
            "triple_count": 0,
            "error": str(exc)[:300],
            "note": "lemma leads require Host REWRITE/REFUSE observations",
        }
        err = leads["error"]
    out = _tg(project_root) / "closure" / "lemmas" / "leads.yaml"
    _dump_closure_yaml(out, leads)
    return {
        "ok": not err,
        "engine": "lemma_leads",
        "artifact": out.as_posix(),
        "lead_count": int(leads.get("lead_count") or 0),
        "observation_count": int(leads.get("observation_count") or 0),
        "pair_count": int(leads.get("pair_count") or 0),
        "triple_count": int(leads.get("triple_count") or 0),
        "error": err,
    }


def _run_lemma_evidence(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Deterministic evidence packs for observation leads (pre-mine)."""
    del ctx
    from testcase_agent.closure import lemma_evidence as LE

    ws = _closure_ws(project_root)
    leads_path = _tg(project_root) / "closure" / "lemmas" / "leads.yaml"
    leads_doc = _load_yaml(leads_path) or {}
    try:
        out = LE.collect_for_leads(leads_doc, ws=ws, top=40)
        err = ""
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "written": [], "lead_count": 0, "error": str(exc)[:300]}
        err = str(exc)[:300]
    receipt = {
        "schema": "tg-lemma-evidence-batch/v1",
        "ok": bool(out.get("ok")),
        "lead_count": int(out.get("lead_count") or 0),
        "written": list(out.get("written") or []),
        "evidence_dir": str(
            out.get("evidence_dir")
            or (_tg(project_root) / "closure" / "lemmas" / "evidence")
        ),
        "error": err,
    }
    receipt_path = _tg(project_root) / "closure" / "lemmas" / "evidence_receipt.yaml"
    _dump_closure_yaml(receipt_path, receipt)
    return {
        "ok": bool(out.get("ok")) and not err,
        "engine": "lemma_evidence",
        "artifact": receipt_path.as_posix(),
        "lead_count": receipt["lead_count"],
        "written_count": len(receipt["written"]),
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
    lead_n = int(
        leads.get("lead_count")
        or len(leads.get("leads") or [])
        or (int(leads.get("pair_count") or 0) + int(leads.get("triple_count") or 0))
    )
    # Hand the producer minimised, R-consistent antecedents plus the values R
    # actually witnessed per dimension. Without these it has to invent
    # propositions and most get refuted on arrival.
    #
    # Aiming information, not a precondition: an operator whose key schema does
    # not parse still gets a staging contract, just without hypotheses. Catching
    # SystemExit is deliberate — the replay runner exits rather than raises when
    # it cannot locate the key header.
    hyp: dict[str, Any] = {}
    r_witness: dict[str, Any] = {}
    try:
        from testcase_agent.closure import hypothesis as HYP
        from testcase_agent.closure import residual as RES

        ws_mine = _closure_ws(project_root)
        analysis = RES.analyse(ws_mine)
        hyp = HYP.propose(ws_mine, analysis=analysis)
        r_witness = analysis.get("r_witness_values") or {}
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        hyp = {"unavailable": str(exc)[:300].splitlines()[0], "hypotheses": []}

    staging = {
        "schema": "tg-lemma-mine-staging/v1",
        "status": "awaiting_subagent",
        "lead_count": lead_n,
        "hypotheses": hyp.get("hypotheses") or [],
        "hypothesis_stats": {
            k: hyp.get(k)
            for k in (
                "open",
                "R",
                "candidate_count",
                "covered_open",
                "pattern_dims",
                "unavailable",
            )
            if hyp.get(k) is not None
        },
        "r_witness_values": r_witness,
        "contract": {
            "required_fields": [
                "proposition",
                "codemap_anchors",
                "obligations",
                "source_citations",
                "verdict",
            ],
            "verdict_enum": ["PROVED", "REFUTED", "INSUFFICIENT"],
            "obligation_status": ["OPEN", "CLOSED", "BLOCKED"],
            "rules": [
                "Each candidate must state P => Q as proposition",
                "codemap_anchors: list of {entity_id or relation_id, query}",
                "obligations: list of {id, status, evidence}",
                "source_citations: list of {file, line, quote}",
                "PROVED requires all required obligations CLOSED",
                "No empty candidates allowed for lemma_apply",
                "A hypothesis is not evidence: absence from R never proves unreachability",
                "Never exclude a value listed under r_witness_values[dim].in_R",
                "when values may be scalars, [a,b], {in:[...]} or {not_in:[...]}",
            ],
        },
        "instructions": (
            "Start from staging hypotheses: each is a minimised antecedent that no "
            "witness satisfies. For each one, either cite the host code that forbids "
            "the combination (verdict PROVED, obligations CLOSED) or mark it REFUTED / "
            "INSUFFICIENT with the reason. Write results to parts/part_0.yaml keeping "
            "the `when` clause as given unless the source says a weaker or stronger "
            "antecedent is the real one. Check r_witness_values before narrowing. "
            "Follow skills/source-proof/SKILL.md."
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
            "note": "placeholder — producer replaces with cited lemmas per staging contract",
        })
    return {
        "ok": True,
        "engine": "lemma_mine",
        "staging": str(parts / "staging.yaml"),
        "need_subagent": True,
        "hypotheses": len(staging["hypotheses"]),
        "covered_open": hyp.get("covered_open"),
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


def _mine_candidates(project_root: Path, run_id: str) -> list[dict[str, Any]]:
    """Candidates written by lemma_mine, placeholders dropped."""
    from ascendc_pilot.paths import agent_root

    mine = agent_root(project_root) / "runs" / run_id / "actions" / "lemma_mine"
    out: list[dict[str, Any]] = []
    paths = sorted(mine.glob("parts/*.yaml"))
    if not paths and (mine / "staging.yaml").is_file():
        paths = [mine / "staging.yaml"]
    for path in paths:
        doc = _load_yaml(path) or {}
        for cand in doc.get("candidates") or []:
            if not isinstance(cand, dict) or not cand:
                continue
            if "placeholder" in str(cand.get("note") or "").lower():
                continue
            out.append(cand)
    return out


def _verify_candidates(ws, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Project each candidate onto R and report refutations with witnesses."""
    from testcase_agent.closure import lemma

    checked = lemma.verify_lemmas(candidates, ws)
    return {
        "candidates": len(candidates),
        "survivors": checked.get("survivors"),
        "refuted": checked.get("refuted") or [],
        "closes": checked.get("closed"),
        "open_before": checked.get("open_before"),
        "open_after": checked.get("open_after"),
        "lemmas": checked.get("lemmas") or [],
    }


def _run_lemma_verify(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Refute mined candidates against R before a referee reviews them.

    A candidate that some witness already satisfies is wrong no matter how good
    the prose is, and finding that out here costs nothing.
    """
    ws = _closure_ws(project_root)
    run_id = str(ctx.get("run_id") or "local")
    candidates = _mine_candidates(project_root, run_id)
    if not candidates:
        return {
            "ok": False,
            "engine": "lemma_verify",
            "reason": "PROOF_REQUIRED",
            "error": "no lemma_mine candidates to verify",
            "candidates": 0,
        }

    result = _verify_candidates(ws, candidates)
    doc = {
        "schema": "tg-lemma-verify/v1",
        **{k: result[k] for k in ("candidates", "survivors", "refuted", "closes", "open_before", "open_after")},
        "survivor_labels": [
            {"label": s.get("label"), "closes": s.get("closes")}
            for s in result["lemmas"]
        ],
    }
    from ascendc_pilot.paths import agent_root

    out = agent_root(project_root) / "runs" / run_id / "actions" / "lemma_verify" / "verify.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    _dump_closure_yaml(out, doc)
    _dump_closure_yaml(_tg(project_root) / "closure" / "lemmas" / "verify.yaml", doc)
    return {
        "ok": True,
        "engine": "lemma_verify",
        "artifact": out.as_posix(),
        "reason": "REFUTED" if result["refuted"] else "",
        **doc,
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
    parts_dir = agent_root(project_root) / "runs" / run_id / "actions" / "lemma_mine" / "parts"
    part_docs: list[dict[str, Any]] = []
    if parts_dir.is_dir():
        for part_path in sorted(parts_dir.glob("*.yaml")):
            doc = _load_yaml(part_path) or {}
            if doc:
                part_docs.append(doc)

    def _candidate_count(docs: list[dict[str, Any]]) -> int:
        total = 0
        for doc in docs:
            for cand in doc.get("candidates") or []:
                if isinstance(cand, dict) and cand:
                    note = str(cand.get("note") or "").lower()
                    if "placeholder" in note:
                        continue
                    total += 1
        return total

    accepted = list(review.get("accepted") or [])
    review_status = str(review.get("status") or "").strip().lower()
    candidate_n = _candidate_count(part_docs)

    if review_status in {"awaiting_referee", "pending", "open", ""} and not accepted:
        return {
            "ok": False,
            "engine": "lemma_apply",
            "reason": "REVIEW_REQUIRED",
            "error": "lemma_review awaiting referee before apply",
        }

    if not accepted:
        if part_docs and candidate_n == 0 and not ctx.get("allow_empty_apply"):
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "PROOF_REQUIRED",
                "error": (
                    "lemma_mine produced no candidates; producer must write "
                    "PROVED/REFUTED certificates before apply"
                ),
            }
        if not part_docs and not ctx.get("allow_empty_apply"):
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "PROOF_REQUIRED",
                "error": "lemma_mine parts missing; proof required before apply",
            }

    for entry in accepted:
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("proposition") or "").strip():
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "PROOF_REQUIRED",
                "error": "accepted entry missing proposition",
            }
        verdict = str(entry.get("verdict") or "").strip().upper()
        if verdict != "PROVED":
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "PROOF_REQUIRED",
                "error": f"accepted entry verdict must be PROVED (got {verdict or 'missing'})",
            }
        obligations = entry.get("obligations") or []
        if obligations:
            open_obs = [
                o for o in obligations
                if isinstance(o, dict)
                and str(o.get("status") or "").strip().upper() not in {"CLOSED"}
            ]
            if open_obs:
                return {
                    "ok": False,
                    "engine": "lemma_apply",
                    "reason": "PROOF_REQUIRED",
                    "error": "PROVED certificate has open obligations",
                }

    # Persist referee receipt into the closure ledger for subsequent rounds.
    if review:
        _dump_closure_yaml(tg / "closure" / "lemmas" / "reviews.yaml", review)
    promoted = {"promoted": 0}
    verification: dict[str, Any] = {}
    if accepted:
        # An accepted entry that a witness already satisfies must never reach E,
        # whatever the referee wrote.
        verification = _verify_candidates(ws, [e for e in accepted if isinstance(e, dict)])
        if verification["refuted"]:
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "REFUTED_BY_R",
                "error": (
                    f"{len(verification['refuted'])} accepted lemma(s) are satisfied "
                    "by real witnesses; they cannot exclude declared keys"
                ),
                "refuted": verification["refuted"],
            }

        from testcase_agent.closure import cold_start as _cs

        pre = _cs.require_cold_start(ws)
        if not pre["ok"]:
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "PROVENANCE_REQUIRED",
                "error": (
                    "E may not grow without a sealed cold start: "
                    f"{','.join(pre['issues'])}; run tg-cold-start before apply"
                ),
                "provenance": pre,
            }
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
    if promoted.get("promoted"):
        # E grew, so a saturated search may be worth reopening.
        try:
            from testcase_agent.closure import search_round

            search_round.clear_lockout(ws)
        except Exception:
            pass
    return {
        "engine": "lemma_apply",
        "promote": promoted,
        "verification": {
            k: verification.get(k) for k in ("candidates", "survivors", "closes")
        } if verification else {},
        **out,
    }


def _run_lemma_loop(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Re-entrant lemma convergence: analyse → hypothesize → verify → apply.

    Replaces the one-shot scripts under artifacts/fa-pr13. Each round records
    ``tg/closure/rounds/round_N/lemma.yaml``. The engine cannot invent source
    citations: when survivors need a producer proof it stops with
    ``NEED_PRODUCER`` and leaves the verified hypotheses in staging for the
    next mine/review turn. When proved candidates are already present it
    promotes them and continues until gap stops falling or the round budget
    is spent.
    """
    from testcase_agent.closure import hypothesis as HYP
    from testcase_agent.closure import ledger
    from testcase_agent.closure import residual as RES
    from ascendc_pilot.paths import agent_root

    ws = _closure_ws(project_root)
    run_id = str(ctx.get("run_id") or "local")
    max_rounds = int(ctx.get("max_rounds") or 8)
    rounds_dir = ws.state / "rounds"
    rounds_dir.mkdir(parents=True, exist_ok=True)

    history: list[dict[str, Any]] = []
    stop_reason = "ROUND_BUDGET"
    final_st = ledger.state(ws)

    for i in range(max_rounds):
        analysis = RES.analyse(ws)
        gap_before = int(analysis.get("open") or 0)
        if gap_before == 0:
            stop_reason = "GAP_ZERO"
            final_st = ledger.state(ws)
            break

        hyp = HYP.propose(ws, analysis=analysis)
        hypotheses = list(hyp.get("hypotheses") or [])
        verification = _verify_candidates(ws, hypotheses) if hypotheses else {
            "candidates": 0, "survivors": 0, "refuted": [], "closes": 0, "lemmas": []
        }

        # Prefer already-proved candidates from mine parts / ctx; otherwise
        # stage the verified hypotheses for a producer.
        proved = [
            c for c in _mine_candidates(project_root, run_id)
            if str(c.get("verdict") or "").upper() == "PROVED"
        ]
        proved.extend(
            c for c in (ctx.get("proved") or [])
            if isinstance(c, dict) and str(c.get("verdict") or "").upper() == "PROVED"
        )

        apply_out: dict[str, Any] = {"skipped": True}
        if proved:
            # Re-verify proved set against R before promote.
            pv = _verify_candidates(ws, proved)
            survivors = [
                c for c in proved
                if not any(
                    str(r.get("label")) == str(c.get("label"))
                    for r in (pv.get("refuted") or [])
                )
            ]
            if not survivors:
                apply_out = {
                    "ok": False,
                    "reason": "REFUTED_BY_R",
                    "refuted": pv.get("refuted"),
                }
            else:
                apply_ctx = {
                    **ctx,
                    "run_id": run_id,
                    "review": {
                        "schema": "tg-lemma-review/v1",
                        "status": "accepted",
                        "accepted": survivors,
                        "rejected": [],
                    },
                }
                # lemma_apply reads review from disk normally; inject via the
                # same path the referee writes.
                review_dir = (
                    agent_root(project_root)
                    / "runs"
                    / run_id
                    / "actions"
                    / "lemma_review"
                )
                review_dir.mkdir(parents=True, exist_ok=True)
                _dump_closure_yaml(review_dir / "review.yaml", apply_ctx["review"])
                apply_out = _run_lemma_apply(project_root, apply_ctx)
        else:
            # Deterministic fallback: put verified hypotheses into mine staging
            # so a producer (or the next loop call after proof) can continue.
            mine_dir = (
                agent_root(project_root) / "runs" / run_id / "actions" / "lemma_mine"
            )
            mine_dir.mkdir(parents=True, exist_ok=True)
            staging = {
                "schema": "tg-lemma-mine-staging/v1",
                "status": "awaiting_subagent",
                "hypotheses": verification.get("lemmas") or hypotheses,
                "r_witness_values": analysis.get("r_witness_values") or {},
                "open_patterns": analysis.get("open_patterns") or [],
                "loop_round": i,
                "note": (
                    "Engine-verified antecedents for this round. Absence from R "
                    "is not unreachability — source proof required before apply."
                ),
            }
            _dump_closure_yaml(mine_dir / "staging.yaml", staging)
            apply_out = {
                "ok": False,
                "reason": "NEED_PRODUCER",
                "hypotheses": len(hypotheses),
                "survivors": verification.get("survivors"),
            }

        st_after = ledger.state(ws)
        gap_after = int(st_after.get("gap") or 0)
        round_doc = {
            "schema": "tg-lemma-loop-round/v1",
            "round": i,
            "gap_before": gap_before,
            "gap_after": gap_after,
            "hypotheses": len(hypotheses),
            "verify": {
                k: verification.get(k)
                for k in ("candidates", "survivors", "closes", "refuted")
            },
            "apply": {
                k: apply_out.get(k)
                for k in ("ok", "reason", "promote", "E", "gap", "error")
                if k in apply_out or apply_out.get(k) is not None
            },
            "state": st_after,
        }
        round_path = rounds_dir / f"round_{i}" / "lemma.yaml"
        round_path.parent.mkdir(parents=True, exist_ok=True)
        _dump_closure_yaml(round_path, round_doc)
        history.append(round_doc)
        final_st = st_after

        if gap_after == 0:
            stop_reason = "GAP_ZERO"
            break
        if apply_out.get("reason") == "NEED_PRODUCER":
            stop_reason = "NEED_PRODUCER"
            break
        if apply_out.get("reason") == "PROVENANCE_REQUIRED":
            stop_reason = "PROVENANCE_REQUIRED"
            break
        if gap_after >= gap_before:
            stop_reason = "GAP_STALLED"
            break

    summary = {
        "schema": "tg-lemma-loop/v1",
        "ok": stop_reason == "GAP_ZERO",
        "engine": "lemma_loop",
        "stop_reason": stop_reason,
        "rounds": len(history),
        "history": history,
        "state": final_st,
    }
    out = _tg(project_root) / "closure" / "lemma_loop.yaml"
    _dump_closure_yaml(out, summary)
    return {**summary, "artifact": out.as_posix()}


def _producer_id(project_root: Path, run_id: str) -> str:
    """Identity that mined the lemmas, read from lemma_mine parts/staging."""
    from ascendc_pilot.paths import agent_root

    mine = agent_root(project_root) / "runs" / run_id / "actions" / "lemma_mine"
    for path in sorted(mine.glob("parts/*.yaml")) + [mine / "staging.yaml"]:
        doc = _load_yaml(path) or {}
        pid = str(doc.get("producer_id") or doc.get("producer") or "").strip()
        if pid:
            return pid
    return ""


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
    soundness = lemma.soundness_ok(ws)
    if existing.is_file():
        doc = yaml.safe_load(existing.read_text(encoding="utf-8")) or {}
        # A referee may set the verdict, but never invent the facts or the
        # writer_role — leaving role empty is how certify rejects a hand-written
        # review that bypasses this action.
        doc["state"] = st
        doc["soundness_ok"] = soundness
        existing.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    else:
        # auto_ok is an engine shortcut only: gap already closed and soundness
        # holds. Certify refuses auto_ok unless writer_role=engine.
        doc = {
            "schema": "tg-closure-audit/v1",
            "status": "awaiting_referee" if st.get("gap", 1) else "auto_ok",
            "state": st,
            "soundness_ok": soundness,
            "writer_role": "engine",
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
    audit_reason = ""
    writer_role = str(audit_doc.get("writer_role") or "").strip().lower()
    # Never trust the verdict written in the file: recompute the facts it claims.
    from testcase_agent.closure import lemma as _lemma

    soundness_now = bool(_lemma.soundness_ok(ws))
    if not audit_doc:
        audit_ok = False
        audit_reason = "audit_missing"
    elif not writer_role:
        # Hand-written review.yaml without role is the bypass
        # certify_with_provenance.py used; refuse it by name.
        audit_ok = False
        audit_reason = "audit_writer_role_invalid"
    elif audit_status in {"awaiting_referee", "pending", "open", "fail", "failed", "reject", "rejected"}:
        audit_ok = False
        audit_reason = f"audit_status={audit_status or 'empty'}"
    elif audit_status == "auto_ok":
        # auto_ok is only an engine shortcut and must be re-derivable right now.
        if writer_role != "engine":
            audit_ok = False
            audit_reason = "audit_writer_role_invalid"
        else:
            audit_ok = soundness_now and bool(rep.get("gap_zero"))
            if not audit_ok:
                audit_reason = (
                    f"auto_ok_not_rederivable soundness={soundness_now} "
                    f"gap_zero={bool(rep.get('gap_zero'))}"
                )
    elif audit_status in {"pass", "passed", "accepted"}:
        # A human/model referee verdict requires writer_role=referee and an
        # identity distinct from the producer that mined the lemmas.
        referee_id = str(audit_doc.get("referee_id") or "").strip()
        producer_id = _producer_id(project_root, run_id)
        if writer_role != "referee":
            audit_ok = False
            audit_reason = "audit_writer_role_invalid"
        elif not referee_id:
            audit_ok = False
            audit_reason = "referee_id_missing"
        elif producer_id and referee_id == producer_id:
            audit_ok = False
            audit_reason = f"referee_equals_producer={referee_id}"
        else:
            audit_ok = soundness_now
            if not audit_ok:
                audit_reason = "referee_verdict_contradicts_soundness"
    else:
        audit_ok = False
        audit_reason = f"audit_status_unknown={audit_status}"

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
            "soundness_ok": soundness_now,
            "reason": audit_reason,
            "writer_role": audit_doc.get("writer_role") or "",
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
        cert["error"] = f"closure_audit rejected: {audit_reason or 'unknown'}"
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
    architecture = str(ctx.get("architecture") or "").strip()
    if not architecture:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
    return uo, op_name, architecture


def _uo_init_engine(action_id: str) -> EngineFn:
    def _run(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
        from uo_init.pilot_engines import ENGINES

        fn = ENGINES[action_id]
        return fn(Path(project_root), ctx or {})

    _run.__name__ = f"_run_uo_init_{action_id}"
    return _run


ENGINE_REGISTRY: dict[tuple[str, str], EngineFn] = {
    # CodeMap compiler public surface (5 Actions).
    ("uo-init", "prepare"): _uo_init_engine("prepare"),
    ("uo-init", "extract"): _uo_init_engine("extract"),
    ("uo-init", "analyze"): _uo_init_engine("analyze"),
    ("uo-init", "commit"): _uo_init_engine("commit"),
    ("uo-init", "verify"): _uo_init_engine("verify"),
    ("uo-update", "detect_changes"): _run_detect_changes,
    ("uo-update", "plan_update"): _run_plan_update,
    ("uo-update", "apply_update"): _run_apply_update,
    ("uo-update", "export_integrity"): _run_export_integrity,
    ("uo-update", "diff_summary"): _run_diff_summary,
    ("uo-update", "diff_only"): _run_diff_summary,
    ("tg-init", "init_intent"): _run_tg_init_intent,
    ("tg-init", "kb_check"): _run_tg_kb_check,
    ("tg-init", "contract_build"): _run_tg_contract_build,
    ("tg-init", "semantic_bind"): _run_tg_semantic_bind,
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
    ("tg-solve", "lemma_evidence"): _run_lemma_evidence,
    ("tg-solve", "lemma_mine"): _run_lemma_mine,
    ("tg-solve", "lemma_verify"): _run_lemma_verify,
    ("tg-solve", "lemma_review"): _run_lemma_review,
    ("tg-solve", "lemma_apply"): _run_lemma_apply,
    ("tg-solve", "lemma_loop"): _run_lemma_loop,
    ("tg-solve", "closure_audit"): _run_closure_audit,
    ("tg-solve", "closure_certify"): _run_closure_certify,
}


# Output contract id → relative paths under .ascendc-pilot (existence + nonempty where applicable)
OUTPUT_CONTRACT_PATHS: dict[str, list[str]] = {
    # Layout artifacts + machine scope receipt (SSOT; composite overlay must match).
    "uo-prepare-v1": [
        "uo/manifest.yaml",
        "uo/operator.yaml",
        "uo/ir/build_variant.yaml",
        "uo/runs/{run_id}/scope/scope_validated.yaml",
        "uo/runs/{run_id}/scope/receipt.yaml",
    ],
    "uo-extract-v1": [
        "uo/ir/host_extract_receipt.yaml",
        "uo/tiling/key_bind_receipt.yaml",
        "uo/tiling/families.yaml",
        "uo/kernel/fold_receipt.yaml",
    ],
    "uo-analyze-v1": [
        "uo/ir/unresolved.yaml",
        "uo/ir/codemap_analyze_receipt.yaml",
    ],
    "uo-commit-v1": ["../uo/*.uo"],
    "uo-verify-v1": ["../uo/*.uo"],
    "integrity-v1": ["uo/checks/integrity.yaml"],
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
    # kb-answer: readiness precondition (existing workspace), not answer payload.
    "kb-answer-v1": ["uo/manifest.yaml", "uo/checks/integrity.yaml"],
    "code-review-v1": [
        "ce/review/index.yaml",
        "ce/review/functional_report.yaml",
        "ce/review/bug_report.yaml",
    ],
    # tg-init kb_check receipt: proves CodeMap .uo TG views are readable.
    "uo-ready-v1": ["tg/init/uo_ready.yaml"],
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
    "init-audit-v1": ["tg/init/audit_report.yaml"],
    "init-confirmed-v1": ["tg/init/status.yaml"],
    "plan-scope-v1": ["tg/plan/levels/*/plan_scope.yaml"],
    "plan-intent-v1": ["tg/plan/plan_intent.yaml"],
    "plan-precheck-v1": ["tg/init/status.yaml"],
    "plan-build-v1": ["tg/plan"],
    "plan-approved-v1": ["tg/plan/levels/*/human_supplement.yaml"],
    # Precondition only (produced by plan_approve); not a solve-precheck output.
    "solve-precheck-v1": ["tg/plan/levels/*/plan_scope.yaml"],
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
    "lemma-verify-v1": [
        "runs/{run_id}/actions/lemma_verify/verify.yaml",
        "tg/closure/lemmas/verify.yaml",
    ],
    "lemma-evidence-v1": [
        "tg/closure/lemmas/evidence_receipt.yaml",
        "tg/closure/lemmas/evidence/**",
    ],
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
}

# Contracts that must contain at least one nonempty concrete artifact (not empty dir / empty file)
OUTPUT_CONTRACT_NONEMPTY_GLOBS: dict[str, list[str]] = {
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
    "code-review-v1": [
        "ce/review/index.yaml",
        "ce/review/functional_report.yaml",
        "ce/review/bug_report.yaml",
    ],
    "plan-build-v1": [
        "tg/plan/levels/*/coverage_obligations.yaml",
        "tg/plan/coverage_obligations.yaml",
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
}


def invoke_engine(project_root: Path, workflow_id: str, action_id: str, *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    from ascendc_pilot.progress import engine_span

    key = (workflow_id, action_id)
    fn = ENGINE_REGISTRY.get(key)
    if fn is None:
        return {"ok": False, "error": f"no deterministic engine for {workflow_id}/{action_id}"}
    payload = dict(ctx or {})
    payload["action_id"] = action_id
    payload["workflow_id"] = workflow_id
    with engine_span(workflow_id, action_id):
        return fn(project_root, payload)
