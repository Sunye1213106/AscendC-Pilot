"""Cross-workflow deterministic performance router.

The router composes the existing UO semantic fast paths with publication deferral,
TG content-addressed reuse, and fresh SQLite reuse. It never changes the semantic
extractors themselves; workers still produce the same Host/Kernel/KEY/Bridge facts.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from ascendc_pilot.actions.fast_tg_engines import invoke_fast_tg_engine
from ascendc_pilot.actions.fast_uo_engines import invoke_fast_uo_engine

EngineFallback = Callable[..., dict[str, Any]]
_STRUCTURAL_UO_ACTIONS = frozenset({"detect_score_pre", "extract_plan", "rebuild_from_ledger"})


def _deferred_stats(name: str) -> dict[str, Any]:
    return {"status": "deferred", "deferred_to": "export_integrity", "product": name}


@contextmanager
def _defer_uo_publish_products() -> Iterator[dict[str, Any]]:
    """Suppress publish-only work while retaining structural graph construction."""

    patched: list[tuple[Any, str, Any]] = []
    state: dict[str, Any] = {"active": False, "deferred_products": []}
    try:
        import uo.scripts.build_layered_kb as layered
        import uo.scripts.classify_input_derivable as classify
        import uo.scripts.export_human_views as human
        import uo.scripts.export_kb_graph as sqlite_export
        import uo.scripts.kb_query_export as contracts
        from uo.scripts._ir_io import write_yaml_if_changed

        def patch(module: Any, name: str, replacement: Any) -> None:
            original = getattr(module, name)
            patched.append((module, name, original))
            setattr(module, name, replacement)

        def defer_classify(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            state["deferred_products"].append("input_derivable")
            return {"stats": _deferred_stats("input_derivable")}

        def defer_contracts(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            state["deferred_products"].append("testcase_contract_files")
            return _deferred_stats("testcase_contract_files")

        def defer_sqlite(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            state["deferred_products"].append("kb_graph.sqlite")
            return {
                **_deferred_stats("kb_graph.sqlite"),
                "entity_count": None,
                "relation_count": None,
            }

        def defer_human(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            state["deferred_products"].append("human_views")
            return {
                **_deferred_stats("human_views"),
                "keys_table": {"key_count": None},
                "ktpl_count": None,
            }

        patch(classify, "classify_and_write", defer_classify)
        patch(contracts, "materialize_testcase_contract_files", defer_contracts)
        patch(sqlite_export, "export_kb_graph", defer_sqlite)
        patch(human, "export_human_views", defer_human)
        # build_layered_kb keeps a module-local alias. Content-aware writes remove
        # duplicate bridge writes and unchanged graph rewrites.
        patch(layered, "write_yaml", write_yaml_if_changed)
        state["active"] = True
        yield state
    except ImportError:
        yield state
    finally:
        for module, name, original in reversed(patched):
            setattr(module, name, original)


def _invoke_structural(
    project_root: Path,
    workflow_id: str,
    action_id: str,
    ctx: dict[str, Any],
    *,
    fallback: EngineFallback,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    with _defer_uo_publish_products() as state:
        result = fallback(project_root, workflow_id, action_id, ctx=ctx)
    if not isinstance(result, dict):
        return result
    out = dict(result)
    if state.get("active"):
        out["build_mode"] = "structural" if not out.get("rebuild_skipped") else "noop"
        out["publish_deferred"] = True
        out["deferred_products"] = sorted(set(state.get("deferred_products") or []))
        timing = dict(out.get("timing_ms") or {})
        timing.setdefault("pipeline_router", int((time.perf_counter() - t0) * 1000))
        out["timing_ms"] = timing
    return out


@contextmanager
def _reuse_fresh_sqlite_index(project_root: Path, ctx: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Skip SQLite rebuild when its recorded YAML hashes are already fresh."""

    state: dict[str, Any] = {"cache_hit": False}
    try:
        import sqlite3

        import uo.scripts.export_kb_graph as export_mod
        from ascendc_pilot.paths import uo_root
        from uo.scripts.kb_graph_query import index_status

        uo = uo_root(project_root)
        db_path = uo / "indexes" / "kb_graph.sqlite"
        original = export_mod.export_kb_graph

        def cached_or_export(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                status = index_status(uo)
            except Exception:  # noqa: BLE001
                status = {}
            if db_path.is_file() and status.get("index_status") == "fresh":
                meta: dict[str, str] = {}
                try:
                    with sqlite3.connect(db_path) as db:
                        meta = {str(k): str(v) for k, v in db.execute("SELECT key, value FROM metadata")}
                except Exception:  # noqa: BLE001
                    meta = {}
                state["cache_hit"] = True
                return {
                    "status": "ok",
                    "cache_hit": True,
                    "db_path": str(db_path),
                    "entity_count": int(meta.get("entity_count") or 0),
                    "relation_count": int(meta.get("relation_count") or 0),
                    "alias_count": int(meta.get("alias_count") or 0),
                    "schema_version": meta.get("schema_version") or "1",
                    "source_hashes": status.get("source_hashes") or {},
                }
            return original(*args, **kwargs)

        export_mod.export_kb_graph = cached_or_export
        try:
            yield state
        finally:
            export_mod.export_kb_graph = original
    except ImportError:
        yield state


def _invoke_export_integrity(
    project_root: Path,
    workflow_id: str,
    action_id: str,
    ctx: dict[str, Any],
    *,
    fallback: EngineFallback,
) -> dict[str, Any]:
    with _reuse_fresh_sqlite_index(project_root, ctx) as state:
        result = fallback(project_root, workflow_id, action_id, ctx=ctx)
    if isinstance(result, dict):
        result = dict(result)
        result["sqlite_cache_hit"] = bool(state.get("cache_hit"))
    return result


def invoke_fast_pipeline_engine(
    project_root: Path,
    workflow_id: str,
    action_id: str,
    *,
    ctx: dict[str, Any] | None,
    fallback: EngineFallback,
) -> dict[str, Any]:
    """Compose UO/TG fast paths while preserving the canonical fallback."""

    payload = dict(ctx or {})

    def tg_or_canonical(
        inner_root: Path,
        inner_workflow: str,
        inner_action: str,
        *,
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return invoke_fast_tg_engine(
            Path(inner_root),
            inner_workflow,
            inner_action,
            ctx=ctx,
            fallback=fallback,
        )

    def uo_then_tg(
        inner_root: Path,
        inner_workflow: str,
        inner_action: str,
        *,
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return invoke_fast_uo_engine(
            Path(inner_root),
            inner_workflow,
            inner_action,
            ctx=ctx,
            fallback=tg_or_canonical,
        )

    if workflow_id == "uo-init" and action_id in _STRUCTURAL_UO_ACTIONS:
        return _invoke_structural(
            Path(project_root), workflow_id, action_id, payload, fallback=uo_then_tg
        )
    if workflow_id == "uo-init" and action_id == "export_integrity":
        return _invoke_export_integrity(
            Path(project_root), workflow_id, action_id, payload, fallback=uo_then_tg
        )
    return uo_then_tg(project_root, workflow_id, action_id, ctx=payload)
