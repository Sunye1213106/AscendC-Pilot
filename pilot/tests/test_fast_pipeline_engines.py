from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.fast_pipeline_engines import invoke_fast_pipeline_engine


def test_structural_action_defers_publish_products(monkeypatch, tmp_path: Path) -> None:
    import uo.scripts.export_human_views as human
    import uo.scripts.export_kb_graph as sqlite_export

    originals = (
        sqlite_export.export_kb_graph,
        human.export_human_views,
    )

    def fallback(root, workflow_id, action_id, *, ctx=None):
        assert sqlite_export.export_kb_graph(tmp_path, "op")["status"] == "deferred"
        assert human.export_human_views(tmp_path)["status"] == "deferred"
        return {"ok": True, "engine": action_id}

    result = invoke_fast_pipeline_engine(
        tmp_path,
        "uo-init",
        "extract_plan",
        ctx={"run_id": "RUN"},
        fallback=fallback,
    )

    assert result["ok"] is True
    assert result["build_mode"] == "structural"
    assert result["publish_deferred"] is True
    assert set(result["deferred_products"]) == {"kb_graph.sqlite", "human_views"}
    assert sqlite_export.export_kb_graph is originals[0]
    assert human.export_human_views is originals[1]


def test_non_structural_action_delegates_unchanged(tmp_path: Path) -> None:
    calls = []

    def fallback(root, workflow_id, action_id, *, ctx=None):
        calls.append((workflow_id, action_id, ctx))
        return {"ok": True}

    out = invoke_fast_pipeline_engine(
        tmp_path,
        "uo-init",
        "detect_score_post",
        ctx={"x": 1},
        fallback=fallback,
    )
    assert out == {"ok": True}
    assert calls == [("uo-init", "detect_score_post", {"x": 1})]


def test_update_apply_reuses_detect_plan_and_defers_duplicate_gates(monkeypatch, tmp_path: Path) -> None:
    import ascendc_pilot.actions.fast_pipeline_engines as fast
    import uo.scripts.update_operator as update_mod

    change_set = {"head_revision": "HEAD", "files": []}
    update_plan = {"head_revision": "HEAD", "mode": "selective", "affected_layers": ["kernel"]}
    monkeypatch.setattr(
        fast,
        "_update_documents",
        lambda _root: (tmp_path / ".ascendc-pilot" / "uo", change_set, update_plan, True),
    )

    calls = []

    def canonical_update(*args, **kwargs):
        calls.append(kwargs)
        assert update_mod.detect_kb_changes(tmp_path, "op") == change_set
        assert update_mod.plan_kb_update(tmp_path, "op") == update_plan
        assert update_mod._safe_export_kb_graph(tmp_path, "op")["status"] == "deferred"
        assert update_mod._safe_export_human_views(tmp_path)["status"] == "deferred"
        return {"status": "pass"}

    monkeypatch.setattr(update_mod, "update_operator", canonical_update)
    original = update_mod.update_operator

    def fallback(root, workflow_id, action_id, *, ctx=None):
        result = update_mod.update_operator(root, "op")
        assert result["status"] == "pass"
        return {"ok": True, "engine": action_id}

    out = invoke_fast_pipeline_engine(
        tmp_path,
        "uo-update",
        "apply_update",
        ctx={"run_id": "RUN"},
        fallback=fallback,
    )
    assert out["ok"] is True
    assert out["change_set_cache_hit"] is True
    assert out["update_plan_cache_hit"] is True
    assert out["validation_deferred"] is True
    assert calls and calls[0]["skip_validate"] is True
    assert update_mod.update_operator is original
